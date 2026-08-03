import os
from flask import Flask, render_template, request, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, logout_user, UserMixin, login_required, current_user
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

ROLES = ["Employee", "Manager", "Senior Manager", "Head of Practice", "Admin"]
PUBLIC_ROLES = ["Employee", "Manager", "Senior Manager", "Head of Practice"]
PRACTICES = ["Human Resources", "Finance", "Development", "Testing"]

class Holiday(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)


def calculate_business_days(start_date_str, end_date_str):
    start = datetime.strptime(start_date_str, "%Y-%m-%d")
    end = datetime.strptime(end_date_str, "%Y-%m-%d")
    holiday_dates = {h.date for h in Holiday.query.all()}
    business_days = 0
    current = start
    while current <= end:
        current_str = current.strftime("%Y-%m-%d")
        if current.weekday() < 5 and current_str not in holiday_dates:
            business_days += 1
        current += timedelta(days=1)
    return business_days


class LeaveRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", foreign_keys=[user_id], backref="leave_requests")
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
    role = db.Column(db.String(30), nullable=False, default="Employee")
    practice = db.Column(db.String(50), nullable=True)
    leave_balance = db.Column(db.Integer, nullable=False, default=24)
    phone_number = db.Column(db.String(20), nullable=True)
    manager_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    manager = db.relationship("User", remote_side=[id], backref="team_members")


