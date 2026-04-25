from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "Agent-Pilot Backend"
    DEBUG: bool = True
    MOCK_MODE: bool = True

    DATABASE_URL: str = "sqlite+aiosqlite:///./data/agent_pilot.db"

    # LLM Configuration - MiniMax
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.minimaxi.com/v1"
    LLM_MODEL: str = "abab6.5s-chat"

    # Rocket.Chat Configuration
    ROCKET_CHAT_URL: Optional[str] = None
    ROCKET_CHAT_USER: Optional[str] = None
    ROCKET_CHAT_PASSWORD: Optional[str] = None

    # AFFiNE Configuration
    AFFINE_URL: Optional[str] = None
    AFFINE_TOKEN: Optional[str] = None

    # Lark Configuration
    LARK_APP_ID: Optional[str] = None
    LARK_APP_SECRET: Optional[str] = None
    # 飞书 CLI 默认关闭，避免未安装或未登录时影响本地 Demo 主流程。
    LARK_CLI_ENABLED: bool = False
    # 允许通过环境变量指定 lark-cli 的完整路径，便于 Windows 上定位全局 npm 命令。
    LARK_CLI_BIN: str = "lark-cli"
    # CLI 默认使用用户授权身份；如后续切应用身份，只改配置不改调用层。
    LARK_CLI_AS: str = "user"
    # 群消息通知是可选能力，没有配置 chat_id 时只同步文件/文档。
    LARK_DEFAULT_CHAT_ID: Optional[str] = None
    # 外部 CLI 调用必须有超时，避免请求线程被飞书授权或网络问题长期挂住。
    LARK_CLI_TIMEOUT_SECONDS: int = 30

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
