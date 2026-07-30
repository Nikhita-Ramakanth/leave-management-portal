import pytest
from app import create_app, db, LeaveRequest

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


def test_homepage_loads(client):
    response = client.get("/")
    assert response.status_code == 200


def test_apply_page_requires_login(client):
    response = client.get("/apply")
    assert response.status_code == 302

    from app import LeaveRequest

def test_submit_leave_request(client):
    client.post("/register", data={
        "name": "Test Employee",
        "email": "test@example.com",
        "password": "testpass123",
        "role": "Employee"
    })
    client.post("/login", data={
        "email": "test@example.com",
        "password": "testpass123"
    })

    response = client.post("/apply", data={
        "leave_type": "Sick",
        "start_date": "2026-08-01",
        "end_date": "2026-08-03",
        "reason": "Testing"
    })

    assert response.status_code == 200

    saved = LeaveRequest.query.filter_by(leave_type="Sick").first()
    assert saved is not None
    assert saved.status == "Pending"
    assert saved.user.name == "Test Employee"