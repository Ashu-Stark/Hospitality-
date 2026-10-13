from conftest import auth


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_requires_token(client):
    assert client.get("/workspace").status_code == 401
    assert client.get("/workspace", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_password_login_and_lockout(client, platform):
    t = client.post("/platform/tenants", json={"name": "Lockout Hotel"}, headers=platform).json()
    code = t["owner_invite"]["code"]
    r = client.post("/auth/register", json={"code": code, "username": "lock.owner", "password": "correct-horse"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "owner"
    assert client.post("/auth/register", json={"code": code, "username": "x2", "password": "123456"}).status_code == 422  # single use
    assert client.post("/auth/login", json={"username": "lock.owner", "password": "correct-horse"}).status_code == 200
    for _ in range(5):
        r = client.post("/auth/login", json={"username": "lock.owner", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/auth/login", json={"username": "lock.owner", "password": "correct-horse"})
    assert r.status_code == 401 and "Too many" in r.json()["detail"]
    unknown = client.post("/auth/login", json={"username": "nobody", "password": "wrong"}).json()["detail"]
    assert unknown == "Wrong username or password."  # same message: no account enumeration


def test_worker_invite_needs_employee_id(client, owner):
    code = client.post("/workspace/invites", json={"role": "worker"}, headers=owner).json()["code"]
    r = client.post("/auth/register", json={"code": code, "username": "w.new", "password": "123456"})
    assert r.status_code == 422
    r = client.post("/auth/register", json={"code": code, "username": "w.new", "password": "123456", "employee_id": "e555"})
    assert r.status_code == 200 and r.json()["user"]["employee_id"] == "E555"


def test_role_guards(client, hr, worker, store, owner):
    assert client.get("/inventory/items", headers=hr).status_code == 403
    assert client.get("/workspace/users", headers=store).status_code == 403
    assert client.get("/platform/tenants", headers=owner).status_code == 403
    assert client.post("/dispatch/jobs", json={"title": "x"}, headers=worker).status_code == 403
    assert client.post("/inventory/pos", json={"supplier_id": "s", "lines": {}}, headers=worker).status_code == 403


def test_tenant_isolation_and_suspension(client, platform, owner):
    created = client.post(
        "/platform/tenants", json={"name": "Other Group", "first_property": "Ridge", "rooms": 20}, headers=platform
    ).json()
    other_id = created["tenant"]["id"]
    code = created["owner_invite"]["code"]
    other = client.post("/auth/register", json={"code": code, "username": "other.owner", "password": "pass1234"}).json()
    oh = {"Authorization": f"Bearer {other['token']}"}
    # the demo owner's data is invisible to the other tenant
    demo_items = client.get("/inventory/items", headers=owner).json()
    assert demo_items and client.get("/inventory/items", headers=oh).json() == []
    # and cannot be touched by id
    r = client.post("/inventory/issue", json={"item_id": demo_items[0]["id"], "location_id": "x", "qty": 1}, headers=oh)
    assert r.status_code == 422
    # suspension blocks sign-in and existing sessions
    assert client.patch(f"/platform/tenants/{other_id}", json={"status": "suspended"}, headers=platform).status_code == 200
    assert client.get("/workspace", headers=oh).status_code == 403
    assert client.post("/auth/login", json={"username": "other.owner", "password": "pass1234"}).status_code == 401


def test_impersonation_is_scoped_and_audited(client, platform):
    r = client.post("/auth/impersonate/org_demo", headers=platform)
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/workspace", headers=h).json()["id"] == "org_demo"
    log = client.get("/platform/audit?tenant_id=org_demo", headers=platform).json()
    assert any(e["action"] == "platform.open_workspace" for e in log)


def test_privacy_guard_on_staff_import(client, owner):
    r = client.post(
        "/workspace/staff/import", json={"rows": [{"employee_id": "S1", "department": "kitchen", "full_name": "X"}]}, headers=owner
    )
    assert r.status_code == 422 and "personal" in r.json()["detail"]
    r = client.post("/workspace/staff/import", json={"rows": [{"employee_id": "s1", "department": "Front Office"}]}, headers=owner)
    assert r.status_code == 200
    assert any(s["employee_id"] == "S1" and s["department"] == "front_office" for s in client.get("/workspace/staff", headers=owner).json())


def test_cannot_disable_self(client, owner):
    me = client.get("/auth/me", headers=owner).json()["user"]
    assert client.patch(f"/workspace/users/{me['id']}", json={"active": False}, headers=owner).status_code == 422


def test_demo_login_unknown_user_404(client):
    assert client.post("/auth/demo/not-a-demo-user").status_code == 404
    assert auth(client, "demo.store")
