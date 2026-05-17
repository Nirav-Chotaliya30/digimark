from datetime import datetime

from models import db


class LectureSession(db.Model):
    __tablename__ = "lecture_sessions"

    id = db.Column(db.Integer, primary_key=True)
    timetable_id = db.Column(db.Integer, db.ForeignKey("timetable_entries.id"), nullable=False, index=True)
    start_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    end_time = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    ended_early = db.Column(db.Boolean, nullable=False, default=False)

    timetable = db.relationship("TimetableEntry", back_populates="lecture_sessions")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timetable_id": self.timetable_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "is_active": self.is_active,
            "ended_early": self.ended_early,
        }
