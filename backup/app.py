import os
import datetime
import filetype
from bson.objectid import ObjectId
from flask import flash, redirect, url_for
from flask_login import current_user, login_required
from datetime import datetime, timedelta
import datetime
import io
import pandas as pd
from datetime import datetime
from bson import ObjectId 
from flask_wtf import FlaskForm
from bson.objectid import ObjectId
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, IntegerField, SubmitField
from wtforms.validators import DataRequired
from flask import abort, session
from wtforms import StringField, SubmitField, PasswordField, FileField, IntegerField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional, EqualTo
from flask import (
    Flask, render_template, redirect, url_for, request,
    flash, send_from_directory, send_file
)
from flask_pymongo import PyMongo
from flask_login import (
    LoginManager, login_user, logout_user, login_required,
    current_user, UserMixin
)
from passlib.hash import bcrypt
from flask_mail import Mail, Message
import random
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import pytz

from flask import Flask
from flask_pymongo import PyMongo
import os

app = Flask(__name__)

# Get the Mongo URI from Render (or .env for local)
import os
app.config['MONGO_URI'] = os.environ.get('MONGO_URI')

mongo = PyMongo(app)


IST = pytz.timezone('Asia/Kolkata')
now_ist = datetime.now(IST)
deadline = now_ist + timedelta(hours=48)

# ---------- App Setup and Configuration ----------

# Load environment variables from .env file securely
load_dotenv()

# Instantiate Flask app with template and static folders
app = Flask(__name__, template_folder="templates", static_folder="static")

# Configure app settings
app.config.from_mapping(
    SECRET_KEY=os.getenv("SECRET_KEY", "dev-secret"),
    UPLOAD_FOLDER=os.getenv("UPLOAD_FOLDER", "uploads"),
    MAX_CONTENT_LENGTH=int(os.getenv("MAX_CONTENT_LENGTH", 5 * 1024 * 1024)),  # 5MB default max upload size
    MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
    MAIL_PORT=int(os.getenv("MAIL_PORT", 465)),
    MAIL_USE_TLS=os.getenv("MAIL_USE_TLS", "false").lower() == "true",
    MAIL_USE_SSL=os.getenv("MAIL_USE_SSL", "true").lower() == "true",
    MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
)

# Ensure upload folder exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Setup extensions: MongoDB, Mail, Login Manager, Scheduler
mongo = PyMongo(app)
mail = Mail(app)
login_manager = LoginManager(app)
scheduler = BackgroundScheduler()
scheduler.start()


# ---------- User Model ----------

class User(UserMixin):
    """User class wrapping MongoDB user document for Flask-Login"""

    def __init__(self, doc):
        self.id = str(doc["_id"])
        self.role = doc["role"]
        self.email = doc["email"]
        self.student_id = doc.get("student_id")  # Optional
        self.name = doc["name"]

    @staticmethod
    def get(user_id):
        """Load user by MongoDB ObjectId string"""
        doc = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        return User(doc) if doc else None


@login_manager.user_loader
def load_user(user_id):
    """Flask-Login user loader callback"""
    return User.get(user_id)


# ---------- Forms ----------

class LoginForm(FlaskForm):
    """Login form accepting email or student ID"""
    email_or_sid = StringField("Email or Student ID", validators=[DataRequired()])
    password     = PasswordField("Password", validators=[DataRequired()])
    submit       = SubmitField("Sign In")


class RegisterForm(FlaskForm):
    """Registration form for students"""
    student_id = StringField("Student ID", validators=[DataRequired()])
    name       = StringField("Full Name", validators=[DataRequired()])
    email      = StringField("Email", validators=[Email(), DataRequired()])
    phone      = StringField("Phone", validators=[Length(min=8), DataRequired()])
    password   = PasswordField(
        "Password",
        validators=[Length(min=8), EqualTo("confirm", "Passwords must match")],
    )
    confirm    = PasswordField("Repeat Password")
    submit     = SubmitField("Create Account")


class JobForm(FlaskForm):
    """Form to create or edit a job"""
    title       = StringField("Job Title", validators=[DataRequired()])
    description = TextAreaField("Description", validators=[DataRequired()])
    vacancies   = IntegerField("Vacancies", validators=[DataRequired()])
    pof         = FileField("PoF (PDF)")
    submit      = SubmitField("Save")


class EditProfileForm(FlaskForm):
    """Form for student profile editing with optional password change"""
    name = StringField("Full Name", validators=[DataRequired()])
    email = StringField("Email", validators=[Email(), DataRequired()])
    phone = StringField("Phone", validators=[Length(min=8), DataRequired()])
    password = PasswordField(
        "New Password", validators=[Optional(), Length(min=8)]
    )
    confirm = PasswordField(
        "Repeat Password",
        validators=[EqualTo("password", "Passwords must match"), Optional()]
    )
    submit = SubmitField("Save Changes")


# ---------- Helper Functions ----------

def hash_pw(raw):
    """Hash a raw password"""
    return bcrypt.hash(raw)

def check_pw(raw, h):
    """Verify a password against hash"""
    return bcrypt.verify(raw, h)

