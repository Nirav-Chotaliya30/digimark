import csv
import io
import os
from datetime import date, datetime, timedelta

import pandas as pd
from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from flask_login import login_required
from sqlalchemy.exc import SQLAlchemyError

from models import db
from models.attendance import Attendance
from models.department import Department
from models.faculty import Faculty
from models.student import Student
from models.subject import Subject
from models.timetable import TimetableEntry
from models.user import User
from utils.decorators import role_required

admin_bp = Blueprint("admin", __name__)
WEEKDAY_ORDER = {
    "Monday": 1,
    "Tuesday": 2,
    "Wednesday": 3,
    "Thursday": 4,
    "Friday": 5,
    "Saturday": 6,
}


def _api_success(message: str, data=None, status_code: int = 200, **extras):
    payload = {"success": True, "message": message, "data": data}
    payload.update(extras)
    return jsonify(payload), status_code


def _api_error(message: str, status_code: int = 400, data=None, **extras):
    payload = {"success": False, "message": message, "data": data}
    payload.update(extras)
    return jsonify(payload), status_code


def _parse_bulk_rows():
    if request.files.get("file"):
        uploaded = request.files["file"]
        if not uploaded.filename:
            raise ValueError("Uploaded file is empty.")
        _, ext = os.path.splitext(uploaded.filename.lower())
        if ext in {".xlsx", ".xls"}:
            frame = pd.read_excel(uploaded, dtype=str).fillna("")
        else:
            frame = pd.read_csv(uploaded, dtype=str).fillna("")
        return frame.to_dict(orient="records")

    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError("rows must be a list.")
    return rows


def _department_id_from_branch(branch: str):
    department = Department.query.filter_by(name=branch).first()
    return department.id if department else None


def _build_dashboard_metrics():
    total_students = Student.query.count()
    total_faculty = Faculty.query.count()
    total_subjects = Subject.query.count()
    face_registered_count = Student.query.filter_by(face_registered=True).count()
    face_registration_percent = round((face_registered_count / total_students) * 100, 2) if total_students else 0

    last_seven_days = []
    for i in range(6, -1, -1):
        day = date.today() - timedelta(days=i)
        count = Attendance.query.filter_by(date=day).count()
        last_seven_days.append({"date": day.isoformat(), "count": count})

    branch_data = db.session.query(Student.branch).distinct().all()
    branch_stats = []
    branch_overview = []
    for (branch_name,) in branch_data:
        students = Student.query.filter_by(branch=branch_name).all()
        total = 0
        present = 0
        branch_face_registered = 0
        for student in students:
            records = Attendance.query.filter_by(student_id=student.id).all()
            total += len(records)
            present += len([r for r in records if r.status == "present"])
            if student.face_registered:
                branch_face_registered += 1
        percentage = round((present / total) * 100, 2) if total else 0
        branch_stats.append({"branch": branch_name, "attendance_percentage": percentage})
        branch_overview.append(
            {
                "branch": branch_name,
                "student_count": len(students),
                "face_registered_count": branch_face_registered,
                "attendance_percentage": percentage,
            }
        )
    return {
        "total_students": total_students,
        "total_faculty": total_faculty,
        "total_subjects": total_subjects,
        "face_registration_percent": face_registration_percent,
        "daily_attendance": last_seven_days,
        "branch_stats": branch_stats,
        "branch_overview": sorted(branch_overview, key=lambda x: x["branch"]),
    }


def _resolve_faculty_from_row(row: dict):
    faculty_id = str(row.get("faculty_id", "")).strip()
    faculty_email = str(row.get("faculty_email", "")).strip().lower()
    if faculty_id:
        return Faculty.query.get(int(faculty_id))
    if faculty_email:
        user = User.query.filter_by(email=faculty_email, role="faculty").first()
        if user:
            return Faculty.query.filter_by(user_id=user.id).first()
    return None


def _build_subject_from_row(row: dict, row_number: int):
    name = str(row.get("name", "")).strip()
    code = str(row.get("code", "")).strip().upper()
    branch = str(row.get("branch", "")).strip()
    passout_year_raw = str(row.get("passout_year", row.get("year", ""))).strip()
    semester_raw = str(row.get("semester", "")).strip()

    if not name or not code or not branch or not passout_year_raw:
        raise ValueError(f"Row {row_number}: name, code, branch, passout_year are required.")
    if branch not in current_app.config["BRANCHES"]:
        raise ValueError(f"Row {row_number}: invalid branch '{branch}'.")
    if not passout_year_raw.isdigit():
        raise ValueError(f"Row {row_number}: invalid passout_year '{passout_year_raw}'.")
    if semester_raw and (not semester_raw.isdigit() or int(semester_raw) not in range(1, 9)):
        raise ValueError(f"Row {row_number}: invalid semester '{semester_raw}'.")
    if Subject.query.filter_by(code=code).first():
        raise ValueError(f"Row {row_number}: subject code '{code}' already exists.")

    faculty = _resolve_faculty_from_row(row)
    return Subject(
        name=name,
        code=code,
        faculty_id=faculty.id if faculty else None,
        branch=branch,
        department_id=_department_id_from_branch(branch),
        year=int(passout_year_raw),
        semester=int(semester_raw) if semester_raw else None,
    ), faculty


