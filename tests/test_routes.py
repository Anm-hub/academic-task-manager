import pytest
from app import app, db
from models import User, Course, Task, ProgressLog
from werkzeug.security import generate_password_hash
from datetime import date, datetime, timedelta
from unittest.mock import patch


# ── Fixture ────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SECRET_KEY'] = 'test-secret-key'
    # Disable actual email sending during tests
    app.config['MAIL_SUPPRESS_SEND'] = True

    with app.test_client() as client:
        with app.app_context():
            db.create_all()

            # Normal student user — uses set_password() since model now has it
            user = User(username="testuser", email="testuser@gmail.com", is_admin=False)
            user.set_password("password123")
            db.session.add(user)

            # Admin user
            admin = User(username="admintest", email="admintest@test.com", is_admin=True)
            admin.set_password("adminpass")
            db.session.add(admin)

            db.session.commit()

        yield client

        with app.app_context():
            db.session.remove()
            db.drop_all()


# ── Helpers ────────────────────────────────────────────────────────────────

def login_full(client, username, password):
    """
    Full login flow: POST credentials → get user_id from redirect →
    inject OTP into DB → POST OTP → fully authenticated.
    We patch send_otp_email so no real email is sent.
    """
    with patch('app.send_otp_email'):
        resp = client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False
        )

    # The login route redirects to /verify-otp/<user_id>
    # Extract user_id from the Location header
    location = resp.headers.get("Location", "")
    assert "/verify-otp/" in location, f"Expected OTP redirect, got: {location}"
    user_id = int(location.rstrip("/").split("/")[-1])

    # Inject a known OTP directly into the DB, bypassing email
    with app.app_context():
        user = User.query.get(user_id)
        user.otp_code   = "123456"
        user.otp_expiry = datetime.utcnow() + timedelta(minutes=5)
        db.session.commit()

    # Submit the OTP
    resp = client.post(
        f"/verify-otp/{user_id}",
        data={"otp": "123456"},
        follow_redirects=True
    )
    return resp


def logout(client):
    return client.get("/logout", follow_redirects=True)


# ── Auth Tests ─────────────────────────────────────────────────────────────

def test_login_page_loads(client):
    """Login page returns 200"""
    response = client.get("/login")
    assert response.status_code == 200


def test_register_page_loads(client):
    """Register page returns 200"""
    response = client.get("/register")
    assert response.status_code == 200


def test_login_correct_credentials_redirects_to_otp(client):
    """Valid credentials redirects to OTP verification page"""
    with patch('app.send_otp_email'):
        response = client.post(
            "/login",
            data={"username": "testuser", "password": "password123"},
            follow_redirects=False
        )
    assert response.status_code == 302
    assert "/verify-otp/" in response.headers.get("Location", "")


def test_login_wrong_password_stays_on_login(client):
    """Wrong password does not redirect to OTP"""
    with patch('app.send_otp_email'):
        response = client.post(
            "/login",
            data={"username": "testuser", "password": "wrongpassword"},
            follow_redirects=True
        )
    assert b"verify-otp" not in response.data
    assert b"HELLO" not in response.data


def test_login_wrong_username(client):
    """Non-existent username stays on login"""
    with patch('app.send_otp_email'):
        response = client.post(
            "/login",
            data={"username": "nobody", "password": "password123"},
            follow_redirects=True
        )
    assert b"verify-otp" not in response.data


def test_otp_correct_logs_in_student(client):
    """Correct OTP logs in student and redirects to dashboard"""
    response = login_full(client, "testuser", "password123")
    assert response.status_code == 200
    assert b"HELLO" in response.data or b"Dashboard" in response.data


