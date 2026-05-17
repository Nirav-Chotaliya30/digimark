from datetime import datetime

from models import db


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    students = db.relationship("Student", back_populates="department", lazy="dynamic")
    faculties = db.relationship("Faculty", back_populates="department_ref", lazy="dynamic")
    subjects = db.relationship("Subject", back_populates="department_ref", lazy="dynamic")

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "created_at": self.created_at.isoformat()}
