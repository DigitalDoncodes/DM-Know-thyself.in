
"""
Know-Thyself — consolidated app.py
Features:
 - Local MongoDB (db name 'portal')
 - Student registration/login (Flask-Login)
 - Teacher fixed credentials inside file (can move to .env)
 - Jobs, applications, uploads (resume + photo)
 - Teacher assessment, per-application clear/delete
 - Brevo (SendinBlue) transactional email sending (with attachments)
 - CSV export for registered students and assessed students
 - /debug/db to quickly verify data
 - Server runs on port 10000 for local testing
"""

import os
import base64
import io
import json
import logging
from functools import wraps
from datetime import datetime, timedelta, timezone as tz
from pathlib import Path
from bson import ObjectId

def mongo_objid_from_str(id_str):
    try:
        return ObjectId(id_str)
    except (InvalidId, TypeError):
        return None
    
from flask import current_app
from flask import (
    Flask, render_template, request, redirect, url_for, flash, abort,
    send_file, send_from_directory, jsonify
)
from flask_login import (
    LoginManager, login_user, logout_user, login_required, current_user, UserMixin
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
# --- SECURITY / PRODUCTION HELPERS ---
from flask_wtf import CSRFProtect
import threading
from werkzeug.exceptions import BadRequest
from bson.errors import InvalidId
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os
from bson.objectid import ObjectId
from dotenv import load_dotenv
import requests
import pandas as pd
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired
# forms.py or inside app.py
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired

class LoginForm(FlaskForm):
    email_or_sid = StringField("Email or SID", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")
class SimpleForm(FlaskForm):
    email_or_sid = StringField("Email or Student ID", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")



# --------------------- place near top of app.py (after imports) ---------------------
from datetime import datetime, timedelta, timezone
UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))

def local_dt_now():
    """Return timezone-aware current UTC datetime."""
    return datetime.now(UTC)

def utc_to_ist(dt):
    """Convert a UTC-aware datetime -> IST-aware datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)

def ist_to_utc(dt):
    """Convert local IST (naive or aware) to UTC-aware datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # assume dt is in IST if naive
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(UTC)

def make_attachment_from_file_path(filepath):
    """Return Brevo attachment dict from file path {name, content(base64)}"""
    import base64, os
    if not filepath or not os.path.exists(filepath):
        return None
    with open(filepath, "rb") as fh:
        b = fh.read()
    content_b64 = base64.b64encode(b).decode("utf-8")
    return {"name": os.path.basename(filepath), "content": content_b64}
# -----------------------------------------------------------------------------------
# -------------------------
# Load .env (if exists)
# -------------------------
load_dotenv()

# -------------------------
# Basic config
# -------------------------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

ALLOWED_RESUME = {"pdf", "doc", "docx"}
ALLOWED_PHOTO = {"png", "jpg", "jpeg"}

# -------------------------
# App setup
# -------------------------
app = Flask(__name__)
from datetime import datetime
app.jinja_env.globals['datetime'] = datetime
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
# limit uploads to e.g., 5 MB per file
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("know-thyself")

# -------------------------
# MongoDB connection
# -------------------------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
db = client["portal"]  # your local DB (portal)
users_col = db["users"]
jobs_col = db["jobs"]
applications_col = db["applications"]
growth_col = db["growth_responses"]
self_assess_col = db["self_assessments"]
otp_col = db["otp_store"]

# -------------------------
# Brevo config (SendinBlue)
# -------------------------
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "no-reply@example.com")
FROM_NAME = os.getenv("FROM_NAME", "Know-Thyself")

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"  # transactional send endpoint

# require SECRET_KEY in production
if os.getenv("FLASK_ENV") == "production":
    if not os.getenv("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set in production")
    app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
else:
    # keep development fallback but warn
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")

# Secure cookie settings (override in prod via env if desired)
app.config.update(
    SESSION_COOKIE_SECURE=(os.getenv("FLASK_ENV") == "production"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
    REMEMBER_COOKIE_HTTPONLY=True
)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# -------------------------
# Login manager
# -------------------------
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

# -------------------------
# Teachers (fixed local credentials)
# -------------------------
TEACHERS = [
    {
        "email": "gnanaprakash@kclas.ac.in",
        "password": "gpsir098",
        "name": "Prof. Gnanaprakash",
        "role": "teacher"
    },
    {
        "email": "dhatchinamoorthiai@gmail.com",
        "password": "DigitalDonDa@2005",
        "name": "Deeksha",
        "role": "teacher"
    }
]

# Wrap teacher credentials with hashed password for safer local checks
for t in TEACHERS:
    if not t.get("password_hash"):
        t["password_hash"] = generate_password_hash(t["password"])
        # Keep plaintext only if you need (not recommended). We'll use password_hash.

# -------------------------
# Helpers & utilities
# -------------------------
def allowed_file(filename, allowed_set):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in allowed_set

def local_dt_now():
    """Return timezone-aware UTC now"""
    return datetime.now(tz=tz.utc)

def ist_to_utc(dt_ist):
    """Convert naive IST datetime (assumed) to UTC aware"""
    # dt_ist is naive local (IST) like datetime.strptime(...). Add IST offset -5.5 hours
    return (dt_ist - timedelta(hours=5, minutes=30)).replace(tzinfo=tz.utc)

def utc_to_ist_str(dt_utc):
    if dt_utc is None:
        return None
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=tz.utc)
    dt_ist = dt_utc.astimezone(tz=tz(timedelta(hours=5, minutes=30)))
    return dt_ist.strftime("%d %b %Y, %I:%M %p")

def objectid_to_str(doc):
    if not doc:
        return doc
    doc = dict(doc)
    if "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    return doc

def mongo_objid_from_str(s):
    try:
        return ObjectId(s)
    except Exception:
        return None

