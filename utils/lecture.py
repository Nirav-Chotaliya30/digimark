import logging
from datetime import date, datetime, timedelta, timezone

from flask import current_app
from models.attendance import Attendance
from models import db
from models.lecture_session import LectureSession
from models.student import Student
from models.timetable import TimetableEntry
from sqlalchemy import func
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
WEEKDAY_ORDER = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6}


def app_now() -> datetime:
    tz_name = current_app.config.get("APP_TIMEZONE", "Asia/Kolkata")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    now_local = datetime.now(timezone.utc).astimezone(tz)
    # Keep datetime naive in local timezone for compatibility with existing model fields.
    return now_local.replace(tzinfo=None)


def _slot_window(entry: TimetableEntry, on_date: date):
    start_dt = datetime.combine(on_date, datetime.strptime(entry.start_time, "%H:%M").time())
    end_dt = datetime.combine(on_date, datetime.strptime(entry.end_time, "%H:%M").time())
    return start_dt, end_dt


def _slot_window_safe(entry: TimetableEntry, on_date: date):
    if not entry.start_time or not entry.end_time:
        return None
    try:
        return _slot_window(entry, on_date)
    except (ValueError, TypeError):
        logger.warning("Invalid timetable times timetable_id=%s start=%s end=%s", entry.id, entry.start_time, entry.end_time)
        return None


def _stamp_in_slot(entry: TimetableEntry, stamp: datetime) -> bool:
    if not entry.start_time or not entry.end_time:
        return False
    try:
        start_time = datetime.strptime(entry.start_time, "%H:%M").time()
        end_time = datetime.strptime(entry.end_time, "%H:%M").time()
    except ValueError:
        return False
    return start_time <= stamp.time() <= end_time


def _matching_entries(branch: str, year: int, semester: int | None, now: datetime, subject_id: int | None = None, faculty_id: int | None = None):
    weekday = now.strftime("%A")
    query = TimetableEntry.query.filter(func.lower(TimetableEntry.day_of_week) == weekday.lower()).filter_by(branch=branch, year=year)
    if semester is not None:
        # Allow timetable slots configured as generic (semester NULL) to match.
        query = query.filter((TimetableEntry.semester == semester) | (TimetableEntry.semester.is_(None)))
    if subject_id:
        query = query.filter_by(subject_id=subject_id)
    if faculty_id:
        query = query.filter_by(faculty_id=faculty_id)
    entries = query.all()
    active_slots = []
    for entry in entries:
        window = _slot_window_safe(entry, now.date())
        if not window:
            continue
        start_dt, end_dt = window
        if start_dt <= now <= end_dt:
            active_slots.append((entry, start_dt, end_dt))
    return active_slots


def _get_today_session(entry_id: int, on_date: date):
    start_of_day = datetime.combine(on_date, datetime.min.time())
    end_of_day = datetime.combine(on_date, datetime.max.time())
    return (
        LectureSession.query.filter_by(timetable_id=entry_id)
        .filter(LectureSession.start_time >= start_of_day, LectureSession.start_time <= end_of_day)
        .order_by(LectureSession.start_time.desc())
        .first()
    )


def ensure_active_session(entry: TimetableEntry, start_dt: datetime, end_dt: datetime, now: datetime | None = None, auto_start: bool = True):
    now = now or app_now()
    today_session = _get_today_session(entry.id, now.date())

    if today_session and today_session.is_active and now > end_dt:
        today_session.is_active = False
        today_session.end_time = now
        db.session.commit()
        return None

    if today_session and today_session.is_active:
        return today_session

    if today_session and today_session.ended_early:
        return None

    if auto_start:
        session = LectureSession(timetable_id=entry.id, start_time=max(now, start_dt), is_active=True, ended_early=False)
        db.session.add(session)
        db.session.commit()
        return session
    return None


def get_current_lecture(
    department: str | None = None,
    faculty_id: int | None = None,
    year: int | None = None,
    semester: int | None = None,
    subject_id: int | None = None,
    now: datetime | None = None,
    auto_start: bool = True,
):
    """
    Returns (timetable_entry, lecture_session, debug_info).
    """
    now = now or app_now()
    weekday = now.strftime("%A")
    current_time = now.strftime("%H:%M")
    debug_info = {"day": weekday, "time": current_time, "matches": []}

    if faculty_id:
        query = TimetableEntry.query.filter(func.lower(TimetableEntry.day_of_week) == weekday.lower()).filter_by(faculty_id=faculty_id)
    else:
        query = TimetableEntry.query.filter(func.lower(TimetableEntry.day_of_week) == weekday.lower()).filter_by(branch=department, year=year)
        if semester is not None:
            query = query.filter((TimetableEntry.semester == semester) | (TimetableEntry.semester.is_(None)))
        else:
            query = query.filter(TimetableEntry.semester.is_(None))

    if subject_id:
        query = query.filter_by(subject_id=subject_id)

    entries = query.all()
    for entry in entries:
        window = _slot_window_safe(entry, now.date())
        in_window = False
        start_dt = end_dt = None
        if window:
            start_dt, end_dt = window
            in_window = bool(start_dt <= now <= end_dt)
        debug_info["matches"].append(
            {
                "timetable_id": entry.id,
                "subject_id": entry.subject_id,
                "faculty_id": entry.faculty_id,
                "department": entry.branch,
                "start_time": entry.start_time,
                "end_time": entry.end_time,
                "in_window": in_window,
            }
        )
        if not window or not in_window:
            continue
        session = ensure_active_session(entry, start_dt, end_dt, now=now, auto_start=auto_start)
        if session and session.is_active:
            logger.info("Current lecture detected day=%s time=%s timetable_id=%s faculty_id=%s subject_id=%s", weekday, current_time, entry.id, entry.faculty_id, entry.subject_id)
            return entry, session, debug_info

    logger.info("No current lecture day=%s time=%s evaluated_slots=%s", weekday, current_time, len(debug_info["matches"]))
    return None, None, debug_info


