from datetime import datetime

from models import db


class TimetableEntry(db.Model):
    __tablename__ = "timetable_entries"

    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.String(12), nullable=False, index=True)
    period_no = db.Column(db.Integer, nullable=False, index=True)
    start_time = db.Column(db.String(5), nullable=True, index=True)
    end_time = db.Column(db.String(5), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey("faculties.id"), nullable=False, index=True)
    branch = db.Column(db.String(50), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    semester = db.Column(db.Integer, nullable=True, index=True)
    classroom = db.Column(db.String(120), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    geofence_radius_meters = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    subject = db.relationship("Subject", lazy="joined")
    faculty = db.relationship("Faculty", lazy="joined")
    lecture_sessions = db.relationship(
        "LectureSession",
        back_populates="timetable",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "day_of_week": self.day_of_week,
            "period_no": self.period_no,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "subject_id": self.subject_id,
            "faculty_id": self.faculty_id,
            "branch": self.branch,
            "year": self.year,
            "semester": self.semester,
            "classroom": self.classroom,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "geofence_radius_meters": self.geofence_radius_meters,
            "radius": self.geofence_radius_meters,
        }
