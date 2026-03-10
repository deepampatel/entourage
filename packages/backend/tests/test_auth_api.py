"""Phase 9: Auth + Multi-Tenant tests.

Learn: Tests cover:
1. User registration + duplicate prevention
2. Login → JWT tokens
3. Token refresh
4. Protected /me endpoint
5. API key creation, listing, revocation
6. API key authentication
"""

import uuid

import pytest


# ═══════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_register_user(client):
    """Register a new user account."""
    email = f"test-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "name": "Test User",
            "password": "secure_password_123",
        },
    )
    assert r.status_code == 201
    user = r.json()
    assert user["email"] == email
    assert user["name"] == "Test User"
    assert "id" in user


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    """Can't register with the same email twice."""
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    body = {
        "email": email,
        "name": "User 1",
        "password": "password_123",
    }

    r1 = await client.post("/api/v1/auth/register", json=body)
    assert r1.status_code == 201

    r2 = await client.post("/api/v1/auth/register", json=body)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_register_short_password(client):
    """Password must be at least 8 characters."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"short-{uuid.uuid4().hex[:8]}@example.com",
            "name": "Short",
            "password": "abc",
        },
    )
    assert r.status_code == 422  # validation error


# ═══════════════════════════════════════════════════════════
# Login
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_login_success(client):
    """Login with valid credentials returns tokens."""
    email = f"login-{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Login User", "password": "my_password_123"},
    )

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "my_password_123"},
    )
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    """Login with wrong password returns 401."""
    email = f"wrong-{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "User", "password": "correct_password"},
    )

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong_password"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client):
    """Login with nonexistent email returns 401."""
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever"},
    )
    assert r.status_code == 401


# ═══════════════════════════════════════════════════════════
# Token Refresh
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_refresh_token(client):
    """Refresh token returns new access + refresh tokens."""
    email = f"refresh-{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "User", "password": "password_123"},
    )
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password_123"},
    )
    refresh = r.json()["refresh_token"]

    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh},
    )
    assert r.status_code == 200
    assert "access_token" in r.json()
    assert "refresh_token" in r.json()


@pytest.mark.asyncio
async def test_refresh_with_access_token_fails(client):
    """Can't use access token as refresh token."""
    email = f"badref-{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "User", "password": "password_123"},
    )
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password_123"},
    )
    access = r.json()["access_token"]

    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": access},
    )
    assert r.status_code == 401


# ═══════════════════════════════════════════════════════════
# Protected Endpoint (/me)
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_me_with_token(unauthenticated_client):
    """Access /me with valid JWT token.

    Learn: Uses unauthenticated_client so the real JWT auth flow runs
    (no get_current_user mock override). This tests the full flow:
    register → login → use JWT → /me returns user info.
    """
    email = f"me-{uuid.uuid4().hex[:8]}@example.com"
    await unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Me User", "password": "password_123"},
    )
    r = await unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password_123"},
    )
    token = r.json()["access_token"]

    r = await unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == email
    assert r.json()["type"] == "user"


@pytest.mark.asyncio
async def test_me_without_token(unauthenticated_client):
    """Access /me without token returns 401."""
    r = await unauthenticated_client.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_with_invalid_token(unauthenticated_client):
    """Access /me with invalid token returns 401."""
    r = await unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid_token_here"},
    )
    assert r.status_code == 401


# ═══════════════════════════════════════════════════════════
# API Keys
# ═══════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_api_key(client):
    """Create an API key for an org."""
    slug = f"apikey-{uuid.uuid4().hex[:8]}"
    r = await client.post("/api/v1/orgs", json={"name": "Key Org", "slug": slug})
    org_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/auth/orgs/{org_id}/api-keys",
        json={"name": "Test Key", "scopes": ["all"]},
    )
    assert r.status_code == 201
    key = r.json()
    assert key["name"] == "Test Key"
    assert key["key"].startswith("oc_")
    assert key["prefix"] == key["key"][:10]


@pytest.mark.asyncio
async def test_list_api_keys(client):
    """List API keys for an org (without actual key values)."""
    slug = f"listkeys-{uuid.uuid4().hex[:8]}"
    r = await client.post("/api/v1/orgs", json={"name": "List Keys Org", "slug": slug})
    org_id = r.json()["id"]

    # Create 2 keys
    await client.post(
        f"/api/v1/auth/orgs/{org_id}/api-keys",
        json={"name": "Key 1"},
    )
    await client.post(
        f"/api/v1/auth/orgs/{org_id}/api-keys",
        json={"name": "Key 2"},
    )

    r = await client.get(f"/api/v1/auth/orgs/{org_id}/api-keys")
    assert r.status_code == 200
    keys = r.json()
    assert len(keys) == 2
    # Keys should NOT contain the actual key value
    for k in keys:
        assert "key" not in k or k.get("key") is None


@pytest.mark.asyncio
async def test_revoke_api_key(client):
    """Revoke an API key."""
    slug = f"revoke-{uuid.uuid4().hex[:8]}"
    r = await client.post("/api/v1/orgs", json={"name": "Revoke Org", "slug": slug})
    org_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/auth/orgs/{org_id}/api-keys",
        json={"name": "Revokable Key"},
    )
    key_id = r.json()["id"]

    r = await client.delete(f"/api/v1/auth/api-keys/{key_id}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    # Verify it's gone
    r = await client.get(f"/api/v1/auth/orgs/{org_id}/api-keys")
    assert len(r.json()) == 0


@pytest.mark.asyncio
async def test_api_key_auth(unauthenticated_client):
    """Authenticate with API key via x-api-key header.

    Learn: Uses unauthenticated_client so the real auth flow runs.
    First registers+logs in a user to get a JWT (needed for protected
    org creation). Then creates an API key and verifies /me works with it.
    """
    # Bootstrap: register + login to get JWT for org creation
    email = f"apiauth-{uuid.uuid4().hex[:8]}@example.com"
    await unauthenticated_client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Key User", "password": "password_123"},
    )
    r = await unauthenticated_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password_123"},
    )
    token = r.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Create org (protected route — needs JWT)
    slug = f"auth-{uuid.uuid4().hex[:8]}"
    r = await unauthenticated_client.post(
        "/api/v1/orgs", json={"name": "Auth Org", "slug": slug},
        headers=auth_headers,
    )
    org_id = r.json()["id"]

    # Create API key (auth router — open)
    r = await unauthenticated_client.post(
        f"/api/v1/auth/orgs/{org_id}/api-keys",
        json={"name": "Auth Key"},
    )
    api_key = r.json()["key"]

    # Test: /me with API key
    r = await unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"x-api-key": api_key},
    )
    assert r.status_code == 200
    assert r.json()["type"] == "api_key"
    assert r.json()["org_id"] == org_id


@pytest.mark.asyncio
async def test_api_key_invalid(unauthenticated_client):
    """Invalid API key returns 401."""
    r = await unauthenticated_client.get(
        "/api/v1/auth/me",
        headers={"x-api-key": "oc_invalid_key_12345"},
    )
    assert r.status_code == 401