def test_otp_wrong_shows_error(client):
    """Wrong OTP shows error message"""
    with patch('app.send_otp_email'):
        resp = client.post(
            "/login",
            data={"username": "testuser", "password": "password123"},
            follow_redirects=False
        )
    location = resp.headers.get("Location", "")
    user_id  = int(location.rstrip("/").split("/")[-1])

    with app.app_context():
        user = User.query.get(user_id)
        user.otp_code   = "123456"
        user.otp_expiry = datetime.utcnow() + timedelta(minutes=5)
        db.session.commit()

    response = client.post(
        f"/verify-otp/{user_id}",
        data={"otp": "000000"},
        follow_redirects=True
    )
    assert b"Invalid" in response.data or b"expired" in response.data or b"invalid" in response.data


def test_otp_expired_shows_error(client):
    """Expired OTP shows error message"""
    with patch('app.send_otp_email'):
        resp = client.post(
            "/login",
            data={"username": "testuser", "password": "password123"},
            follow_redirects=False
        )
    location = resp.headers.get("Location", "")
    user_id  = int(location.rstrip("/").split("/")[-1])

    with app.app_context():
        user = User.query.get(user_id)
        user.otp_code   = "123456"
        user.otp_expiry = datetime.utcnow() - timedelta(minutes=10)  # already expired
        db.session.commit()

    response = client.post(
        f"/verify-otp/{user_id}",
        data={"otp": "123456"},
        follow_redirects=True
    )
    assert b"Invalid" in response.data or b"expired" in response.data or b"invalid" in response.data


def test_admin_login_redirects_to_admin_dashboard(client):
    """Admin OTP login redirects to admin dashboard"""
    response = login_full(client, "admintest", "adminpass")
    assert response.status_code == 200
    assert b"Admin Dashboard" in response.data


def test_logout(client):
    """Logout redirects to login page"""
    login_full(client, "testuser", "password123")
    response = logout(client)
    assert response.status_code == 200
    assert b"login" in response.data.lower() or b"sign in" in response.data.lower()


def test_register_new_user(client):
    """New user registration works and redirects to login"""
    response = client.post(
        "/register",
        data={"username": "brandnew", "email": "brandnew@test.com", "password": "pass123"},
        follow_redirects=True
    )
    assert response.status_code == 200
    with app.app_context():
        user = User.query.filter_by(username="brandnew").first()
        assert user is not None


# ── Access Control Tests ───────────────────────────────────────────────────

def test_dashboard_requires_login(client):
    """Dashboard redirects unauthenticated users to login"""
    response = client.get("/dashboard", follow_redirects=True)
    assert b"login" in response.data.lower()


def test_courses_requires_login(client):
    response = client.get("/courses", follow_redirects=True)
    assert b"login" in response.data.lower()


def test_schedule_requires_login(client):
    response = client.get("/schedule", follow_redirects=True)
    assert b"login" in response.data.lower()


def test_settings_requires_login(client):
    response = client.get("/settings", follow_redirects=True)
    assert b"login" in response.data.lower()


def test_admin_dashboard_blocks_student(client):
    """Student cannot access admin dashboard"""
    login_full(client, "testuser", "password123")
    response = client.get("/admin", follow_redirects=True)
    assert b"Admin Dashboard" not in response.data


def test_admin_dashboard_accessible_to_admin(client):
    """Admin can access admin dashboard"""
    login_full(client, "admintest", "adminpass")
    response = client.get("/admin")
    assert response.status_code == 200
    assert b"Admin Dashboard" in response.data


def test_admin_redirected_from_student_dashboard(client):
    """Admin hitting /dashboard gets redirected to admin dashboard"""
    login_full(client, "admintest", "adminpass")
    response = client.get("/dashboard", follow_redirects=True)
    assert b"Admin Dashboard" in response.data


# ── Student Feature Tests ──────────────────────────────────────────────────

def test_dashboard_loads(client):
    login_full(client, "testuser", "password123")
    response = client.get("/dashboard")
    assert response.status_code == 200


def test_courses_page_loads(client):
    login_full(client, "testuser", "password123")
    response = client.get("/courses")
    assert response.status_code == 200


