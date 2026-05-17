import logging
from datetime import date, datetime, timezone

import numpy as np
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from zoneinfo import ZoneInfo

from face_module import FaceEncodingError, compare_face_encodings, decode_base64_to_image, extract_face_encoding, extract_face_location
from models import db
from models.attendance import Attendance
from models.faculty import Faculty
from models.student import Student
from models.subject import Subject
from models.timetable import TimetableEntry
from utils.decorators import role_required
from utils.lecture import current_student_lecture, get_current_lecture, get_previous_lectures
from utils.helpers import calculate_attendance_percentage, calculate_haversine_distance, check_basic_liveness

student_bp = Blueprint("student", __name__)
logger = logging.getLogger(__name__)
WEEKDAY_ORDER = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5, "Saturday": 6}


def _api_success(message: str, data=None, status_code: int = 200, **extras):
    payload = {"success": True, "message": message, "data": data}
    payload.update(extras)
    return jsonify(payload), status_code


def _api_error(message: str, status_code: int = 400, data=None, **extras):
    payload = {"success": False, "message": message, "data": data}
    payload.update(extras)
    return jsonify(payload), status_code


def _current_student() -> Student | None:
    return Student.query.filter_by(user_id=current_user.id).first()


def _require_student_api():
    student = _current_student()
    if student is None:
        logger.warning("Student profile missing for user_id=%s", current_user.id)
        return None, _api_error("Student profile not found for this account.", 404)
    return student, None


def _require_student_page():
    student = _current_student()
    if student is None:
        logger.warning("Student profile missing for user_id=%s", current_user.id)
        flash("Your student profile is missing. Please contact the administrator.", "danger")
        return None, redirect(url_for("auth.login"))
    return student, None


def _faculty_may_access_student(faculty: Faculty, target: Student) -> bool:
    for subj in Subject.query.filter_by(faculty_id=faculty.id).all():
        if subj.branch != target.branch or subj.year != target.year:
            continue
        if target.semester is not None and subj.semester is not None and subj.semester != target.semester:
            continue
        return True
    return False


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


def _parse_latitude_longitude(lat, lng) -> tuple[float, float] | None:
    try:
        la = float(lat)
        lo = float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90 <= la <= 90 and -180 <= lo <= 180):
        return None
    return la, lo


def _record_covers_timetable_slot(record: Attendance, slot: TimetableEntry) -> bool:
    if record.subject_id != slot.subject_id:
        return False
    if record.timetable_id and record.timetable_id == slot.id:
        return True
    if not record.timetable_id and slot.start_time and slot.end_time:
        return _slot_match_for_timestamp(slot, record.time)
    return False


def _slot_match_for_timestamp(entry: TimetableEntry, stamp: datetime) -> bool:
    if not entry.start_time or not entry.end_time:
        return False
    try:
        start_time = datetime.strptime(entry.start_time, "%H:%M").time()
        end_time = datetime.strptime(entry.end_time, "%H:%M").time()
    except ValueError:
        return False
    value = stamp.time()
    return start_time <= value <= end_time


def _format_local_mark_time(stamp: datetime) -> str:
    tz_name = current_app.config.get("APP_TIMEZONE", "Asia/Kolkata")
    try:
        target_tz = ZoneInfo(tz_name)
    except Exception:
        target_tz = ZoneInfo("Asia/Kolkata")

    if stamp.tzinfo is None:
        aware = stamp.replace(tzinfo=timezone.utc)
    else:
        aware = stamp
    return aware.astimezone(target_tz).strftime("%H:%M:%S")


