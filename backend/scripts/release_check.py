"""Active, secret-safe release verification for production dependencies.

Unlike `/health/ready`, this command intentionally spends one minimal provider
request. Run it as a one-off with the same image and dashboard environment
before promoting a deployment; it never runs during API startup.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx
from langchain_core.messages import HumanMessage

from app.config import Settings
from app.db import create_db_pool
from app.llm.gemini import GeminiProvider
from app.llm.openrouter import OpenRouterProvider
from app.tools.web_search import WebSearchTool

logger = logging.getLogger("agent_ops.release_check")


def _run_check(name: str, check: Callable[[], None]) -> None:
    try:
        check()
    except Exception as exc:
        # Deliberately log only the exception type. Provider errors frequently
        # embed request headers, URLs, or response bodies that do not belong in
        # a public CI/deployment log.
        logger.error("release_check name=%s status=failed type=%s", name, type(exc).__name__)
        raise RuntimeError(f"release dependency check failed: {name}") from None
    logger.info("release_check name=%s status=passed", name)


def run_release_checks(settings: Settings, *, http_client: httpx.Client | None = None) -> None:
    """Verify every required provider and the optional fallback when present."""
    owned_client = http_client is None
    client = http_client or httpx.Client(timeout=15)
    try:
        _run_check(
            "gemini",
            lambda: GeminiProvider(settings.gemini_api_key, settings.gemini_model).generate(
                [HumanMessage(content="Reply with the single word ready.")]
            ),
        )

        if settings.openrouter_api_key and settings.openrouter_model:
            _run_check(
                "openrouter",
                lambda: OpenRouterProvider(
                    settings.openrouter_api_key, settings.openrouter_model
                ).generate([HumanMessage(content="Reply with the single word ready.")]),
            )
        else:
            logger.info("release_check name=openrouter status=skipped_optional")

        _run_check(
            "tavily",
            lambda: WebSearchTool(settings.tavily_api_key, client=client).run(
                query="OpenAI official website", include_domains=["openai.com"]
            ),
        )

        def verify_supabase() -> None:
            response = client.get(
                f"{settings.supabase_url.rstrip('/')}/rest/v1/",
                headers={
                    "apikey": settings.supabase_secret_key,
                    "Authorization": f"Bearer {settings.supabase_secret_key}",
                },
            )
            response.raise_for_status()

        _run_check("supabase", verify_supabase)

        def verify_database() -> None:
            pool = create_db_pool(settings)
            try:
                pool.open(wait=True, timeout=10)
                with pool.connection(timeout=5) as connection:
                    connection.execute("SELECT 1").fetchone()
            finally:
                pool.close()

        _run_check("database", verify_database)
    finally:
        if owned_client:
            client.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    for noisy_logger in ("google_genai", "httpx", "httpx2"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    settings = Settings()
    required = {
        "GEMINI_API_KEY": settings.gemini_api_key,
        "TAVILY_API_KEY": settings.tavily_api_key,
        "SUPABASE_URL": settings.supabase_url,
        "SUPABASE_SECRET_KEY": settings.supabase_secret_key,
        "DATABASE_URL": settings.database_url,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit(f"release dependency configuration missing: {', '.join(missing)}")
    run_release_checks(settings)


if __name__ == "__main__":
    main()
