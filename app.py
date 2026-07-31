import os
from flask import Flask, render_template, request, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, UserMixin, login_required, current_user
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def calculate_business_days(start_date_str, end_date_str):
    start = datetime.strptime(start_date_str, "%Y-%m-%d")
    end = datetime.strptime(end_date_str, "%Y-%m-%d")
    business_days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            business_days += 1
        current += timedelta(days=1)
    return business_days


class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref="leave_requests")
    leave_type = db.Column(db.String(50), nullable=False)
    start_date = db.Column(db.String(20), nullable=False)
    end_date = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(300))
    status = db.Column(db.String(20), default="Pending")
    manager_comment = db.Column(db.String(300))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="Employee")
    leave_balance = db.Column(db.Integer, nullable=False, default=24)


def create_app(test_config=None):
    app = Flask(__name__)

    if test_config:
        app.config.update(test_config)
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
            "DATABASE_URL", "sqlite:///leave.db"
        )

    db.init_app(app)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-later")

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "login"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.route("/")
    def home():
        return render_template("index.html")

    @app.route("/apply", methods=["GET", "POST"])
    @login_required
    def apply():
        if request.method == "POST":
            days_requested = calculate_business_days(request.form["start_date"], request.form["end_date"])

            if days_requested > current_user.leave_balance:
                return f"""
                <h2>Request Denied</h2>
                <p>You requested {days_requested} day(s), but only have {current_user.leave_balance} day(s) remaining.</p>
                <a href="/apply">Back</a>
                """

            new_request = LeaveRequest(
                user_id=current_user.id,
                leave_type=request.form["leave_type"],
                start_date=request.form["start_date"],
                end_date=request.form["end_date"],
                reason=request.form["reason"]
            )
            db.session.add(new_request)
            db.session.commit()

            return f"""
            <h2>Leave Request Submitted!</h2>
            <p><b>Name:</b> {current_user.name}</p>
            <p><b>Leave Type:</b> {new_request.leave_type}</p>
            <p><b>From:</b> {new_request.start_date} <b>To:</b> {new_request.end_date}</p>
            <p><b>Business days:</b> {days_requested}</p>
            <p><b>Current balance (unchanged until approved):</b> {current_user.leave_balance}</p>
            <p><b>Status:</b> {new_request.status}</p>
            <a href="/">Back to Home</a>
            """
        return render_template("apply.html")

    @app.route("/requests")
    @login_required
    def view_requests():
        if current_user.role == "Manager":
            all_requests = LeaveRequest.query.all()
        else:
            all_requests = LeaveRequest.query.filter_by(user_id=current_user.id).all()
        return render_template("requests.html", requests=all_requests, calc_days=calculate_business_days)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            hashed_password = generate_password_hash(request.form["password"])
            new_user = User(
                name=request.form["name"],
                email=request.form["email"],
                password_hash=hashed_password,
                role=request.form["role"]
            )
            db.session.add(new_user)
            db.session.commit()
            return redirect("/login")
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = User.query.filter_by(email=request.form["email"]).first()
            if user and check_password_hash(user.password_hash, request.form["password"]):
                login_user(user)
                return redirect("/")
            return "Invalid email or password"
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        logout_user()
        return redirect("/")

    @app.route("/manage")
    @login_required
    def manage_requests():
        if current_user.role != "Manager":
            return "Access denied - Managers only", 403
        pending = LeaveRequest.query.filter_by(status="Pending").all()
        return render_template("manage_requests.html", requests=pending, calc_days=calculate_business_days)

    @app.route("/manage/<int:request_id>/approve", methods=["POST"])
    @login_required
    def approve_request(request_id):
        if current_user.role != "Manager":
            return "Access denied - Managers only", 403
        leave_request = LeaveRequest.query.get_or_404(request_id)
        days = calculate_business_days(leave_request.start_date, leave_request.end_date)
        leave_request.user.leave_balance -= days
        leave_request.status = "Approved"
        leave_request.manager_comment = request.form.get("comment", "")
        db.session.commit()
        return redirect("/manage")

    @app.route("/manage/<int:request_id>/reject", methods=["POST"])
    @login_required
    def reject_request(request_id):
        if current_user.role != "Manager":
            return "Access denied - Managers only", 403
        leave_request = LeaveRequest.query.get_or_404(request_id)
        leave_request.status = "Rejected"
        leave_request.manager_comment = request.form.get("comment", "")
        db.session.commit()
        return redirect("/manage")

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)