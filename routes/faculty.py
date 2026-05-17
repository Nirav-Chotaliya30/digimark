import logging

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from models import db
from models.attendance import Attendance
from models.faculty import Faculty
from models.lecture_session import LectureSession
from models.student import Student
from models.subject import Subject
from models.timetable import TimetableEntry
from utils.decorators import role_required
from utils.lecture import (
    _slot_window_safe,
    _stamp_in_slot,
    app_now,
    current_faculty_lecture,
    get_current_lecture,
    get_previous_lectures,
)
from utils.helpers import attendance_rows_to_csv, calculate_attendance_percentage, normalize_date_range

faculty_bp = Blueprint("faculty", __name__)
logger = logging.getLogger(__name__)


def _api_success(message: str, data=None, status_code: int = 200, **extras):
    payload = {"success": True, "message": message, "data": data}
    payload.update(extras)
    return jsonify(payload), status_code


def _api_error(message: str, status_code: int = 400, **extras):
    payload = {"success": False, "message": message, "data": None}
    payload.update(extras)
    return jsonify(payload), status_code


def _current_faculty() -> Faculty | None:
    return Faculty.query.filter_by(user_id=current_user.id).first()


def _require_faculty_api():
    faculty = _current_faculty()
    if faculty is None:
        logger.warning("Faculty profile missing for user_id=%s", current_user.id)
        return None, _api_error("Faculty profile not found for this account.", 404)
    return faculty, None


def _require_faculty_page():
    faculty = _current_faculty()
    if faculty is None:
        logger.warning("Faculty profile missing for user_id=%s", current_user.id)
        flash("Your faculty profile is missing. Please contact the administrator.", "danger")
        return None, redirect(url_for("auth.login"))
    return faculty, None


def _parse_positive_int(value) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            return None
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _faculty_metrics(faculty: Faculty):
    subjects = Subject.query.filter_by(faculty_id=faculty.id).order_by(Subject.code.asc()).all()
    total_students = 0
    attendance_total = 0
    attendance_present = 0
    for subject in subjects:
        subject_students = Student.query.filter_by(branch=subject.branch, year=subject.year)
        if subject.semester is not None:
            subject_students = subject_students.filter_by(semester=subject.semester)
        total_students += subject_students.count()
        records = Attendance.query.filter_by(subject_id=subject.id).all()
        attendance_total += len(records)
        attendance_present += len([r for r in records if r.status == "present"])
    attendance_percentage = calculate_attendance_percentage(attendance_total, attendance_present)
    return subjects, total_students, attendance_percentage


@faculty_bp.route("/faculty/dashboard")
@login_required
@role_required("faculty")
def faculty_dashboard():
    faculty, redirect_resp = _require_faculty_page()
    if redirect_resp:
        return redirect_resp
    subjects, total_students, attendance_percentage = _faculty_metrics(faculty)
    return render_template("faculty/dashboard.html", faculty=faculty, subjects=subjects, total_students=total_students, attendance_percentage=attendance_percentage)


@faculty_bp.route("/faculty/students")
@login_required
@role_required("faculty")
def faculty_students_page():
    faculty, redirect_resp = _require_faculty_page()
    if redirect_resp:
        return redirect_resp
    subjects = Subject.query.filter_by(faculty_id=faculty.id).all()
    subject_id = request.args.get("subject_id", type=int)
    selected_subject = None
    students = []
    if subject_id:
        selected_subject = Subject.query.filter_by(id=subject_id, faculty_id=faculty.id).first()
    if not selected_subject and subjects:
        selected_subject = subjects[0]
    if selected_subject:
        students_query = Student.query.filter_by(branch=selected_subject.branch, year=selected_subject.year)
        if selected_subject.semester is not None:
            students_query = students_query.filter_by(semester=selected_subject.semester)
        students = students_query.order_by(Student.full_name.asc()).all()
    return render_template("faculty/students.html", subjects=subjects, selected_subject=selected_subject, students=students)