# -------------------------
# Brevo (Send email) wrapper
# -------------------------
def send_brevo_email(to_email, to_name, subject, html_content, attachments=None):
    """
    Send transactional email via Brevo.
    """
    if not BREVO_API_KEY:
        logger.warning("No BREVO_API_KEY set — skipping email send to %s", to_email)
        print(f"❌ Email not sent: Missing BREVO_API_KEY for {to_email}")
        return False

    payload = {
        "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
        "to": [{"email": to_email, "name": to_name or ""}],
        "subject": subject,
        "htmlContent": html_content
    }
    if attachments:
        payload["attachment"] = attachments  # [{name, content}]

    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }

    print(f"📤 Sending email to {to_email} | Subject: {subject}")
    try:
        resp = requests.post(BREVO_SEND_URL, headers=headers, json=payload, timeout=10)
        print(f"✅ Brevo response: {resp.status_code} | {resp.text[:200]}")
        logger.info("Brevo send status: %s %s", resp.status_code, resp.text)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Brevo email send failed: {e}")
        logger.exception("Failed to send Brevo email: %s", e)
        return False
def send_brevo_email_async(*args, **kwargs):
    """Fire-and-forget email sending using a daemon thread.
    For production, replace with Celery/RQ to guarantee delivery and retries."""
    t = threading.Thread(target=send_brevo_email, args=args, kwargs=kwargs, daemon=True)
    t.start()
import os, base64, requests, logging
from dotenv import load_dotenv

# --- Email Config ---
load_dotenv()
BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
FROM_NAME = "Know-Thyself"
FROM_EMAIL = "psychologyresumemail@gmail.com"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Helper: Convert file to Brevo attachment format ---
def make_attachment_from_file_path(filepath):
    """
    Return Brevo attachment dict {name, content(base64)} from a local file path.
    """
    if not filepath or not os.path.exists(filepath):
        return None
    with open(filepath, "rb") as f:
        file_bytes = f.read()
        encoded = base64.b64encode(file_bytes).decode("utf-8")
        return {"name": os.path.basename(filepath), "content": encoded}


# --- Helper: Send Brevo Email ---
def send_brevo_email(to_email, to_name, subject, html_content, attachments=None):
    """
    Send transactional email via Brevo API.
    """
    if not BREVO_API_KEY:
        logger.warning("No BREVO_API_KEY set — skipping email send to %s", to_email)
        print(f"❌ Email not sent — missing BREVO_API_KEY for {to_email}")
        return False

    payload = {
        "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
        "to": [{"email": to_email, "name": to_name or ""}],
        "subject": subject,
        "htmlContent": html_content,
    }

    if attachments:
        payload["attachment"] = attachments

    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }

    try:
        response = requests.post(BREVO_SEND_URL, headers=headers, json=payload, timeout=10)
        logger.info("📤 Brevo status: %s | %s", response.status_code, response.text[:150])
        response.raise_for_status()
        print(f"✅ Email sent to {to_email}")
        return True
    except Exception as e:
        logger.error("❌ Failed to send Brevo email: %s", e)
        return False

# -------------------------
# Users for Flask-Login
# -------------------------
class User(UserMixin):
    def __init__(self, data):
        # data can be dict from Mongo or teacher dict
        self._raw = data
        self.id = str(data.get("_id", data.get("email")))
        self.email = data.get("email")
        self.name = data.get("name")
        self.role = data.get("role", "student")

@login_manager.user_loader
def load_user(user_id):
    # first check teachers by email
    for t in TEACHERS:
        if user_id == t["email"]:
            return User(t)
    # then check users collection by _id (ObjectId) or email fallback
    try:
        # try as ObjectId
        u = users_col.find_one({"_id": ObjectId(user_id)})
        if u:
            return User(u)
    except Exception:
        # maybe it's an email stored as id
        u = users_col.find_one({"email": user_id})
        if u:
            return User(u)
    return None

def teacher_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "teacher":
            flash("Unauthorized — teacher only area.", "danger")
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper

def student_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "student":
            flash("Unauthorized — student only area.", "danger")
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper

# -------------------------
# Routes - General
# -------------------------
@app.route('/')
@app.route('/index')
def startpage():
    return render_template('startpage.html')

# -------------------------
# Auth: login/logout/register
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    form = SimpleForm()

    if request.method == "POST" and form.validate_on_submit():
        email_or_sid = form.email_or_sid.data.strip()
        password = form.password.data.strip()

        # 🔹 Teacher login
        teacher = next((t for t in TEACHERS if t.get("email") == email_or_sid), None)
        if teacher and check_password_hash(teacher["password_hash"], password):
            user = User(teacher)
            login_user(user)
            flash("Welcome, Teacher!", "success")
            return redirect(url_for("teacher_dashboard"))

        # 🔹 Student login
        student = users_col.find_one({"email": email_or_sid})
        if student:
            stored_hash = student.get("password_hash") or student.get("password")
            if stored_hash and check_password_hash(stored_hash, password):
                user = User(student)
                login_user(user)
                flash("Welcome, Student!", "success")
                return redirect(url_for("student_dashboard"))

        # ⚠️ Only runs if no teacher/student matched
        flash("Invalid credentials. Please try again.", "danger")

    # Always render template with form for GET or failed POST
    return render_template("login.html", form=form)        
@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        sid = request.form.get("sid", "").strip()

        if not email or not password or not name:
            flash("Please provide name, email and password.", "danger")
            return redirect(url_for("register"))

        existing = users_col.find_one({"email": email})
        if existing:
            flash("Email already registered. Please log in.", "warning")
            return redirect(url_for("login"))

        password_hash = generate_password_hash(password)
        new_user = {
            "name": name,
            "email": email,
            "sid": sid or None,
            "password_hash": password_hash,
            "role": "student",
            "created_at": local_dt_now()
        }
        res = users_col.insert_one(new_user)
        new_user["_id"] = res.inserted_id
        login_user(User(new_user))
        flash("Registration successful — welcome!", "success")
        return redirect(url_for("student_dashboard"))
    return render_template("register.html")

