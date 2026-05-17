from datetime import date, datetime

from models import db


class Attendance(db.Model):
    __tablename__ = "attendance"
    __table_args__ = (
        db.UniqueConstraint("student_id", "timetable_id", "date", name="uq_student_timetable_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    timetable_id = db.Column(db.Integer, db.ForeignKey("timetable_entries.id"), nullable=True, index=True)
    date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    face_verified = db.Column(db.Boolean, nullable=False, default=False)
    gps_verified = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(20), nullable=False, default="present")

    student = db.relationship("Student", back_populates="attendance_records")
    subject = db.relationship("Subject", back_populates="attendance_records")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "student_id": self.student_id,
            "subject_id": self.subject_id,
            "timetable_id": self.timetable_id,
            "date": self.date.isoformat(),
            "time": self.time.isoformat(),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "face_verified": self.face_verified,
            "gps_verified": self.gps_verified,
            "status": self.status,
        }
