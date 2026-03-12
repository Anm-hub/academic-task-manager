from flask import Flask, render_template, redirect, url_for, request
from config import Config
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Course, Task, ProgressLog
from datetime import datetime, date




app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route("/")
def home():
    return "Home Page"


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

    # GET request: render the HTML template
    return render_template("register.html")



@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("dashboard"))

    # GET request: render the HTML template
    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
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

    # Course task counts
    course_data = []
    for c in courses:
        count = len([t for t in tasks if t.course_id == c.id])
        course_data.append((c, count))

    # Adaptive upcoming tasks
    sorted_tasks = sorted(tasks, key=lambda x: x.deadline)
    upcoming_tasks = []

    for t in sorted_tasks:
        course = Course.query.get(t.course_id)

        days_left = (t.deadline - today).days

        if days_left > 0:
            required_daily = t.remaining_effort_hours / days_left
        else:
            required_daily = t.remaining_effort_hours  # overdue case

        overload = required_daily > 4  # threshold you can adjust

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

    # Security check: make sure user owns this course
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

    # Security check
    if task.user_id != current_user.id:
        return "Unauthorized", 403

    db.session.delete(task)
    db.session.commit()

    return redirect(url_for("dashboard"))

@app.route("/edit_task/<int:task_id>", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    task = Task.query.get_or_404(task_id)

    # Security check
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

    # Security check
    if task.user_id != current_user.id:
        return "Unauthorized", 403

    hours_logged = float(request.form.get("hours_logged"))

    if hours_logged <= 0:
        return redirect(url_for("course_detail", course_id=task.course_id))

    # Cap remaining hours at 0
    new_remaining = task.remaining_effort_hours - hours_logged
    task.remaining_effort_hours = max(new_remaining, 0)

    # Create progress log entry
    log_entry = ProgressLog(
        effort_completed_hours=hours_logged,
        task_id=task.id
    )

    db.session.add(log_entry)
    db.session.commit()

    return redirect(url_for("course_detail", course_id=task.course_id))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
