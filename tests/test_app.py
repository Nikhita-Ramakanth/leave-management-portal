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
    with client.application.app_context():
        from app import Organization, OrgRole, OrgPractice, Invite, db
        import secrets as secrets_module
        from datetime import datetime, timedelta

        org = Organization.query.first()
        if org is None:
            org = Organization(name="Test Org")
            db.session.add(org)
            db.session.commit()

        org_role = OrgRole.query.filter_by(organization_id=org.id, title=role).first()
        if org_role is None:
            level_map = {
                "Employee": 1,
                "Manager": 2,
                "Senior Manager": 3,
                "Head of Practice": 4
            }
            org_role = OrgRole(organization_id=org.id, title=role, level=level_map.get(role, 1))
            db.session.add(org_role)
            db.session.commit()

        org_practice_id = None
        if practice:
            org_practice = OrgPractice.query.filter_by(organization_id=org.id, name=practice).first()
            if org_practice is None:
                org_practice = OrgPractice(organization_id=org.id, name=practice)
                db.session.add(org_practice)
                db.session.commit()
            org_practice_id = org_practice.id

        token = secrets_module.token_urlsafe(16)
        invite = Invite(
            token=token,
            organization_id=org.id,
            expires_at=datetime.utcnow() + timedelta(days=7),
            name=name,
            email=email,
            org_role_id=org_role.id,
            org_practice_id=org_practice_id,
            manager_id=manager_id
        )
        db.session.add(invite)
        db.session.commit()

    return client.post("/register", data={
        "invite": token,
        "password": password,
        "confirm_password": password
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
    register(client, "Test Employee", "employee@test.com", "pass12345", "Employee")
    login(client, "employee@test.com", "pass12345")

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
    register(client, "Weekend Tester", "weekend@test.com", "pass12345", "Employee")
    login(client, "weekend@test.com", "pass12345")

    response = client.post("/apply", data={
        "leave_type": "Casual",
        "start_date": "2026-08-07",
        "end_date": "2026-08-10",
        "reason": "Long weekend"
    }, follow_redirects=True)

    assert b">2<" in response.data


def test_approval_deducts_balance_correctly(client):
    register(client, "Approve Test", "approvetest@test.com", "pass12345", "Employee")
    register(client, "Manager One", "manager1@test.com", "mgrpass12345", "Manager")

    with client.application.app_context():
        manager_id = User.query.filter_by(email="manager1@test.com").first().id
        employee = User.query.filter_by(email="approvetest@test.com").first()
        employee.manager_id = manager_id
        db.session.commit()

    login(client, "approvetest@test.com", "pass12345")
    client.post("/apply", data={
        "leave_type": "Annual",
        "start_date": "2026-08-03",
        "end_date": "2026-08-05",
        "reason": "Vacation"
    })
    client.get("/logout")

    login(client, "manager1@test.com", "mgrpass12345")

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
    register(client, "Reject Test", "rejecttest@test.com", "pass12345", "Employee")
    register(client, "Manager Two", "manager2@test.com", "mgrpass12345", "Manager")

    with client.application.app_context():
        manager_id = User.query.filter_by(email="manager2@test.com").first().id
        employee = User.query.filter_by(email="rejecttest@test.com").first()
        employee.manager_id = manager_id
        db.session.commit()

    login(client, "rejecttest@test.com", "pass12345")
    client.post("/apply", data={
        "leave_type": "Sick",
        "start_date": "2026-08-03",
        "end_date": "2026-08-05",
        "reason": "Testing rejection"
    })
    client.get("/logout")

    login(client, "manager2@test.com", "mgrpass12345")

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
    register(client, "Regular Employee", "regular@test.com", "pass12345", "Employee")
    login(client, "regular@test.com", "pass12345")

    response = client.get("/manage")
    assert response.status_code == 403


def test_employee_only_sees_own_requests(client):
    register(client, "Employee A", "empA@test.com", "pass12345", "Employee")
    register(client, "Employee B", "empB@test.com", "pass12345", "Employee")

    login(client, "empA@test.com", "pass12345")
    client.post("/apply", data={
        "leave_type": "Sick", "start_date": "2026-08-03",
        "end_date": "2026-08-03", "reason": "A's request"
    })
    client.get("/logout")

    login(client, "empB@test.com", "pass12345")
    response = client.get("/requests")
    assert b"A's request" not in response.data


def test_full_hierarchy_chain_development_practice(client):
    register(client, "Head H", "headh@test.com", "pass12345", "Head of Practice", "Development")
    with client.application.app_context():
        head_h_id = User.query.filter_by(email="headh@test.com").first().id

    register(client, "Senior S", "seniors@test.com", "pass12345", "Senior Manager", "Development", head_h_id)
    with client.application.app_context():
        senior_s_id = User.query.filter_by(email="seniors@test.com").first().id

    register(client, "Manager M", "managerm@test.com", "pass12345", "Manager", "Development", senior_s_id)
    with client.application.app_context():
        manager_m_id = User.query.filter_by(email="managerm@test.com").first().id

    register(client, "Employee E", "employeee@test.com", "pass12345", "Employee", "Development", manager_m_id)

    login(client, "employeee@test.com", "pass12345")
    client.post("/apply", data={
        "leave_type": "Casual", "start_date": "2026-08-03",
        "end_date": "2026-08-03", "reason": "E leave"
    })
    client.get("/logout")

    login(client, "managerm@test.com", "pass12345")
    response = client.get("/manage")
    assert b"E leave" in response.data
    with client.application.app_context():
        pending = LeaveRequest.query.filter_by(reason="E leave").first()
        req_id = pending.id
    client.post(f"/manage/{req_id}/approve", data={"comment": "Approved by M"})
    client.get("/logout")

    login(client, "managerm@test.com", "pass12345")
    client.post("/apply", data={
        "leave_type": "Sick", "start_date": "2026-08-04",
        "end_date": "2026-08-04", "reason": "M leave"
    })
    client.get("/logout")

    login(client, "seniors@test.com", "pass12345")
    response = client.get("/manage")
    assert b"M leave" in response.data
    with client.application.app_context():
        pending = LeaveRequest.query.filter_by(reason="M leave").first()
        req_id = pending.id
    client.post(f"/manage/{req_id}/approve", data={"comment": "Approved by S"})
    client.get("/logout")

    login(client, "seniors@test.com", "pass12345")
    client.post("/apply", data={
        "leave_type": "Annual", "start_date": "2026-08-05",
        "end_date": "2026-08-05", "reason": "S leave"
    })
    client.get("/logout")

    login(client, "headh@test.com", "pass12345")
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
    register(client, "Head Dev", "headdev@test.com", "pass12345", "Head of Practice", "Development")
    with client.application.app_context():
        head_dev_id = User.query.filter_by(email="headdev@test.com").first().id

    register(client, "Manager Dev", "managerdev@test.com", "pass12345", "Manager", "Development", head_dev_id)
    with client.application.app_context():
        manager_dev_id = User.query.filter_by(email="managerdev@test.com").first().id

    register(client, "Employee Dev", "employeedev@test.com", "pass12345", "Employee", "Development", manager_dev_id)

    register(client, "Head Fin", "headfin@test.com", "pass12345", "Head of Practice", "Finance")
    with client.application.app_context():
        head_fin_id = User.query.filter_by(email="headfin@test.com").first().id

    register(client, "Manager Fin", "managerfin@test.com", "pass12345", "Manager", "Finance", head_fin_id)
    with client.application.app_context():
        manager_fin_id = User.query.filter_by(email="managerfin@test.com").first().id

    register(client, "Employee Fin", "employeefin@test.com", "pass12345", "Employee", "Finance", manager_fin_id)

    login(client, "employeedev@test.com", "pass12345")
    client.post("/apply", data={
        "leave_type": "Casual", "start_date": "2026-08-10",
        "end_date": "2026-08-10", "reason": "Dev leave request"
    })
    client.get("/logout")

    login(client, "employeefin@test.com", "pass12345")
    client.post("/apply", data={
        "leave_type": "Casual", "start_date": "2026-08-11",
        "end_date": "2026-08-11", "reason": "Fin leave request"
    })
    client.get("/logout")

    login(client, "managerdev@test.com", "pass12345")
    response = client.get("/manage")
    assert b"Dev leave request" in response.data
    assert b"Fin leave request" not in response.data
    client.get("/logout")

    login(client, "managerfin@test.com", "pass12345")
    response = client.get("/manage")
    assert b"Fin leave request" in response.data
    assert b"Dev leave request" not in response.data


def test_cannot_invite_with_manager_from_different_department(client):
    register(client, "Head Dev2", "headdev2@test.com", "pass12345", "Head of Practice", "Development")
    with client.application.app_context():
        from app import Organization, OrgRole, OrgPractice, db
        head_dev2 = User.query.filter_by(email="headdev2@test.com").first()
        head_dev2_id = head_dev2.id
        head_dev2.role = "Admin"

        org = Organization.query.first()
        employee_role = OrgRole(organization_id=org.id, title="Employee", level=1)
        db.session.add(employee_role)
        finance_dept = OrgPractice(organization_id=org.id, name="Finance")
        db.session.add(finance_dept)
        db.session.commit()
        employee_role_id = employee_role.id
        finance_dept_id = finance_dept.id

    login(client, "headdev2@test.com", "pass12345")

    response = client.post("/invite", data={
        "name": "Sneaky Employee",
        "email": "sneaky@test.com",
        "org_role_id": employee_role_id,
        "org_practice_id": finance_dept_id,
        "manager_id": head_dev2_id
    })

    assert response.status_code == 400

    with client.application.app_context():
        from app import Invite
        assert Invite.query.filter_by(email="sneaky@test.com").first() is None


def test_holidays_page_requires_admin_role(client):
    register(client, "Regular Employee2", "regular2@test.com", "pass12345", "Employee")
    login(client, "regular2@test.com", "pass12345")

    response = client.get("/holidays")
    assert response.status_code == 403


def test_admin_can_add_and_view_holidays(client):
    register(client, "HR Admin", "hradmin@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        org = Organization(name="Test Org")
        db.session.add(org)
        db.session.commit()
        org_id = org.id

        admin = User.query.filter_by(email="hradmin@test.com").first()
        admin.role = "Admin"
        admin.organization_id = org_id
        db.session.commit()
    login(client, "hradmin@test.com", "pass12345")

    response = client.post("/holidays", data={
        "date": "2026-08-15",
        "name": "Independence Day"
    })

    assert response.status_code == 200
    assert b"Independence Day" in response.data

    with client.application.app_context():
        from app import Holiday
        saved = Holiday.query.filter_by(name="Independence Day").first()
        assert saved is not None
        assert saved.date == "2026-08-15"
        assert saved.organization_id == org_id


def test_holiday_excluded_from_business_day_count(client):
    register(client, "HR Admin2", "hradmin2@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        org = Organization(name="Test Org 2")
        db.session.add(org)
        db.session.commit()

        admin = User.query.filter_by(email="hradmin2@test.com").first()
        admin.role = "Admin"
        admin.organization_id = org.id
        db.session.commit()
    login(client, "hradmin2@test.com", "pass12345")
    client.post("/holidays", data={
        "date": "2026-08-19",
        "name": "Test Holiday"
    })
    client.get("/logout")

    register(client, "Holiday Tester", "holidaytest@test.com", "pass12345", "Employee")
    login(client, "holidaytest@test.com", "pass12345")

    # Mon Aug 17 -> Wed Aug 19 (2026). Normally 3 business days,
    # but Aug 19 is now a holiday, so it should count as 2.
    response = client.post("/apply", data={
        "leave_type": "Casual",
        "start_date": "2026-08-17",
        "end_date": "2026-08-19",
        "reason": "Testing holiday exclusion"
    }, follow_redirects=True)

    assert b">2<" in response.data


def test_end_date_before_start_date_rejected(client):
    register(client, "Date Tester", "datetest@test.com", "pass12345", "Employee")
    login(client, "datetest@test.com", "pass12345")

    response = client.post("/apply", data={
        "leave_type": "Casual",
        "start_date": "2026-08-10",
        "end_date": "2026-08-05",
        "reason": "Invalid date range"
    })

    assert response.status_code == 400

    with client.application.app_context():
        from app import LeaveRequest
        saved = LeaveRequest.query.filter_by(reason="Invalid date range").first()
        assert saved is None


def test_cannot_invite_with_role_from_different_organization(client):
    register(client, "Some Admin", "someadmin@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization, OrgRole, db
        admin = User.query.filter_by(email="someadmin@test.com").first()
        admin.role = "Admin"
        db.session.commit()

        other_org = Organization(name="Other Org")
        db.session.add(other_org)
        db.session.commit()
        other_role = OrgRole(organization_id=other_org.id, title="Foreign Role", level=2)
        db.session.add(other_role)
        db.session.commit()
        other_role_id = other_role.id

    login(client, "someadmin@test.com", "pass12345")

    response = client.post("/invite", data={
        "name": "Sneaky Employee",
        "email": "sneaky@test.com",
        "org_role_id": other_role_id
    })
    assert response.status_code == 400

    with client.application.app_context():
        from app import Invite
        assert Invite.query.filter_by(email="sneaky@test.com").first() is None


def test_existing_admin_can_promote_another_user(client):
    register(client, "Real Admin", "realadmin@test.com", "pass12345", "Employee")
    with client.application.app_context():
        admin_user = User.query.filter_by(email="realadmin@test.com").first()
        admin_user.role = "Admin"
        db.session.commit()

    register(client, "Future Admin", "futureadmin@test.com", "pass12345", "Employee")
    with client.application.app_context():
        future_admin_id = User.query.filter_by(email="futureadmin@test.com").first().id

    login(client, "realadmin@test.com", "pass12345")
    response = client.post(f"/users/{future_admin_id}/promote-admin")
    assert response.status_code == 302

    with client.application.app_context():
        promoted = db.session.get(User, future_admin_id)
        assert promoted.role == "Admin"


def test_non_admin_cannot_promote_users(client):
    register(client, "Regular User", "regularuser@test.com", "pass12345", "Employee")
    register(client, "Target User", "targetuser@test.com", "pass12345", "Employee")
    with client.application.app_context():
        target_id = User.query.filter_by(email="targetuser@test.com").first().id

    login(client, "regularuser@test.com", "pass12345")
    response = client.post(f"/users/{target_id}/promote-admin")
    assert response.status_code == 403


def test_duplicate_email_registration_rejected(client):
    register(client, "First User", "duplicate@test.com", "pass12345", "Employee")

    response = register(client, "Second User", "duplicate@test.com", "pass12345", "Employee")
    assert response.status_code == 400

    with client.application.app_context():
        matching_users = User.query.filter_by(email="duplicate@test.com").all()
        assert len(matching_users) == 1
        assert matching_users[0].name == "First User"


def test_promote_super_admin_cli(client):
    register(client, "Promote Test", "promotetest@test.com", "pass12345", "Employee")

    runner = client.application.test_cli_runner()
    runner.invoke(args=["promote-super-admin"], input="promotetest@test.com\n")

    with client.application.app_context():
        promoted = User.query.filter_by(email="promotetest@test.com").first()
        assert promoted.is_super_admin is True
        assert promoted.organization_id is None


def test_super_admin_can_create_organization(client):
    register(client, "Super Test", "supertest@test.com", "pass12345", "Employee")
    with client.application.app_context():
        user = User.query.filter_by(email="supertest@test.com").first()
        user.is_super_admin = True
        user.organization_id = None
        db.session.commit()

    login(client, "supertest@test.com", "pass12345")

    response = client.post("/super-admin/organizations/new", data={
        "name": "Acme Corp",
        "industry": "Healthcare",
        "subscription_type": "Monthly",
        "subscription_status": "Trial"
    })

    assert response.status_code == 302

    with client.application.app_context():
        from app import Organization
        org = Organization.query.filter_by(name="Acme Corp").first()
        assert org is not None
        assert org.industry == "Healthcare"
        assert org.subscription_type == "Monthly"


def test_non_super_admin_cannot_create_organization(client):
    register(client, "Regular Admin", "regularadmin@test.com", "pass12345", "Employee")
    with client.application.app_context():
        admin = User.query.filter_by(email="regularadmin@test.com").first()
        admin.role = "Admin"
        db.session.commit()
    login(client, "regularadmin@test.com", "pass12345")

    response = client.post("/super-admin/organizations/new", data={"name": "Sneaky Org"})
    assert response.status_code == 403


def test_super_admin_can_create_org_admin(client):
    register(client, "Super Test2", "supertest2@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        super_user = User.query.filter_by(email="supertest2@test.com").first()
        super_user.is_super_admin = True
        super_user.organization_id = None
        db.session.commit()

        org = Organization(name="Test Org For Admin")
        db.session.add(org)
        db.session.commit()
        org_id = org.id

    login(client, "supertest2@test.com", "pass12345")

    response = client.post("/super-admin/admins/new", data={
        "organization_id": org_id,
        "name": "Org Admin One",
        "email": "orgadmin1@test.com",
        "password": "pass12345",
        "confirm_password": "pass12345"
    })

    assert response.status_code == 302

    with client.application.app_context():
        created_admin = User.query.filter_by(email="orgadmin1@test.com").first()
        assert created_admin is not None
        assert created_admin.role == "Admin"
        assert created_admin.organization_id == org_id


def test_non_super_admin_cannot_create_org_admin(client):
    register(client, "Regular User2", "regularuser2@test.com", "pass12345", "Employee")
    login(client, "regularuser2@test.com", "pass12345")

    response = client.post("/super-admin/admins/new", data={
        "organization_id": 1,
        "name": "Sneaky Admin",
        "email": "sneakyadmin2@test.com",
        "password": "pass12345",
        "confirm_password": "pass12345"
    })
    assert response.status_code == 403


def test_super_admin_can_toggle_organization_active(client):
    register(client, "Super Test3", "supertest3@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        super_user = User.query.filter_by(email="supertest3@test.com").first()
        super_user.is_super_admin = True
        super_user.organization_id = None
        db.session.commit()

        org = Organization(name="Toggle Test Org")
        db.session.add(org)
        db.session.commit()
        org_id = org.id
        assert org.is_active is True

    login(client, "supertest3@test.com", "pass12345")

    response = client.post(f"/super-admin/organizations/{org_id}/toggle-active")
    assert response.status_code == 302

    with client.application.app_context():
        from app import Organization
        toggled_org = db.session.get(Organization, org_id)
        assert toggled_org.is_active is False

    response = client.post(f"/super-admin/organizations/{org_id}/toggle-active")
    assert response.status_code == 302

    with client.application.app_context():
        from app import Organization
        toggled_back = db.session.get(Organization, org_id)
        assert toggled_back.is_active is True


def test_non_super_admin_cannot_toggle_organization_active(client):
    register(client, "Regular User3", "regularuser3@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        org = Organization(name="Protected Org")
        db.session.add(org)
        db.session.commit()
        org_id = org.id

    login(client, "regularuser3@test.com", "pass12345")

    response = client.post(f"/super-admin/organizations/{org_id}/toggle-active")
    assert response.status_code == 403

def test_duplicate_organization_name_rejected_on_create(client):
    register(client, "Super Test5", "supertest5@test.com", "pass12345", "Employee")
    with client.application.app_context():
        user = User.query.filter_by(email="supertest5@test.com").first()
        user.is_super_admin = True
        user.organization_id = None
        db.session.commit()

    login(client, "supertest5@test.com", "pass12345")

    client.post("/super-admin/organizations/new", data={"name": "Duplicate Org"})
    response = client.post("/super-admin/organizations/new", data={"name": "Duplicate Org"})
    assert response.status_code == 400

    with client.application.app_context():
        from app import Organization
        matching = Organization.query.filter_by(name="Duplicate Org").all()
        assert len(matching) == 1


def test_duplicate_organization_name_rejected_on_edit(client):
    register(client, "Super Test6", "supertest6@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        user = User.query.filter_by(email="supertest6@test.com").first()
        user.is_super_admin = True
        user.organization_id = None
        db.session.commit()

        org_a = Organization(name="Org A")
        org_b = Organization(name="Org B")
        db.session.add_all([org_a, org_b])
        db.session.commit()
        org_b_id = org_b.id

    login(client, "supertest6@test.com", "pass12345")

    response = client.post(f"/super-admin/organizations/{org_b_id}/edit", data={"name": "Org A"})
    assert response.status_code == 400

    with client.application.app_context():
        from app import Organization
        unchanged = db.session.get(Organization, org_b_id)
        assert unchanged.name == "Org B"


def test_create_organization_redirects_to_setup(client):
    register(client, "Super Test7", "supertest7@test.com", "pass12345", "Employee")
    with client.application.app_context():
        user = User.query.filter_by(email="supertest7@test.com").first()
        user.is_super_admin = True
        user.organization_id = None
        db.session.commit()

    login(client, "supertest7@test.com", "pass12345")

    response = client.post("/super-admin/organizations/new", data={"name": "Setup Flow Org"})
    assert response.status_code == 302
    assert "/setup" in response.location


def test_super_admin_can_add_and_delete_org_role(client):
    register(client, "Super Test8", "supertest8@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        user = User.query.filter_by(email="supertest8@test.com").first()
        user.is_super_admin = True
        user.organization_id = None
        db.session.commit()

        org = Organization(name="Role Test Org")
        db.session.add(org)
        db.session.commit()
        org_id = org.id

    login(client, "supertest8@test.com", "pass12345")

    response = client.post(f"/super-admin/organizations/{org_id}/roles", data={
        "title": "Team Lead",
        "level": "2"
    })
    assert response.status_code == 302

    with client.application.app_context():
        from app import OrgRole
        role = OrgRole.query.filter_by(organization_id=org_id, title="Team Lead").first()
        assert role is not None
        assert role.level == 2
        role_id = role.id

    response = client.post(f"/super-admin/organizations/{org_id}/roles/{role_id}/delete")
    assert response.status_code == 302

    with client.application.app_context():
        from app import OrgRole
        assert db.session.get(OrgRole, role_id) is None


def test_non_super_admin_cannot_add_org_role(client):
    register(client, "Regular User5", "regularuser5@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        org = Organization(name="Protected Role Org")
        db.session.add(org)
        db.session.commit()
        org_id = org.id

    login(client, "regularuser5@test.com", "pass12345")

    response = client.post(f"/super-admin/organizations/{org_id}/roles", data={
        "title": "Sneaky Role",
        "level": "5"
    })
    assert response.status_code == 403


def test_super_admin_can_add_and_delete_org_practice(client):
    register(client, "Super Test9", "supertest9@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        user = User.query.filter_by(email="supertest9@test.com").first()
        user.is_super_admin = True
        user.organization_id = None
        db.session.commit()

        org = Organization(name="Practice Test Org")
        db.session.add(org)
        db.session.commit()
        org_id = org.id

    login(client, "supertest9@test.com", "pass12345")

    response = client.post(f"/super-admin/organizations/{org_id}/practices", data={"name": "Product"})
    assert response.status_code == 302

    with client.application.app_context():
        from app import OrgPractice
        practice = OrgPractice.query.filter_by(organization_id=org_id, name="Product").first()
        assert practice is not None
        practice_id = practice.id

    response = client.post(f"/super-admin/organizations/{org_id}/practices/{practice_id}/delete")
    assert response.status_code == 302

    with client.application.app_context():
        from app import OrgPractice
        assert db.session.get(OrgPractice, practice_id) is None

def test_non_super_admin_cannot_add_org_practice(client):
    register(client, "Regular User6", "regularuser6@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        org = Organization(name="Protected Practice Org")
        db.session.add(org)
        db.session.commit()
        org_id = org.id

    login(client, "regularuser6@test.com", "pass12345")

    response = client.post(f"/super-admin/organizations/{org_id}/practices", data={"name": "Sneaky Dept"})
    assert response.status_code == 403

def test_super_admin_can_edit_organization(client):
    register(client, "Super Test4", "supertest4@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        super_user = User.query.filter_by(email="supertest4@test.com").first()
        super_user.is_super_admin = True
        super_user.organization_id = None
        db.session.commit()

        org = Organization(name="Edit Test Org", subscription_status="Trial")
        db.session.add(org)
        db.session.commit()
        org_id = org.id

    login(client, "supertest4@test.com", "pass12345")

    response = client.post(f"/super-admin/organizations/{org_id}/edit", data={
        "name": "Edit Test Org",
        "subscription_status": "Active",
        "employee_count": "75"
    })
    assert response.status_code == 302

    with client.application.app_context():
        from app import Organization
        updated_org = db.session.get(Organization, org_id)
        assert updated_org.subscription_status == "Active"
        assert updated_org.employee_count == 75


def test_non_super_admin_cannot_edit_organization(client):
    register(client, "Regular User4", "regularuser4@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization
        org = Organization(name="Protected Edit Org")
        db.session.add(org)
        db.session.commit()
        org_id = org.id

    login(client, "regularuser4@test.com", "pass12345")

    response = client.post(f"/super-admin/organizations/{org_id}/edit", data={"name": "Hacked Name"})
    assert response.status_code == 403


def test_register_with_invalid_token_shows_invalid_page(client):
    response = client.get("/register?invite=not-a-real-token")
    assert response.status_code == 400


def test_register_with_used_invite_rejected(client):
    register(client, "Used Invite Test", "usedinvite@test.com", "pass12345", "Employee")

    with client.application.app_context():
        from app import Invite
        used_invite = Invite.query.filter_by(email="usedinvite@test.com").first()
        token = used_invite.token
        assert used_invite.used is True

    response = client.get(f"/register?invite={token}")
    assert response.status_code == 400


def test_register_with_expired_invite_rejected(client):
    with client.application.app_context():
        from app import Organization, OrgRole, Invite, db
        from datetime import datetime, timedelta
        import secrets as secrets_module

        org = Organization(name="Expired Test Org")
        db.session.add(org)
        db.session.commit()

        expired_role = OrgRole(organization_id=org.id, title="Employee", level=1)
        db.session.add(expired_role)
        db.session.commit()

        expired_token = secrets_module.token_urlsafe(16)
        expired_invite = Invite(
            token=expired_token,
            organization_id=org.id,
            expires_at=datetime.utcnow() - timedelta(days=1),
            name="Expired Test",
            email="expiredtest@test.com",
            org_role_id=expired_role.id
        )
        db.session.add(expired_invite)
        db.session.commit()

    response = client.get(f"/register?invite={expired_token}")
    assert response.status_code == 400

def test_invite_creation_works_even_without_email_configured(client):
    register(client, "Email Test Admin", "emailtestadmin@test.com", "pass12345", "Employee")
    with client.application.app_context():
        from app import Organization, OrgRole
        admin = User.query.filter_by(email="emailtestadmin@test.com").first()
        admin.role = "Admin"
        db.session.commit()

        org = Organization.query.get(admin.organization_id)
        test_role = OrgRole(organization_id=org.id, title="Test Role", level=1)
        db.session.add(test_role)
        db.session.commit()
        role_id = test_role.id

    login(client, "emailtestadmin@test.com", "pass12345")

    response = client.post("/invite", data={
        "name": "New Hire",
        "email": "newhire@test.com",
        "org_role_id": role_id
    })

    assert response.status_code == 200
    assert b"Invite link created" in response.data

    with client.application.app_context():
        from app import Invite
        invite = Invite.query.filter_by(email="newhire@test.com").first()
        assert invite is not None