@student_bp.route("/student/dashboard")
@login_required
@role_required("student")
def student_dashboard():
    student, redirect_resp = _require_student_page()
    if redirect_resp:
        return redirect_resp
    subjects_query = Subject.query.filter_by(branch=student.branch, year=student.year)
    if student.semester:
        subjects_query = subjects_query.filter_by(semester=student.semester)
    subjects = subjects_query.all()
    subject_cards = []
    today = date.today()
    weekday = today.strftime("%A")
    today_slots_query = TimetableEntry.query.filter(func.lower(TimetableEntry.day_of_week) == weekday.lower()).filter_by(
        branch=student.branch, year=student.year
    )
    if student.semester is not None:
        today_slots_query = today_slots_query.filter((TimetableEntry.semester == student.semester) | (TimetableEntry.semester.is_(None)))
    else:
        today_slots_query = today_slots_query.filter(TimetableEntry.semester.is_(None))
    today_slots = today_slots_query.all()
    slots_by_subject: dict[int, list[TimetableEntry]] = {}
    for slot in today_slots:
        slots_by_subject.setdefault(slot.subject_id, []).append(slot)

    def _matches_any_slot(record: Attendance, slots: list[TimetableEntry]) -> bool:
        if record.timetable_id and any(slot.id == record.timetable_id for slot in slots):
            return True
        if not record.timetable_id and any(_slot_match_for_timestamp(slot, record.time) for slot in slots):
            return True
        return False

    for subject in subjects:
        total = Attendance.query.filter_by(student_id=student.id, subject_id=subject.id).count()
        present = Attendance.query.filter_by(student_id=student.id, subject_id=subject.id, status="present").count()
        subject_today_records = Attendance.query.filter_by(student_id=student.id, subject_id=subject.id, date=today).all()
        subject_slots = slots_by_subject.get(subject.id, [])
        marked_today = any(_matches_any_slot(record, subject_slots) for record in subject_today_records) if subject_slots else bool(subject_today_records)
        subject_cards.append(
            {
                "subject": subject,
                "percentage": calculate_attendance_percentage(total, present),
                "today_marked": marked_today,
            }
        )
    # Keep template cards rich (with ORM subject) and pass a JSON-safe copy for Chart.js.
    subject_cards_json = [
        {
            "subject": {"code": card["subject"].code, "name": card["subject"].name},
            "percentage": card["percentage"],
            "today_marked": card["today_marked"],
        }
        for card in subject_cards
    ]

    current_entry, current_session = current_student_lecture(student)
    all_today_records = Attendance.query.filter_by(student_id=student.id, date=today).all()
    if current_entry and current_session:
        current_marked = any(_record_covers_timetable_slot(record, current_entry) for record in all_today_records)
        today_status = "Marked" if current_marked else "Pending"
    elif today_slots:
        covered_count = sum(
            1 for slot in today_slots if any(_record_covers_timetable_slot(record, slot) for record in all_today_records)
        )
        if covered_count >= len(today_slots):
            today_status = "Marked"
        elif covered_count > 0:
            today_status = "Partial"
        else:
            today_status = "Pending"
    else:
        today_status = "Pending"
    attendance_history = (
        Attendance.query.filter_by(student_id=student.id)
        .order_by(Attendance.date.desc(), Attendance.time.desc())
        .limit(8)
        .all()
    )
    avg_attendance = round(sum(card["percentage"] for card in subject_cards) / len(subject_cards), 2) if subject_cards else 0
    last_record = attendance_history[0] if attendance_history else None
    timetable_q = TimetableEntry.query.filter_by(branch=student.branch, year=student.year)
    if student.semester is not None:
        timetable_q = timetable_q.filter((TimetableEntry.semester == student.semester) | (TimetableEntry.semester.is_(None)))
    else:
        timetable_q = timetable_q.filter(TimetableEntry.semester.is_(None))
    timetable_entries = timetable_q.all()
    timetable_entries.sort(
        key=lambda e: (
            WEEKDAY_ORDER.get(e.day_of_week, 99),
            e.start_time if e.start_time else f"{e.period_no:02d}:00",
        )
    )
    return render_template(
        "student/dashboard.html",
        student=student,
        subject_cards=subject_cards,
        subject_cards_json=subject_cards_json,
        today_status=today_status,
        attendance_history=attendance_history,
        avg_attendance=avg_attendance,
        last_record=last_record,
        timetable_entries=timetable_entries,
    )


@student_bp.route("/student/register-face")
@login_required
@role_required("student")
def register_face_page():
    return render_template("student/register_face.html")


@student_bp.route("/student/mark-attendance")
@login_required
@role_required("student")
def mark_attendance_page():
    student, redirect_resp = _require_student_page()
    if redirect_resp:
        return redirect_resp
    entry, session, _ = get_current_lecture(
        department=student.branch,
        year=student.year,
        semester=student.semester if student.semester else None,
        auto_start=True,
    )
    if not entry or not session or not session.is_active:
        flash("No lecture running currently. Attendance page is available only during active lecture.", "warning")
        return redirect(url_for("student.student_dashboard"))

    subjects_query = Subject.query.filter_by(branch=student.branch, year=student.year)
    if student.semester:
        subjects_query = subjects_query.filter_by(semester=student.semester)
    subjects = subjects_query.all()
    return render_template("student/attendance.html", subjects=subjects)


@student_bp.route("/student/attendance")
@login_required
@role_required("student")
def student_attendance_page():
    return mark_attendance_page()