def send_resume_mail(filename, applicant_email):
    """Send email to notify about new résumé submission"""
    msg = Message(
        "New Résumé Submission",
        sender=app.config["MAIL_USERNAME"],
        recipients=[os.getenv("NOTICE_MAILBOX")]
    )
    msg.body = f"Résumé from {applicant_email}"
    with app.open_resource(os.path.join(app.config["UPLOAD_FOLDER"], filename)) as fp:
        msg.attach(filename, "application/pdf", fp.read())
    mail.send(msg)

def cleanup_deadlines():
    """Mark applications with expired upload window as rejected_auto"""
    now = datetime.utcnow()
    expired = mongo.db.applications.find({
        "resume_filename": {"$exists": False},
        "resume_deadline": {"$lt": now},
    })
    for doc in expired:
        mongo.db.applications.update_one(
            {"_id": doc["_id"]}, {"$set": {"status": "rejected_auto"}}
        )

# Schedule deadline cleanup every 12 hours
scheduler.add_job(cleanup_deadlines, "interval", hours=12)

def generate_otp():
    """Generate a 6-digit OTP"""
    return str(random.randint(100000, 999999))

def send_otp_email(to_email, otp):
    """Send OTP email for password change verification"""
    msg = Message(
        subject='Your OTP for Password Change',
        sender=app.config["MAIL_USERNAME"],
        recipients=[to_email]
    )
    msg.body = f"Your OTP to change your password is: {otp}\nIf you did not request this, ignore this email."
    mail.send(msg)


# ---------- Routes ----------

# --- Homepage showing Public Jobs ---
@app.route("/")
def startpage():
    # This ALWAYS shows the startup page/quote, no matter user type or login status
    return render_template("startpage.html")

# --- Authentication ---

