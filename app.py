from flask_mail import Mail, Message
from flask import Flask, render_template, redirect, url_for, request, session, flash
from config import Config
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Course, Task, ProgressLog
from datetime import datetime, date
from functools import wraps
import random
from datetime import datetime, timedelta

app = Flask(__name__)
app.config.from_object(Config)

mail = Mail(app)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
def generate_otp():
    return str(random.randint(100000, 999999))

def send_otp_email(user_email, otp):
    msg = Message(
        subject="Your OTP Code",
        sender=app.config['MAIL_USERNAME'],
        recipients=[user_email]
    )
    
    msg.body = f"Your OTP code is: {otp}\nIt will expire in 5 minutes."
    
    mail.send(msg)


# ── Admin required decorator ───────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


# ──────────────────────────────────────────────────────────────────────────
# STUDENT ROUTES
# ──────────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        hashed_password = generate_password_hash(password)
        user = User(username=username, email=email, password_hash=hashed_password)

        db.session.add(user)
        db.session.commit()

        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            otp = generate_otp()
            user.otp_code = otp
            user.otp_expiry = datetime.utcnow() + timedelta(minutes=5)
            db.session.commit()

            try:
                 send_otp_email(user.email, otp)
                 print(f"✅ OTP email sent to {user.email}")
            except Exception as e:
                 print(f"⚠️  Email failed ({e}) — OTP for {user.username}: {otp}")

            return redirect(url_for("verify_otp", user_id=user.id))

    return render_template("login.html")


@app.route("/verify-otp/<int:user_id>", methods=["GET", "POST"])
def verify_otp(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == "POST":
        entered_otp = request.form.get("otp")

        if user.otp_code == entered_otp and user.otp_expiry > datetime.utcnow():
            # ✅ OTP correct → NOW log user in
            login_user(user)

            # clear OTP after use (VERY important)
            user.otp_code = None
            user.otp_expiry = None
            db.session.commit()

            if user.is_admin:
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid or expired OTP", "danger")

    return render_template("verify_otp.html")

@app.route("/dashboard")
@login_required
def dashboard():
    # Prevent admin from accessing student dashboard
    if current_user.is_admin:
        return redirect(url_for("admin_dashboard"))

    courses = Course.query.filter_by(user_id=current_user.id).all()
    tasks = Task.query.filter_by(user_id=current_user.id).all()
    task_progress = []

    for t in tasks:
        if t.total_effort_hours > 0:
            progress = round(((t.total_effort_hours - t.remaining_effort_hours) / t.total_effort_hours) * 100)
        else:
            progress = 0

        task_progress.append({
            "title": t.title,
            "progress": progress,
            "course_id": t.course_id
        })

    today = datetime.today().date()

    course_data = []
    for c in courses:
        count = len([t for t in tasks if t.course_id == c.id])
        course_data.append((c, count))

    sorted_tasks = sorted(tasks, key=lambda x: x.deadline)
    upcoming_tasks = []

    for t in sorted_tasks:
        course = Course.query.get(t.course_id)
        days_left = (t.deadline - today).days

        if days_left > 0:
            required_daily = t.remaining_effort_hours / days_left
        else:
            required_daily = t.remaining_effort_hours

        overload = required_daily > 4

        upcoming_tasks.append({
            "title": t.title,
            "deadline": t.deadline,
            "course_code": course.course_code,
            "remaining_hours": t.remaining_effort_hours,
            "days_left": days_left,
            "required_daily": round(required_daily, 2),
            "overload": overload
        })

    return render_template(
        "dashboard.html",
        courses=course_data,
        upcoming_tasks=upcoming_tasks,
        task_progress=task_progress
    )


@app.route("/schedule")
@login_required
def schedule():
    tasks = Task.query.filter_by(user_id=current_user.id).all()
    courses = Course.query.filter_by(user_id=current_user.id).all()
    return render_template("schedule.html", tasks=tasks, courses=courses, today=date.today())


@app.route("/courses")
@login_required
def courses():
    courses = Course.query.filter_by(user_id=current_user.id).all()
    return render_template("courses.html", courses=courses)


@app.route("/course/<int:course_id>")
@login_required
def course_detail(course_id):
    course = Course.query.get_or_404(course_id)

    if course.user_id != current_user.id:
        return "Unauthorized", 403

    tasks = Task.query.filter_by(course_id=course.id).all()

    return render_template(
        "course_detail.html",
        course=course,
        tasks=tasks,
        today=date.today()
    )


@app.route("/delete_task/<int:task_id>")
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)

    if task.user_id != current_user.id:
        return "Unauthorized", 403

    db.session.delete(task)
    db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/edit_task/<int:task_id>", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    task = Task.query.get_or_404(task_id)

    if task.user_id != current_user.id:
        return "Unauthorized", 403

    if request.method == "POST":
        task.title = request.form.get("title")
        task.description = request.form.get("description")
        deadline_str = request.form.get("deadline")
        task.deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        task.total_effort_hours = float(request.form.get("total_effort_hours"))
        task.remaining_effort_hours = float(request.form.get("remaining_effort_hours"))
        db.session.commit()
        return redirect(url_for("dashboard"))

    return render_template("edit_task.html", task=task)