@student_bp.route("/student/history")
@login_required
@role_required("student")
def student_history_page():
    student, redirect_resp = _require_student_page()
    if redirect_resp:
        return redirect_resp
    records = (
        Attendance.query.filter_by(student_id=student.id)
        .order_by(Attendance.date.desc(), Attendance.time.desc())
        .all()
    )
    return render_template("student/history.html", records=records)


@student_bp.route("/student/profile")
@login_required
@role_required("student")
def student_profile_page():
    student, redirect_resp = _require_student_page()
    if redirect_resp:
        return redirect_resp
    return render_template("student/profile.html", student=student, user=current_user)


@student_bp.route("/api/register-face", methods=["POST"])
@login_required
@role_required("student")
def register_face():
    payload = request.get_json(silent=True) or {}
    images = payload.get("images", [])
    if not isinstance(images, list) or len(images) != current_app.config["MAX_FACE_IMAGES"]:
        return _api_error(f"Exactly {current_app.config['MAX_FACE_IMAGES']} images are required.", 400)

    encodings = []
    locations = []

    try:
        for image_base64 in images:
            rgb_image = decode_base64_to_image(image_base64)
            locations.append(extract_face_location(rgb_image))
            encodings.append(extract_face_encoding(rgb_image))
    except FaceEncodingError as exc:
        logger.warning("Face registration failed user_id=%s reason=%s", current_user.id, str(exc))
        return _api_error(str(exc), 400)
    except Exception:
        logger.exception("Unexpected face registration error user_id=%s", current_user.id)
        return _api_error("Could not process face images.", 500)

    if not check_basic_liveness(locations):
        return _api_error("Liveness check failed. Move your head slightly while capturing.", 400)

    student, err = _require_student_api()
    if err:
        return err
    average_encoding = np.mean(np.array(encodings), axis=0).tolist()
    student.face_encoding = average_encoding
    student.face_registered = True
    db.session.commit()
    return _api_success("Face registered successfully.")


@student_bp.route("/api/mark-attendance", methods=["POST"])
@login_required
@role_required("student")
def mark_attendance():
    student, err = _require_student_api()
    if err:
        return err
    if not student.face_registered or not student.face_encoding:
        return _api_error("Please register your face first.", 400)

    payload = request.get_json(silent=True) or {}
    subject_id_raw = payload.get("subject_id")
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    image_base64 = payload.get("image")

    if not all(v is not None for v in [subject_id_raw, latitude, longitude, image_base64]):
        return _api_error("Subject, GPS, and image are required.", 400)
    if not isinstance(image_base64, str) or not image_base64.strip():
        return _api_error("A valid face image payload is required.", 400)

    coords = _parse_latitude_longitude(latitude, longitude)
    if coords is None:
        return _api_error("Invalid latitude or longitude.", 400)
    latitude_f, longitude_f = coords

    requested_subject_id = _parse_positive_int(subject_id_raw)
    if requested_subject_id is None:
        return _api_error("Invalid subject.", 400)

    entry, session = current_student_lecture(student, subject_id=requested_subject_id)
    if not entry or not session or not session.is_active:
        return _api_error("Attendance allowed only during lecture.", 400)
    subject = entry.subject
    if not subject:
        return _api_error("Invalid subject selection.", 400)
    if subject.id != requested_subject_id:
        return _api_error("Subject does not match the active lecture.", 400)
    if subject.branch != student.branch or subject.year != student.year:
        return _api_error("Subject is not part of your cohort.", 403)
    if student.semester is not None and subject.semester is not None and subject.semester != student.semester:
        return _api_error("Subject is not part of your cohort.", 403)

    today = date.today()
    existing = Attendance.query.filter_by(student_id=student.id, timetable_id=entry.id, date=today).first()
    if not existing:
        # Legacy fallback for records created before timetable_id migration.
        legacy_rows = Attendance.query.filter_by(student_id=student.id, subject_id=subject.id, date=today).all()
        existing = next((row for row in legacy_rows if _slot_match_for_timestamp(entry, row.time)), None)
    if existing:
        return _api_error(f"Already marked at {existing.time.strftime('%H:%M')}.", 409)

    lecture_slot = entry
    target_lat = lecture_slot.latitude if lecture_slot and lecture_slot.latitude is not None else current_app.config["COLLEGE_LAT"]
    target_lng = lecture_slot.longitude if lecture_slot and lecture_slot.longitude is not None else current_app.config["COLLEGE_LNG"]
    target_radius = (
        lecture_slot.geofence_radius_meters
        if lecture_slot and lecture_slot.geofence_radius_meters is not None
        else current_app.config["GEOFENCE_RADIUS_METERS"]
    )

    distance = calculate_haversine_distance(latitude_f, longitude_f, target_lat, target_lng)
    if distance > target_radius:
        location_label = lecture_slot.classroom if lecture_slot and lecture_slot.classroom else "assigned lecture location"
        return _api_error(
            f"Outside geofence by {round(distance, 2)} meters from {location_label}.",
            400,
            data={"gps_verified": False, "distance": round(distance, 2)},
            gps_verified=False,
            distance=round(distance, 2),
        )

    try:
        rgb_image = decode_base64_to_image(image_base64)
        live_encoding = extract_face_encoding(rgb_image)
        result = compare_face_encodings(student.face_encoding, live_encoding, tolerance=current_app.config["FACE_TOLERANCE"])
    except FaceEncodingError as exc:
        return _api_error(str(exc), 400)
    except Exception:
        logger.exception("Attendance face verification failed user_id=%s", current_user.id)
        return _api_error("Face verification failed.", 500)

    logger.info(
        "Face verification user_id=%s match=%s confidence=%s distance=%s",
        current_user.id,
        result["match"],
        result["confidence"],
        result["distance"],
    )
    if not result["match"]:
        return _api_error(
            "Face not matched.",
            401,
            data={"face_verified": False, "confidence": result["confidence"]},
            face_verified=False,
            confidence=result["confidence"],
        )

    attendance = Attendance(
        student_id=student.id,
        subject_id=subject.id,
        timetable_id=entry.id,
        latitude=latitude_f,
        longitude=longitude_f,
        face_verified=True,
        gps_verified=True,
        status="present",
    )
    db.session.add(attendance)
    db.session.commit()
    logger.info("Attendance marked student_id=%s subject_id=%s", student.id, subject.id)

    response_data = {
        "lecture_session_id": session.id,
        "timetable_id": entry.id,
        "gps_verified": True,
        "face_verified": True,
        "confidence": result["confidence"],
        "distance": round(distance, 2),
        "classroom": lecture_slot.classroom if lecture_slot and lecture_slot.classroom else None,
    }
    return _api_success(
        "Attendance marked successfully.",
        data=response_data,
        gps_verified=True,
        face_verified=True,
        confidence=result["confidence"],
        distance=round(distance, 2),
        classroom=response_data["classroom"],
        lecture_session_id=session.id,
        timetable_id=entry.id,
    )


