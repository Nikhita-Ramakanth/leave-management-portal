import os
import smtplib
from email.mime.text import MIMEText
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


def error_response(message, status_code=400):
    titles = {400: "Invalid request", 403: "Access denied", 404: "Not found"}
    title = titles.get(status_code, "Something went wrong")
    return render_template("error.html", title=title, message=message), status_code

def send_email(to_email, subject, body):
    smtp_email = os.environ.get("SMTP_EMAIL")
    smtp_password = os.environ.get("SMTP_APP_PASSWORD")
    if not smtp_email or not smtp_password:
        print(f"SMTP not configured - skipping email to {to_email}")
        return False
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_email
    msg["To"] = to_email
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    industry = db.Column(db.String(100), nullable=True)
    contact_email = db.Column(db.String(120), nullable=True)
    contact_phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    employee_count = db.Column(db.Integer, nullable=True)
    subscription_type = db.Column(db.String(20), nullable=True)
    subscription_status = db.Column(db.String(20), nullable=True)
    subscription_start_date = db.Column(db.Date, nullable=True)

class OrgRole(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False)
    organization = db.relationship("Organization", backref="org_roles")
    title = db.Column(db.String(50), nullable=False)
    level = db.Column(db.Integer, nullable=False)


class OrgPractice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False)
    organization = db.relationship("Organization", backref="org_practices")
    name = db.Column(db.String(50), nullable=False)
class Invite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False)
    organization = db.relationship("Organization", backref="invites")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    org_role_id = db.Column(db.Integer, db.ForeignKey("org_role.id"), nullable=False)
    org_role = db.relationship("OrgRole")
    org_practice_id = db.Column(db.Integer, db.ForeignKey("org_practice.id"), nullable=True)
    org_practice = db.relationship("OrgPractice")
    manager_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    manager = db.relationship("User", foreign_keys=[manager_id])

class PasswordReset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)

