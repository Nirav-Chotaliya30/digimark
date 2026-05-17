<h1 align="center">
  <br>
  DigiMark - Smart Attendance System
  <br>
</h1>

<h4 align="center">A production-ready Flask web application for role-based attendance featuring dual verification (Facial Recognition + GPS Geofencing).</h4>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/Flask-3.0-lightgrey.svg" alt="Flask Version">
  <img src="https://img.shields.io/badge/OpenCV-4.10-green.svg" alt="OpenCV">
  <img src="https://img.shields.io/badge/Bootstrap-5.3-purple.svg" alt="Bootstrap">
</p>

<p align="center">
  <a href="#key-features">Key Features</a> •
  <a href="#tech-stack">Tech Stack</a> •
  <a href="#local-setup">Local Setup</a> •
  <a href="#how-it-works">How To Use</a> •
  <a href="#deployment">Deployment</a>
</p>

---

## ✨ Key Features

* **🔐 Role-Based Access Control:** Secure portals for Students, Faculty, and Administrators.
* **👩‍🎓 Student Face Registration:** Seamless 5-frame auto-capture, average encoding generation, and basic liveness checks.
* **📍 GPS Geofencing:** Ensures attendance can only be marked within the designated college perimeter using Haversine distance calculations.
* **✅ Dual-Verification Attendance:** Requires both face match and valid GPS location to mark attendance, preventing proxy logging.
* **📊 Analytics & Reports:** Faculty and Admins get rich dashboards, real-time analytics, filtering, defaulter tracking APIs, and CSV export functionality.
* **🛡️ Security First:** Bcrypt password hashing, session management, and robust logging.

## 🛠️ Tech Stack

* **Backend:** Python, Flask, Flask-Blueprints, SQLAlchemy (ORM)
* **Authentication:** Flask-Login, Flask-Bcrypt, Flask-CORS
* **Database:** SQLite (Default, configurable to MySQL/PostgreSQL)
* **Frontend:** HTML5, CSS3, Bootstrap 5, Vanilla JavaScript
* **AI & Machine Learning:** OpenCV, `face_recognition` (dlib)
* **Production Servers:** Gunicorn (Linux), Waitress (Windows)

## 🚀 Local Setup

### Prerequisites
- Python 3.8 or higher installed on your machine.
- For Windows users, `face_recognition` requires [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (C++ workload) and CMake.

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Nirav-Chotaliya30/digimark.git
   cd digimark
   ```

2. **Create and activate a virtual environment**
   * Windows:
     ```bash
     python -m venv .venv
     .venv\Scripts\Activate.ps1
     ```
   * Linux/Mac:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables**
   * Copy the `.env.example` file and rename it to `.env`.
   * Fill in your specific secrets, college latitude/longitude, and database connection strings.

5. **Run the Application (Development)**
   ```bash
   python app.py
   ```
   *Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.*

---

## 🔑 Default Admin Account

On the very first run, the system automatically creates a default admin account so you can set up the institution:
- **Email:** `admin@digimark.com`
- **Password:** `Admin@123`

*(Note: Please change this immediately after your first login in a production environment).*

---

## 🌐 API Endpoints

The system exposes clean RESTful APIs for frontend interactions:
| Endpoint | Method | Description |
|---|---|---|
| `/api/register-face` | `POST` | Processes and encodes a student's face via webcam. |
| `/api/mark-attendance` | `POST` | Validates Face + GPS to log an attendance record. |
| `/api/attendance/<student_id>` | `GET` | Fetches a specific student's attendance history. |
| `/api/defaulters/<subject_id>` | `GET` | Returns a list of students below the attendance threshold. |
| `/api/export/csv/<subject_id>`| `GET` | Generates a downloadable CSV report for a subject. |

---

## ☁️ Deployment

### Render / Railway (Linux Environments)
1. Connect your GitHub repository to your hosting provider.
2. **Build Command:** `pip install -r requirements.txt`
3. **Start Command:** `gunicorn app:app` *(Do NOT use `python app.py` for production)*
4. Copy variables from `.env.example` into the Environment Variables dashboard of your host.

### Windows Server (IIS / Waitress)
If hosting on a Windows Server, use `waitress` to serve the application:
```bash
waitress-serve --listen=0.0.0.0:8080 app:app
```

### Production Checklist
- [x] Change `app.run(debug=True)` to `debug=False` in `app.py`. *(Already Done!)*
- [ ] Replace `SECRET_KEY` in `.env` with a strong, randomly generated string.
- [ ] Migrate from SQLite to a robust database like **MySQL** or **PostgreSQL** by updating the `SQLALCHEMY_DATABASE_URI`.

---
*Developed by [Nirav Chotaliya](https://github.com/Nirav-Chotaliya30)*