@student_bp.route("/api/attendance/<int:student_id>")
@login_required
def get_attendance(student_id: int):
    if current_user.role == "student":
        student, err = _require_student_api()
        if err:
            return err
        if student_id != student.id:
            return _api_error("Forbidden", 403)
    elif current_user.role == "admin":
        pass
    elif current_user.role == "faculty":
        faculty = Faculty.query.filter_by(user_id=current_user.id).first()
        if not faculty:
            return _api_error("Faculty profile not found.", 404)
        target = Student.query.get(student_id)
        if not target:
            return _api_error("Student not found.", 404)
        if not _faculty_may_access_student(faculty, target):
            return _api_error("Forbidden", 403)
    else:
        return _api_error("Forbidden", 403)

    records = Attendance.query.filter_by(student_id=student_id).order_by(Attendance.date.desc(), Attendance.time.desc()).all()
    rows = [r.to_dict() for r in records]
    return _api_success("Attendance records fetched successfully.", data={"records": rows}, records=rows)


@student_bp.route("/api/student/attendance", methods=["POST"])
@login_required
@role_required("student")
def student_attendance_alias():
    return mark_attendance()


@student_bp.route("/api/student/mark-attendance", methods=["POST"])
@login_required
@role_required("student")
def student_mark_attendance_alias():
    return mark_attendance()


@student_bp.route("/api/student/history")
@login_required
@role_required("student")
def student_history():
    student, err = _require_student_api()
    if err:
        return err
    records = (
        Attendance.query.filter_by(student_id=student.id)
        .order_by(Attendance.date.desc(), Attendance.time.desc())
        .all()
    )
    rows = [record.to_dict() for record in records]
    return _api_success("Attendance history fetched successfully.", data={"records": rows}, records=rows)


@student_bp.route("/api/student/profile")
@login_required
@role_required("student")
def student_profile():
    student, err = _require_student_api()
    if err:
        return err
    profile = student.to_dict()
    profile["email"] = current_user.email
    return _api_success("Student profile fetched successfully.", data=profile, profile=profile)