def _build_faculty_from_row(row: dict, row_number: int):
    username = str(row.get("username", "")).strip()
    email = str(row.get("email", "")).strip().lower()
    password = str(row.get("password", "")).strip() or "Faculty@123"
    full_name = str(row.get("full_name", "")).strip()
    department = str(row.get("department", "")).strip()

    if not username or not email or not full_name or not department:
        raise ValueError(f"Row {row_number}: username, email, full_name, department are required.")
    if department not in current_app.config["BRANCHES"]:
        raise ValueError(f"Row {row_number}: invalid department '{department}'.")
    if User.query.filter((User.username == username) | (User.email == email)).first():
        raise ValueError(f"Row {row_number}: username/email already exists.")

    user = User(username=username, email=email, role="faculty")
    user.set_password(password)
    return user, Faculty(
        full_name=full_name,
        department=department,
        department_id=_department_id_from_branch(department),
        subject_ids=[],
    )


def _build_student_from_row(row: dict, row_number: int):
    enrollment_no = str(row.get("enrollment_no", "")).strip()
    email = str(row.get("email", "")).strip().lower()
    password = str(row.get("password", "")).strip() or "Student@123"
    full_name = str(row.get("full_name", "")).strip()
    branch = str(row.get("branch", "")).strip()
    passout_year_raw = str(row.get("passout_year", row.get("year", ""))).strip()
    semester_raw = str(row.get("semester", "")).strip()

    if not enrollment_no or not email or not full_name or not branch or not passout_year_raw:
        raise ValueError(f"Row {row_number}: enrollment_no, email, full_name, branch, passout_year are required.")
    if branch not in current_app.config["BRANCHES"]:
        raise ValueError(f"Row {row_number}: invalid branch '{branch}'.")
    if not passout_year_raw.isdigit():
        raise ValueError(f"Row {row_number}: invalid passout_year '{passout_year_raw}'.")
    if semester_raw and (not semester_raw.isdigit() or int(semester_raw) not in range(1, 9)):
        raise ValueError(f"Row {row_number}: invalid semester '{semester_raw}'.")
    if Student.query.filter_by(enrollment_no=enrollment_no).first():
        raise ValueError(f"Row {row_number}: enrollment number already exists.")
    if User.query.filter_by(email=email).first():
        raise ValueError(f"Row {row_number}: email already exists.")

    user = User(username=enrollment_no, email=email, role="student")
    user.set_password(password)
    student = Student(
        enrollment_no=enrollment_no,
        full_name=full_name,
        branch=branch,
        department_id=_department_id_from_branch(branch),
        year=int(passout_year_raw),
        semester=int(semester_raw) if semester_raw else None,
    )
    return user, student


@admin_bp.route("/admin/dashboard")
@login_required
@role_required("admin")
def admin_dashboard():
    metrics = _build_dashboard_metrics()

    faculty_cards = []
    faculties = Faculty.query.all()
    for faculty in faculties:
        subjects_for_faculty = Subject.query.filter_by(faculty_id=faculty.id).all()
        student_pool = 0
        for subject in subjects_for_faculty:
            student_pool += Student.query.filter_by(branch=subject.branch, year=subject.year).count()
        faculty_cards.append(
            {
                "faculty": faculty,
                "subject_count": len(subjects_for_faculty),
                "student_pool": student_pool,
            }
        )
    timetable_entries = TimetableEntry.query.all()
    timetable_entries.sort(
        key=lambda e: (
            WEEKDAY_ORDER.get(e.day_of_week, 99),
            e.start_time if e.start_time else f"{e.period_no:02d}:00",
        )
    )

    return render_template(
        "admin/dashboard.html",
        total_students=metrics["total_students"],
        total_faculty=metrics["total_faculty"],
        total_subjects=metrics["total_subjects"],
        face_registration_percent=metrics["face_registration_percent"],
        branch_total=current_app.config["BRANCH_COUNT"],
        branches=sorted(current_app.config["BRANCHES"]),
        passout_years=list(range(date.today().year, date.today().year + 8)),
        daily_attendance=metrics["daily_attendance"],
        branch_stats=metrics["branch_stats"],
        branch_overview=metrics["branch_overview"],
        subjects=Subject.query.all(),
        faculties=faculties,
        faculty_cards=faculty_cards,
        students=Student.query.all(),
        weekdays=list(WEEKDAY_ORDER.keys()),
        timetable_entries=timetable_entries,
    )


@admin_bp.route("/admin/students")
@login_required
@role_required("admin")
def admin_students_page():
    return render_template(
        "admin/students.html",
        students=Student.query.order_by(Student.id.desc()).all(),
        branches=sorted(current_app.config["BRANCHES"]),
        passout_years=list(range(date.today().year, date.today().year + 8)),
    )


