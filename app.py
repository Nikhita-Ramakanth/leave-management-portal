from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

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


def create_app(test_config=None):
    app = Flask(__name__)

    if test_config:
        app.config.update(test_config)
    else:
        app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
            "DATABASE_URL", "sqlite:///leave.db"
        )

    db.init_app(app)

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

    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5000)