@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user_doc = mongo.db.users.find_one({
            "$or": [
                {"email": form.email_or_sid.data.lower()},
                {"student_id": form.email_or_sid.data.upper()}
            ]
        })
        if user_doc and check_pw(form.password.data, user_doc.get("pw_hash", "")):
            login_user(User(user_doc))
            flash("Welcome!", "success")
            if user_doc["role"] == "teacher":
                return redirect(url_for("teacher_dashboard"))
            else:
                return redirect(url_for("student_dashboard"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html", form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('startpage'))

@app.route("/register", methods=["GET", "POST"])
def register():
    """Student registration page"""
    form = RegisterForm()
    if form.validate_on_submit():
        exists = mongo.db.users.find_one({
            "$or": [
                {"email": form.email.data.lower()},
                {"student_id": form.student_id.data.upper()}
            ]})
        if exists:
            flash("Account already exists", "warning")
        else:
            mongo.db.users.insert_one({
                "role": "student",
                "student_id": form.student_id.data.upper(),
                "name": form.name.data,
                "email": form.email.data.lower(),
                "phone": form.phone.data,
                "pw_hash": hash_pw(form.password.data),
                "created_at": datetime.utcnow(),
            })
            flash("Account created—please sign in", "success")
            return redirect(url_for("login"))
    return render_template("register.html", form=form)


# --- Student Routes ---

@app.route("/jobs")
def job_list():
    jobs = list(mongo.db.jobs.find({"status": "open"}))
    return render_template("job_list.html", jobs=jobs)
@app.route('/resources')
def resources():
    return render_template('resources.html')
@app.route('/advice')
def advice():
    return render_template("advice.html")
import os
from flask import request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from bson import ObjectId
from werkzeug.utils import secure_filename
from flask_mail import Message

@app.route("/upload_resume/<job_id>", methods=["POST"])
@login_required
def upload_resume(job_id):
    if current_user.role != "student":
        flash("Unauthorized access.", "danger")
        return redirect(url_for('startpage'))
    
    file = request.files.get('resume')
    if not file or file.filename == '':
        flash("No resume selected.", "warning")
        return redirect(url_for('student_dashboard'))

    # Validate file type - allow PDF or Word Documents
    # You can improve with filetype==1.2.0 or filename checks
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.pdf', '.doc', '.docx']:
        flash("Allowed file types are PDF, DOC, DOCX.", "warning")
        return redirect(url_for('student_dashboard'))

    # Secure filename to avoid path injection
    filename = secure_filename(f"{current_user.student_id}_{job_id}{ext}")
    upload_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    
    # Save file
    file.save(upload_path)

    # Update application in DB
    mongo.db.applications.update_one(
        {"user_id": ObjectId(current_user.id), "job_id": ObjectId(job_id)},
        {
            "$set": {
                "resume_filename": filename,
                "status": "submitted",
                "resume_uploaded_at": datetime.utcnow()
            }
        },
        upsert=True
    )

    # Send notification email with the resume attached
    job = mongo.db.jobs.find_one({"_id": ObjectId(job_id)})
    faculty_email = job.get('posted_by_email', 'psychologyresumemail@gmail.com')

    msg = Message(
        subject=f"New Resume Uploaded for '{job['title']}'",
        sender=current_app.config['MAIL_USERNAME'],
        recipients=[faculty_email]
    )
    msg.body = f"Student {current_user.name or current_user.email} has uploaded a resume for job '{job['title']}'."

    with open(upload_path, 'rb') as fp:
        msg.attach(filename, "application/octet-stream", fp.read())

    try:
        mail.send(msg)
        flash("Resume uploaded and emailed successfully.", "success")
    except Exception as e:
        flash(f"Resume uploaded but email sending failed: {e}", "warning")

    return redirect(url_for('student_dashboard'))


from datetime import datetime
import pytz
from bson.objectid import ObjectId
from flask import render_template, redirect, url_for, flash
from flask_login import current_user, login_required

IST = pytz.timezone('Asia/Kolkata')

from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

@app.route("/student/")
@login_required
def student_dashboard():
    if current_user.role != "student":
        return redirect(url_for("teacher_dashboard"))

    # 1. Get student applications and enrich with job info
    pipeline = [
        {"$match": {"user_id": ObjectId(current_user.id)}},
        {"$lookup": {
            "from": "jobs",
            "localField": "job_id",
            "foreignField": "_id",
            "as": "job"
        }},
        {"$unwind": "$job"},
        {"$sort": {"applied_at": -1}},
    ]
    apps = list(mongo.db.applications.aggregate(pipeline))

    # 2. Get open jobs
    jobs = list(mongo.db.jobs.find({"status": "open"}).sort("created_at", -1))

    # 3. Determine applied jobs
    applied_ids = {app["job_id"] for app in apps}
    has_active_application = any(
        app.get("status") in ("pending_resume", "submitted") for app in apps
    )

    # 4. Enhance each app object
    now = datetime.now(IST)
    for app in apps:
        # Descriptive message
        status = app.get("status", "")
        if status == "approved":
            app["status_message"] = "🎉 Yay! Your application is approved."
        elif status == "rejected":
            app["status_message"] = "😞 Your application was rejected."
        elif status == "corrections_needed":
            app["status_message"] = "🛠️ Improvements needed – check feedback."
        else:
            app["status_message"] = ""

        # Normalize resume_deadline to IST-aware
        deadline = app.get("resume_deadline")
        if deadline and deadline.tzinfo is None:
            app["resume_deadline"] = IST.localize(deadline)

    return render_template(
        "student_dashboard.html",
        apps=apps,
        jobs=jobs,
        applied_ids=applied_ids,
        has_active=has_active_application,
        now=now  # ✅ IST-aware datetime passed to template
    )

from datetime import datetime, timedelta, timezone
import pytz
from bson.objectid import ObjectId
from flask import flash, redirect, url_for, request
from flask_login import current_user, login_required

IST = pytz.timezone('Asia/Kolkata')

@app.route("/apply/<job_id>", methods=["POST"])
@login_required
def apply(job_id):
    # Only students can apply
    if current_user.role != "student":
        flash("Only students can apply for jobs.", "danger")
        return redirect(url_for("index"))

    # Validate job_id is a valid ObjectId
    try:
        job_obj_id = ObjectId(job_id)
    except Exception:
        flash("Invalid job ID.", "danger")
        return redirect(url_for("student_dashboard"))

    # Check if student has active application
    active_statuses = ["pending_resume", "submitted", "approved"]
    existing_application = mongo.db.applications.find_one({
        "user_id": ObjectId(current_user.id),
        "status": {"$in": active_statuses}
    })

    if existing_application:
        flash("You already have an active application. You can only apply for one job at a time.", "warning")
        return redirect(url_for("student_dashboard"))

    # Check job exists and is open
    job = mongo.db.jobs.find_one({"_id": job_obj_id, "status": "open"})
    if not job:
        flash("This job is no longer available.", "danger")
        return redirect(url_for("student_dashboard"))

    # Check vacancies left
    applications_count = mongo.db.applications.count_documents({
        "job_id": job_obj_id,
        "status": {"$in": active_statuses}
    })

    if applications_count >= job.get("vacancies", 0):
        flash("Sorry, no vacancies are available for this job.", "danger")
        return redirect(url_for("student_dashboard"))

    # Calculate times in IST and convert to UTC naive for storage
    
    now_ist = datetime.now(IST)
    deadline_ist = now_ist + timedelta(hours=48)
    applied_at_utc = now_ist
    deadline_utc = deadline_ist

    # Insert the application
    mongo.db.applications.insert_one({
        "job_id": job_obj_id,
        "user_id": ObjectId(current_user.id),
        "applied_at": applied_at_utc,
        "resume_deadline": deadline_utc,
        "status": "pending_resume",
    })

    # Decrement vacancies atomically, avoid negatives
    mongo.db.jobs.update_one(
        {"_id": job_obj_id, "vacancies": {"$gt": 0}},
        {"$inc": {"vacancies": -1}}
    )

    flash("Application successful! Please upload your résumé within 48 hours.", "success")
    return redirect(url_for("student_dashboard"))


@app.route("/upload/<app_id>", methods=["POST"])
@login_required
def upload(app_id):
    doc = mongo.db.applications.find_one({"_id": ObjectId(app_id)})
    if (not doc) or doc["user_id"] != ObjectId(current_user.id):
        return redirect(url_for("student_dashboard"))
    if datetime.now() > doc["resume_deadline"]:
        flash("Upload window closed", "danger")
        return redirect(url_for("student_dashboard"))

    f = request.files.get("resume")
    if not f:
        flash("No file selected", "warning")
        return redirect(url_for("student_dashboard"))
    if magic.from_buffer(f.read(1024), mime=True) != "application/pdf":
        flash("File must be PDF", "warning")
        return redirect(url_for("student_dashboard"))
    f.seek(0)
    fname = secure_filename(f"{current_user.student_id}_{app_id}.pdf")
    f.save(os.path.join(app.config["UPLOAD_FOLDER"], fname))

    mongo.db.applications.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "resume_filename": fname,
                "status": "submitted",
                "resume_uploaded_at": datetime.utcnow()  # <-- Add timestamp here
            }
        }
    )

    send_resume_mail(fname, current_user.email)
    flash("Résumé uploaded", "success")
    return redirect(url_for("student_dashboard"))