# -------------------------
# Student dashboard & apply
# -------------------------
@app.route("/student/")
@login_required
@student_required
def student_dashboard():
    # fetch all jobs and the student's applications
    jobs_cursor = jobs_col.find().sort("created_at", -1)
    jobs = []
    for j in jobs_cursor:
        j = objectid_to_str(j)
        # compute vacancy display
        j["vacancies"] = j.get("vacancies", 0)
        # deadline display convert to IST string if exists
        j["deadline_str"] = utc_to_ist_str(j.get("deadline"))
        jobs.append(j)

    apps = []
    for a in applications_col.find({"applicant_id": ObjectId(current_user.id)}).sort("application_time", -1):
        # enrich
        a = objectid_to_str(a)
        job = jobs_col.find_one({"_id": mongo_objid_from_str(a.get("job_id"))}) if a.get("job_id") else None
        a["job_title"] = job.get("title") if job else a.get("job_title", "Unknown Job")
        # progress status mapping
        status_stages = ["submitted", "under_review", "corrections_needed", "approved", "rejected"]
        current_status = a.get("status", "submitted")
        a["status_index"] = status_stages.index(current_status) if current_status in status_stages else 0
        # transform times
        a["deadline_str"] = utc_to_ist_str(a.get("deadline"))
        a["resume_upload_ist"] = utc_to_ist_str(a.get("resume_upload_time"))
        apps.append(a)

    # check if has active (pending/submit)
    has_active = any(a["status"] in ("submitted", "under_review", "corrections_needed") for a in apps)
    active_app = next((a for a in apps if a["status"] in ("submitted", "under_review", "corrections_needed")), None)
    return render_template("student_dashboard.html", jobs=jobs, applications=apps, has_active=has_active, active_app=active_app, current_user=current_user,     timedelta=timedelta  # 👈 Add this line
)

class User(UserMixin):
    def __init__(self, data):
        self.id = str(data.get("_id", data.get("email")))
        self.email = data.get("email")
        self.name = data.get("name")
        self.role = data.get("role", "student")

    def has_applied(self, job):
        """Check if the current student has already applied for this job."""
        from bson import ObjectId
        from app import db  # use your MongoDB client directly
        application = db.applications.find_one({
            "applicant_id": ObjectId(self.id),
            "job_id": job["_id"]
        })
        return application is not None
    
@app.route("/job/<job_id>", methods=["GET", "POST"])
@login_required
@student_required
def view_job(job_id):
    job = jobs_col.find_one({"_id": ObjectId(job_id)})
    if not job:
        flash("⚠️ Job not found.", "danger")
        return redirect(url_for("student_dashboard"))

    # Check if the student has an existing application (any job)
    active_app = applications_col.find_one({
        "applicant_id": ObjectId(current_user.id),
        "status": {"$in": ["submitted", "under_review", "corrections_needed"]}
    })

    # Check if they applied for THIS specific job
    existing_app = applications_col.find_one({
        "applicant_id": ObjectId(current_user.id),
        "job_id": ObjectId(job_id)
    })

    has_applied = bool(existing_app)
    has_active = bool(active_app and str(active_app.get("job_id")) != str(job_id))

    return render_template(
        "job_detail.html",
        job=job,
        has_applied=has_applied,
        has_active=has_active,
        app=existing_app
    )
@app.route("/apply/<job_id>", methods=["POST"])
@login_required
@student_required
def apply_job(job_id):
    # Convert job_id to ObjectId safely
    job_oid = mongo_objid_from_str(job_id)
    if not job_oid:
        abort(404)  # Invalid ID

    # Fetch job document
    job = jobs_col.find_one({"_id": job_oid})
    if not job:
        flash("⚠️ Job not found. Please refresh.", "danger")
        return redirect(url_for("student_dashboard"))

    # Check if vacancies available
    if job.get("vacancies", 0) <= 0:
        flash("🚫 No vacancies left for this job.", "warning")
        return redirect(url_for("student_dashboard"))

    # Prevent multiple active applications
    active_app = applications_col.find_one({
        "applicant_id": ObjectId(current_user.id),
        "status": {"$nin": ["rejected", "approved", "cleared", "expired"]}
    })
    if active_app:
        flash("⚠️ You already have an active job application. Please complete or wait for review before applying again.", "warning")
        return redirect(url_for("student_dashboard"))

    # Prevent duplicate application for the same job
    existing = applications_col.find_one({
        "job_id": job_oid,
        "applicant_id": ObjectId(current_user.id)
    })
    if existing:
        flash("ℹ️ You already applied for this job.", "info")
        return redirect(url_for("student_dashboard"))

    # Create new application
    now = local_dt_now()
    application = {
        "job_id": job_oid,  # ✅ FIXED: store as ObjectId, not string
        "job_title": job.get("title"),
        "applicant_id": ObjectId(current_user.id),
        "status": "upload_required",
        "application_time": now,
        "deadline": job.get("deadline"),
    }

    res = applications_col.insert_one(application)

    # Decrement vacancy atomically
    jobs_col.update_one(
        {"_id": job_oid, "vacancies": {"$gt": 0}},
        {"$inc": {"vacancies": -1}}
    )

    flash("✅ Application created successfully! Please upload your resume & photo within 48 hours.", "success")
    return redirect(url_for("upload_files", app_id=str(res.inserted_id)))

