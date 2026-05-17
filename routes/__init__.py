from routes.admin import admin_bp
from routes.auth import auth_bp
from routes.faculty import faculty_bp
from routes.student import student_bp


def register_blueprints(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(faculty_bp)
    app.register_blueprint(admin_bp)