# --- Teacher Routes ---
@app.route("/teacher/")
@login_required
def teacher_dashboard():
    if current_user.role != "teacher":
        return redirect(url_for("student_dashboard"))

    page = int(request.args.get("page", 1))
    per_page = 10
    skip = (page - 1) * per_page

    students_total = mongo.db.users.count_documents({"role": "student"})
    students_cursor = (
        mongo.db.users.find({"role": "student"})
        .sort("name", 1)
        .skip(skip)
        .limit(per_page)
    )
    students = list(students_cursor)
    total_pages = (students_total + per_page - 1) // per_page

    jobs = list(mongo.db.jobs.find().sort("created_at", -1))

    active_statuses = ["pending_resume", "submitted", "approved"]
    pending_statuses = ["pending_resume", "corrections_needed"]

    active_app_count = mongo.db.applications.count_documents({"status": {"$in": active_statuses}})
    pending_app_count = mongo.db.applications.count_documents({"status": {"$in": pending_statuses}})
    total_applications = mongo.db.applications.count_documents({})

    recent_pending_apps = list(mongo.db.applications.aggregate([
        {"$match": {"status": {"$in": pending_statuses}}},
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "_id", "as": "user"}},
        {"$unwind": "$user"},
        {"$lookup": {"from": "jobs", "localField": "job_id", "foreignField": "_id", "as": "job"}},
        {"$unwind": "$job"},
        {"$sort": {"applied_at": -1}},
        {"$limit": 10},
    ]))

    return render_template(
        "teacher_dashboard.html",
        jobs=jobs,
        students=students,
        students_total=students_total,
        total_pages=total_pages,
        page=page,
        active_app_count=active_app_count,
        pending_app_count=pending_app_count,
        total_applications=total_applications,
        recent_pending_apps=recent_pending_apps,
    )

@app.route("/update_application/<app_id>", methods=["POST"])
@login_required
def update_application(app_id):
    if current_user.role != "teacher":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("teacher_dashboard"))

    status = request.form.get("status")
    feedback = request.form.get("feedback")  # Get feedback from form

    update_data = {"$set": {"status": status}}
    if feedback:
        update_data["$set"]["teacher_feedback"] = feedback  # Save feedback here

    mongo.db.applications.update_one({"_id": ObjectId(app_id)}, update_data)
    flash("Application updated successfully.", "success")
    return redirect(url_for("teacher_dashboard"))

from flask import render_template, flash, redirect, url_for, request
from flask_login import current_user, login_required
from bson.objectid import ObjectId

# New route: Page to select a job to delete
@app.route("/select_job_to_delete")
@login_required
def select_job_to_delete():
    if current_user.role != "teacher":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("teacher_dashboard"))

    # Fetch teacher's posted jobs (adjust query if jobs are not teacher-specific)
    jobs = list(mongo.db.jobs.find().sort("created_at", -1))  # Example: all jobs; filter by teacher if needed
    return render_template("select_job_to_delete.html", jobs=jobs)

# Existing/Updated delete route (handles actual deletion)


@app.route("/teacher/job/<job_id>/applications")
@login_required
def job_applications(job_id):
    if current_user.role != "teacher":
        return redirect(url_for("student_dashboard"))

    job = mongo.db.jobs.find_one({"_id": ObjectId(job_id), "created_by": ObjectId(current_user.id)})
    if not job:
        flash("Job not found or access denied.", "danger")
        return redirect(url_for("teacher_dashboard"))

    pipeline = [
        {"$match": {"job_id": ObjectId(job_id)}},
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "_id", "as": "user"}},
        {"$unwind": "$user"},
        {"$sort": {"applied_at": -1}},
    ]
    applications = list(mongo.db.applications.aggregate(pipeline))

    return render_template("job_applications.html", job=job, applications=applications)