from datetime import datetime, timedelta, timezone as tz
@app.route("/upload/<app_id>", methods=["GET", "POST"])
@login_required
@student_required
def upload_files(app_id):
    # fetch
    application = applications_col.find_one({"_id": mongo_objid_from_str(app_id)})
    if not application or str(application.get("applicant_id")) != str(current_user.id):
        flash("⚠️ Application not found.", "danger")
        abort(403)

    # timezone aware now
    now = datetime.now(UTC)

    # compute created_time (UTC-aware) and 48-hour deadline from application_time if present
    created_time = application.get("application_time")
    if created_time:
        if created_time.tzinfo is None:
            created_time = created_time.replace(tzinfo=UTC)
    else:
        created_time = now

    # compute active deadline: teacher-set deadline (if any) else created+48h
    deadline = application.get("deadline")
    if deadline:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        effective_deadline = deadline
    else:
        effective_deadline = created_time + timedelta(hours=48)

    # if already submitted, allow viewing but not re-upload (unless status indicates corrections_needed)
    status = application.get("status", "upload_required")

    # expire if time up (and not submitted)
    if now > effective_deadline and status not in ("submitted", "corrections_needed"):
        applications_col.update_one({"_id": application["_id"]}, {"$set": {"status": "expired", "last_updated": now}})
        flash("⏰ Deadline expired. Upload not allowed.", "danger")
        return render_template("upload_blocked.html", app=objectid_to_str(application))

    # handle POST uploads
    if request.method == "POST":
        # ensure enctype multipart/form-data in template
        resume = request.files.get("resume")
        photo = request.files.get("photo")
        updates = {}
        resume_saved = photo_saved = None

        if resume and allowed_file(resume.filename, ALLOWED_RESUME):
            ext = resume.filename.rsplit(".", 1)[1]
            resume_name = secure_filename(f"{app_id}_resume.{ext}")
            resume_path = os.path.join(app.config["UPLOAD_FOLDER"], resume_name)
            resume.save(resume_path)
            updates["resume_filename"] = resume_name
            updates["resume_upload_time"] = now
            resume_saved = resume_path

        if photo and allowed_file(photo.filename, ALLOWED_PHOTO):
            ext = photo.filename.rsplit(".", 1)[1]
            photo_name = secure_filename(f"{app_id}_photo.{ext}")
            photo_path = os.path.join(app.config["UPLOAD_FOLDER"], photo_name)
            photo.save(photo_path)
            updates["photo_filename"] = photo_name
            photo_saved = photo_path

        if updates:
            updates["status"] = "submitted"
            updates["last_updated"] = now
            applications_col.update_one({"_id": application["_id"]}, {"$set": updates})

            # notify teacher and student
            teacher_inbox = os.getenv("TEACHER_INBOX", "psychologyresumemail@gmail.com")
            student_doc = users_col.find_one({"_id": ObjectId(current_user.id)})
            student_name = student_doc.get("name") if student_doc else current_user.name
            student_email = student_doc.get("email") if student_doc else None
            job_title = application.get("job_title", "Application")
            submitted_time = (now.astimezone(IST)).strftime('%d %b %Y, %I:%M %p') + " IST"

            attachments = []
            if resume_saved:
                att = make_attachment_from_file_path(resume_saved)
                if att:
                    attachments.append(att)
            if photo_saved:
                att = make_attachment_from_file_path(photo_saved)
                if att:
                    attachments.append(att)

            # teacher email
            teacher_html = render_template(
                "email/teacher_notification.html",
                student_name=student_name,
                job_title=job_title,
                app_id=app_id,
                submitted_on=submitted_time,
                photo_url=(f"/uploads/{os.path.basename(photo_saved)}" if photo_saved else None)
            )
            send_brevo_email(teacher_inbox, "Teacher", f"📥 New Application from {student_name}", teacher_html, attachments=attachments)

            # student confirmation
            if student_email:
                student_html = render_template(
                    "email/student_confirmation.html",
                    student_name=student_name,
                    job_title=job_title,
                    app_id=app_id,
                    submitted_on=submitted_time
                )
                send_brevo_email(student_email, student_name, f"✅ Application received for {job_title}", student_html)

            flash("✅ Files uploaded and notifications sent!", "success")
            return redirect(url_for("student_dashboard"))

        flash("⚠️ No valid files uploaded.", "warning")
        return redirect(request.url)

    # GET -> render template; convert fields for template usage
    app_for_template = objectid_to_str(application)
    # add ISO datetimes for JS
    if created_time:
        app_for_template["application_time_iso"] = created_time.isoformat()
    else:
        app_for_template["application_time_iso"] = None
    if deadline:
        app_for_template["deadline_iso"] = deadline.isoformat()
    else:
        app_for_template["deadline_iso"] = None
    app_for_template["_id_str"] = str(app_for_template["_id"])

    return render_template("upload_files.html", app=app_for_template, deadline_iso=effective_deadline.isoformat())# -------------------------
# View files (resume/photo)
# -------------------------
@app.route("/uploads/<filename>")
@login_required
def view_file(filename):
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(path):
        abort(404)
    # Let browser handle (for pdf) or download
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# -------------------------
# Teacher dashboard & job management
# -------------------------
@app.route("/teacher/dashboard")
@login_required
@teacher_required
def teacher_dashboard():
    # Fetch all jobs posted by teacher (or all jobs if global view)
    jobs = list(jobs_col.find().sort("created_at", -1))

    for job in jobs:
        job_id = job["_id"]  # ✅ ObjectId (consistent with applications)

        # 🔹 Total applications for this job
        job["total_applications"] = applications_col.count_documents({"job_id": job_id})

        # 🔹 Active (not yet approved/rejected)
        job["active_applications"] = applications_col.count_documents({
            "job_id": job_id,
            "status": {"$in": ["upload_required", "submitted", "corrections_needed"]}
        })

        # 🔹 Approved
        job["approved_applications"] = applications_col.count_documents({
            "job_id": job_id,
            "status": "approved"
        })

    # Fetch all students (for reference, optional)
    students = list(users_col.find({"role": "student"}))

    return render_template(
        "teacher_dashboard.html",
        jobs=jobs,
        students=students,
        teacher=current_user
    )
