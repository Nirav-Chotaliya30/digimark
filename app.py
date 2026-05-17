import logging
import os
from datetime import date, datetime, timezone

from flask import Flask
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_login import LoginManager
from sqlalchemy import text
from zoneinfo import ZoneInfo

from config import Config
from models import db

bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"


def configure_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.FileHandler("logs/digimark.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def seed_admin() -> None:
    from models.user import User
    from models.department import Department
    from models.student import Student  # noqa: F401
    from models.faculty import Faculty  # noqa: F401
    from models.subject import Subject  # noqa: F401
    from models.attendance import Attendance  # noqa: F401
    from models.timetable import TimetableEntry  # noqa: F401

    admin_email = "admin@digimark.com"
    admin_password = "Admin@123"

    if not Department.query.first():
        for branch in Config.BRANCHES:
            db.session.add(Department(name=branch))
        db.session.commit()
        logging.getLogger(__name__).info("Seeded default departments.")

    existing = User.query.filter_by(email=admin_email).first()
    if existing:
        return

    user = User(username="admin", email=admin_email, role="admin")
    user.set_password(admin_password)
    db.session.add(user)
    db.session.commit()
    logging.getLogger(__name__).info("Seeded default admin account: %s", admin_email)


def migrate_legacy_year_to_passout_year() -> None:
    from models.student import Student
    from models.subject import Subject

    current_year = date.today().year

    def convert(value: int) -> int:
        if 1 <= value <= 4:
            return current_year + (4 - value)
        return value

    student_updates = 0
    for student in Student.query.all():
        converted = convert(student.year)
        if converted != student.year:
            student.year = converted
            student_updates += 1

    subject_updates = 0
    for subject in Subject.query.all():
        converted = convert(subject.year)
        if converted != subject.year:
            subject.year = converted
            subject_updates += 1

    if student_updates or subject_updates:
        db.session.commit()
        logging.getLogger(__name__).info(
            "Migrated legacy year values to passout year. students=%s subjects=%s",
            student_updates,
            subject_updates,
        )


def ensure_semester_columns() -> None:
    inspector_queries = {
        "students": "ALTER TABLE students ADD COLUMN semester INTEGER",
        "subjects": "ALTER TABLE subjects ADD COLUMN semester INTEGER",
    }
    for table_name, alter_query in inspector_queries.items():
        columns = db.session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        column_names = {col[1] for col in columns}
        if "semester" not in column_names:
            db.session.execute(text(alter_query))
            db.session.commit()
            logging.getLogger(__name__).info("Added semester column to %s table", table_name)


def ensure_department_columns() -> None:
    table_columns = {
        "students": "ALTER TABLE students ADD COLUMN department_id INTEGER",
        "subjects": "ALTER TABLE subjects ADD COLUMN department_id INTEGER",
        "faculties": "ALTER TABLE faculties ADD COLUMN department_id INTEGER",
    }
    for table_name, alter_query in table_columns.items():
        columns = db.session.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        column_names = {col[1] for col in columns}
        if "department_id" not in column_names:
            db.session.execute(text(alter_query))
            db.session.commit()
            logging.getLogger(__name__).info("Added department_id column to %s table", table_name)


def backfill_department_ids() -> None:
    from models.department import Department
    from models.student import Student
    from models.subject import Subject
    from models.faculty import Faculty

    departments = {dept.name: dept.id for dept in Department.query.all()}
    touched = 0

    for student in Student.query.all():
        if not student.department_id and student.branch in departments:
            student.department_id = departments[student.branch]
            touched += 1
    for faculty in Faculty.query.all():
        if not faculty.department_id and faculty.department in departments:
            faculty.department_id = departments[faculty.department]
            touched += 1
    for subject in Subject.query.all():
        if not subject.department_id and subject.branch in departments:
            subject.department_id = departments[subject.branch]
            touched += 1

    if touched:
        db.session.commit()
        logging.getLogger(__name__).info("Backfilled department_id for %s records.", touched)


def ensure_timetable_location_columns() -> None:
    alter_queries = {
        "classroom": "ALTER TABLE timetable_entries ADD COLUMN classroom VARCHAR(120)",
        "latitude": "ALTER TABLE timetable_entries ADD COLUMN latitude FLOAT",
        "longitude": "ALTER TABLE timetable_entries ADD COLUMN longitude FLOAT",
        "geofence_radius_meters": "ALTER TABLE timetable_entries ADD COLUMN geofence_radius_meters FLOAT",
    }
    columns = db.session.execute(text("PRAGMA table_info(timetable_entries)")).fetchall()
    column_names = {col[1] for col in columns}
    for column_name, alter_query in alter_queries.items():
        if column_name not in column_names:
            db.session.execute(text(alter_query))
            db.session.commit()
            logging.getLogger(__name__).info("Added %s column to timetable_entries table", column_name)


def ensure_timetable_time_columns() -> None:
    alter_queries = {
        "start_time": "ALTER TABLE timetable_entries ADD COLUMN start_time VARCHAR(5)",
        "end_time": "ALTER TABLE timetable_entries ADD COLUMN end_time VARCHAR(5)",
    }
    columns = db.session.execute(text("PRAGMA table_info(timetable_entries)")).fetchall()
    column_names = {col[1] for col in columns}
    for column_name, alter_query in alter_queries.items():
        if column_name not in column_names:
            db.session.execute(text(alter_query))
            db.session.commit()
            logging.getLogger(__name__).info("Added %s column to timetable_entries table", column_name)


def ensure_attendance_schema() -> None:
    """
    Upgrade attendance table to support per-lecture-slot tracking.
    """
    schema_row = db.session.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name='attendance'")
    ).fetchone()
    schema_sql = (schema_row[0] or "") if schema_row else ""
    has_timetable_id = "timetable_id" in schema_sql
    has_old_unique = "UNIQUE (student_id, subject_id, date)" in schema_sql or "uq_student_subject_date" in schema_sql

    if has_timetable_id and not has_old_unique:
        return

    # Rebuild table in-place for SQLite to change unique constraint safely.
    db.session.execute(text("PRAGMA foreign_keys=OFF"))
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS attendance_new (
                id INTEGER NOT NULL PRIMARY KEY,
                student_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                timetable_id INTEGER,
                date DATE NOT NULL,
                time DATETIME NOT NULL,
                latitude FLOAT NOT NULL,
                longitude FLOAT NOT NULL,
                face_verified BOOLEAN NOT NULL,
                gps_verified BOOLEAN NOT NULL,
                status VARCHAR(20) NOT NULL,
                CONSTRAINT uq_student_timetable_date UNIQUE (student_id, timetable_id, date),
                FOREIGN KEY(student_id) REFERENCES students (id),
                FOREIGN KEY(subject_id) REFERENCES subjects (id),
                FOREIGN KEY(timetable_id) REFERENCES timetable_entries (id)
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            INSERT INTO attendance_new (id, student_id, subject_id, timetable_id, date, time, latitude, longitude, face_verified, gps_verified, status)
            SELECT id, student_id, subject_id, NULL as timetable_id, date, time, latitude, longitude, face_verified, gps_verified, status
            FROM attendance
            """
        )
    )
    db.session.execute(text("DROP TABLE attendance"))
    db.session.execute(text("ALTER TABLE attendance_new RENAME TO attendance"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_attendance_student_id ON attendance (student_id)"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_attendance_subject_id ON attendance (subject_id)"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_attendance_timetable_id ON attendance (timetable_id)"))
    db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_attendance_date ON attendance (date)"))
    db.session.execute(text("PRAGMA foreign_keys=ON"))
    db.session.commit()
    logging.getLogger(__name__).info("Attendance schema upgraded to per-timetable unique tracking.")


def create_app() -> Flask:
    configure_logging()

    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    from models.user import User
    from routes import register_blueprints

    @login_manager.user_loader
    def load_user(user_id: str):
        return User.query.get(int(user_id))

    register_blueprints(app)

    def _app_tz():
        tz_name = app.config.get("APP_TIMEZONE", "Asia/Kolkata")
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return ZoneInfo("Asia/Kolkata")

    @app.template_filter("local_time")
    def local_time_filter(value):
        if not value:
            return "-"
        if isinstance(value, datetime):
            source = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return source.astimezone(_app_tz()).strftime("%H:%M:%S")
        return str(value)

    @app.template_filter("local_date")
    def local_date_filter(value):
        if not value:
            return "-"
        if isinstance(value, datetime):
            source = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return source.astimezone(_app_tz()).strftime("%d %b %Y")
        if isinstance(value, date):
            return value.strftime("%d %b %Y")
        return str(value)

    with app.app_context():
        db.create_all()
        ensure_semester_columns()
        ensure_department_columns()
        ensure_timetable_time_columns()
        ensure_timetable_location_columns()
        ensure_attendance_schema()
        migrate_legacy_year_to_passout_year()
        seed_admin()
        backfill_department_ids()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=False)