@app.route("/job/new", methods=["GET", "POST"])
@login_required
def new_job():
    """Page for teachers to add a new job"""
    if current_user.role != "teacher":
        return redirect(url_for("index"))
    form = JobForm()
    if form.validate_on_submit():
        pof_name = None
        if form.pof.data and form.pof.data.filename:
            pof_name = secure_filename(form.pof.data.filename)
            form.pof.data.save(os.path.join(app.config["UPLOAD_FOLDER"], pof_name))
        mongo.db.jobs.insert_one({
            "title": form.title.data,
            "description": form.description.data,
            "vacancies": form.vacancies.data,
            "pof_filename": pof_name,
            "created_by": ObjectId(current_user.id),
            "status": "open",
            "created_at": datetime.utcnow(),
        })
        flash("Job created", "success")
        return redirect(url_for("teacher_dashboard"))
    return render_template("job_form.html", form=form)


@app.route("/job/edit/<job_id>", methods=["GET", "POST"])
@login_required
def edit_job(job_id):
    """Page to edit an existing job"""
    if current_user.role != "teacher":
        return redirect(url_for("index"))

    job = mongo.db.jobs.find_one({"_id": ObjectId(job_id)})
    if not job:
        flash("Job not found.", "danger")
        return redirect(url_for("teacher_dashboard"))

    form = JobForm()
    if request.method == "GET":
        form.title.data = job.get("title", "")
        form.description.data = job.get("description", "")
        form.vacancies.data = job.get("vacancies", 6)

    if form.validate_on_submit():
        if form.pof.data and form.pof.data.filename:
            pof_name = secure_filename(form.pof.data.filename)
            form.pof.data.save(os.path.join(app.config["UPLOAD_FOLDER"], pof_name))
        else:
            pof_name = job.get("pof_filename")

        mongo.db.jobs.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {
                "title": form.title.data,
                "description": form.description.data,
                "vacancies": form.vacancies.data,
                "pof_filename": pof_name,
            }}
        )
        flash("Job updated", "success")
        return redirect(url_for("teacher_dashboard"))

    return render_template("job_form.html", form=form)


@app.route("/job/delete/<job_id>", methods=["POST"])
@login_required
def delete_job(job_id):
    """
    Deletes job from database; only accessible to teachers.
    Redirects to delete jobs listing page.
    """
    if current_user.role != "teacher":
        abort(403)   # Forbidden if not teacher

    result = mongo.db.jobs.delete_one({"_id": ObjectId(job_id)})
    if result.deleted_count:
        flash("Job deleted.", "info")
    else:
        flash("Job not found.", "warning")

    return redirect(url_for("select_job_to_delete"))


@app.route("/jobs/manage")
@app.route("/jobs/edit")
@login_required
def edit_jobs_list():
    """Page showing all jobs to be edited by teachers"""
    if current_user.role != "teacher":
        return redirect(url_for("student_dashboard"))

    jobs = list(mongo.db.jobs.find().sort("created_at", -1))
    return render_template("edit_jobs_list.html", jobs=jobs)


# --- Application Status Updates by Teacher ---

@app.route("/teacher/application/update_status/<app_id>", methods=["POST"])
@login_required
def update_application_status(app_id):
    if current_user.role != "teacher":
        return redirect(url_for("student_dashboard"))

    status = request.form.get("status")
    feedback = request.form.get("feedback")
    feedback = feedback.strip() if feedback else ""

    if status not in {"approved", "rejected", "corrections_needed"}:
        flash("Invalid status.", "danger")
        return redirect(url_for("teacher_dashboard"))

    mongo.db.applications.update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {"status": status, "teacher_feedback": feedback}}
    )
    flash("Application updated.", "success")
    return redirect(url_for("teacher_dashboard"))


@app.route('/teacher/application/clear/<app_id>', methods=['POST'])
@login_required
def clear_application(app_id):
    if current_user.role != 'teacher':
        return redirect(url_for('student_dashboard'))

    app_doc = mongo.db.applications.find_one({"_id": ObjectId(app_id)})
    if not app_doc:
        flash('Application not found.', 'warning')
        return redirect(url_for('teacher_dashboard'))
    
    # Increment vacancy back only if the job is still existing
    job_id = app_doc['job_id']
    mongo.db.applications.delete_one({"_id": ObjectId(app_id)})

    # Update job's vacancy count
    mongo.db.jobs.update_one(
        {"_id": job_id},
        {"$inc": {"vacancies": 1}}
    )

    flash('Application cleared and vacancy updated.', 'success')
    return redirect(url_for('teacher_dashboard'))



# --- Export Applications Data ---

@app.route("/teacher/export")
@login_required
def export_dashboard_data():
    """Export applications and related student/job info as Excel file"""
    if current_user.role != "teacher":
        return redirect(url_for("student_dashboard"))

    cursor = mongo.db.applications.aggregate([
        {"$lookup": {
            "from": "users",
            "localField": "user_id",
            "foreignField": "_id",
            "as": "user"
        }},
        {"$unwind": "$user"},
        {"$lookup": {
            "from": "jobs",
            "localField": "job_id",
            "foreignField": "_id",
            "as": "job"
        }},
        {"$unwind": "$job"}
    ])

    records = []
    for doc in cursor:
        records.append({
            "Student ID": doc["user"].get("student_id", ""),
            "Student Name": doc["user"]["name"],
            "Student Email": doc["user"]["email"],
            "Job Title": doc["job"]["title"],
            "Application Status": doc.get("status", ""),
            "Teacher Feedback": doc.get("teacher_feedback", ""),
            "Applied At": doc.get("applied_at", "").strftime("%Y-%m-%d %H:%M") if doc.get("applied_at") else "",
        })

    # Use pandas to create Excel file in-memory
    df = pd.DataFrame(records)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Applications")
    output.seek(0)

    return send_file(
        output,
        download_name="applications.xlsx",
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ---------- File Serving Routes ----------

@app.route("/uploads/<path:filename>")
@login_required
def view_resume(filename):
    """
    Serve uploaded PDF files inline in the browser (résumés).
    """
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        as_attachment=False,
        mimetype="application/pdf"
    )


