"""Release API runtime settings (NFR-03, NFR-09).

Loaded from environment variables only (no .env files); in deployed environments the platform populates them from the
approved secret provider. MYSQL_PASSWORD is required, has no default and is held as a SecretStr so it is masked in
repr/str/serialization; validation errors never echo input values.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_env: str = "dev"
    log_level: str = "INFO"
    mysql_host: str | None = None
    mysql_port: int = 3306
    mysql_database: str | None = None
    mysql_user: str | None = None
    mysql_password: SecretStr
