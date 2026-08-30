from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_container_trusts_render_forwarding_proxy_for_client_rate_limits() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "--proxy-headers" in dockerfile
    assert "--forwarded-allow-ips='*'" in dockerfile


def test_render_routes_health_checks_to_dependency_free_liveness() -> None:
    blueprint = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "healthCheckPath: /health" in blueprint
    assert "healthCheckPath: /health/ready" not in blueprint


def test_live_smoke_configures_openrouter_model_without_a_secret() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "live-smoke.yml").read_text(encoding="utf-8")
    assert "nvidia/nemotron-3-super-120b-a12b:free" in workflow
    assert "secrets.OPENROUTER_MODEL" not in workflow


def test_live_smoke_runs_migrations_and_release_checks_from_release_image() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "live-smoke.yml").read_text(encoding="utf-8")
    assert "docker build --tag agent-ops-backend:live ." in workflow
    assert "agent-ops-backend:live\n          python -m scripts.migrate" in workflow
    assert "agent-ops-backend:live\n          python -m scripts.release_check" in workflow
