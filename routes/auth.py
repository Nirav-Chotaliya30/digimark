import logging
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from models import db
from models.department import Department
from models.faculty import Faculty
from models.student import Student
from models.user import User

auth_bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)

def _register_context():
    current_year = datetime.utcnow().year
    return {
        "branches": current_app.config["BRANCHES"],
        "branch_count": current_app.config["BRANCH_COUNT"],
        "passout_years": list(range(current_year, current_year + 8)),
        "semesters": list(range(1, 9)),
    }


def _redirect_for_role(role: str):
    if role == "student":
        return redirect(url_for("student.student_dashboard"))
    if role == "faculty":
        return redirect(url_for("faculty.faculty_dashboard"))
    return redirect(url_for("admin.admin_dashboard"))


def _current_profile():
    if not current_user.is_authenticated:
        return None
    if current_user.role == "student":
        return Student.query.filter_by(user_id=current_user.id).first()
    if current_user.role == "faculty":
        return Faculty.query.filter_by(user_id=current_user.id).first()
    return None


@auth_bp.route("/")
def home():
    if current_user.is_authenticated:
        return _redirect_for_role(current_user.role)
    return render_template("home.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return _redirect_for_role(current_user.role)

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password) or user.role != role:
            logger.warning("Failed login for email=%s role=%s", email, role)
            flash("Invalid credentials or role mismatch.", "danger")
            return render_template("auth/login.html")

        remember_me = request.form.get("remember_me") == "on"
        login_user(user, remember=remember_me)
        logger.info("Successful login: user_id=%s role=%s", user.id, user.role)
        flash("Welcome back.", "success")
        return _redirect_for_role(user.role)

    return render_template("auth/login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return _redirect_for_role(current_user.role)

    if request.method == "POST":
        raw_username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "").strip()
        enrollment_no = request.form.get("enrollment_no", "").strip()

        if role not in {"student", "faculty"}:
            flash("Invalid role selected.", "danger")
            return render_template("auth/register.html", **_register_context())

        if role == "student":
            if not enrollment_no:
                flash("Enrollment number is required for students.", "danger")
                return render_template("auth/register.html", **_register_context())
            username = enrollment_no
            if Student.query.filter_by(enrollment_no=enrollment_no).first():
                flash("Enrollment number already exists.", "warning")
                return render_template("auth/register.html", **_register_context())
            branch = request.form.get("branch", "").strip()
            passout_year = request.form.get("passout_year", "").strip()
            semester_raw = request.form.get("semester", "").strip()
            if branch not in current_app.config["BRANCHES"]:
                flash("Please select a valid branch.", "danger")
                return render_template("auth/register.html", **_register_context())
            if not passout_year.isdigit():
                flash("Please select a valid passout year.", "danger")
                return render_template("auth/register.html", **_register_context())
            if not semester_raw.isdigit() or int(semester_raw) not in range(1, 9):
                flash("Please select a valid semester (1-8).", "danger")
                return render_template("auth/register.html", **_register_context())
        else:
            username = raw_username
            if not username:
                flash("Username is required for faculty.", "danger")
                return render_template("auth/register.html", **_register_context())

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash("Username or email already exists.", "warning")
            return render_template("auth/register.html", **_register_context())

        user = User(username=username, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        if role == "student":
            student_department = Department.query.filter_by(name=branch).first()
            profile = Student(
                user_id=user.id,
                enrollment_no=enrollment_no,
                full_name=request.form.get("full_name", "").strip(),
                branch=branch,
                department_id=student_department.id if student_department else None,
                year=int(passout_year),
                semester=int(semester_raw),
            )
            db.session.add(profile)
        else:
            department_name = request.form.get("department", "").strip()
            faculty_department = Department.query.filter_by(name=department_name).first()
            profile = Faculty(
                user_id=user.id,
                full_name=request.form.get("full_name", "").strip(),
                department=department_name,
                department_id=faculty_department.id if faculty_department else None,
                subject_ids=[],
            )
            db.session.add(profile)

        db.session.commit()
        flash("Registration successful. Please login.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", **_register_context())


@auth_bp.route("/logout")
@login_required
def logout():
    logger.info("Logout user_id=%s", current_user.id)
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/profile")
@login_required
def profile():
    return render_template("profile.html", profile=_current_profile())
