import pytest
from app import create_app, db, LeaveRequest, User


@pytest.fixture
def client():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"
    })

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client


def register(client, name, email, password, role):
    return client.post("/register", data={
        "name": name,
        "email": email,
        "password": password,
        "role": role
    })


def login(client, email, password):
    return client.post("/login", data={
        "email": email,
        "password": password
    })


def test_homepage_loads(client):
    response = client.get("/")
    assert response.status_code == 200


def test_apply_page_requires_login(client):
    response = client.get("/apply")
    assert response.status_code == 302


def test_submit_leave_request_does_not_deduct_balance_immediately(client):
    register(client, "Test Employee", "employee@test.com", "pass123", "Employee")
    login(client, "employee@test.com", "pass123")

    client.post("/apply", data={
        "leave_type": "Sick",
        "start_date": "2026-08-03",  # Monday
        "end_date": "2026-08-05",    # Wednesday
        "reason": "Testing"
    })

    with client.application.app_context():
        user = User.query.filter_by(email="employee@test.com").first()
        assert user.leave_balance == 24  # unchanged until approved

        saved_request = LeaveRequest.query.filter_by(user_id=user.id).first()
        assert saved_request is not None
        assert saved_request.status == "Pending"


def test_weekend_days_excluded_from_business_day_count(client):
    register(client, "Weekend Tester", "weekend@test.com", "pass123", "Employee")
    login(client, "weekend@test.com", "pass123")

    # Friday to Monday — should count as 2 business days, not 4
    response = client.post("/apply", data={
        "leave_type": "Casual",
        "start_date": "2026-08-07",  # Friday
        "end_date": "2026-08-10",    # Monday
        "reason": "Long weekend"
    })

    assert b"Business days:</b> 2" in response.data


def test_approval_deducts_balance_correctly(client):
    register(client, "Approve Test", "approvetest@test.com", "pass123", "Employee")
    register(client, "Manager One", "manager1@test.com", "mgrpass123", "Manager")

    login(client, "approvetest@test.com", "pass123")
    client.post("/apply", data={
        "leave_type": "Annual",
        "start_date": "2026-08-03",  # Monday
        "end_date": "2026-08-05",    # Wednesday
        "reason": "Vacation"
    })
    client.get("/logout")

    login(client, "manager1@test.com", "mgrpass123")

    with client.application.app_context():
        pending = LeaveRequest.query.filter_by(status="Pending").first()
        request_id = pending.id

    client.post(f"/manage/{request_id}/approve", data={"comment": "Approved, enjoy!"})

    with client.application.app_context():
        employee = User.query.filter_by(email="approvetest@test.com").first()
        assert employee.leave_balance == 21  # 24 - 3 business days

        approved_request = LeaveRequest.query.get(request_id)
        assert approved_request.status == "Approved"
        assert approved_request.manager_comment == "Approved, enjoy!"


def test_rejection_does_not_deduct_balance(client):
    register(client, "Reject Test", "rejecttest@test.com", "pass123", "Employee")
    register(client, "Manager Two", "manager2@test.com", "mgrpass123", "Manager")

    login(client, "rejecttest@test.com", "pass123")
    client.post("/apply", data={
        "leave_type": "Sick",
        "start_date": "2026-08-03",
        "end_date": "2026-08-05",
        "reason": "Testing rejection"
    })
    client.get("/logout")

    login(client, "manager2@test.com", "mgrpass123")

    with client.application.app_context():
        pending = LeaveRequest.query.filter_by(status="Pending").first()
        request_id = pending.id

    client.post(f"/manage/{request_id}/reject", data={"comment": "Team is short-staffed"})

    with client.application.app_context():
        employee = User.query.filter_by(email="rejecttest@test.com").first()
        assert employee.leave_balance == 24  # unchanged

        rejected_request = LeaveRequest.query.get(request_id)
        assert rejected_request.status == "Rejected"
        assert rejected_request.manager_comment == "Team is short-staffed"


def test_employee_cannot_access_manage_page(client):
    register(client, "Regular Employee", "regular@test.com", "pass123", "Employee")
    login(client, "regular@test.com", "pass123")

    response = client.get("/manage")
    assert response.status_code == 403


def test_employee_only_sees_own_requests(client):
    register(client, "Employee A", "empA@test.com", "pass123", "Employee")
    register(client, "Employee B", "empB@test.com", "pass123", "Employee")

    login(client, "empA@test.com", "pass123")
    client.post("/apply", data={
        "leave_type": "Sick", "start_date": "2026-08-03",
        "end_date": "2026-08-03", "reason": "A's request"
    })
    client.get("/logout")

    login(client, "empB@test.com", "pass123")
    response = client.get("/requests")
    assert b"A&#39;s request" not in response.data and b"A's request" not in response.data