@admin_bp.route("/admin/faculty")
@login_required
@role_required("admin")
def admin_faculty_page():
    return render_template(
        "admin/faculty.html",
        faculties=Faculty.query.order_by(Faculty.id.desc()).all(),
        branches=sorted(current_app.config["BRANCHES"]),
    )


@admin_bp.route("/admin/subjects")
@login_required
@role_required("admin")
def admin_subjects_page():
    return render_template(
        "admin/subjects.html",
        subjects=Subject.query.order_by(Subject.id.desc()).all(),
        faculties=Faculty.query.order_by(Faculty.full_name.asc()).all(),
        branches=sorted(current_app.config["BRANCHES"]),
        passout_years=list(range(date.today().year, date.today().year + 8)),
    )


@admin_bp.route("/admin/attendance")
@login_required
@role_required("admin")
def admin_attendance_page():
    records = (
        Attendance.query.join(Student, Attendance.student_id == Student.id)
        .join(Subject, Attendance.subject_id == Subject.id)
        .order_by(Attendance.date.desc(), Attendance.time.desc())
        .limit(500)
        .all()
    )
    return render_template(
        "admin/attendance.html",
        records=records,
        branches=sorted(current_app.config["BRANCHES"]),
        subjects=Subject.query.order_by(Subject.code.asc()).all(),
        faculties=Faculty.query.order_by(Faculty.full_name.asc()).all(),
        weekdays=list(WEEKDAY_ORDER.keys()),
        timetable_entries=TimetableEntry.query.order_by(TimetableEntry.day_of_week.asc(), TimetableEntry.start_time.asc()).all(),
        passout_years=list(range(date.today().year, date.today().year + 8)),
    )


@admin_bp.route("/admin/reports")
@login_required
@role_required("admin")
def admin_reports_page():
    threshold = float(current_app.config.get("DEFAULTER_THRESHOLD", 75))
    defaulters = []
    for student in Student.query.all():
        total = Attendance.query.filter_by(student_id=student.id).count()
        present = Attendance.query.filter_by(student_id=student.id, status="present").count()
        percentage = round((present / total) * 100, 2) if total else 0
        if percentage < threshold:
            defaulters.append({"student": student, "attendance_percentage": percentage})
    defaulters.sort(key=lambda x: x["attendance_percentage"])
    return render_template("admin/reports.html", defaulters=defaulters, threshold=threshold)


@admin_bp.route("/admin/settings")
@login_required
@role_required("admin")
def admin_settings_page():
    return render_template("admin/settings.html")


@admin_bp.route("/api/admin/dashboard-stats")
@login_required
@role_required("admin")
def dashboard_stats():
    metrics = _build_dashboard_metrics()
    stats = {
        "total_students": metrics["total_students"],
        "total_faculty": metrics["total_faculty"],
        "total_subjects": metrics["total_subjects"],
        "face_registration_percent": metrics["face_registration_percent"],
    }
    return _api_success("Dashboard stats fetched successfully.", data=stats, stats=stats)


@admin_bp.route("/api/admin/charts-data")
@login_required
@role_required("admin")
def charts_data():
    metrics = _build_dashboard_metrics()
    charts = {
        "daily_attendance": metrics["daily_attendance"],
        "branch_stats": metrics["branch_stats"],
    }
    return _api_success("Chart data fetched successfully.", data=charts, charts=charts)


@admin_bp.route("/api/admin/add-subject", methods=["POST"])
@login_required
@role_required("admin")
def add_subject():
    data = request.get_json(silent=True) or request.form
    faculty_id = data.get("faculty_id")
    faculty = Faculty.query.get(faculty_id) if faculty_id else None
    branch = data.get("branch", "").strip()
    passout_year_raw = str(data.get("passout_year", data.get("year", ""))).strip()
    if branch not in current_app.config["BRANCHES"]:
        return _api_error("Invalid branch selected.", 400)
    if not passout_year_raw.isdigit():
        return _api_error("Invalid passout year.", 400)
    passout_year = int(passout_year_raw)

    subject = Subject(
        name=data.get("name", "").strip(),
        code=data.get("code", "").strip().upper(),
        faculty_id=faculty.id if faculty else None,
        branch=branch,
        department_id=_department_id_from_branch(branch),
        year=passout_year,
        semester=int(data.get("semester")) if str(data.get("semester", "")).isdigit() else None,
    )
    try:
        db.session.add(subject)
        db.session.flush()

        if faculty:
            ids = set(faculty.subject_ids or [])
            ids.add(subject.id)
            faculty.subject_ids = list(ids)

        db.session.commit()
        subject_data = subject.to_dict()
        return _api_success("Subject added successfully.", data=subject_data, subject=subject_data)
    except SQLAlchemyError:
        db.session.rollback()
        return _api_error("Could not add subject due to a database error.", 500)


