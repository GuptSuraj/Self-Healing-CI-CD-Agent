from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SHCA_", extra="ignore")

    env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "sqlite:///./self_healing.db"
    redis_url: str = "redis://localhost:6379/0"
    github_api_url: str = "https://api.github.com"
    github_web_url: str = "https://github.com"
    github_app_id: str = "local-dev"
    github_installation_id: str | None = None
    github_private_key: str | None = None
    github_webhook_secret: str = "local-secret"
    github_probe_timeout_seconds: float = 15.0
    github_context_file_limit: int = 5
    github_context_snippet_chars: int = 4000
    github_log_excerpt_chars: int = 6000
    github_writeback_max_retries: int = 3
    allowed_repositories: str = "*"
    blocked_categories: str = "flaky,unsupported"
    allowed_patch_generation_sources: str = "deterministic,llm"
    protected_paths: str = ".github/secrets,infra/prod,terraform/prod"
    max_changed_files: int = 3
    max_changed_lines: int = 80
    min_confidence_for_pr: float = 0.85
    min_confidence_for_draft_pr: float = 0.65
    require_known_fixer_for_pr: bool = False
    validation_timeout_seconds: int = 900
    sandbox_image_name: str = "self-healing-sandbox"
    enable_validation_execution: bool = False
    enable_validation_repo_sync: bool = False
    validation_checkout_root: str = "./.cache/validation_repos"
    enable_github_writeback: bool = False
    enable_llm_patch_generation: bool = False
    llm_patch_provider: str = "openai"
    llm_patch_model: str = "gpt-4.1-mini"
    llm_patch_max_context_chars: int = 12000
    llm_patch_temperature: float = 0.1
    openai_api_key: str | None = None
    openai_api_base_url: str = "https://api.openai.com/v1"
    run_db_migrations_on_startup: bool = False
    worker_max_attempts: int = 3
    worker_poll_interval_seconds: float = 2.0
    artifact_storage_path: str = "./artifacts"


settings = Settings()