@app.route("/settings")
@login_required
def settings():
    return render_template("settings.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/add_course", methods=["GET", "POST"])
@login_required
def add_course():
    if request.method == "POST":
        course_name = request.form.get("course_name")
        course_code = request.form.get("course_code")

        new_course = Course(
            course_name=course_name,
            course_code=course_code,
            user_id=current_user.id
        )

        db.session.add(new_course)
        db.session.commit()
        return redirect(url_for("dashboard"))

    return render_template("add_course.html")


@app.route("/add_task", methods=["GET", "POST"])
@login_required
def add_task():
    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        deadline_str = request.form.get("deadline")
        deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        total_effort_hours = float(request.form.get("total_effort_hours"))
        course_id = int(request.form.get("course_id"))

        new_task = Task(
            title=title,
            description=description,
            deadline=deadline,
            total_effort_hours=total_effort_hours,
            remaining_effort_hours=total_effort_hours,
            user_id=current_user.id,
            course_id=course_id
        )

        db.session.add(new_task)
        db.session.commit()
        return redirect(url_for("dashboard"))

    courses = Course.query.filter_by(user_id=current_user.id).all()
    return render_template("add_task.html", courses=courses)


@app.route("/log_progress/<int:task_id>", methods=["POST"])
@login_required
def log_progress(task_id):
    task = Task.query.get_or_404(task_id)

    if task.user_id != current_user.id:
        return "Unauthorized", 403

    hours_logged = float(request.form.get("hours_logged"))

    if hours_logged <= 0:
        return redirect(url_for("course_detail", course_id=task.course_id))

    new_remaining = task.remaining_effort_hours - hours_logged
    task.remaining_effort_hours = max(new_remaining, 0)

    log_entry = ProgressLog(
        effort_completed_hours=hours_logged,
        task_id=task.id
    )

    db.session.add(log_entry)
    db.session.commit()
    return redirect(url_for("course_detail", course_id=task.course_id))


# ──────────────────────────────────────────────────────────────────────────
# ADMIN ROUTES
# ──────────────────────────────────────────────────────────────────────────

