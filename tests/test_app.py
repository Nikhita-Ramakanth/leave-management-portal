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


def test_apply_page_loads(client):
    response = client.get("/apply")
    assert response.status_code == 200

    from app import LeaveRequest

def test_submit_leave_request(client):
    response = client.post("/apply", data={
        "name": "Test Employee",
        "leave_type": "Sick",
        "start_date": "2026-08-01",
        "end_date": "2026-08-03",
        "reason": "Testing"
    })

    assert response.status_code == 200

    saved = LeaveRequest.query.filter_by(name="Test Employee").first()
    assert saved is not None
    assert saved.leave_type == "Sick"
    assert saved.status == "Pending"