@faculty_bp.route("/faculty/attendance")
@login_required
@role_required("faculty")
def faculty_attendance_page():
    faculty, redirect_resp = _require_faculty_page()
    if redirect_resp:
        return redirect_resp
    subjects = Subject.query.filter_by(faculty_id=faculty.id).order_by(Subject.code.asc()).all()
    subject_id = request.args.get("subject_id", type=int)
    query = Attendance.query.join(Subject, Attendance.subject_id == Subject.id).join(Student, Attendance.student_id == Student.id)
    query = query.filter(Subject.faculty_id == faculty.id)
    if subject_id:
        query = query.filter(Attendance.subject_id == subject_id)
    records = query.order_by(Attendance.date.desc(), Attendance.time.desc()).limit(500).all()
    _, active_session = current_faculty_lecture(faculty.id, auto_start=True)
    return render_template("faculty/attendance.html", subjects=subjects, records=records, selected_subject_id=subject_id, active_session=active_session)


@faculty_bp.route("/faculty/reports")
@login_required
@role_required("faculty")
def faculty_reports_page():
    faculty, redirect_resp = _require_faculty_page()
    if redirect_resp:
        return redirect_resp
    subjects = Subject.query.filter_by(faculty_id=faculty.id).all()
    return render_template("faculty/reports.html", subjects=subjects, branches=current_app.config["BRANCHES"])


@faculty_bp.route("/faculty/attendance-report")
@login_required
@role_required("faculty")
def attendance_report_page():
    return faculty_reports_page()


def _lecture_payload(entry, session):
    if not entry or not session:
        return None
    return {
        "session": session.to_dict(),
        "timetable": {
            "id": entry.id,
            "subject_id": entry.subject_id,
            "subject_name": entry.subject.name if entry.subject else "",
            "subject_code": entry.subject.code if entry.subject else "",
            "faculty_id": entry.faculty_id,
            "department": entry.branch,
            "day_of_week": entry.day_of_week,
            "start_time": entry.start_time,
            "end_time": entry.end_time,
            "classroom": entry.classroom,
            "latitude": entry.latitude,
            "longitude": entry.longitude,
            "radius": entry.geofence_radius_meters,
        },
    }


@faculty_bp.route("/api/faculty/current-lecture")
@login_required
@role_required("faculty")
def faculty_current_lecture():
    faculty, err = _require_faculty_api()
    if err:
        return err
    entry, session, debug_info = get_current_lecture(faculty_id=faculty.id, auto_start=True)
    if not entry or not session:
        return _api_success("No active lecture", data={"lecture": None, "debug": debug_info}, lecture=None, debug=debug_info)
    lecture = _lecture_payload(entry, session)
    today_d = app_now().date()
    present_count = Attendance.query.filter_by(timetable_id=entry.id, date=today_d, status="present").count()
    if present_count == 0:
        fallback_rows = Attendance.query.filter_by(subject_id=entry.subject_id, date=today_d, status="present").all()
        present_count = len([row for row in fallback_rows if row.time and _stamp_in_slot(entry, row.time)])
    response_lecture = {
        "subject": lecture["timetable"]["subject_name"],
        "subject_code": lecture["timetable"]["subject_code"],
        "start_time": lecture["timetable"]["start_time"],
        "end_time": lecture["timetable"]["end_time"],
        "classroom": lecture["timetable"]["classroom"],
        "is_active": True,
        "timetable_id": lecture["timetable"]["id"],
        "faculty": faculty.full_name,
        "students_present": present_count,
        "location": {
            "latitude": lecture["timetable"]["latitude"],
            "longitude": lecture["timetable"]["longitude"],
            "radius": lecture["timetable"]["radius"],
        },
    }
    return _api_success(
        "Current lecture fetched successfully.",
        data={"lecture": response_lecture, "debug": debug_info},
        lecture=response_lecture,
        debug=debug_info,
    )


