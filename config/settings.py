from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal


class Settings(BaseSettings):
    # AI
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-sonnet-4-6")
    openai_compatible_base_url: str = Field(default="https://api.openai.com/v1")
    openai_compatible_api_key: str = Field(default="")
    openai_compatible_model: str = Field(default="gpt-4o")
    ai_primary_provider: Literal["anthropic", "openai"] = Field(default="anthropic")

    # LinkedIn
    linkedin_client_id: str = Field(default="")
    linkedin_client_secret: str = Field(default="")
    linkedin_access_token: str = Field(default="")
    linkedin_organization_id: str = Field(default="")

    # Facebook / Instagram
    facebook_app_id: str = Field(default="")
    facebook_app_secret: str = Field(default="")
    facebook_access_token: str = Field(default="")
    facebook_page_id: str = Field(default="")
    instagram_business_account_id: str = Field(default="")

    # Web search
    tavily_api_key: str = Field(default="")

    # Dashboard
    dashboard_host: str = Field(default="127.0.0.1")
    dashboard_port: int = Field(default=8000)
    dashboard_secret_key: str = Field(default="change_this_secret_key")
    dashboard_password: str = Field(default="")

    # Database
    database_url: str = Field(default="sqlite:///./storage/social_manager.db")

    # Scheduling
    linkedin_post_times: str = Field(default="09:00,12:00,17:00")
    facebook_post_times: str = Field(default="10:00,14:00,19:00")
    instagram_post_times: str = Field(default="08:00,13:00,18:00")

    # Monitoring
    monitor_interval_minutes: int = Field(default=15)
    company_name: str = Field(default="Azienda")
    brand_keywords: str = Field(default="")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def brand_keywords_list(self) -> list[str]:
        return [k.strip() for k in self.brand_keywords.split(",") if k.strip()]


settings = Settings()
