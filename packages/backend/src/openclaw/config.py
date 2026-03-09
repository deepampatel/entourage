"""Application configuration via environment variables.

Uses pydantic-settings to load config from env vars with OPENCLAW_ prefix.
No YAML files, no file-based config — just env vars (12-factor app style).

Learn: pydantic-settings auto-loads from environment, validates types,
provides defaults. Much cleaner than Delegate's YAML config.py.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All app configuration. Set via OPENCLAW_* env vars."""

    # Database
    database_url: str = (
        "postgresql+asyncpg://openclaw:openclaw_dev@localhost:5433/openclaw"
    )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Anthropic API (for built-in agent runner)
    anthropic_api_key: str = ""

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # Server
    environment: str = "development"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # Rate limiting
    rate_limit_rpm: int = 100  # requests per minute per IP
    rate_limit_auth_rpm: int = 10  # stricter limit for auth endpoints

    # Agent defaults
    default_agent_model: str = "claude-sonnet-4-20250514"
    max_concurrent_agents: int = 32

    # Agent adapter settings
    default_adapter: str = "claude_code"
    mcp_server_path: str = ""  # auto-detected if empty
    agent_timeout_seconds: int = 1800  # 30 min default

    # Pipeline execution
    max_concurrent_pipeline_tasks: int = 4
    task_polling_interval_seconds: float = 10.0
    max_task_retries: int = 2

    # Agent memory + context
    context_rotation_threshold_tokens: int = 150_000
    enable_convention_discovery: bool = True
    enable_agent_memory: bool = True

    model_config = {"env_prefix": "OPENCLAW_"}

    @model_validator(mode="after")
    def validate_production_settings(self):
        """Ensure sensitive defaults are changed in non-development environments."""
        if (
            self.environment != "development"
            and self.jwt_secret == "change-me-in-production"
        ):
            raise ValueError(
                "OPENCLAW_JWT_SECRET must be set to a secure value in "
                "non-development environments. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return self


# Singleton — import this everywhere
settings = Settings()