class Holiday(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False)
    organization = db.relationship("Organization", backref="holidays")


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
    org_practice_id = db.Column(db.Integer, db.ForeignKey("org_practice.id"), nullable=True)
    org_practice = db.relationship("OrgPractice", backref="users")
    leave_balance = db.Column(db.Integer, nullable=False, default=24)
    phone_number = db.Column(db.String(20), nullable=True)
    manager_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    manager = db.relationship("User", remote_side=[id], backref="team_members")
    is_super_admin = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    organization_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=True)
    organization = db.relationship("Organization", backref="users")
    org_role_id = db.Column(db.Integer, db.ForeignKey("org_role.id"), nullable=True)
    org_role = db.relationship("OrgRole", backref="users")

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
        if current_user.is_authenticated and current_user.is_super_admin:
            return redirect("/super-admin")
        if current_user.is_authenticated and current_user.team_members:
            return redirect("/manage")
        return render_template("index.html")

    @app.route("/apply", methods=["GET", "POST"])
    @login_required
    def apply():
        if request.method == "POST":
            if request.form["end_date"] < request.form["start_date"]:
                return error_response("End date cannot be before start date", 400)
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

            if current_user.manager:
                send_email(
                    to_email=current_user.manager.email,
                    subject=f"New leave request from {current_user.name}",
                    body=f"{current_user.name} has submitted a {new_request.leave_type} leave request from {new_request.start_date} to {new_request.end_date}.\n\nReason: {new_request.reason}\n\nReview it at {request.host_url}manage"
                )

            return redirect(f"/apply/success/{new_request.id}")
        holidays_list = Holiday.query.order_by(Holiday.date).all()
        return render_template("apply.html", holidays=holidays_list)
    @app.route("/apply/success/<int:request_id>")
    @login_required
    def apply_success(request_id):
        leave_request = LeaveRequest.query.get_or_404(request_id)
        if leave_request.user_id != current_user.id:
            return error_response("Access denied", 403)
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
        token = request.args.get("invite") or request.form.get("invite")
        invite = Invite.query.filter_by(token=token).first() if token else None

        if invite is None or invite.used or invite.expires_at < datetime.utcnow():
            return render_template("invite_invalid.html"), 400

        if request.method == "POST":
            if request.form["password"] != request.form["confirm_password"]:
                return error_response("Passwords do not match", 400)

            if len(request.form["password"]) < 8:
                return error_response("Password must be at least 8 characters", 400)

            if User.query.filter_by(email=invite.email).first():
                return error_response("An account with this email already exists", 400)

            hashed_password = generate_password_hash(request.form["password"])
            new_user = User(
                name=invite.name,
                email=invite.email,
                password_hash=hashed_password,
                role="Employee",
                org_role_id=invite.org_role_id,
                org_practice_id=invite.org_practice_id,
                manager_id=invite.manager_id,
                organization_id=invite.organization_id
            )
            db.session.add(new_user)
            invite.used = True
            db.session.commit()
            return redirect("/login")

        return render_template("register.html", invite=invite, invite_token=token)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = User.query.filter_by(email=request.form["email"]).first()
            if user and check_password_hash(user.password_hash, request.form["password"]):
                login_user(user)
                if user.is_super_admin:
                    return redirect("/super-admin")
                return redirect("/")
            return error_response("Invalid email or password", 401)
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        logout_user()
        return redirect("/")

    @app.route("/manage")
    @login_required
    def manage_requests():
        if not current_user.team_members:
            return error_response("Access denied - you have no team members to manage", 403)
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
            return error_response("Access denied - not your team member", 403)
        days = calculate_business_days(leave_request.start_date, leave_request.end_date)
        leave_request.user.leave_balance -= days
        leave_request.status = "Approved"
        leave_request.manager_comment = request.form.get("comment", "")
        db.session.commit()

        send_email(
            to_email=leave_request.user.email,
            subject="Your leave request was approved",
            body=f"Your {leave_request.leave_type} leave request from {leave_request.start_date} to {leave_request.end_date} has been approved.\n\nComment: {leave_request.manager_comment}"
        )

        return redirect("/manage")

    @app.route("/manage/<int:request_id>/reject", methods=["POST"])
    @login_required
    def reject_request(request_id):
        leave_request = LeaveRequest.query.get_or_404(request_id)
        if leave_request.user.manager_id != current_user.id:
            return error_response("Access denied - not your team member", 403)
        leave_request.status = "Rejected"
        leave_request.manager_comment = request.form.get("comment", "")
        db.session.commit()

        send_email(
            to_email=leave_request.user.email,
            subject="Your leave request was rejected",
            body=f"Your {leave_request.leave_type} leave request from {leave_request.start_date} to {leave_request.end_date} was rejected.\n\nComment: {leave_request.manager_comment}"
        )

        return redirect("/manage")

    @app.route("/holidays", methods=["GET", "POST"])
    @login_required
    def holidays():
        if current_user.role != "Admin":
            return error_response("Access denied - Admins only", 403)
        if request.method == "POST":
            new_holiday = Holiday(
                date=request.form["date"],
                name=request.form["name"],
                organization_id=current_user.organization_id
            )
            db.session.add(new_holiday)
            db.session.commit()
        all_holidays = Holiday.query.order_by(Holiday.date).all()
        return render_template("holidays.html", holidays=all_holidays)
    @app.route("/users")
    @login_required
    def manage_users():
        if current_user.role != "Admin":
            return error_response("Access denied - Admins only", 403)
        all_users = User.query.filter(
            User.id != current_user.id,
            User.organization_id == current_user.organization_id
        ).all()
        org_roles = OrgRole.query.filter_by(organization_id=current_user.organization_id).order_by(OrgRole.level.desc()).all()
        org_practices = OrgPractice.query.filter_by(organization_id=current_user.organization_id).order_by(OrgPractice.name).all()
        return render_template("manage_users.html", users=all_users, org_roles=org_roles, org_practices=org_practices)

    @app.route("/users/<int:user_id>/reassign", methods=["POST"])
    @login_required
    def reassign_user(user_id):
        if current_user.role != "Admin":
            return error_response("Access denied - Admins only", 403)
        user_to_update = db.session.get(User, user_id)
        if user_to_update is None:
            return error_response("User not found", 404)

        new_manager_id = request.form.get("manager_id") or None

        if new_manager_id:
            new_manager = db.session.get(User, int(new_manager_id))
            if new_manager is None or new_manager.org_practice_id != user_to_update.org_practice_id:
                return error_response("Invalid selection: manager must belong to the same department", 400)
            if int(new_manager_id) == user_to_update.id:
                return error_response("A user cannot report to themselves", 400)

        user_to_update.manager_id = new_manager_id
        db.session.commit()
        return redirect("/users")

    @app.route("/users/<int:user_id>/promote-admin", methods=["POST"])
    @login_required
    def promote_admin(user_id):
        if current_user.role != "Admin":
            return error_response("Access denied - Admins only", 403)
        user_to_promote = db.session.get(User, user_id)
        if user_to_promote is None:
            return error_response("User not found", 404)
        user_to_promote.role = "Admin"
        db.session.commit()
        return redirect("/users")

    @app.route("/users/<int:user_id>/update", methods=["POST"])
    @login_required
    def update_user(user_id):
        if current_user.role != "Admin":
            return error_response("Access denied - Admins only", 403)
        user_to_update = db.session.get(User, user_id)
        if user_to_update is None:
            return error_response("User not found", 404)

        new_email = request.form["email"]
        existing = User.query.filter(User.email == new_email, User.id != user_to_update.id).first()
        if existing:
            return error_response("An account with this email already exists", 400)

        org_role = db.session.get(OrgRole, int(request.form["org_role_id"]))
        if org_role is None or org_role.organization_id != current_user.organization_id:
            return error_response("Invalid role selection", 400)

        org_practice_id = request.form.get("org_practice_id") or None
        manager_id = request.form.get("manager_id") or None

        if manager_id:
            if int(manager_id) == user_to_update.id:
                return error_response("A user cannot report to themselves", 400)
            new_manager = db.session.get(User, int(manager_id))
            if new_manager is None or new_manager.role == "Admin":
                return error_response("Invalid manager selection", 400)
            submitted_practice_id = int(org_practice_id) if org_practice_id else None
            if new_manager.org_practice_id != submitted_practice_id:
                return error_response("Invalid selection: manager must belong to the same department", 400)
            if new_manager.org_role is None or new_manager.org_role.level <= org_role.level:
                return error_response("Invalid selection: manager must be at a higher level", 400)

        user_to_update.email = new_email
        user_to_update.org_role_id = org_role.id
        user_to_update.org_practice_id = org_practice_id
        user_to_update.manager_id = manager_id
        db.session.commit()
        return redirect("/users")

    @app.route("/super-admin")
    @login_required
    def super_admin_dashboard():
        if not current_user.is_super_admin:
            return error_response("Access denied - Super Admins only", 403)
        organizations = Organization.query.order_by(Organization.created_at.desc()).all()
        total_orgs = len(organizations)
        total_users = User.query.filter(User.organization_id.isnot(None)).count()
        active_orgs = Organization.query.filter_by(is_active=True).count()
        return render_template(
            "super_admin_dashboard.html",
            organizations=organizations,
            total_orgs=total_orgs,
            total_users=total_users,
            active_orgs=active_orgs
        )

    @app.route("/super-admin/admins/new", methods=["GET", "POST"])
    @login_required
    def create_org_admin():
        if not current_user.is_super_admin:
            return error_response("Access denied - Super Admins only", 403)
        if request.method == "POST":
            if request.form["password"] != request.form["confirm_password"]:
                return error_response("Passwords do not match", 400)
            if len(request.form["password"]) < 8:
                return error_response("Password must be at least 8 characters", 400)
            if User.query.filter_by(email=request.form["email"]).first():
                return error_response("An account with this email already exists", 400)

            hashed_password = generate_password_hash(request.form["password"])
            new_admin = User(
                name=request.form["name"],
                email=request.form["email"],
                password_hash=hashed_password,
                role="Admin",
                organization_id=int(request.form["organization_id"])
            )
            db.session.add(new_admin)
            db.session.commit()
            return redirect("/super-admin")
        organizations = Organization.query.filter_by(is_active=True).order_by(Organization.name).all()
        return render_template("create_org_admin.html", organizations=organizations)

    @app.route("/super-admin/organizations/<int:org_id>/toggle-active", methods=["POST"])
    @login_required
    def toggle_organization_active(org_id):
        if not current_user.is_super_admin:
            return error_response("Access denied - Super Admins only", 403)
        org = db.session.get(Organization, org_id)
        if org is None:
            return error_response("Organization not found", 404)
        org.is_active = not org.is_active
        db.session.commit()
        return redirect("/super-admin")

    @app.route("/super-admin/organizations/<int:org_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_organization(org_id):
        if not current_user.is_super_admin:
            return error_response("Access denied - Super Admins only", 403)
        org = db.session.get(Organization, org_id)
        if org is None:
            return error_response("Organization not found", 404)
        if request.method == "POST":
            existing = Organization.query.filter(
                Organization.name == request.form["name"],
                Organization.id != org.id
            ).first()
            if existing:
                return error_response("An organization with this name already exists", 400)
            org.name = request.form["name"]
            org.industry = request.form.get("industry") or None
            org.contact_email = request.form.get("contact_email") or None
            org.contact_phone = request.form.get("contact_phone") or None
            org.address = request.form.get("address") or None
            org.website = request.form.get("website") or None
            org.employee_count = int(request.form["employee_count"]) if request.form.get("employee_count") else None
            org.subscription_type = request.form.get("subscription_type") or None
            org.subscription_status = request.form.get("subscription_status") or None
            db.session.commit()
            return redirect("/super-admin")
        return render_template("edit_organization.html", org=org)

    @app.route("/super-admin/organizations/<int:org_id>/roles", methods=["GET", "POST"])
    @login_required
    def manage_org_roles(org_id):
        if not current_user.is_super_admin:
            return error_response("Access denied - Super Admins only", 403)
        org = db.session.get(Organization, org_id)
        if org is None:
            return error_response("Organization not found", 404)
        if request.method == "POST":
            new_role = OrgRole(
                organization_id=org_id,
                title=request.form["title"],
                level=int(request.form["level"])
            )
            db.session.add(new_role)
            db.session.commit()
            return redirect(f"/super-admin/organizations/{org_id}/roles")
        roles = OrgRole.query.filter_by(organization_id=org_id).order_by(OrgRole.level.desc()).all()
        return render_template("manage_org_roles.html", org=org, roles=roles)

    @app.route("/super-admin/organizations/<int:org_id>/roles/<int:role_id>/delete", methods=["POST"])
    @login_required
    def delete_org_role(org_id, role_id):
        if not current_user.is_super_admin:
            return error_response("Access denied - Super Admins only", 403)
        role = db.session.get(OrgRole, role_id)
        if role is None or role.organization_id != org_id:
            return error_response("Role not found", 404)
        db.session.delete(role)
        db.session.commit()
        return redirect(f"/super-admin/organizations/{org_id}/roles")

    @app.route("/super-admin/organizations/<int:org_id>/practices", methods=["GET", "POST"])
    @login_required
    def manage_org_practices(org_id):
        if not current_user.is_super_admin:
            return error_response("Access denied - Super Admins only", 403)
        org = db.session.get(Organization, org_id)
        if org is None:
            return error_response("Organization not found", 404)
        if request.method == "POST":
            new_practice = OrgPractice(
                organization_id=org_id,
                name=request.form["name"]
            )
            db.session.add(new_practice)
            db.session.commit()
            return redirect(f"/super-admin/organizations/{org_id}/practices")
        practices = OrgPractice.query.filter_by(organization_id=org_id).order_by(OrgPractice.name).all()
        return render_template("manage_org_practices.html", org=org, practices=practices)

    @app.route("/super-admin/organizations/<int:org_id>/practices/<int:practice_id>/delete", methods=["POST"])
    @login_required
    def delete_org_practice(org_id, practice_id):
        if not current_user.is_super_admin:
            return error_response("Access denied - Super Admins only", 403)
        practice = db.session.get(OrgPractice, practice_id)
        if practice is None or practice.organization_id != org_id:
            return error_response("Practice not found", 404)
        db.session.delete(practice)
        db.session.commit()
        return redirect(f"/super-admin/organizations/{org_id}/practices")

    @app.route("/invite", methods=["GET", "POST"])
    @login_required
    def create_invite():
        if current_user.role != "Admin":
            return error_response("Access denied - Admins only", 403)
        if request.method == "POST":
            org_role = db.session.get(OrgRole, int(request.form["org_role_id"]))
            if org_role is None or org_role.organization_id != current_user.organization_id:
                return error_response("Invalid role selection", 400)

            org_practice_id = request.form.get("org_practice_id") or None
            manager_id = request.form.get("manager_id") or None

            if manager_id:
                selected_manager = db.session.get(User, int(manager_id))
                if selected_manager is None:
                    return error_response("Invalid manager selection", 400)
                manager_practice_id = selected_manager.org_practice_id
                submitted_practice_id = int(org_practice_id) if org_practice_id else None
                if manager_practice_id != submitted_practice_id:
                    return error_response("Invalid selection: manager must belong to the same department", 400)
                if selected_manager.org_role is None or selected_manager.org_role.level <= org_role.level:
                    return error_response("Invalid selection: manager must be at a higher level than the invited role", 400)

            if User.query.filter_by(email=request.form["email"]).first():
                return error_response("An account with this email already exists", 400)

            import secrets as secrets_module
            token = secrets_module.token_urlsafe(32)
            new_invite = Invite(
                token=token,
                organization_id=current_user.organization_id,
                expires_at=datetime.utcnow() + timedelta(days=7),
                name=request.form["name"],
                email=request.form["email"],
                org_role_id=org_role.id,
                org_practice_id=org_practice_id,
                manager_id=manager_id
            )
            db.session.add(new_invite)
            db.session.commit()
            invite_link = f"{request.host_url}register?invite={token}"
            email_sent = send_email(
                to_email=request.form["email"],
                subject=f"You're invited to Leavepoint",
                body=f"Hi {request.form['name']},\n\nYou've been invited to join Leavepoint. Click the link below to complete your registration and set your password:\n\n{invite_link}\n\nThis link expires in 7 days."
            )
            return render_template("invite_created.html", invite_link=invite_link, email_sent=email_sent)

        org_roles = OrgRole.query.filter_by(organization_id=current_user.organization_id).order_by(OrgRole.level.desc()).all()
        org_practices = OrgPractice.query.filter_by(organization_id=current_user.organization_id).order_by(OrgPractice.name).all()
        lowest_level = min((r.level for r in org_roles), default=None)
        potential_managers = User.query.filter(
            User.organization_id == current_user.organization_id,
            User.role != "Admin",
            User.org_role_id.isnot(None)
        ).all()
        potential_managers = [
            m for m in potential_managers
            if m.org_role and m.org_role.level != lowest_level
        ]
        return render_template(
            "create_invite.html",
            managers=potential_managers,
            org_roles=org_roles,
            org_practices=org_practices
        )
    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            user = User.query.filter_by(email=request.form["email"]).first()
            if user:
                import secrets as secrets_module
                token = secrets_module.token_urlsafe(32)
                reset = PasswordReset(
                    token=token,
                    user_id=user.id,
                    expires_at=datetime.utcnow() + timedelta(hours=1)
                )
                db.session.add(reset)
                db.session.commit()
                reset_link = f"{request.host_url}reset-password?token={token}"
                send_email(
                    to_email=user.email,
                    subject="Reset your Leavepoint password",
                    body=f"Hi {user.name},\n\nClick the link below to reset your password. This link expires in 1 hour.\n\n{reset_link}\n\nIf you didn't request this, you can safely ignore this email."
                )
            return render_template("forgot_password.html", submitted=True)
        return render_template("forgot_password.html", submitted=False)

    @app.route("/reset-password", methods=["GET", "POST"])
    def reset_password():
        token = request.args.get("token") or request.form.get("token")
        reset = PasswordReset.query.filter_by(token=token).first() if token else None

        if reset is None or reset.used or reset.expires_at < datetime.utcnow():
            return render_template("invite_invalid.html"), 400

        if request.method == "POST":
            if request.form["password"] != request.form["confirm_password"]:
                return error_response("Passwords do not match", 400)
            if len(request.form["password"]) < 8:
                return error_response("Password must be at least 8 characters", 400)

            reset.user.password_hash = generate_password_hash(request.form["password"])
            reset.used = True
            db.session.commit()
            return redirect("/login")

        return render_template("reset_password.html", token=token)

    
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

    @app.cli.command("promote-super-admin")
    def promote_super_admin():
        email = input("Email of the account to promote to Super Admin: ")
        user = User.query.filter_by(email=email).first()
        if user is None:
            print(f"No user found with email {email}.")
            return
        user.is_super_admin = True
        user.organization_id = None
        db.session.commit()
        print(f"{user.name} ({user.email}) promoted to Super Admin.")

    @app.route("/super-admin/organizations/new", methods=["GET", "POST"])
    @login_required
    def create_organization():
        if not current_user.is_super_admin:
            return error_response("Access denied - Super Admins only", 403)
        if request.method == "POST":
            if Organization.query.filter_by(name=request.form["name"]).first():
                return error_response("An organization with this name already exists", 400)
            new_org = Organization(
                name=request.form["name"],
                industry=request.form.get("industry") or None,
                contact_email=request.form.get("contact_email") or None,
                contact_phone=request.form.get("contact_phone") or None,
                address=request.form.get("address") or None,
                website=request.form.get("website") or None,
                employee_count=int(request.form["employee_count"]) if request.form.get("employee_count") else None,
                subscription_type=request.form.get("subscription_type") or None,
                subscription_status=request.form.get("subscription_status") or None
            )
            db.session.add(new_org)
            db.session.commit()
            return redirect(f"/super-admin/organizations/{new_org.id}/setup")
        return render_template("create_organization.html")

    @app.route("/super-admin/organizations/<int:org_id>/setup")
    @login_required
    def org_setup(org_id):
        if not current_user.is_super_admin:
            return error_response("Access denied - Super Admins only", 403)
        org = db.session.get(Organization, org_id)
        if org is None:
            return error_response("Organization not found", 404)
        return render_template("org_setup.html", org=org)

    return app


if __name__ == "__main__":
    app = create_app()
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, host="0.0.0.0", port=5000)
