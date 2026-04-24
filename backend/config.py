from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "Agent-Pilot Backend"
    DEBUG: bool = True
    MOCK_MODE: bool = True

    DATABASE_URL: str = "sqlite+aiosqlite:///./data/agent_pilot.db"

    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4"

    LARK_APP_ID: Optional[str] = None
    LARK_APP_SECRET: Optional[str] = None

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
        env_file = ".env"
        extra = "allow"


settings = Settings()