@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    all_users   = User.query.filter_by(is_admin=False).all()
    all_courses = Course.query.all()
    all_tasks   = Task.query.all()

    # System-wide stats
    total_users   = len(all_users)
    total_courses = len(all_courses)
    total_tasks   = len(all_tasks)

    today = date.today()

    overdue_tasks = [t for t in all_tasks if t.deadline < today and t.remaining_effort_hours > 0]
    completed_tasks = [t for t in all_tasks if t.remaining_effort_hours == 0]

    if total_tasks > 0:
        total_pct_all = sum(
            round(((t.total_effort_hours - t.remaining_effort_hours) / t.total_effort_hours) * 100)
            if t.total_effort_hours > 0 else 0
            for t in all_tasks
        )
        completion_rate = round(total_pct_all / total_tasks)
    else:
        completion_rate = 0

    # Per-user breakdown
    user_stats = []
    for u in all_users:
        u_courses = Course.query.filter_by(user_id=u.id).all()
        u_tasks   = Task.query.filter_by(user_id=u.id).all()
        u_done    = [t for t in u_tasks if t.remaining_effort_hours == 0]
        u_overdue = [t for t in u_tasks if t.deadline < today and t.remaining_effort_hours > 0]
        if u_tasks:
            total_pct = sum(
                round(((t.total_effort_hours - t.remaining_effort_hours) / t.total_effort_hours) * 100)
                if t.total_effort_hours > 0 else 0
                for t in u_tasks
            )
            u_rate = round(total_pct / len(u_tasks))
        else:
            u_rate = 0

        user_stats.append({
            "user":         u,
            "course_count": len(u_courses),
            "task_count":   len(u_tasks),
            "done_count":   len(u_done),
            "overdue_count":len(u_overdue),
            "completion":   u_rate
        })

    # Sort by most tasks
    user_stats.sort(key=lambda x: x["task_count"], reverse=True)

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        total_courses=total_courses,
        total_tasks=total_tasks,
        overdue_count=len(overdue_tasks),
        completion_rate=completion_rate,
        user_stats=user_stats,
        today=today
    )


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    all_users = User.query.filter_by(is_admin=False).all()
    today = date.today()

    user_stats = []
    for u in all_users:
        u_courses = Course.query.filter_by(user_id=u.id).all()
        u_tasks   = Task.query.filter_by(user_id=u.id).all()
        u_done    = [t for t in u_tasks if t.remaining_effort_hours == 0]
        u_overdue = [t for t in u_tasks if t.deadline < today and t.remaining_effort_hours > 0]
        if u_tasks:
            total_pct = sum(
                round(((t.total_effort_hours - t.remaining_effort_hours) / t.total_effort_hours) * 100)
                if t.total_effort_hours > 0 else 0
                for t in u_tasks
            )
            u_rate = round(total_pct / len(u_tasks))
        else:
            u_rate = 0

        user_stats.append({
            "user":         u,
            "course_count": len(u_courses),
            "task_count":   len(u_tasks),
            "done_count":   len(u_done),
            "overdue_count":len(u_overdue),
            "completion":   u_rate
        })

    return render_template("admin_users.html", user_stats=user_stats)


@app.route("/admin/courses")
@login_required
@admin_required
def admin_courses():
    all_courses = Course.query.all()
    course_data = []

    for c in all_courses:
        owner     = User.query.get(c.user_id)
        tasks     = Task.query.filter_by(course_id=c.id).all()
        done      = [t for t in tasks if t.remaining_effort_hours == 0]
        # Calculate real progress across all tasks in the course
        if tasks:
            total_pct = sum(
                round(((t.total_effort_hours - t.remaining_effort_hours) / t.total_effort_hours) * 100)
                if t.total_effort_hours > 0 else 0
                for t in tasks
            )
            rate = round(total_pct / len(tasks))
        else:
            rate = 0

        course_data.append({
            "course":       c,
            "owner":        owner,
            "task_count":   len(tasks),
            "done_count":   len(done),
            "completion":   rate
        })

    return render_template("admin_courses.html", course_data=course_data)


@app.route("/admin/delete_user/<int:user_id>")
@login_required
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)

    # Delete all progress logs, tasks, courses belonging to this user
    for task in Task.query.filter_by(user_id=user.id).all():
        ProgressLog.query.filter_by(task_id=task.id).delete()
    Task.query.filter_by(user_id=user.id).delete()
    Course.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()

    return redirect(url_for("admin_users"))

# ──────────────────────────────────────────────────────────────────────────
# APP STARTUP — create tables + auto-seed admin user
# ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

        # Create admin user if one doesn't exist yet
        if not User.query.filter_by(username="admin").first():
            admin = User(
                username="admin",
                email="anastaciamwangi12@gmail.com",
                password_hash=generate_password_hash("smartech2025"),
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin user created: admin / smartech2025")

    app.run(debug=True)