@app.route("/teacher/add_job", methods=["GET", "POST"])
@login_required
@teacher_required
def add_job():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        specifications = request.form.get("specifications", "").strip()
        vacancies = int(request.form.get("vacancies") or 1)
        deadline_str = request.form.get("deadline")  # expect "YYYY-MM-DDTHH:MM" from datetime-local input

        if deadline_str:
            try:
                dt_ist = datetime.strptime(deadline_str, "%Y-%m-%dT%H:%M")
                deadline_utc = ist_to_utc(dt_ist)
            except Exception:
                flash("Invalid deadline format.", "danger")
                return redirect(request.url)
        else:
            deadline_utc = None

        job_doc = {
            "title": title,
            "description": description,
            "specifications": specifications,
            "vacancies": vacancies,
            "deadline": deadline_utc,
            "created_by": current_user.id,
            "created_at": local_dt_now()
        }
        jobs_col.insert_one(job_doc)
        flash("✅ Job posted successfully.", "success")
        return redirect(url_for("teacher_dashboard"))
    return render_template("add_job.html")
app.jinja_env.globals.update(getenv=os.getenv)

# Ensure teacher password hashes exist and remove plaintext passwords from memory
for t in TEACHERS:
    # if teacher already has password_hash, keep it
    if not t.get("password_hash") and t.get("password"):
        t["password_hash"] = generate_password_hash(t["password"])
    # remove plaintext password to avoid accidental leakage
    if "password" in t:
        del t["password"]

@app.route("/teacher/manage_jobs", methods=["GET", "POST"])
@login_required
@teacher_required
def manage_jobs():
    """
    Teacher job management page:
    - Lists all jobs with deadlines, application counts, and statuses.
    - Allows safe deletion only if no active applications exist.
    """
    IST = tz(timedelta(hours=5, minutes=30))

    # --- POST: Handle job deletion safely ---
    if request.method == "POST":
        job_id = request.form.get("job_id")
        action = request.form.get("action")

        if not job_id:
            flash("⚠️ Missing job ID.", "danger")
            return redirect(url_for("manage_jobs"))

        # ✅ Safe ObjectId conversion
        job_oid = mongo_objid_from_str(job_id)
        if not job_oid:
            flash("❌ Invalid Job ID.", "danger")
            return redirect(url_for("manage_jobs"))

        job = jobs_col.find_one({"_id": job_oid})
        if not job:
            flash("⚠️ Job not found.", "warning")
            return redirect(url_for("manage_jobs"))

        # 🔹 Handle deletion
        if action == "delete":
            active_apps = applications_col.count_documents({
                "job_id": job_oid,
                "status": {"$in": ["upload_required", "submitted", "under_review", "corrections_needed"]}
            })

            if active_apps > 0:
                flash("⚠️ Cannot delete job with active applications.", "warning")
                return redirect(url_for("manage_jobs"))

            jobs_col.delete_one({"_id": job_oid})
            flash(f"🗑️ Job '{job.get('title', 'Untitled Job')}' deleted successfully.", "success")
            return redirect(url_for("manage_jobs"))

    # --- GET: Display all jobs ---
    jobs = list(jobs_col.find().sort("deadline", 1))
    now_ist = datetime.now(IST)

    for j in jobs:
        job_id = j["_id"]

        # 🔹 Format deadline
        dl = j.get("deadline")
        if dl:
            if dl.tzinfo is None:
                dl = dl.replace(tzinfo=tz.utc)
            j["deadline_ist"] = dl.astimezone(IST).strftime("%d %b %Y, %I:%M %p")
        else:
            j["deadline_ist"] = "Not set"

        # 🔹 Application counts (consistent with ObjectId job_id)
        j["total_applications"] = applications_col.count_documents({"job_id": job_id})
        j["active_applications"] = applications_col.count_documents({
            "job_id": job_id,
            "status": {"$in": ["upload_required", "submitted", "corrections_needed"]}
        })
        j["approved_applications"] = applications_col.count_documents({
            "job_id": job_id,
            "status": "approved"
        })

        # 🔹 Prepare ID for Jinja templates
        j["job_id_str"] = str(job_id)

    return render_template("manage_jobs.html", jobs=jobs)

from random import randint
from datetime import datetime, timedelta

# temporary in-memory OTP store (you can later move this to Mongo)
otp_store = {}

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password_request():
    if request.method == "POST":
        email = request.form.get("email").strip().lower()
        user = users_col.find_one({"email": email})

        if not user:
            flash("⚠️ No account found with this email.", "warning")
            return redirect(url_for("reset_password_request"))

        # generate a 6-digit OTP
        otp = str(randint(100000, 999999))
        expiry = datetime.now() + timedelta(minutes=10)
        otp_store[email] = {"otp": otp, "expires": expiry}

        # send the OTP via email
        try:
            html = render_template("email/reset_otp.html", otp=otp, user=user)
            send_brevo_email(email, user.get("name", "User"), "🔐 Password Reset OTP", html)
            flash("✅ OTP sent to your registered email.", "success")
            return redirect(url_for("verify_otp"))
        except Exception as e:
            logger.exception("Failed to send OTP: %s", e)
            flash("⚠️ Could not send OTP. Please try again later.", "danger")
            return redirect(url_for("reset_password_request"))

    return render_template("reset_password_request.html")