def create_app(test_config=None):
    app = Flask(__name__)

    if test_config:
        app.config.update(test_config)
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
            "DATABASE_URL", "sqlite:///leave.db"
        )

    db.init_app(app)
    Migrate(app, db)

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
            if request.form["end_date"] < request.form["start_date"]:
                return "End date cannot be before start date", 400
            days_requested = calculate_business_days(request.form["start_date"], request.form["end_date"])
            if days_requested > current_user.leave_balance:
                return render_template(
                    "apply_denied.html",
                    days_requested=days_requested,
                    balance=current_user.leave_balance
                )

            new_request = LeaveRequest(
                user_id=current_user.id,
                leave_type=request.form["leave_type"],
                start_date=request.form["start_date"],
                end_date=request.form["end_date"],
                reason=request.form["reason"]
            )
            db.session.add(new_request)
            db.session.commit()

            return redirect(f"/apply/success/{new_request.id}")
        holidays_list = Holiday.query.order_by(Holiday.date).all()
        return render_template("apply.html", holidays=holidays_list)
    @app.route("/apply/success/<int:request_id>")
    @login_required
    def apply_success(request_id):
        leave_request = LeaveRequest.query.get_or_404(request_id)
        if leave_request.user_id != current_user.id:
            return "Access denied", 403
        days = calculate_business_days(leave_request.start_date, leave_request.end_date)
        return render_template(
            "apply_success.html",
            name=current_user.name,
            leave_type=leave_request.leave_type,
            start_date=leave_request.start_date,
            end_date=leave_request.end_date,
            days=days
        )
    @app.route("/requests")
    @login_required
    def view_requests():
        my_requests = LeaveRequest.query.filter_by(user_id=current_user.id).all()
        team_requests = []
        if current_user.team_members:
            team_ids = [member.id for member in current_user.team_members]
            team_requests = LeaveRequest.query.filter(LeaveRequest.user_id.in_(team_ids)).all()
        return render_template(
            "requests.html",
            my_requests=my_requests,
            team_requests=team_requests,
            calc_days=calculate_business_days
        )

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            submitted_role = request.form["role"]
            if submitted_role not in PUBLIC_ROLES:
                return "Invalid role selection", 400

            if request.form["password"] != request.form["confirm_password"]:
                return "Passwords do not match", 400

            if len(request.form["password"]) < 8:
                return "Password must be at least 8 characters", 400

            manager_id = request.form.get("manager_id") or None
            practice = request.form.get("practice") or None

            if manager_id:
                selected_manager = db.session.get(User, int(manager_id))
                if selected_manager is None or selected_manager.practice != practice:
                    return "Invalid selection: manager must belong to the same practice", 400

            raw_phone = request.form.get("phone_number") or ""
            full_phone = f"{request.form.get('country_code', '')} {raw_phone}".strip() if raw_phone else None

            hashed_password = generate_password_hash(request.form["password"])
            new_user = User(
                name=request.form["name"],
                email=request.form["email"],
                password_hash=hashed_password,
                role=submitted_role,
                practice=practice,
                phone_number=full_phone,
                manager_id=manager_id
            )
            db.session.add(new_user)
            db.session.commit()
            return redirect("/login")
        potential_managers = User.query.filter(User.role != "Employee").all()
        return render_template("register.html", managers=potential_managers, roles=PUBLIC_ROLES, practices=PRACTICES)

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
        if not current_user.team_members:
            return "Access denied - you have no team members to manage", 403
        team_ids = [member.id for member in current_user.team_members]
        pending = LeaveRequest.query.filter(
            LeaveRequest.user_id.in_(team_ids),
            LeaveRequest.status == "Pending"
        ).all()
        return render_template("manage_requests.html", requests=pending, calc_days=calculate_business_days)

    @app.route("/manage/<int:request_id>/approve", methods=["POST"])
    @login_required
    def approve_request(request_id):
        leave_request = LeaveRequest.query.get_or_404(request_id)
        if leave_request.user.manager_id != current_user.id:
            return "Access denied - not your team member", 403
        days = calculate_business_days(leave_request.start_date, leave_request.end_date)
        leave_request.user.leave_balance -= days
        leave_request.status = "Approved"
        leave_request.manager_comment = request.form.get("comment", "")
        db.session.commit()
        return redirect("/manage")

    @app.route("/manage/<int:request_id>/reject", methods=["POST"])
    @login_required
    def reject_request(request_id):
        leave_request = LeaveRequest.query.get_or_404(request_id)
        if leave_request.user.manager_id != current_user.id:
            return "Access denied - not your team member", 403
        leave_request.status = "Rejected"
        leave_request.manager_comment = request.form.get("comment", "")
        db.session.commit()
        return redirect("/manage")

    @app.route("/holidays", methods=["GET", "POST"])
    @login_required
    def holidays():
        if current_user.role != "Admin":
            return "Access denied - Admins only", 403
        if request.method == "POST":
            new_holiday = Holiday(
                date=request.form["date"],
                name=request.form["name"]
            )
            db.session.add(new_holiday)
            db.session.commit()
        all_holidays = Holiday.query.order_by(Holiday.date).all()
        return render_template("holidays.html", holidays=all_holidays)
    @app.route("/users")
    @login_required
    def manage_users():
        if current_user.role != "Admin":
            return "Access denied - Admins only", 403
        all_users = User.query.all()
        return render_template("manage_users.html", users=all_users)

    @app.route("/users/<int:user_id>/reassign", methods=["POST"])
    @login_required
    def reassign_user(user_id):
        if current_user.role != "Admin":
            return "Access denied - Admins only", 403
        user_to_update = db.session.get(User, user_id)
        if user_to_update is None:
            return "User not found", 404

        new_manager_id = request.form.get("manager_id") or None

        if new_manager_id:
            new_manager = db.session.get(User, int(new_manager_id))
            if new_manager is None or new_manager.practice != user_to_update.practice:
                return "Invalid selection: manager must belong to the same practice", 400
            if int(new_manager_id) == user_to_update.id:
                return "A user cannot report to themselves", 400

        user_to_update.manager_id = new_manager_id
        db.session.commit()
        return redirect("/users")

    @app.route("/users/<int:user_id>/promote-admin", methods=["POST"])
    @login_required
    def promote_admin(user_id):
        if current_user.role != "Admin":
            return "Access denied - Admins only", 403
        user_to_promote = db.session.get(User, user_id)
        if user_to_promote is None:
            return "User not found", 404
        user_to_promote.role = "Admin"
        db.session.commit()
        return redirect("/users")

    @app.cli.command("create-admin")
    def create_admin():
        import getpass
        print("=== Create the first Admin account ===")
        name = input("Full name: ")
        email = input("Email: ")
        password = getpass.getpass("Password: ")

        existing = User.query.filter_by(email=email).first()
        if existing:
            print(f"A user with email {email} already exists.")
            return

        hashed_password = generate_password_hash(password)
        admin_user = User(
            name=name,
            email=email,
            password_hash=hashed_password,
            role="Admin"
        )
        db.session.add(admin_user)
        db.session.commit()
        print(f"Admin account created for {name} ({email}).")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5000)