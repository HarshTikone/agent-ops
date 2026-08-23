"""Tests for the liveness/readiness endpoints.

These are deliberately real tests, not placeholders: readiness is the
mechanism that turns "GEMINI_API_KEY was never set on the deploy target"
from a silent downstream 500 (Day 2+) into a loud, immediate, correctly-
reported failure — so the test asserts both the healthy and the unhealthy
shape of that response.
"""


def test_liveness_always_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_not_ready_when_nothing_configured(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"] == {
        "gemini_api_key_set": False,
        "openrouter_api_key_set": False,
        "supabase_configured": False,
        "database_configured": False,
    }


def test_readiness_ready_when_fully_configured(make_client):
    client = make_client(
        gemini_api_key="test-key",
        openrouter_api_key="test-key",
        supabase_url="https://example.supabase.co",
        supabase_secret_key="sb_secret_test",
        database_url="postgresql://user:pass@localhost:5432/db",
    )
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert all(body["checks"].values())


def test_readiness_partial_config_is_not_ready(make_client):
    """A common real misconfiguration: Gemini key set, Supabase forgotten.

    This is the shown failure mode for the config-loading feature area: a
    partially-configured deploy must report exactly which piece is missing,
    not just a blanket "ready"/"not ready" with no way to tell why.
    """
    client = make_client(gemini_api_key="test-key")
    response = client.get("/health/ready")
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["gemini_api_key_set"] is True
    assert body["checks"]["supabase_configured"] is False


def test_readiness_degraded_when_openrouter_missing_but_can_serve(make_client):
    """Per ADR-009: Gemini + Supabase + database present but no OpenRouter
    key means the system can serve every request — it just has no failover
    if Gemini has an outage mid-session. That's "degraded", not "not_ready":
    conflating "can't serve" with "no safety net" would make every demo
    deploy report broken over a resilience feature that hasn't fired yet.
    """
    client = make_client(
        gemini_api_key="test-key",
        supabase_url="https://example.supabase.co",
        supabase_secret_key="sb_secret_test",
        database_url="postgresql://user:pass@localhost:5432/db",
    )
    response = client.get("/health/ready")
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["openrouter_api_key_set"] is False


def test_readiness_not_ready_when_only_openrouter_key_present(make_client):
    """The other direction of ADR-009's split: OpenRouter is a fallback that
    (per ADR-002) only fires on a Gemini timeout/5xx/rate-limit — never on a
    missing/invalid Gemini key, which is deliberately NOT caught as a
    failover trigger. So an OpenRouter key with no Gemini key cannot serve
    anything either; this must stay "not_ready", not "degraded".
    """
    client = make_client(
        openrouter_api_key="test-key",
        supabase_url="https://example.supabase.co",
        supabase_secret_key="sb_secret_test",
        database_url="postgresql://user:pass@localhost:5432/db",
    )
    response = client.get("/health/ready")
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["gemini_api_key_set"] is False
    assert body["checks"]["openrouter_api_key_set"] is True


def test_root_lists_docs_url(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"