@faculty_bp.route("/api/faculty/previous-lectures")
@login_required
@role_required("faculty")
def faculty_previous_lectures():
    faculty, err = _require_faculty_api()
    if err:
        return err
    rows = get_previous_lectures(faculty_id=faculty.id, limit=12)
    if not rows:
        subject_ids = [subject.id for subject in Subject.query.filter_by(faculty_id=faculty.id).all()]
        if subject_ids:
            attendance_rows = (
                Attendance.query.filter(Attendance.subject_id.in_(subject_ids))
                .order_by(Attendance.date.desc(), Attendance.time.desc())
                .limit(12)
                .all()
            )
            rows = []
            for record in attendance_rows:
                weekday = record.date.strftime("%A")
                slots = (
                    TimetableEntry.query.filter_by(subject_id=record.subject_id, faculty_id=faculty.id)
                    .filter(func.lower(TimetableEntry.day_of_week) == weekday.lower())
                    .all()
                )
                slot = next((s for s in slots if record.time and _stamp_in_slot(s, record.time)), None)
                if slot is None and len(slots) == 1:
                    slot = slots[0]
                students_total = 0
                if slot:
                    students_query = Student.query.filter_by(branch=slot.branch, year=slot.year)
                    if slot.semester is not None:
                        students_query = students_query.filter_by(semester=slot.semester)
                    students_total = students_query.count()
                rows.append(
                    {
                        "timetable_id": slot.id if slot else None,
                        "subject_id": record.subject_id,
                        "subject": record.subject.name if record.subject else "",
                        "subject_code": record.subject.code if record.subject else "",
                        "faculty": faculty.full_name,
                        "date": record.date.isoformat(),
                        "start_time": slot.start_time if slot and slot.start_time else record.time.strftime("%H:%M"),
                        "end_time": slot.end_time if slot and slot.end_time else record.time.strftime("%H:%M"),
                        "classroom": slot.classroom if slot else None,
                        "status": record.status,
                        "marked": True,
                        "students_present": (
                            Attendance.query.filter_by(timetable_id=slot.id, date=record.date, status="present").count()
                            if slot
                            else Attendance.query.filter_by(subject_id=record.subject_id, date=record.date, status="present").count()
                        ),
                        "students_total": students_total if students_total else None,
                    }
                )
    return _api_success("Previous lectures fetched successfully.", data={"lectures": rows}, lectures=rows)


@faculty_bp.route("/api/faculty/start-lecture", methods=["POST"])
@login_required
@role_required("faculty")
def _close_active_sessions_for_timetable(timetable_id: int):
    """Ensure at most one active session per timetable row."""
    now = app_now()
    for sess in LectureSession.query.filter_by(timetable_id=timetable_id, is_active=True).all():
        sess.is_active = False
        sess.ended_early = True
        sess.end_time = now


def faculty_start_lecture():
    faculty, err = _require_faculty_api()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    timetable_id = _parse_positive_int(payload.get("timetable_id"))
    if timetable_id:
        entry = TimetableEntry.query.filter_by(id=timetable_id, faculty_id=faculty.id).first()
        if not entry:
            return _api_error("Timetable entry not found.", 404)
        now = app_now()
        window = _slot_window_safe(entry, now.date())
        if window:
            start_dt, end_dt = window
            if not (start_dt <= now <= end_dt):
                return _api_error("That timetable slot is not active at the current time.", 400)
        elif entry.day_of_week.strip().lower() != now.strftime("%A").lower():
            return _api_error("That timetable slot is not scheduled for today.", 400)
        try:
            _close_active_sessions_for_timetable(entry.id)
            session = LectureSession(timetable_id=entry.id, start_time=now, is_active=True, ended_early=False)
            db.session.add(session)
            db.session.commit()
        except Exception:
            logger.exception("faculty_start_lecture manual start failed timetable_id=%s", entry.id)
            db.session.rollback()
            return _api_error("Could not start lecture due to a database error.", 500)
        lecture = _lecture_payload(entry, session)
        return _api_success("Lecture started successfully.", data={"lecture": lecture, "is_active": True}, lecture=lecture, is_active=True)

    entry, session = current_faculty_lecture(faculty.id, auto_start=True)
    if not entry or not session:
        return _api_error("No scheduled lecture slot is active right now.", 400)
    lecture = _lecture_payload(entry, session)
    return _api_success("Lecture started successfully.", data={"lecture": lecture, "is_active": True}, lecture=lecture, is_active=True)


