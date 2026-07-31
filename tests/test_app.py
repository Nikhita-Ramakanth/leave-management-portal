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


def register(client, name, email, password, role, practice=None, manager_id=None):
    return client.post("/register", data={
        "name": name,
        "email": email,
        "password": password,
        "role": role,
        "practice": practice or "",
        "manager_id": manager_id or ""
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
        "start_date": "2026-08-03",
        "end_date": "2026-08-05",
        "reason": "Testing"
    })

    with client.application.app_context():
        user = User.query.filter_by(email="employee@test.com").first()
        assert user.leave_balance == 24

        saved_request = LeaveRequest.query.filter_by(user_id=user.id).first()
        assert saved_request is not None
        assert saved_request.status == "Pending"


def test_weekend_days_excluded_from_business_day_count(client):
    register(client, "Weekend Tester", "weekend@test.com", "pass123", "Employee")
    login(client, "weekend@test.com", "pass123")

    response = client.post("/apply", data={
        "leave_type": "Casual",
        "start_date": "2026-08-07",
        "end_date": "2026-08-10",
        "reason": "Long weekend"
    })

    assert b"Business days:</b> 2" in response.data


def test_approval_deducts_balance_correctly(client):
    register(client, "Approve Test", "approvetest@test.com", "pass123", "Employee")
    register(client, "Manager One", "manager1@test.com", "mgrpass123", "Manager")

    with client.application.app_context():
        manager_id = User.query.filter_by(email="manager1@test.com").first().id
        employee = User.query.filter_by(email="approvetest@test.com").first()
        employee.manager_id = manager_id
        db.session.commit()

    login(client, "approvetest@test.com", "pass123")
    client.post("/apply", data={
        "leave_type": "Annual",
        "start_date": "2026-08-03",
        "end_date": "2026-08-05",
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
        assert employee.leave_balance == 21

        approved_request = db.session.get(LeaveRequest, request_id)
        assert approved_request.status == "Approved"
        assert approved_request.manager_comment == "Approved, enjoy!"


def test_rejection_does_not_deduct_balance(client):
    register(client, "Reject Test", "rejecttest@test.com", "pass123", "Employee")
    register(client, "Manager Two", "manager2@test.com", "mgrpass123", "Manager")

    with client.application.app_context():
        manager_id = User.query.filter_by(email="manager2@test.com").first().id
        employee = User.query.filter_by(email="rejecttest@test.com").first()
        employee.manager_id = manager_id
        db.session.commit()

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
        assert employee.leave_balance == 24

        rejected_request = db.session.get(LeaveRequest, request_id)
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
    assert b"A's request" not in response.data


def test_full_hierarchy_chain_development_practice(client):
    register(client, "Head H", "headh@test.com", "pass123", "Head of Practice", "Leadership")
    with client.application.app_context():
        head_h_id = User.query.filter_by(email="headh@test.com").first().id

    register(client, "Senior S", "seniors@test.com", "pass123", "Senior Manager", "Development", head_h_id)
    with client.application.app_context():
        senior_s_id = User.query.filter_by(email="seniors@test.com").first().id

    register(client, "Manager M", "managerm@test.com", "pass123", "Manager", "Development", senior_s_id)
    with client.application.app_context():
        manager_m_id = User.query.filter_by(email="managerm@test.com").first().id

    register(client, "Employee E", "employeee@test.com", "pass123", "Employee", "Development", manager_m_id)

    login(client, "employeee@test.com", "pass123")
    client.post("/apply", data={
        "leave_type": "Casual", "start_date": "2026-08-03",
        "end_date": "2026-08-03", "reason": "E leave"
    })
    client.get("/logout")

    login(client, "managerm@test.com", "pass123")
    response = client.get("/manage")
    assert b"E leave" in response.data
    with client.application.app_context():
        pending = LeaveRequest.query.filter_by(reason="E leave").first()
        req_id = pending.id
    client.post(f"/manage/{req_id}/approve", data={"comment": "Approved by M"})
    client.get("/logout")

    login(client, "managerm@test.com", "pass123")
    client.post("/apply", data={
        "leave_type": "Sick", "start_date": "2026-08-04",
        "end_date": "2026-08-04", "reason": "M leave"
    })
    client.get("/logout")

    login(client, "seniors@test.com", "pass123")
    response = client.get("/manage")
    assert b"M leave" in response.data
    with client.application.app_context():
        pending = LeaveRequest.query.filter_by(reason="M leave").first()
        req_id = pending.id
    client.post(f"/manage/{req_id}/approve", data={"comment": "Approved by S"})
    client.get("/logout")

    login(client, "seniors@test.com", "pass123")
    client.post("/apply", data={
        "leave_type": "Annual", "start_date": "2026-08-05",
        "end_date": "2026-08-05", "reason": "S leave"
    })
    client.get("/logout")

    login(client, "headh@test.com", "pass123")
    response = client.get("/manage")
    assert b"S leave" in response.data
    with client.application.app_context():
        pending = LeaveRequest.query.filter_by(reason="S leave").first()
        req_id = pending.id
    client.post(f"/manage/{req_id}/approve", data={"comment": "Approved by H"})

    with client.application.app_context():
        assert LeaveRequest.query.filter_by(reason="E leave").first().status == "Approved"
        assert LeaveRequest.query.filter_by(reason="M leave").first().status == "Approved"
        assert LeaveRequest.query.filter_by(reason="S leave").first().status == "Approved"


def test_separate_practice_hierarchies_are_isolated(client):
    register(client, "Head Dev", "headdev@test.com", "pass123", "Head of Practice", "Development")
    with client.application.app_context():
        head_dev_id = User.query.filter_by(email="headdev@test.com").first().id

    register(client, "Manager Dev", "managerdev@test.com", "pass123", "Manager", "Development", head_dev_id)
    with client.application.app_context():
        manager_dev_id = User.query.filter_by(email="managerdev@test.com").first().id

    register(client, "Employee Dev", "employeedev@test.com", "pass123", "Employee", "Development", manager_dev_id)

    register(client, "Head Fin", "headfin@test.com", "pass123", "Head of Practice", "Finance")
    with client.application.app_context():
        head_fin_id = User.query.filter_by(email="headfin@test.com").first().id

    register(client, "Manager Fin", "managerfin@test.com", "pass123", "Manager", "Finance", head_fin_id)
    with client.application.app_context():
        manager_fin_id = User.query.filter_by(email="managerfin@test.com").first().id

    register(client, "Employee Fin", "employeefin@test.com", "pass123", "Employee", "Finance", manager_fin_id)

    login(client, "employeedev@test.com", "pass123")
    client.post("/apply", data={
        "leave_type": "Casual", "start_date": "2026-08-10",
        "end_date": "2026-08-10", "reason": "Dev leave request"
    })
    client.get("/logout")

    login(client, "employeefin@test.com", "pass123")
    client.post("/apply", data={
        "leave_type": "Casual", "start_date": "2026-08-11",
        "end_date": "2026-08-11", "reason": "Fin leave request"
    })
    client.get("/logout")

    login(client, "managerdev@test.com", "pass123")
    response = client.get("/manage")
    assert b"Dev leave request" in response.data
    assert b"Fin leave request" not in response.data
    client.get("/logout")

    login(client, "managerfin@test.com", "pass123")
    response = client.get("/manage")
    assert b"Fin leave request" in response.data
    assert b"Dev leave request" not in response.data
    