import os
from flask import Flask, render_template, request, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    leave_type = db.Column(db.String(50), nullable=False)
    start_date = db.Column(db.String(20), nullable=False)
    end_date = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(300))
    status = db.Column(db.String(20), default="Pending")
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="Employee")


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
    def apply():
        if request.method == "POST":
            new_request = LeaveRequest(
                name=request.form["name"],
                leave_type=request.form["leave_type"],
                start_date=request.form["start_date"],
                end_date=request.form["end_date"],
                reason=request.form["reason"]
            )
            db.session.add(new_request)
            db.session.commit()

            return f"""
            <h2>Leave Request Submitted!</h2>
            <p><b>Name:</b> {new_request.name}</p>
            <p><b>Leave Type:</b> {new_request.leave_type}</p>
            <p><b>From:</b> {new_request.start_date} <b>To:</b> {new_request.end_date}</p>
            <p><b>Status:</b> {new_request.status}</p>
            <a href="/">Back to Home</a>
            """
        return render_template("apply.html")

    @app.route("/requests")
    def view_requests():
        all_requests = LeaveRequest.query.all()
        return render_template("requests.html", requests=all_requests)

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

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)