@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    if request.method == "POST":
        email = request.form.get("email").strip().lower()
        otp_input = request.form.get("otp").strip()
        new_pw = request.form.get("password").strip()

        record = otp_store.get(email)
        if not record:
            flash("❌ No OTP found for this email. Please request again.", "danger")
            return redirect(url_for("reset_password_request"))

        if datetime.now() > record["expires"]:
            flash("⚠️ OTP expired. Please request a new one.", "warning")
            otp_store.pop(email, None)
            return redirect(url_for("reset_password_request"))

        if otp_input != record["otp"]:
            flash("❌ Invalid OTP. Please try again.", "danger")
            return redirect(url_for("verify_otp"))

        # update password in database
        hashed = generate_password_hash(new_pw)
        users_col.update_one({"email": email}, {"$set": {"password_hash": hashed}})
        otp_store.pop(email, None)
        flash("✅ Password reset successful! You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("verify_otp.html")

from flask_wtf.csrf import generate_csrf

@app.route("/debug-token")
def debug_token():
    return generate_csrf()

@app.route("/teacher/edit_job/<job_id>", methods=["GET", "POST"])
@login_required
@teacher_required
def edit_job(job_id):
    job = jobs_col.find_one({"_id": mongo_objid_from_str(job_id)})
    if not job:
        flash("Job not found.", "danger")
        return redirect(url_for("manage_jobs"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        specifications = request.form.get("specifications", "").strip()
        vacancies = int(request.form.get("vacancies") or job.get("vacancies", 1))
        deadline_str = request.form.get("deadline")
        if deadline_str:
            dt_ist = datetime.strptime(deadline_str, "%Y-%m-%dT%H:%M")
            deadline_utc = ist_to_utc(dt_ist)
        else:
            deadline_utc = None
        jobs_col.update_one({"_id": job["_id"]}, {"$set": {
            "title": title,
            "description": description,
            "specifications": specifications,
            "vacancies": vacancies,
            "deadline": deadline_utc
        }})
        flash("Job updated.", "success")
        return redirect(url_for("manage_jobs"))
    job = objectid_to_str(job)
    job["deadline_str"] = utc_to_ist_str(job.get("deadline"))
    return render_template("edit_job.html", job=job)

@app.route("/teacher/delete_job/<job_id>", methods=["POST"])
@login_required
@teacher_required
def delete_job(job_id):
    job = jobs_col.find_one({"_id": mongo_objid_from_str(job_id)})
    if not job:
        flash("Job not found.", "danger")
        return redirect(url_for("manage_jobs"))
    # Optionally delete related applications and files
    apps = list(applications_col.find({"job_id": job["_id"]}))
    for a in apps:
        # delete files referenced by application
        for key in ("resume_filename", "photo_filename"):
            fn = a.get(key)
            if fn:
                p = os.path.join(app.config["UPLOAD_FOLDER"], fn)
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    logger.exception("Failed to remove %s", p)
        applications_col.delete_one({"_id": a["_id"]})
    jobs_col.delete_one({"_id": job["_id"]})
    flash("Job and its applications removed.", "success")
    return redirect(url_for("manage_jobs"))

# 🧠 Teacher — View Self Assessments
@app.route("/teacher/self-assessments", methods=["GET"])
@login_required
@teacher_required
def teacher_self_assessments():
    # Fetch all self-assessment submissions
    responses = list(self_assess_col.find().sort("submitted_at", -1))
    for r in responses:
        student = users_col.find_one({"_id": r.get("student_id")})
        r["student_name"] = student.get("name") if student else "Unknown"
        r["student_email"] = student.get("email") if student else "N/A"
        r["_id_str"] = str(r["_id"])

    return render_template("teacher_self_assessments.html", responses=responses)
# --------------------------------------------------------------------------
# Teacher Growth Hub View
# --------------------------------------------------------------------------
@app.route("/teacher/growth_hub")
@login_required
@teacher_required
def teacher_growth_hub():
    """
    Displays all student progress data from the Growth Hub collection.
    """
    growth_data = list(db.growth_responses.find({}))
    
    # Enrich growth data with student details
    for record in growth_data:
        student = db.users.find_one({"_id": record.get("student_id")})
        record["student_name"] = student.get("name") if student else "Unknown"
        record["student_email"] = student.get("email") if student else "N/A"
        record["_id"] = str(record["_id"])
        record["completion"] = record.get("completion", 0)

    return render_template("teacher_growth_hub.html", growth_data=growth_data)

@app.route("/teacher/assess/<job_id>", methods=["GET", "POST"])
@login_required
@teacher_required
def assess_students_for_job(job_id):
    job_oid = mongo_objid_from_str(job_id)
    if not job_oid:
        if request.is_json:
            return jsonify({"success": False, "error": "Invalid Job ID"}), 400
        flash("❌ Invalid Job ID.", "danger")
        return redirect(url_for("manage_jobs"))

    # -------------------------- POST REQUEST --------------------------
    if request.method == "POST":
        # Parse input (AJAX or normal form)
        if request.is_json:
            data = request.get_json()
            app_id = data.get("app_id")
            new_status = data.get("status")
            feedback = data.get("feedback", "").strip()
        else:
            app_id = request.form.get("app_id")
            new_status = request.form.get("status")
            feedback = request.form.get("feedback", "").strip()

        # Validate input
        if not app_id:
            msg = "❌ Missing application ID."
            if request.is_json:
                return jsonify({"success": False, "error": msg}), 400
            flash(msg, "danger")
            return redirect(url_for("assess_students_for_job", job_id=job_id))

        application = applications_col.find_one({"_id": ObjectId(app_id)})
        if not application:
            msg = "⚠️ Application not found."
            if request.is_json:
                return jsonify({"success": False, "error": msg}), 404
            flash(msg, "danger")
            return redirect(url_for("assess_students_for_job", job_id=job_id))

        previous_status = application.get("status")

        # Update application
        applications_col.update_one(
            {"_id": ObjectId(app_id)},
            {"$set": {
                "status": new_status,
                "teacher_feedback": feedback,
                "last_updated": datetime.now(tz=tz(timedelta(hours=5, minutes=30)))
            }}
        )

        # -------------------------- VACANCY LOGIC --------------------------
        job = jobs_col.find_one({"_id": application.get("job_id")})
        if job:
            vacancies = job.get("vacancies", 0)

            # Only change vacancy if the status actually changes
            if previous_status != new_status:
                # Rejected → +1 (only if wasn't already rejected/cleared)
                if new_status == "rejected" and previous_status not in ["rejected", "cleared"]:
                    vacancies += 1

                # Reinstating from rejected → -1 (if going to active state)
                elif previous_status == "rejected" and new_status not in ["rejected", "cleared"]:
                    vacancies = max(0, vacancies - 1)

                # Newly submitted → -1
                elif new_status == "submitted" and previous_status not in ["submitted"]:
                    vacancies = max(0, vacancies - 1)

            jobs_col.update_one({"_id": job["_id"]}, {"$set": {"vacancies": vacancies}})
            logger.info(f"Vacancy updated for '{job.get('title')}': {previous_status} → {new_status}, now {vacancies}")

        # -------------------------- EMAIL NOTIFICATION --------------------------
        student = users_col.find_one({"_id": application.get("applicant_id")})
        if student:
            try:
                student_name = student.get("name", "Student")
                student_email = student.get("email")
                job_title = job.get("title", "Application") if job else "Application"

                status_html = render_template(
                    "email/student_status_update.html",
                    student_name=student_name,
                    job_title=job_title,
                    status=new_status,
                    feedback=feedback,
                    now=datetime.now
                )
                send_brevo_email(
                    student_email,
                    student_name,
                    f"📢 Update on your application for {job_title}",
                    status_html
                )
                logger.info(f"Email sent to {student_email} ({job_title})")
            except Exception as e:
                logger.exception("Email sending failed: %s", e)

        # -------------------------- RESPONSE HANDLING --------------------------
        if request.is_json:
            return jsonify({"success": True, "new_status": new_status})
        else:
            flash("✅ Application updated and student notified!", "success")
            return redirect(url_for("assess_students_for_job", job_id=job_id))

    # -------------------------- GET REQUEST --------------------------
    job = jobs_col.find_one({"_id": job_oid})
    if not job:
        flash("⚠️ Job not found.", "danger")
        return redirect(url_for("manage_jobs"))

    applications = list(applications_col.find({"job_id": job_oid}).sort("application_time", -1))
    for app in applications:
        student = users_col.find_one({"_id": app.get("applicant_id")})
        app["student_name"] = student.get("name", "Unknown") if student else "Unknown"
        app["student_email"] = student.get("email", "N/A") if student else "N/A"
        app["job_title"] = job.get("title", "Unknown")
        app["app_id_str"] = str(app["_id"])

    return render_template("assess_students.html", applications=applications, job=job)

@app.route("/teacher/clear_applications", methods=["GET", "POST"])
@login_required
@teacher_required
def clear_applications():
    # Fetch all student applications
    applications = list(applications_col.find().sort("application_time", -1))

    if request.method == "POST":
        app_id = request.form.get("app_id")
        if not app_id:
            flash("⚠️ Missing application ID.", "danger")
            return redirect(url_for("clear_applications"))

        app_to_delete = applications_col.find_one({"_id": ObjectId(app_id)})
        if not app_to_delete:
            flash("Application not found.", "danger")
            return redirect(url_for("clear_applications"))

        # Delete uploaded files if they exist
        for key in ("resume_filename", "photo_filename"):
            fn = app_to_delete.get(key)
            if fn:
                file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], fn)
                if os.path.exists(file_path):
                    os.remove(file_path)

        # Remove from DB
        applications_col.delete_one({"_id": ObjectId(app_id)})

        # Restore job vacancy if deleted before
        job = jobs_col.find_one({"_id": app_to_delete.get("job_id")})
        if job:
            jobs_col.update_one(
                {"_id": job["_id"]},
                {"$inc": {"vacancies": 1}}
            )

        flash("✅ Application cleared successfully!", "success")
        return redirect(url_for("clear_applications"))

    # Attach readable details for table view
    applications_with_details = []
    for app_entry in applications:
        student = users_col.find_one({"_id": app_entry.get("applicant_id")})
        job = jobs_col.find_one({"_id": app_entry.get("job_id")})
        app_entry["student_name"] = student.get("name", "Unknown") if student else "Unknown"
        app_entry["student_email"] = student.get("email", "N/A") if student else "N/A"
        app_entry["job_title"] = job.get("title", "Deleted Job") if job else app_entry.get("job_title", "Unknown")
        app_entry["app_id_str"] = str(app_entry["_id"])
        applications_with_details.append(app_entry)

    return render_template("clear_application.html", applications=applications_with_details)

@app.route("/teacher/clear-application/<app_id>", methods=["POST"])
@login_required
@teacher_required
def clear_application(app_id):
    # Find the application
    application = applications_col.find_one({"_id": mongo_objid_from_str(app_id)})
    if not application:
        flash("⚠️ Application not found.", "danger")
        return redirect(url_for("assess_students"))

    # --- Handle vacancy restoration ---
    job = jobs_col.find_one({"_id": application.get("job_id")})
    if job:
        new_vacancies = job.get("vacancies", 0) + 1
        jobs_col.update_one({"_id": job["_id"]}, {"$set": {"vacancies": new_vacancies}})
        logger.info(f"Vacancy restored for job '{job.get('title', 'Unknown')}'. Now: {new_vacancies}")

    # --- Delete uploaded files (resume & photo) safely ---
    for key in ("resume_filename", "photo_filename"):
        filename = application.get(key)
        if filename:
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Deleted file: {file_path}")
            except Exception as e:
                logger.exception(f"Failed to remove {file_path}: {e}")

    # --- Remove the application from database ---
    applications_col.delete_one({"_id": application["_id"]})

    flash("🗑️ Application cleared and vacancy restored.", "success")
    return redirect(url_for("assess_students"))

# -------------------------
# Exports (CSV)
# -------------------------
# --------------------------------------------------------------------------
# Teacher: Export Dashboard Data (Registered & Assessed Students)
# --------------------------------------------------------------------------
from flask import make_response
import pandas as pd
from io import BytesIO

@app.route("/teacher/export", methods=["GET"])
@login_required
@teacher_required
def export_dashboard_data():
    """
    Exports two Excel sheets:
    1. Registered Students
    2. Assessed Applications
    """
    # Fetch Registered Students
    students = list(db.users.find({"role": "student"}))
    for s in students:
        s["_id"] = str(s["_id"])

    # Fetch Applications with Student & Job info
    applications = list(db.applications.find())
    for a in applications:
        user = db.users.find_one({"_id": a.get("applicant_id")})
        job = db.jobs.find_one({"_id": a.get("job_id")})
        a["student_name"] = user.get("name") if user else "Unknown"
        a["student_email"] = user.get("email") if user else "N/A"
        a["job_title"] = job.get("title") if job else "N/A"
        a["_id"] = str(a["_id"])
        if a.get("application_time"):
            a["application_time"] = a["application_time"].strftime("%Y-%m-%d %H:%M:%S")

    # Create DataFrames
    df_students = pd.DataFrame(students)
    df_apps = pd.DataFrame(applications)

    # Excel in memory
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_students.to_excel(writer, sheet_name="Registered Students", index=False)
        df_apps.to_excel(writer, sheet_name="Assessed Applications", index=False)

    # Build response
    output.seek(0)
    response = make_response(output.read())
    response.headers["Content-Disposition"] = "attachment; filename=TeacherDashboardData.xlsx"
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return response

@app.route("/teacher/export/registered")
@login_required
def export_registered_students():
    from io import BytesIO
    import pandas as pd
    from flask import send_file

    students = list(db.users.find({"role": "student"}))
    if not students:
        flash("No registered students to export.", "warning")
        return redirect(url_for("registered_students"))

    # Convert MongoDB data to DataFrame
    df = pd.DataFrame(students)
    df = df[["name", "email"]]  # Keep relevant columns only

    # Convert to Excel
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Registered Students")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="registered_students.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# --------------------------------------------------------------------------
# Teacher: View Registered Students
# --------------------------------------------------------------------------
@app.route("/teacher/registered_students")
@login_required
@teacher_required
def registered_students():
    """
    Displays a list of all registered students from the database.
    """
    students = list(db.users.find({"role": "student"}))
    for s in students:
        s["_id"] = str(s["_id"])
        s["app_count"] = db.applications.count_documents({"applicant_id": s["_id"]})
        s["growth_progress"] = 0  # placeholder — replace if growth tracking exists

    return render_template("registered_students.html", students=students)

@app.route("/teacher/export/assessed_students")
@login_required
@teacher_required
def export_assessed_students():
    cursor = applications_col.find({"status": {"$in": ["approved", "rejected", "corrections_needed"]}})
    rows = []
    for a in cursor:
        applicant = users_col.find_one({"_id": a.get("applicant_id")})
        rows.append({
            "application_id": str(a.get("_id")),
            "student_name": applicant.get("name") if applicant else "",
            "student_email": applicant.get("email") if applicant else "",
            "job_title": a.get("job_title"),
            "status": a.get("status"),
            "application_time": a.get("application_time").isoformat() if a.get("application_time") else "",
            "teacher_feedback": a.get("teacher_feedback", "")
        })
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="assessed_students.csv", mimetype="text/csv")