@app.route("/resumes/download/<path:filename>")
@login_required
def download_resume(filename):
    """
    Force download of résumé PDF files.
    """
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename,
        as_attachment=True
    )


# ---------- Profile Editing with OTP Verification ----------

@app.route("/student/edit_profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    """
    Student profile editing page which supports optional password change
    verified with OTP sent to email.
    """
    if current_user.role != "student":
        return redirect(url_for("teacher_dashboard"))
    student = mongo.db.users.find_one({"_id": ObjectId(current_user.id)})
    if not student:
        flash("User not found", "danger")
        return redirect(url_for("student_dashboard"))
    

    form = EditProfileForm()
    # First phase: normal profile update or start OTP password change
    if 'awaiting_otp' not in session:
        if form.validate_on_submit():
            if not form.password:
                # Update profile fields only, no password change
                mongo.db.users.update_one(
                    {"_id": ObjectId(current_user.id)},
                    {"$set": {
                        "name": form.name.data,
                        "email": form.email.data.lower(),
                        "phone": form.phone.data,
                    }}
                )
                flash("Profile updated!", "success")
                return redirect(url_for("student_dashboard"))
            else:
                # Password change requested: generate OTP and send email
                otp = generate_otp()
                session['awaiting_otp'] = True
                session['pending_profile'] = {
                    "name": form.name.data,
                    "email": form.email.data.lower(),
                    "phone": form.phone.data,
                    "password": form.password.data,
                }
                session['otp_code'] = otp
                send_otp_email(form.email.data.lower(), otp)
                flash("OTP sent to your email for password change.", "info")
                return render_template("otp_verify.html")

        if request.method == "GET":
            # Pre-fill form on GET
            form.name.data = student.get("name", "")
            form.email.data = student.get("email", "")
            form.phone.data = student.get("phone", "")
        return render_template("edit_profile.html", form=form)

    # Second phase: OTP verification form submission
    if request.method == "POST" and 'otp' in request.form:
        user_input_otp = request.form.get("otp")
        pending = session.get('pending_profile')
        if pending and user_input_otp == session.get('otp_code'):
            update_fields = dict(pending)
            update_fields["pw_hash"] = hash_pw(update_fields.pop("password"))
            mongo.db.users.update_one(
                {"_id": ObjectId(current_user.id)},
                {"$set": update_fields}
            )
            flash("Profile and password updated!", "success")
            session.pop('awaiting_otp', None)
            session.pop('pending_profile', None)
            session.pop('otp_code', None)
            return redirect(url_for("student_dashboard"))
        else:
            flash("Incorrect OTP. Please try again.", "danger")
        return render_template("otp_verify.html")

    # Fallback: render OTP verification form
    return render_template("otp_verify.html")


# ---------- Teacher's Applied and Registered Students ----------

# Applied students filtered on teacher dashboard
@app.route("/teacher/applied_students")
@login_required
def applied_students():
    if current_user.role != "teacher":
        return redirect(url_for("student_dashboard"))

    name_filter = request.args.get("name", "").strip()
    status_filter = request.args.get("status", "").strip()

    pipeline = [
        {"$lookup": {
            "from": "users",
            "localField": "user_id",
            "foreignField": "_id",
            "as": "user",
        }},
        {"$unwind": "$user"},
        {"$lookup": {
            "from": "jobs",
            "localField": "job_id",
            "foreignField": "_id",
            "as": "job",
        }},
        {"$unwind": "$job"},
    ]

    match_filters = {}
    if name_filter:
        match_filters["user.name"] = {"$regex": name_filter, "$options": "i"}
    if status_filter:
        match_filters["status"] = status_filter

    if match_filters:
        pipeline.insert(0, {"$match": match_filters})

    applications = list(mongo.db.applications.aggregate(pipeline))

    statuses = ["pending_resume", "submitted", "approved", "rejected", "rejected_auto", "corrections_needed"]

    return render_template("applied_students.html",
                           applications=applications,
                           name_filter=name_filter,
                           status_filter=status_filter,
                           statuses=statuses)


# Registered students with sorting options
@app.route("/teacher/registered_students")
@login_required
def registered_students():
    if current_user.role != "teacher":
        return redirect(url_for("student_dashboard"))

    # Get filters from query params
    name_filter = request.args.get("name", "").strip().lower()
    student_id_filter = request.args.get("student_id", "").strip().lower()
    phone_filter = request.args.get("phone", "").strip()
    email_filter = request.args.get("email", "").strip().lower()

    # Sorting
    sort_field = request.args.get("sort", "name")
    direction = request.args.get("direction", "asc")
    allowed_sort_fields = {"name", "student_id", "phone", "email"}
    sort_by = sort_field if sort_field in allowed_sort_fields else "name"
    sort_dir = 1 if direction == "asc" else -1

    # Build MongoDB query with filters
    query = {"role": "student"}
    if name_filter:
        query["name"] = {"$regex": name_filter, "$options": "i"}
    if student_id_filter:
        query["student_id"] = {"$regex": student_id_filter, "$options": "i"}
    if phone_filter:
        query["phone"] = {"$regex": phone_filter}
    if email_filter:
        query["email"] = {"$regex": email_filter, "$options": "i"}

    # Query and sort
    students = list(mongo.db.users.find(query).sort(sort_by, sort_dir))

    # Pass everything to the template
    return render_template("registered_students.html",
                           students=students,
                           name_filter=name_filter,
                           student_id_filter=student_id_filter,
                           phone_filter=phone_filter,
                           email_filter=email_filter,
                           sort_field=sort_by,
                           direction=direction)

# New route for clear applications page
@app.route("/teacher/clear_applications")
@login_required
def clear_applications():
    if current_user.role != "teacher":
        return redirect(url_for("student_dashboard"))

    name_filter = request.args.get("name", "").strip()
    status_filter = request.args.get("status", "").strip()
    resume_filter = request.args.get("resume", "").strip()

    pipeline = [
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "_id", "as": "user"}},
        {"$unwind": "$user"},
        {"$lookup": {"from": "jobs", "localField": "job_id", "foreignField": "_id", "as": "job"}},
        {"$unwind": "$job"},
        {"$sort": {"applied_at": -1}}
    ]

    match_filters = {}
    if name_filter:
        match_filters["user.name"] = {"$regex": name_filter, "$options": "i"}
    if status_filter:
        match_filters["status"] = status_filter
    if resume_filter == 'uploaded':
        match_filters["resume_filename"] = {"$exists": True, "$ne": None}
    elif resume_filter == 'not_uploaded':
        match_filters["resume_filename"] = {"$exists": False}

    if match_filters:
        pipeline.insert(0, {"$match": match_filters})

    applications = list(mongo.db.applications.aggregate(pipeline))
    all_statuses = ["pending_resume", "submitted", "approved", "rejected", "rejected_auto", "corrections_needed"]
    resume_options = [
        {"value": "", "label": "All"},
        {"value": "uploaded", "label": "Resume Uploaded"},
        {"value": "not_uploaded", "label": "Resume Not Uploaded"},
    ]

    return render_template(
        "clear_applications.html",
        applications=applications,
        name_filter=name_filter,
        status_filter=status_filter,
        resume_filter=resume_filter,
        statuses=all_statuses,
        resume_options=resume_options
    )

@app.route('/teacher/clear_applications_bulk', methods=['POST'])
@login_required
def clear_applications_bulk():
    if current_user.role != 'teacher':
        return redirect(url_for('student_dashboard'))

    app_ids = request.form.getlist('app_ids')
    if not app_ids:
        flash('No applications selected.', 'warning')
        return redirect(url_for('clear_applications'))

    object_ids = [ObjectId(app_id) for app_id in app_ids]

    # Find all applications to clear to gather job_ids
    apps_to_clear = list(mongo.db.applications.find({"_id": {"$in": object_ids}}))
    job_id_to_count = {}
    for app_doc in apps_to_clear:
        job_id = app_doc['job_id']
        job_id_to_count[job_id] = job_id_to_count.get(job_id, 0) + 1

    # Delete the applications
    result = mongo.db.applications.delete_many({"_id": {"$in": object_ids}})

    # Increment vacancies for each affected job
    for job_id, inc_count in job_id_to_count.items():
        mongo.db.jobs.update_one(
            {"_id": job_id},
            {"$inc": {"vacancies": inc_count}}
        )

    flash(f'{result.deleted_count} application(s) cleared and vacancies updated.', 'success')
    return redirect(url_for('clear_applications'))
 
@app.route("/teacher/assess", methods=["GET", "POST"])
@login_required
def assess_students():
    if current_user.role != "teacher":
        return redirect(url_for("student_dashboard"))

    # Handle POST request to update application status and feedback
    if request.method == "POST":
        app_id = request.form.get("app_id")
        new_status = request.form.get("status")
        feedback = request.form.get("feedback", "").strip()

        if app_id and new_status in {"approved", "rejected", "corrections_needed"}:
            mongo.db.applications.update_one(
                {"_id": ObjectId(app_id)},
                {"$set": {"status": new_status, "teacher_feedback": feedback}}
            )
            flash("Application updated successfully.", "success")
        else:
            flash("Invalid update data.", "danger")
        return redirect(url_for("assess_students"))

    # GET request: handle filtering parameters
    name_filter = request.args.get("name", "").strip()
    status_filter = request.args.get("status", "").strip()
    resume_filter = request.args.get("resume", "").strip()

    pipeline = [
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "_id", "as": "user"}},
        {"$unwind": "$user"},
        {"$lookup": {"from": "jobs", "localField": "job_id", "foreignField": "_id", "as": "job"}},
        {"$unwind": "$job"},
        {"$sort": {"applied_at": -1}},
    ]

    match_filters = {}
    if name_filter:
        match_filters["user.name"] = {"$regex": name_filter, "$options": "i"}
    if status_filter:
        match_filters["status"] = status_filter
    if resume_filter == "uploaded":
        match_filters["resume_filename"] = {"$exists": True, "$ne": None}
    elif resume_filter == "not_uploaded":
        match_filters["resume_filename"] = {"$exists": False}

    if match_filters:
        pipeline.insert(0, {"$match": match_filters})

    applications = list(mongo.db.applications.aggregate(pipeline))

    now = datetime.utcnow()

    # Compute upload duration in hours and add field to each app
    for app in applications:
        applied_at = app.get("applied_at")
        resume_uploaded_at = app.get("resume_uploaded_at")

        if applied_at and resume_uploaded_at:
            duration = resume_uploaded_at - applied_at
            hours = duration.total_seconds() / 3600
            app["upload_duration_hours"] = round(hours, 1)
        elif applied_at and app.get("resume_filename"):
            # Estimate duration as current time - applied_at if uploaded_at missing
            duration = now - applied_at
            hours = duration.total_seconds() / 3600
            app["upload_duration_hours"] = round(hours, 1)
        else:
            app["upload_duration_hours"] = None

    all_statuses = [
        "pending_resume", "submitted", "approved",
        "rejected", "rejected_auto", "corrections_needed"
    ]
    resume_options = [
        {"value": "", "label": "All"},
        {"value": "uploaded", "label": "Resume Uploaded"},
        {"value": "not_uploaded", "label": "Resume Not Uploaded"},
    ]

    return render_template(
        "assess_students.html",
        applications=applications,
        name_filter=name_filter,
        status_filter=status_filter,
        resume_filter=resume_filter,
        statuses=all_statuses,
        resume_options=resume_options,
    )

@app.route("/teacher/edit_profile", methods=["GET", "POST"])
@login_required
def edit_teacher_profile():
    if current_user.role != "teacher":
        return redirect(url_for("student_dashboard"))  # Only allow teachers!

    teacher = mongo.db.users.find_one({"_id": ObjectId(current_user.id)})
    if not teacher:
        flash("User not found", "danger")
        return redirect(url_for("teacher_dashboard"))

    form = EditProfileForm()
    if form.validate_on_submit():
        update_dict = {
            "name": form.name.data,
            "email": form.email.data.lower(),
            "phone": form.phone.data,
        }
        # ✅ Fixed this line: proper check for filled password field
        if form.password.data and form.password.data.strip():
            update_dict["pw_hash"] = hash_pw(form.password.data)

        mongo.db.users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": update_dict}
        )
        flash("Profile updated!", "success")
        return redirect(url_for("teacher_dashboard"))

    if request.method == "GET":
        form.name.data = teacher.get("name", "")
        form.email.data = teacher.get("email", "")
        form.phone.data = teacher.get("phone", "")

    return render_template("edit_teacher_profile.html", form=form)

import io
import pandas as pd
from flask import send_file
from bson.objectid import ObjectId

from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user, login_required

def teacher_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "teacher":
            flash("You must be a teacher to access this page.", "warning")
            return redirect(url_for("dashboard"))  # or any other appropriate page
        return f(*args, **kwargs)
    return decorated_function

@app.route("/teacher/export_assessed")
@teacher_required
def export_assessed_students():
    # Query assessed applications (approved, rejected or corrections needed)
    assessed_statuses = ["approved", "rejected", "corrections_needed"]
    pipeline = [
        {"$match": {"status": {"$in": assessed_statuses}}},
        {
            "$lookup": {
                "from": "users",
                "localField": "user_id",
                "foreignField": "_id",
                "as": "user"
            }
        },
        {"$unwind": "$user"},
        {
            "$lookup": {
                "from": "jobs",
                "localField": "job_id",
                "foreignField": "_id",
                "as": "job"
            }
        },
        {"$unwind": "$job"},
        {"$sort": {"applied_at": -1}},
    ]
    results = list(mongo.db.applications.aggregate(pipeline))

    # Prepare data for Excel
    data = []
    for app in results:
        row = {
            "Student Name": app["user"].get("name", ""),
            "Student Email": app["user"].get("email", ""),
            "Job Title": app["job"].get("title", ""),
            "Status": app.get("status", "").replace("_", " ").title(),
            "Applied At": app.get("applied_at").strftime("%Y-%m-%d %H:%M") if app.get("applied_at") else "",
            "Teacher Feedback": app.get("teacher_feedback") or "",
        }
        data.append(row)

    # Create DataFrame
    df = pd.DataFrame(data)

    # Output Excel to a bytes buffer
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Assessed Students")

    output.seek(0)

    # Send file
    filename = f"Assessed_Students_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(
        output,
        download_name=filename,  
        as_attachment=True,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )



# ---------- Support and Contact Pages ----------

@app.route("/support")
def support():
    return render_template("support.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route("/about")
def about():
    return render_template("about.html")

# ---------- Run the app ----------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))