def current_student_lecture(student, now: datetime | None = None, subject_id: int | None = None):
    now = now or app_now()
    entry, session, _ = get_current_lecture(
        department=student.branch,
        year=student.year,
        semester=student.semester if student.semester else None,
        subject_id=subject_id,
        now=now,
        auto_start=True,
    )
    if entry and session:
        return entry, session
    return None, None


def current_faculty_lecture(faculty_id: int, now: datetime | None = None, auto_start: bool = True):
    now = now or app_now()
    entry, session, _ = get_current_lecture(faculty_id=faculty_id, now=now, auto_start=auto_start)
    if entry and session:
        return entry, session
    return None, None


def _last_date_for_weekday(target_weekday: str, now: datetime):
    target = WEEKDAY_ORDER.get((target_weekday or "").strip(), None)
    if target is None:
        return None
    delta = (now.weekday() - target) % 7
    candidate = now.date() - timedelta(days=delta)
    if delta == 0:
        # Same day: keep only ended slots.
        return candidate
    return candidate


def get_previous_lectures(
    department: str | None = None,
    faculty_id: int | None = None,
    year: int | None = None,
    semester: int | None = None,
    student_id: int | None = None,
    now: datetime | None = None,
    limit: int = 10,
):
    now = now or app_now()
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        lim = 10
    limit = max(1, min(lim, 50))

    if faculty_id:
        query = TimetableEntry.query.filter_by(faculty_id=faculty_id)
    else:
        query = TimetableEntry.query.filter_by(branch=department, year=year)
        if semester is not None:
            query = query.filter((TimetableEntry.semester == semester) | (TimetableEntry.semester.is_(None)))
        else:
            query = query.filter(TimetableEntry.semester.is_(None))

    rows = []
    for entry in query.all():
        lecture_date = _last_date_for_weekday(entry.day_of_week, now)
        if lecture_date is None:
            continue
        window = _slot_window_safe(entry, lecture_date)
        if not window:
            continue
        start_dt, end_dt = window
        if end_dt >= now:
            continue

        status = "not_marked"
        marked = False
        students_present = None
        students_total = None

        if student_id:
            record = Attendance.query.filter_by(student_id=student_id, timetable_id=entry.id, date=lecture_date).first()
            if not record:
                # Legacy fallback for records created before timetable_id tracking.
                candidates = Attendance.query.filter_by(student_id=student_id, subject_id=entry.subject_id, date=lecture_date).all()
                record = next((item for item in candidates if _stamp_in_slot(entry, item.time)), None)
            if record:
                marked = True
                status = record.status
        else:
            students_query = Student.query.filter_by(branch=entry.branch, year=entry.year)
            if entry.semester is not None:
                students_query = students_query.filter_by(semester=entry.semester)
            students_total = students_query.count()
            students_present = Attendance.query.filter_by(timetable_id=entry.id, date=lecture_date, status="present").count()
            if students_present == 0:
                # Legacy fallback for records without timetable_id.
                fallback_rows = Attendance.query.filter_by(subject_id=entry.subject_id, date=lecture_date, status="present").all()
                students_present = len([row for row in fallback_rows if _stamp_in_slot(entry, row.time)])

        rows.append(
            {
                "timetable_id": entry.id,
                "subject_id": entry.subject_id,
                "subject": entry.subject.name if entry.subject else "",
                "subject_code": entry.subject.code if entry.subject else "",
                "faculty": entry.faculty.full_name if entry.faculty else "",
                "date": lecture_date.isoformat(),
                "start_time": entry.start_time,
                "end_time": entry.end_time,
                "classroom": entry.classroom,
                "status": status,
                "marked": marked,
                "students_present": students_present,
                "students_total": students_total,
            }
        )

    rows.sort(key=lambda item: (item["date"], item["end_time"]), reverse=True)
    return rows[:limit]