def test_schedule_page_loads(client):
    login_full(client, "testuser", "password123")
    response = client.get("/schedule")
    assert response.status_code == 200


def test_settings_page_loads(client):
    login_full(client, "testuser", "password123")
    response = client.get("/settings")
    assert response.status_code == 200


def test_add_course(client):
    """Student can add a course"""
    login_full(client, "testuser", "password123")
    response = client.post(
        "/add_course",
        data={"course_name": "Intro to Python", "course_code": "CS101"},
        follow_redirects=True
    )
    assert response.status_code == 200
    with app.app_context():
        user = User.query.filter_by(username="testuser").first()
        course = Course.query.filter_by(user_id=user.id, course_code="CS101").first()
        assert course is not None


def test_add_task(client):
    """Student can add a task after creating a course"""
    login_full(client, "testuser", "password123")
    client.post("/add_course", data={"course_name": "Test Course", "course_code": "TC101"})

    with app.app_context():
        user   = User.query.filter_by(username="testuser").first()
        course = Course.query.filter_by(user_id=user.id).first()
        assert course is not None

        deadline = (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")
        response = client.post(
            "/add_task",
            data={
                "title":              "Test Task",
                "description":        "A test task",
                "deadline":           deadline,
                "total_effort_hours": "5",
                "course_id":          str(course.id)
            },
            follow_redirects=True
        )
        assert response.status_code == 200
        task = Task.query.filter_by(user_id=user.id, title="Test Task").first()
        assert task is not None


def test_log_progress(client):
    """Student can log work on a task"""
    login_full(client, "testuser", "password123")
    client.post("/add_course", data={"course_name": "Log Course", "course_code": "LC101"})

    with app.app_context():
        user   = User.query.filter_by(username="testuser").first()
        course = Course.query.filter_by(user_id=user.id).first()
        deadline = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")

        client.post("/add_task", data={
            "title": "Log Task", "description": "",
            "deadline": deadline, "total_effort_hours": "10",
            "course_id": str(course.id)
        })

        task = Task.query.filter_by(user_id=user.id, title="Log Task").first()
        response = client.post(
            f"/log_progress/{task.id}",
            data={"hours_logged": "2"},
            follow_redirects=True
        )
        assert response.status_code == 200

        task = Task.query.get(task.id)
        assert task.remaining_effort_hours == 8.0


def test_delete_task(client):
    """Student can delete their own task"""
    login_full(client, "testuser", "password123")
    client.post("/add_course", data={"course_name": "Del Course", "course_code": "DC101"})

    with app.app_context():
        user   = User.query.filter_by(username="testuser").first()
        course = Course.query.filter_by(user_id=user.id).first()
        deadline = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")

        client.post("/add_task", data={
            "title": "Delete Me", "description": "",
            "deadline": deadline, "total_effort_hours": "3",
            "course_id": str(course.id)
        })

        task = Task.query.filter_by(title="Delete Me").first()
        task_id = task.id

        response = client.get(f"/delete_task/{task_id}", follow_redirects=True)
        assert response.status_code == 200
        assert Task.query.get(task_id) is None


# ── Admin Feature Tests ────────────────────────────────────────────────────

def test_admin_users_page(client):
    login_full(client, "admintest", "adminpass")
    response = client.get("/admin/users")
    assert response.status_code == 200


def test_admin_courses_page(client):
    login_full(client, "admintest", "adminpass")
    response = client.get("/admin/courses")
    assert response.status_code == 200


def test_admin_delete_user(client):
    """Admin can delete a student and all their data"""
    login_full(client, "admintest", "adminpass")

    with app.app_context():
        user = User.query.filter_by(username="testuser").first()
        user_id = user.id
        response = client.get(f"/admin/delete_user/{user_id}", follow_redirects=True)
        assert response.status_code == 200
        assert User.query.get(user_id) is None