import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "fallback-dev-key")
    SQLALCHEMY_DATABASE_URI = os.environ.get("SQLALCHEMY_DATABASE_URI", "sqlite:///digimark.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    COLLEGE_LAT = float(os.environ.get("COLLEGE_LAT", 23.0225))
    COLLEGE_LNG = float(os.environ.get("COLLEGE_LNG", 72.5714))
    GEOFENCE_RADIUS_METERS = float(os.environ.get("GEOFENCE_RADIUS_METERS", 200))
    FACE_TOLERANCE = float(os.environ.get("FACE_TOLERANCE", 0.5))
    MAX_FACE_IMAGES = int(os.environ.get("MAX_FACE_IMAGES", 5))
    DEFAULTER_THRESHOLD = float(os.environ.get("DEFAULTER_THRESHOLD", 75))
    APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Kolkata")

    BRANCHES = [
        "Artificial Intelligence and Machine Learning",
        "Automobile Engineering",
        "Biomedical Engineering",
        "Chemical Engineering",
        "Civil Engineering",
        "Computer Engineering",
        "Electrical Engineering",
        "Electronics and Communication Engineering",
        "Environmental Engineering",
        "Information Technology",
        "Instrumentation and Control Engineering",
        "Mechanical Engineering",
        "Plastics Technology",
        "Robotics and Automation",
        "Rubber Technology",
        "Textile Technology",
    ]
    BRANCH_COUNT = len(BRANCHES)
