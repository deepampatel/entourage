"""
Shared helpers for Entourage examples.

Handles authentication (register + login) and workspace setup
so each example can focus on its specific workflow.
"""

from __future__ import annotations

import sys
import uuid

import httpx

BASE = "http://localhost:8000/api/v1"


def check_backend() -> None:
    """Verify the backend is reachable and healthy."""
    try:
        resp = httpx.get(f"{BASE}/health", timeout=5)
    except httpx.ConnectError:
        print(f"ERROR: Backend not reachable at {BASE}")
        print("Start it with:  cd packages/backend && uv run uvicorn openclaw.main:app --reload --port 8000")
        sys.exit(1)

    if resp.status_code != 200:
        print(f"ERROR: Health check returned {resp.status_code}")
        sys.exit(1)

    health = resp.json()
    print("Backend health:")
    print(f"  Postgres: {'✓' if health['postgres'] else '✗'}")
    print(f"  Redis:    {'✓' if health['redis'] else '✗'}")

    if not health["postgres"]:
        print("\nERROR: Postgres is not connected. Start it with: docker compose up -d")
        sys.exit(1)


def authenticate() -> str:
    """Register a fresh user and login, returning an access token.

    Uses a unique email per run so examples are idempotent.
    """
    run_id = uuid.uuid4().hex[:8]
    email = f"demo-{run_id}@example.com"
    password = "demo-password-123"

    # Register
    resp = httpx.post(
        f"{BASE}/auth/register",
        json={"email": email, "name": f"Demo User {run_id}", "password": password},
        timeout=10,
    )
    if resp.status_code not in (201, 409):  # 409 = already exists
        print(f"ERROR: Registration failed: {resp.status_code} {resp.text}")
        sys.exit(1)

    # Login
    resp = httpx.post(
        f"{BASE}/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"ERROR: Login failed: {resp.status_code} {resp.text}")
        sys.exit(1)

    tokens = resp.json()
    return tokens["access_token"]


def create_client() -> httpx.Client:
    """Check backend, authenticate, and return an httpx Client with auth headers."""
    check_backend()
    token = authenticate()
    print(f"  Auth:     ✓ (JWT)")
    return httpx.Client(
        base_url=BASE,
        timeout=10,
        headers={"Authorization": f"Bearer {token}"},
    )


def setup_workspace(
    name: str,
    *,
    engineers: list[dict] | None = None,
    repo: dict | None = None,
) -> dict:
    """Create authenticated client + org + team + optional agents and repo.

    Returns a dict with keys: client, org, team, manager, engineers, repo.
    """
    run_id = uuid.uuid4().hex[:6]
    client = create_client()

    print(f"\nSetting up workspace '{name}'...")

    # Create org
    resp = client.post("/orgs", json={"name": name, "slug": f"{name.lower().replace(' ', '-')}-{run_id}"})
    assert resp.status_code == 201, f"Org creation failed: {resp.text}"
    org = resp.json()

    # Create team
    resp = client.post(f"/orgs/{org['id']}/teams", json={"name": "Engineering", "slug": "engineering"})
    assert resp.status_code == 201, f"Team creation failed: {resp.text}"
    team = resp.json()

    # Get auto-created manager
    agents = client.get(f"/teams/{team['id']}/agents").json()
    manager = agents[0]

    print(f"  Org:     {org['name']} ({org['id'][:8]}...)")
    print(f"  Team:    {team['name']} ({team['id'][:8]}...)")
    print(f"  Manager: {manager['name']} ({manager['role']})")

    result = {
        "client": client,
        "org": org,
        "team": team,
        "manager": manager,
        "engineers": [],
        "repo": None,
    }

    # Create engineer agents
    if engineers:
        for eng_spec in engineers:
            resp = client.post(f"/teams/{team['id']}/agents", json={
                "name": eng_spec["name"],
                "role": eng_spec.get("role", "engineer"),
                "model": eng_spec.get("model", "claude-sonnet-4-20250514"),
                "config": {"description": eng_spec.get("description", "Engineer")},
            })
            assert resp.status_code == 201, f"Agent creation failed: {resp.text}"
            agent = resp.json()
            result["engineers"].append(agent)
            print(f"  Agent:   {agent['name']} ({agent['id'][:8]}...)")

    # Register repo
    if repo:
        resp = client.post(f"/teams/{team['id']}/repos", json={
            "name": repo["name"],
            "clone_url": repo.get("clone_url", f"https://github.com/example/{repo['name']}.git"),
            "default_branch": repo.get("default_branch", "main"),
            "local_path": repo.get("local_path", f"/tmp/{repo['name']}"),
        })
        assert resp.status_code == 201, f"Repo creation failed: {resp.text}"
        result["repo"] = resp.json()
        print(f"  Repo:    {result['repo']['name']}")

    return result
