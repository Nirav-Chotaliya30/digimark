from datetime import datetime

from models import db


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    enrollment_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    branch = db.Column(db.String(50), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    semester = db.Column(db.Integer, nullable=True, index=True)
    face_encoding = db.Column(db.JSON, nullable=True)
    face_registered = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", back_populates="student_profile")
    department = db.relationship("Department", back_populates="students")
    attendance_records = db.relationship(
        "Attendance",
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "enrollment_no": self.enrollment_no,
            "full_name": self.full_name,
            "branch": self.branch,
            "department_id": self.department_id,
            "year": self.year,
            "passout_year": self.year,
            "semester": self.semester,
            "face_registered": self.face_registered,
            "created_at": self.created_at.isoformat(),
        }
