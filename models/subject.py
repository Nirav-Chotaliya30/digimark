from models import db


class Subject(db.Model):
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    faculty_id = db.Column(db.Integer, db.ForeignKey("faculties.id"), nullable=True, index=True)
    branch = db.Column(db.String(50), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    semester = db.Column(db.Integer, nullable=True, index=True)

    faculty = db.relationship("Faculty", back_populates="subjects")
    department_ref = db.relationship("Department", back_populates="subjects")
    attendance_records = db.relationship(
        "Attendance",
        back_populates="subject",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "faculty_id": self.faculty_id,
            "branch": self.branch,
            "department_id": self.department_id,
            "year": self.year,
            "passout_year": self.year,
            "semester": self.semester,
        }
