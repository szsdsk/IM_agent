from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Agent-Pilot Backend"
    DEBUG: bool = True
    MOCK_MODE: bool = True

    DATABASE_URL: str = "sqlite+aiosqlite:///./data/agent_pilot.db"

    # LLM Configuration - MiniMax
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.minimaxi.com/v1"
    LLM_MODEL: str = "abab6.5s-chat"

    # IM provider selector. The current demo defaults to Feishu/Lark bot events.
    IM_PROVIDER: str = "lark"

    # Rocket.Chat Configuration
    ROCKET_CHAT_URL: Optional[str] = None
    ROCKET_CHAT_USER: Optional[str] = None
    ROCKET_CHAT_PASSWORD: Optional[str] = None

    # AFFiNE Configuration
    AFFINE_URL: Optional[str] = None
    AFFINE_TOKEN: Optional[str] = None

    # Lark / Feishu OpenAPI configuration for bot message receive/send and file delivery.
    LARK_APP_ID: Optional[str] = None
    LARK_APP_SECRET: Optional[str] = None
    LARK_VERIFICATION_TOKEN: Optional[str] = None
    LARK_BOT_ENABLED: bool = True
    LARK_BOT_REQUIRE_MENTION: bool = True
    LARK_DEFAULT_CHAT_ID: Optional[str] = None

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
        return value

    class Config:
        env_file = (".env", "backend/.env")
        extra = "allow"


settings = Settings()