@faculty_bp.route("/api/faculty/end-lecture", methods=["POST"])
@login_required
@role_required("faculty")
def faculty_end_lecture():
    faculty, err = _require_faculty_api()
    if err:
        return err
    entry, session = current_faculty_lecture(faculty.id, auto_start=False)
    if not entry or not session:
        return _api_error("No active lecture to end.", 400)
    session.is_active = False
    session.ended_early = True
    session.end_time = app_now()
    db.session.commit()
    lecture = _lecture_payload(entry, session)
    return _api_success("Lecture ended successfully.", data={"lecture": lecture, "is_active": False}, lecture=lecture, is_active=False)


@faculty_bp.route("/api/defaulters/<int:subject_id>")
@login_required
@role_required("faculty", "admin")
def defaulters(subject_id: int):
    subject = Subject.query.get_or_404(subject_id)
    if current_user.role == "faculty":
        faculty, ferr = _require_faculty_api()
        if ferr:
            return ferr
        if subject.faculty_id != faculty.id:
            return _api_error("Forbidden.", 403)
    elif current_user.role != "admin":
        return _api_error("Forbidden.", 403)

    raw_threshold = request.args.get("threshold", current_app.config["DEFAULTER_THRESHOLD"])
    try:
        threshold = float(raw_threshold)
    except (TypeError, ValueError):
        threshold = float(current_app.config["DEFAULTER_THRESHOLD"])
    threshold = max(0.0, min(threshold, 100.0))

    students_query = Student.query.filter_by(branch=subject.branch, year=subject.year)
    if subject.semester is not None:
        students_query = students_query.filter_by(semester=subject.semester)
    students = students_query.all()
    defaulter_list = []

    for student in students:
        total = Attendance.query.filter_by(student_id=student.id, subject_id=subject.id).count()
        present = Attendance.query.filter_by(student_id=student.id, subject_id=subject.id, status="present").count()
        percent = calculate_attendance_percentage(total, present)
        if percent < threshold:
            defaulter_list.append(
                {
                    "student_id": student.id,
                    "full_name": student.full_name,
                    "enrollment_no": student.enrollment_no,
                    "attendance_percentage": percent,
                }
            )

    return _api_success(
        "Defaulter list fetched successfully.",
        data={"threshold": threshold, "defaulters": defaulter_list},
        threshold=threshold,
        defaulters=defaulter_list,
    )


@faculty_bp.route("/api/export/csv/<int:subject_id>")
@login_required
@role_required("faculty", "admin")
def export_csv(subject_id: int):
    subject = Subject.query.get_or_404(subject_id)
    if current_user.role == "faculty":
        faculty, ferr = _require_faculty_api()
        if ferr:
            return ferr
        if subject.faculty_id != faculty.id:
            return _api_error("Forbidden.", 403)
    elif current_user.role != "admin":
        return _api_error("Forbidden.", 403)
    start, end = normalize_date_range(request.args.get("start_date"), request.args.get("end_date"))
    query = Attendance.query.filter_by(subject_id=subject.id)
    if start:
        query = query.filter(Attendance.date >= start)
    if end:
        query = query.filter(Attendance.date <= end)
    records = query.order_by(Attendance.date.desc()).all()

    rows = []
    for record in records:
        rows.append(
            {
                "attendance_id": record.id,
                "student_id": record.student_id,
                "student_name": record.student.full_name,
                "enrollment_no": record.student.enrollment_no,
                "subject_code": subject.code,
                "subject_name": subject.name,
                "date": record.date.isoformat(),
                "time": record.time.isoformat(),
                "status": record.status,
                "face_verified": record.face_verified,
                "gps_verified": record.gps_verified,
                "latitude": record.latitude,
                "longitude": record.longitude,
            }
        )

    stream = attendance_rows_to_csv(rows)
    return send_file(stream, mimetype="text/csv", as_attachment=True, download_name=f"{subject.code}_attendance.csv")