@admin_bp.route("/api/admin/add-student", methods=["POST"])
@login_required
@role_required("admin")
def add_student():
    data = request.get_json(silent=True) or request.form
    required_fields = ("enrollment_no", "email", "full_name", "branch", "passout_year")
    if any(not str(data.get(field, "")).strip() for field in required_fields):
        return _api_error("enrollment_no, email, full_name, branch, passout_year are required.", 400)

    branch = str(data.get("branch", "")).strip()
    if branch not in current_app.config["BRANCHES"]:
        return _api_error("Invalid branch selected.", 400)

    passout_year_raw = str(data.get("passout_year", data.get("year", ""))).strip()
    if not passout_year_raw.isdigit():
        return _api_error("Invalid passout year.", 400)

    semester_raw = str(data.get("semester", "")).strip()
    if semester_raw and (not semester_raw.isdigit() or int(semester_raw) not in range(1, 9)):
        return _api_error("Invalid semester.", 400)

    enrollment_no = str(data.get("enrollment_no", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    if Student.query.filter_by(enrollment_no=enrollment_no).first():
        return _api_error("Enrollment number already exists.", 409)
    if User.query.filter_by(email=email).first():
        return _api_error("Email already exists.", 409)

    user = User(username=enrollment_no, email=email, role="student")
    user.set_password(str(data.get("password", "Student@123")).strip() or "Student@123")
    student = Student(
        enrollment_no=enrollment_no,
        full_name=str(data.get("full_name", "")).strip(),
        branch=branch,
        department_id=_department_id_from_branch(branch),
        year=int(passout_year_raw),
        semester=int(semester_raw) if semester_raw else None,
    )
    try:
        db.session.add(user)
        db.session.flush()
        student.user_id = user.id
        db.session.add(student)
        db.session.commit()
        student_data = student.to_dict()
        return _api_success("Student added successfully.", data=student_data, student=student_data)
    except SQLAlchemyError:
        db.session.rollback()
        return _api_error("Could not add student due to a database error.", 500)


@admin_bp.route("/api/admin/add-subjects-bulk", methods=["POST"])
@login_required
@role_required("admin")
def add_subjects_bulk():
    try:
        rows = _parse_bulk_rows()
    except Exception as exc:
        return _api_error(f"Invalid bulk upload payload: {exc}", 400)

    if not rows:
        return _api_error("No rows found for bulk upload.", 400)

    created = []
    errors = []
    new_codes = set()

    for idx, row in enumerate(rows, start=2):
        try:
            subject, faculty = _build_subject_from_row(row, idx)
            if subject.code in new_codes:
                raise ValueError(f"Row {idx}: duplicate code '{subject.code}' in upload file.")

            db.session.add(subject)
            db.session.flush()
            new_codes.add(subject.code)

            if faculty:
                ids = set(faculty.subject_ids or [])
                ids.add(subject.id)
                faculty.subject_ids = list(ids)

            db.session.commit()
            created.append(subject.to_dict())
        except Exception as exc:
            db.session.rollback()
            errors.append(str(exc))
            continue

    success = len(created) > 0
    message = "Bulk subject upload completed." if success else "No subjects were created."
    return _api_success(
        message,
        data={"created": created, "errors": errors[:20]},
        created_count=len(created),
        error_count=len(errors),
        errors=errors[:20],
        subjects=created,
    ) if success else _api_error(
        message,
        400,
        data={"created": created, "errors": errors[:20]},
        created_count=len(created),
        error_count=len(errors),
        errors=errors[:20],
        subjects=created,
    )


@admin_bp.route("/api/admin/add-faculty", methods=["POST"])
@login_required
@role_required("admin")
def add_faculty():
    data = request.get_json(silent=True) or request.form
    department = str(data.get("department", "")).strip()
    if department not in current_app.config["BRANCHES"]:
        return _api_error("Invalid department selected.", 400)
    if User.query.filter((User.username == data.get("username", "").strip()) | (User.email == data.get("email", "").strip().lower())).first():
        return _api_error("Username or email already exists.", 400)
    user = User(
        username=data.get("username", "").strip(),
        email=data.get("email", "").strip().lower(),
        role="faculty",
    )
    user.set_password(data.get("password", "Faculty@123"))
    db.session.add(user)
    db.session.flush()

    faculty = Faculty(
        user_id=user.id,
        full_name=data.get("full_name", "").strip(),
        department=department,
        department_id=_department_id_from_branch(department),
        subject_ids=[],
    )
    try:
        db.session.add(faculty)
        db.session.commit()
        faculty_data = faculty.to_dict()
        return _api_success("Faculty added successfully.", data=faculty_data, faculty=faculty_data)
    except SQLAlchemyError:
        db.session.rollback()
        return _api_error("Could not add faculty due to a database error.", 500)


@admin_bp.route("/api/admin/delete/student/<int:student_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def delete_student(student_id: int):
    student = Student.query.get_or_404(student_id)
    user = User.query.get(student.user_id)
    db.session.delete(student)
    if user:
        db.session.delete(user)
    db.session.commit()
    return _api_success("Student deleted successfully.", data={"id": student_id})


@admin_bp.route("/api/admin/delete/faculty/<int:faculty_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def delete_faculty(faculty_id: int):
    faculty = Faculty.query.get_or_404(faculty_id)
    user = User.query.get(faculty.user_id)
    db.session.delete(faculty)
    if user:
        db.session.delete(user)
    db.session.commit()
    return _api_success("Faculty deleted successfully.", data={"id": faculty_id})


@admin_bp.route("/api/admin/delete/subject/<int:subject_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def delete_subject(subject_id: int):
    subject = Subject.query.get_or_404(subject_id)
    db.session.delete(subject)
    db.session.commit()
    return _api_success("Subject deleted successfully.", data={"id": subject_id})


@admin_bp.route("/api/admin/add-faculties-bulk", methods=["POST"])
@login_required
@role_required("admin")
def add_faculties_bulk():
    try:
        rows = _parse_bulk_rows()
    except Exception as exc:
        return _api_error(f"Invalid bulk upload payload: {exc}", 400)
    if not rows:
        return _api_error("No rows found for bulk upload.", 400)

    created = []
    errors = []
    for idx, row in enumerate(rows, start=2):
        try:
            user, faculty = _build_faculty_from_row(row, idx)
            db.session.add(user)
            db.session.flush()
            faculty.user_id = user.id
            db.session.add(faculty)
            db.session.commit()
            created.append(faculty.to_dict())
        except Exception as exc:
            db.session.rollback()
            errors.append(str(exc))
    success = len(created) > 0
    payload = {"created": created, "errors": errors[:20]}
    message = "Bulk faculty upload completed." if success else "No faculty records were created."
    return _api_success(
        message,
        data=payload,
        created_count=len(created),
        error_count=len(errors),
        errors=errors[:20],
    ) if success else _api_error(
        message,
        400,
        data=payload,
        created_count=len(created),
        error_count=len(errors),
        errors=errors[:20],
    )


@admin_bp.route("/api/admin/add-students-bulk", methods=["POST"])
@login_required
@role_required("admin")
def add_students_bulk():
    try:
        rows = _parse_bulk_rows()
    except Exception as exc:
        return _api_error(f"Invalid bulk upload payload: {exc}", 400)
    if not rows:
        return _api_error("No rows found for bulk upload.", 400)

    created = []
    errors = []
    for idx, row in enumerate(rows, start=2):
        try:
            user, student = _build_student_from_row(row, idx)
            db.session.add(user)
            db.session.flush()
            student.user_id = user.id
            db.session.add(student)
            db.session.commit()
            created.append(student.to_dict())
        except Exception as exc:
            db.session.rollback()
            errors.append(str(exc))
    success = len(created) > 0
    payload = {"created": created, "errors": errors[:20]}
    message = "Bulk student upload completed." if success else "No student records were created."
    return _api_success(
        message,
        data=payload,
        created_count=len(created),
        error_count=len(errors),
        errors=errors[:20],
    ) if success else _api_error(
        message,
        400,
        data=payload,
        created_count=len(created),
        error_count=len(errors),
        errors=errors[:20],
    )


@admin_bp.route("/api/admin/bulk-delete", methods=["POST"])
@login_required
@role_required("admin")
def bulk_delete():
    payload = request.get_json(silent=True) or {}
    entity_type = str(payload.get("type", "")).strip()
    ids = payload.get("ids", [])
    if entity_type not in {"student", "faculty", "subject"} or not isinstance(ids, list):
        return _api_error("Invalid delete request.", 400)
    deleted_count = 0
    for raw_id in ids:
        if not str(raw_id).isdigit():
            continue
        item_id = int(raw_id)
        if entity_type == "student":
            item = Student.query.get(item_id)
            if item:
                user = User.query.get(item.user_id)
                db.session.delete(item)
                if user:
                    db.session.delete(user)
                deleted_count += 1
        elif entity_type == "faculty":
            item = Faculty.query.get(item_id)
            if item:
                user = User.query.get(item.user_id)
                db.session.delete(item)
                if user:
                    db.session.delete(user)
                deleted_count += 1
        else:
            item = Subject.query.get(item_id)
            if item:
                db.session.delete(item)
                deleted_count += 1
    db.session.commit()
    return _api_success("Bulk delete completed.", data={"deleted_count": deleted_count}, deleted_count=deleted_count)


@admin_bp.route("/api/admin/export/<string:entity_type>")
@login_required
@role_required("admin")
def export_registry(entity_type: str):
    stream = io.StringIO()
    if entity_type == "students":
        rows = [
            {
                "id": s.id,
                "enrollment_no": s.enrollment_no,
                "full_name": s.full_name,
                "branch": s.branch,
                "year": s.year,
                "semester": s.semester,
                "face_registered": s.face_registered,
            }
            for s in Student.query.order_by(Student.id.desc()).all()
        ]
    elif entity_type == "faculties":
        rows = [
            {
                "id": f.id,
                "full_name": f.full_name,
                "department": f.department,
                "email": f.user.email if f.user else "",
            }
            for f in Faculty.query.order_by(Faculty.id.desc()).all()
        ]
    elif entity_type == "subjects":
        rows = [
            {
                "id": s.id,
                "code": s.code,
                "name": s.name,
                "branch": s.branch,
                "year": s.year,
                "semester": s.semester,
                "faculty": s.faculty.full_name if s.faculty else "",
            }
            for s in Subject.query.order_by(Subject.id.desc()).all()
        ]
    else:
        return _api_error("Unsupported export type.", 400)

    if not rows:
        return _api_error("No data to export.", 400)

    writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    bytes_stream = io.BytesIO(stream.getvalue().encode("utf-8"))
    bytes_stream.seek(0)
    return send_file(bytes_stream, mimetype="text/csv", as_attachment=True, download_name=f"{entity_type}_registry.csv")


@admin_bp.route("/api/admin/update/student/<int:student_id>", methods=["PUT"])
@login_required
@role_required("admin")
def update_student(student_id: int):
    student = Student.query.get_or_404(student_id)
    data = request.get_json(silent=True) or {}
    full_name = str(data.get("full_name", student.full_name)).strip()
    branch = str(data.get("branch", student.branch)).strip()
    year = str(data.get("year", student.year)).strip()
    semester_raw = str(data.get("semester", student.semester or "")).strip()
    if not full_name or branch not in current_app.config["BRANCHES"] or not year.isdigit():
        return _api_error("Invalid student data.", 400)
    if semester_raw and (not semester_raw.isdigit() or int(semester_raw) not in range(1, 9)):
        return _api_error("Invalid semester.", 400)
    student.full_name = full_name
    student.branch = branch
    student.department_id = _department_id_from_branch(branch)
    student.year = int(year)
    student.semester = int(semester_raw) if semester_raw else None
    db.session.commit()
    student_data = student.to_dict()
    return _api_success("Student updated successfully.", data=student_data, student=student_data)


@admin_bp.route("/api/admin/update/faculty/<int:faculty_id>", methods=["PUT"])
@login_required
@role_required("admin")
def update_faculty(faculty_id: int):
    faculty = Faculty.query.get_or_404(faculty_id)
    data = request.get_json(silent=True) or {}
    full_name = str(data.get("full_name", faculty.full_name)).strip()
    department = str(data.get("department", faculty.department)).strip()
    if not full_name or not department:
        return _api_error("Invalid faculty data.", 400)
    if department not in current_app.config["BRANCHES"]:
        return _api_error("Invalid department selected.", 400)
    faculty.full_name = full_name
    faculty.department = department
    faculty.department_id = _department_id_from_branch(department)
    db.session.commit()
    faculty_data = faculty.to_dict()
    return _api_success("Faculty updated successfully.", data=faculty_data, faculty=faculty_data)


@admin_bp.route("/api/admin/update/subject/<int:subject_id>", methods=["PUT"])
@login_required
@role_required("admin")
def update_subject(subject_id: int):
    subject = Subject.query.get_or_404(subject_id)
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", subject.name)).strip()
    branch = str(data.get("branch", subject.branch)).strip()
    year = str(data.get("year", subject.year)).strip()
    semester_raw = str(data.get("semester", subject.semester or "")).strip()
    faculty_id_raw = str(data.get("faculty_id", "")).strip()
    if not name or branch not in current_app.config["BRANCHES"] or not year.isdigit():
        return _api_error("Invalid subject data.", 400)
    if semester_raw and (not semester_raw.isdigit() or int(semester_raw) not in range(1, 9)):
        return _api_error("Invalid semester.", 400)
    faculty = None
    if faculty_id_raw:
        if not faculty_id_raw.isdigit():
            return _api_error("Invalid faculty selected.", 400)
        faculty = Faculty.query.get(int(faculty_id_raw))
        if not faculty:
            return _api_error("Faculty not found.", 404)

    previous_faculty = Faculty.query.get(subject.faculty_id) if subject.faculty_id else None
    subject.name = name
    subject.branch = branch
    subject.department_id = _department_id_from_branch(branch)
    subject.year = int(year)
    subject.semester = int(semester_raw) if semester_raw else None
    subject.faculty_id = faculty.id if faculty else None

    if previous_faculty:
        previous_ids = set(previous_faculty.subject_ids or [])
        if subject.id in previous_ids:
            previous_ids.remove(subject.id)
            previous_faculty.subject_ids = list(previous_ids)
    if faculty:
        new_ids = set(faculty.subject_ids or [])
        new_ids.add(subject.id)
        faculty.subject_ids = list(new_ids)

    db.session.commit()
    subject_data = subject.to_dict()
    return _api_success("Subject updated successfully.", data=subject_data, subject=subject_data)


@admin_bp.route("/api/admin/timetable", methods=["POST"])
@login_required
@role_required("admin")
def add_timetable_entry():
    data = request.get_json(silent=True) or request.form
    day_of_week = str(data.get("day_of_week", "")).strip()
    start_time = str(data.get("start_time", "")).strip()
    end_time = str(data.get("end_time", "")).strip()
    subject_id_raw = str(data.get("subject_id", "")).strip()
    faculty_id_raw = str(data.get("faculty_id", "")).strip()
    branch = str(data.get("branch", "")).strip()
    year_raw = str(data.get("year", "")).strip()
    semester_raw = str(data.get("semester", "")).strip()
    classroom = str(data.get("classroom", "")).strip() or None
    latitude_raw = str(data.get("latitude", "")).strip()
    longitude_raw = str(data.get("longitude", "")).strip()
    geofence_radius_raw = str(data.get("geofence_radius_meters", "")).strip()

    if day_of_week not in WEEKDAY_ORDER:
        return _api_error("Invalid day selected.", 400)
    if not start_time or not end_time:
        return _api_error("Start time and end time are required.", 400)
    try:
        start_dt = datetime.strptime(start_time, "%H:%M")
        end_dt = datetime.strptime(end_time, "%H:%M")
    except ValueError:
        return _api_error("Time format must be HH:MM (24-hour).", 400)
    if end_dt <= start_dt:
        return _api_error("End time must be after start time.", 400)
    if not subject_id_raw.isdigit() or not faculty_id_raw.isdigit():
        return _api_error("Subject and faculty are required.", 400)
    if branch not in current_app.config["BRANCHES"]:
        return _api_error("Invalid branch selected.", 400)
    if not year_raw.isdigit():
        return _api_error("Invalid passout year.", 400)
    if semester_raw and (not semester_raw.isdigit() or int(semester_raw) not in range(1, 9)):
        return _api_error("Invalid semester.", 400)
    if (latitude_raw and not longitude_raw) or (longitude_raw and not latitude_raw):
        return _api_error("Both latitude and longitude are required when setting class location.", 400)

    latitude = None
    longitude = None
    geofence_radius_meters = None
    if latitude_raw and longitude_raw:
        try:
            latitude = float(latitude_raw)
            longitude = float(longitude_raw)
        except ValueError:
            return _api_error("Latitude and longitude must be valid numbers.", 400)
        if latitude < -90 or latitude > 90 or longitude < -180 or longitude > 180:
            return _api_error("Latitude/longitude out of valid range.", 400)
        if geofence_radius_raw:
            try:
                geofence_radius_meters = float(geofence_radius_raw)
            except ValueError:
                return _api_error("Geofence radius must be a number.", 400)
            if geofence_radius_meters <= 0:
                return _api_error("Geofence radius must be greater than zero.", 400)

    subject = Subject.query.get(int(subject_id_raw))
    faculty = Faculty.query.get(int(faculty_id_raw))
    if not subject or not faculty:
        return _api_error("Subject or faculty not found.", 404)

    batch_semester = int(semester_raw) if semester_raw else None
    existing = TimetableEntry.query.filter_by(
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        branch=branch,
        year=int(year_raw),
        semester=batch_semester,
    ).first()
    if existing:
        return _api_error("A timetable entry already exists for this batch/day/time slot.", 409)

    sequence_no = (
        TimetableEntry.query.filter_by(
            day_of_week=day_of_week,
            branch=branch,
            year=int(year_raw),
            semester=batch_semester,
        ).count()
        + 1
    )

    entry = TimetableEntry(
        day_of_week=day_of_week,
        period_no=sequence_no,
        start_time=start_time,
        end_time=end_time,
        subject_id=subject.id,
        faculty_id=faculty.id,
        branch=branch,
        year=int(year_raw),
        semester=batch_semester,
        classroom=classroom,
        latitude=latitude,
        longitude=longitude,
        geofence_radius_meters=geofence_radius_meters,
    )
    db.session.add(entry)
    db.session.commit()
    entry_data = entry.to_dict()
    return _api_success("Timetable entry added successfully.", data=entry_data, entry=entry_data)


@admin_bp.route("/api/admin/timetable/update", methods=["PUT"])
@login_required
@role_required("admin")
def update_timetable_entry():
    payload = request.get_json(silent=True) or {}
    entry_id = payload.get("id")
    if not str(entry_id).isdigit():
        return _api_error("Valid timetable id is required.", 400)
    entry = TimetableEntry.query.get_or_404(int(entry_id))

    day_of_week = str(payload.get("day_of_week", entry.day_of_week)).strip()
    start_time = str(payload.get("start_time", entry.start_time)).strip()
    end_time = str(payload.get("end_time", entry.end_time)).strip()
    branch = str(payload.get("branch", entry.branch)).strip()
    year_raw = str(payload.get("year", entry.year)).strip()
    semester_raw = str(payload.get("semester", entry.semester if entry.semester is not None else "")).strip()
    classroom = str(payload.get("classroom", entry.classroom or "")).strip() or None
    latitude_raw = str(payload.get("latitude", entry.latitude if entry.latitude is not None else "")).strip()
    longitude_raw = str(payload.get("longitude", entry.longitude if entry.longitude is not None else "")).strip()
    radius_raw = str(payload.get("radius", payload.get("geofence_radius_meters", entry.geofence_radius_meters if entry.geofence_radius_meters is not None else ""))).strip()

    if day_of_week not in WEEKDAY_ORDER:
        return _api_error("Invalid day selected.", 400)
    if not start_time or not end_time:
        return _api_error("Start time and end time are required.", 400)
    try:
        start_dt = datetime.strptime(start_time, "%H:%M")
        end_dt = datetime.strptime(end_time, "%H:%M")
    except ValueError:
        return _api_error("Time format must be HH:MM (24-hour).", 400)
    if end_dt <= start_dt:
        return _api_error("End time must be after start time.", 400)
    if branch not in current_app.config["BRANCHES"]:
        return _api_error("Invalid department selected.", 400)
    if not year_raw.isdigit():
        return _api_error("Invalid passout year.", 400)
    if semester_raw and (not semester_raw.isdigit() or int(semester_raw) not in range(1, 9)):
        return _api_error("Invalid semester.", 400)

    latitude = None
    longitude = None
    radius = None
    if latitude_raw or longitude_raw:
        try:
            latitude = float(latitude_raw)
            longitude = float(longitude_raw)
        except ValueError:
            return _api_error("Latitude and longitude must be valid numbers.", 400)
    if radius_raw:
        try:
            radius = float(radius_raw)
        except ValueError:
            return _api_error("Radius must be a number.", 400)
        if radius <= 0:
            return _api_error("Radius must be greater than zero.", 400)

    entry.day_of_week = day_of_week
    entry.start_time = start_time
    entry.end_time = end_time
    entry.branch = branch
    entry.year = int(year_raw)
    entry.semester = int(semester_raw) if semester_raw else None
    entry.classroom = classroom
    entry.latitude = latitude
    entry.longitude = longitude
    entry.geofence_radius_meters = radius
    db.session.commit()
    entry_data = entry.to_dict()
    return _api_success("Timetable entry updated successfully.", data=entry_data, entry=entry_data)


@admin_bp.route("/api/admin/timetable/<int:entry_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def delete_timetable_entry(entry_id: int):
    entry = TimetableEntry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    return _api_success("Timetable entry deleted successfully.", data={"id": entry_id})


@admin_bp.route("/api/admin/timetable/add", methods=["POST"])
@login_required
@role_required("admin")
def add_timetable_entry_alias():
    return add_timetable_entry()


@admin_bp.route("/api/admin/timetable/delete/<int:entry_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def delete_timetable_entry_alias(entry_id: int):
    return delete_timetable_entry(entry_id)


@admin_bp.route("/api/admin/bulk-upload/students", methods=["POST"])
@login_required
@role_required("admin")
def bulk_upload_students_alias():
    return add_students_bulk()


@admin_bp.route("/api/admin/bulk-upload/faculties", methods=["POST"])
@login_required
@role_required("admin")
def bulk_upload_faculties_alias():
    return add_faculties_bulk()


@admin_bp.route("/api/admin/bulk-upload/subjects", methods=["POST"])
@login_required
@role_required("admin")
def bulk_upload_subjects_alias():
    return add_subjects_bulk()


@admin_bp.route("/api/admin/dashboard-data")
@login_required
@role_required("admin")
def dashboard_data():
    metrics = _build_dashboard_metrics()
    threshold = float(current_app.config.get("DEFAULTER_THRESHOLD", 75))
    defaulters = []
    for student in Student.query.all():
        total = Attendance.query.filter_by(student_id=student.id).count()
        present = Attendance.query.filter_by(student_id=student.id, status="present").count()
        percentage = round((present / total) * 100, 2) if total else 0
        if percentage < threshold:
            defaulters.append(
                {
                    "student_id": student.id,
                    "enrollment_no": student.enrollment_no,
                    "full_name": student.full_name,
                    "attendance_percentage": percentage,
                }
            )

    payload = {
        "kpis": {
            "total_students": metrics["total_students"],
            "total_faculty": metrics["total_faculty"],
            "total_subjects": metrics["total_subjects"],
            "attendance_percentage": round(
                (sum(item["attendance_percentage"] for item in metrics["branch_stats"]) / len(metrics["branch_stats"]))
                if metrics["branch_stats"]
                else 0,
                2,
            ),
            "defaulters_count": len(defaulters),
        },
        "charts": {
            "daily_attendance": metrics["daily_attendance"],
            "branch_stats": metrics["branch_stats"],
        },
        "defaulters": defaulters,
    }
    return _api_success("Dashboard data fetched successfully.", data=payload, dashboard=payload)