@student_bp.route("/api/student/current-lecture")
@login_required
@role_required("student")
def student_current_lecture():
    student, err = _require_student_api()
    if err:
        return err
    entry, session, debug_info = get_current_lecture(
        department=student.branch,
        year=student.year,
        semester=student.semester if student.semester else None,
        now=None,
        auto_start=True,
    )
    if not entry or not session:
        logger.info("student_current_lecture no-active user_id=%s debug=%s", current_user.id, debug_info)
        return _api_success(
            "No active lecture.",
            data={"lecture": None, "debug": debug_info},
            lecture=None,
            debug=debug_info,
        )
    lecture = {
        "subject": entry.subject.name if entry.subject else "",
        "subject_code": entry.subject.code if entry.subject else "",
        "subject_id": entry.subject_id,
        "start_time": entry.start_time,
        "end_time": entry.end_time,
        "classroom": entry.classroom,
        "is_active": True,
        "timetable_id": entry.id,
        "faculty": entry.faculty.full_name if entry.faculty else "",
        "location": {"latitude": entry.latitude, "longitude": entry.longitude, "radius": entry.geofence_radius_meters},
    }
    today_record = Attendance.query.filter_by(student_id=student.id, timetable_id=entry.id, date=date.today()).first()
    if not today_record:
        # Legacy fallback for pre-migration records.
        legacy_rows = Attendance.query.filter_by(student_id=student.id, subject_id=entry.subject_id, date=date.today()).all()
        today_record = next((row for row in legacy_rows if _slot_match_for_timestamp(entry, row.time)), None)
    lecture["already_marked"] = bool(today_record)
    lecture["marked_at"] = _format_local_mark_time(today_record.time) if today_record else None
    logger.info("student_current_lecture active user_id=%s timetable_id=%s", current_user.id, entry.id)
    return _api_success("Current lecture fetched successfully.", data={"lecture": lecture, "debug": debug_info}, lecture=lecture, debug=debug_info)


@student_bp.route("/api/student/previous-lectures")
@login_required
@role_required("student")
def student_previous_lectures():
    student, err = _require_student_api()
    if err:
        return err
    rows = get_previous_lectures(
        department=student.branch,
        year=student.year,
        semester=student.semester if student.semester else None,
        student_id=student.id,
        limit=12,
    )
    if not rows:
        attendance_rows = (
            Attendance.query.filter_by(student_id=student.id)
            .order_by(Attendance.date.desc(), Attendance.time.desc())
            .limit(12)
            .all()
        )
        rows = []
        for record in attendance_rows:
            weekday = record.date.strftime("%A")
            timetable_query = TimetableEntry.query.filter_by(subject_id=record.subject_id, branch=student.branch, year=student.year)
            timetable_query = timetable_query.filter(func.lower(TimetableEntry.day_of_week) == weekday.lower())
            if student.semester is not None:
                timetable_query = timetable_query.filter((TimetableEntry.semester == student.semester) | (TimetableEntry.semester.is_(None)))
            else:
                timetable_query = timetable_query.filter(TimetableEntry.semester.is_(None))
            slots = timetable_query.all()
            matched_slot = next((slot for slot in slots if _slot_match_for_timestamp(slot, record.time)), None)
            selected_slot = matched_slot or (slots[0] if slots else None)
            fac_name = ""
            if selected_slot and selected_slot.faculty:
                fac_name = selected_slot.faculty.full_name or ""
            elif record.subject and record.subject.faculty:
                fac_name = record.subject.faculty.full_name or ""
            rows.append(
                {
                    "timetable_id": selected_slot.id if selected_slot else None,
                    "subject_id": record.subject_id,
                    "subject": (record.subject.name if record.subject else "") or "",
                    "subject_code": (record.subject.code if record.subject else "") or "",
                    "faculty": fac_name,
                    "date": record.date.isoformat(),
                    "start_time": selected_slot.start_time if selected_slot and selected_slot.start_time else record.time.strftime("%H:%M"),
                    "end_time": selected_slot.end_time if selected_slot and selected_slot.end_time else record.time.strftime("%H:%M"),
                    "classroom": selected_slot.classroom if selected_slot else None,
                    "status": record.status,
                    "marked": True,
                    "students_present": None,
                    "students_total": None,
                }
            )
    logger.info("student_previous_lectures user_id=%s count=%s", current_user.id, len(rows))
    return _api_success("Previous lectures fetched successfully.", data={"lectures": rows}, lectures=rows)