@faculty_bp.route("/api/faculty/attendance-summary")
@login_required
@role_required("faculty")
def attendance_summary():
    faculty, err = _require_faculty_api()
    if err:
        return err
    subject_id = request.args.get("subject_id", type=int)
    branch = request.args.get("branch")
    year = request.args.get("year", type=int)
    semester = request.args.get("semester", type=int)
    start, end = normalize_date_range(request.args.get("start_date"), request.args.get("end_date"))

    query = Attendance.query.join(Subject, Attendance.subject_id == Subject.id).join(Student, Attendance.student_id == Student.id)
    query = query.filter(Subject.faculty_id == faculty.id)
    if subject_id:
        query = query.filter(Attendance.subject_id == subject_id)
    if branch:
        query = query.filter(Student.branch == branch)
    if year:
        query = query.filter(Student.year == year)
    if semester:
        query = query.filter(Subject.semester == semester)
    if start:
        query = query.filter(Attendance.date >= start)
    if end:
        query = query.filter(Attendance.date <= end)

    records = query.all()
    grouped = {}
    for rec in records:
        key = rec.student_id
        grouped.setdefault(
            key,
            {
                "student_id": rec.student_id,
                "full_name": rec.student.full_name,
                "enrollment_no": rec.student.enrollment_no,
                "present": 0,
                "total": 0,
            },
        )
        grouped[key]["total"] += 1
        if rec.status == "present":
            grouped[key]["present"] += 1

    result = []
    for row in grouped.values():
        row["attendance_percentage"] = calculate_attendance_percentage(row["total"], row["present"])
        result.append(row)
    result.sort(key=lambda x: x["attendance_percentage"])

    return _api_success("Attendance summary fetched successfully.", data={"rows": result}, rows=result)


@faculty_bp.route("/api/faculty/subjects")
@login_required
@role_required("faculty")
def faculty_subjects():
    faculty, err = _require_faculty_api()
    if err:
        return err
    subjects = Subject.query.filter_by(faculty_id=faculty.id).order_by(Subject.code.asc()).all()
    rows = [subject.to_dict() for subject in subjects]
    return _api_success("Assigned subjects fetched successfully.", data={"subjects": rows}, subjects=rows)


@faculty_bp.route("/api/faculty/students")
@login_required
@role_required("faculty")
def faculty_students():
    faculty, err = _require_faculty_api()
    if err:
        return err
    subject_id = request.args.get("subject_id", type=int)
    branch = request.args.get("branch")
    year = request.args.get("year", type=int)
    semester = request.args.get("semester", type=int)

    query = Student.query
    if subject_id:
        subject = Subject.query.filter_by(id=subject_id, faculty_id=faculty.id).first()
        if not subject:
            return _api_error("Subject not found for current faculty.", 404)
        query = query.filter_by(branch=subject.branch, year=subject.year)
        if subject.semester is not None:
            query = query.filter_by(semester=subject.semester)
    else:
        faculty_subjects = Subject.query.filter_by(faculty_id=faculty.id).all()
        if not faculty_subjects:
            return _api_success("No students found for faculty subjects.", data={"students": []}, students=[])
        branch_year_pairs = {(s.branch, s.year, s.semester) for s in faculty_subjects}
        filters = []
        for b, y, sem in branch_year_pairs:
            clause = (Student.branch == b) & (Student.year == y)
            if sem is not None:
                clause = clause & (Student.semester == sem)
            filters.append(clause)
        if filters:
            query = query.filter(or_(*filters))

    if branch:
        query = query.filter(Student.branch == branch)
    if year:
        query = query.filter(Student.year == year)
    if semester:
        query = query.filter(Student.semester == semester)

    students = query.order_by(Student.full_name.asc()).all()
    rows = [student.to_dict() for student in students]
    return _api_success("Student list fetched successfully.", data={"students": rows}, students=rows)


@faculty_bp.route("/api/faculty/reports")
@login_required
@role_required("faculty")
def faculty_reports_alias():
    return attendance_summary()