# -------------------------
# Debug route (DB counts)
# -------------------------
@app.route("/debug/db")
def debug_db():
    try:
        info = {
            "users": users_col.count_documents({}),
            "jobs": jobs_col.count_documents({}),
            "applications": applications_col.count_documents({}),
            "growth_responses": growth_col.count_documents({}),
            "self_assessments": self_assess_col.count_documents({})
        }
        sample_users = list(users_col.find().limit(5))
        # convert ObjectId to str for JSON
        for u in sample_users:
            u["_id"] = str(u["_id"])
            if "created_at" in u and hasattr(u["created_at"], "isoformat"):
                u["created_at"] = u["created_at"].isoformat()
        return jsonify({"ok": True, "info": info, "sample_users": sample_users})
    except Exception as e:
        logger.exception("Debug DB failed")
        return jsonify({"ok": False, "error": str(e)}), 500

# -------------------------
# Error handlers
# -------------------------
@app.errorhandler(403)
def forbidden(e):
    try:
        return render_template("403.html"), 403
    except Exception:
        return "403 Forbidden", 403

@app.errorhandler(404)
def not_found(e):
    try:
        return render_template("404.html"), 404
    except Exception:
        return "404 Not Found", 404

@app.errorhandler(500)
def server_error(e):
    try:
        return render_template("500.html", error=str(e)), 500
    except Exception:
        return f"500 Server Error: {e}", 500

# -------------------------
# Helper: ensure templates present (warn)
# -------------------------
def check_templates_exist():
    # We'll scan common templates referenced above
    templates = [
        "startpage.html", "login.html", "register.html", "student_dashboard.html",
        "teacher_dashboard.html", "upload_files.html", "upload_blocked.html",
        "add_job.html", "manage_jobs.html", "edit_job.html", "job_detail.html",
        "assess_students.html", "403.html", "404.html", "500.html"
    ]
    missing = []
    for t in templates:
        p = BASE_DIR / "templates" / t
        if not p.exists():
            missing.append(t)
    if missing:
        logger.warning("Missing templates detected: %s", missing)

# Run check at startup
check_templates_exist()

# -------------------------
# Run app
# -------------------------
if __name__ == "__main__":
    # Local dev: port 10000
    port = int(os.getenv("PORT", 10000))
    host = os.getenv("HOST", "0.0.0.0")
    logger.info("Starting Know-Thyself local server on %s:%s", host, port)
    app.run(host=host, port=port, debug=True)