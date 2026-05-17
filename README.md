# DigiMark - Smart Attendance System

Production-ready Flask web application for role-based attendance with dual verification (face + GPS geofence).

## Tech Stack
- Backend: Flask, Blueprints, SQLAlchemy, Flask-Login, Flask-Bcrypt, Flask-CORS
- Database: SQLite
- Frontend: HTML5, Bootstrap 5, Vanilla JS
- AI/ML: OpenCV + face_recognition

## Project Structure
Implemented exactly as requested in the workspace root:
- `app.py`, `config.py`, `.env`, `requirements.txt`
- `models/`, `routes/`, `templates/`, `static/`, `face_module/`, `utils/`

## Setup (Local)
1. Create and activate virtual environment:
   - Windows PowerShell:
     - `python -m venv .venv`
     - `.venv\\Scripts\\Activate.ps1`
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Verify `.env` values (defaults already included).
4. Run the app:
   - `python app.py`
5. Open:
   - [http://127.0.0.1:5000](http://127.0.0.1:5000)

## Default Admin Seed
- Email: `admin@digimark.com`
- Password: `Admin@123`

The admin account is auto-seeded on first run if missing.

## Native Dependency Notes (face_recognition)
`face_recognition` depends on `dlib` and system build tools.

### Windows (common prerequisites)
- Install Visual Studio Build Tools (C++ workload).
- Install CMake.
- Ensure Python version is compatible with your installed wheels.

If face-recognition build fails, install prebuilt wheels for `dlib` matching your Python version, then reinstall `face_recognition`.

## Core Features Implemented
- Role-based auth (student/faculty/admin), bcrypt password hashing, session management
- Student profile + face registration (5-frame auto capture + average encoding + basic liveness check)
- GPS geofence verification via Haversine distance
- Dual-verification attendance marking with duplicate prevention
- Faculty reports, filtering, defaulter API, CSV export
- Admin dashboard with analytics and management APIs
- Logging to `logs/digimark.log`

## API Endpoints
- `POST /api/register-face`
- `POST /api/mark-attendance`
- `GET /api/attendance/<student_id>`
- `GET /api/defaulters/<subject_id>`
- `POST /api/admin/add-subject`
- `POST /api/admin/add-faculty`
- `GET /api/export/csv/<subject_id>`

## Deployment

### Render
1. Push project to GitHub.
2. Create a new **Web Service** in Render from the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `python app.py`
5. Add environment variables from `.env.example`.
6. Persist SQLite only for testing; use managed DB for long-term production.

### Railway
1. Create new project from GitHub repo.
2. Set start command to `python app.py`.
3. Add all `.env` variables in Railway Variables.
4. Deploy and verify routes.

## Production Notes
- Replace `SECRET_KEY` with a strong secret.
- Move from SQLite to managed DB for scale.
- Set `debug=False` in production startup.
