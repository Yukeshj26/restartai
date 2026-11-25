"""Centralized settings loaded from environment variables."""
import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

# Load .env at project root
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT_DIR / ".env")


def _val(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # Telephony
    call_e_mode: str
    calle_api_key: str
    calle_base_url: str
    poll_interval_seconds: float
    poll_timeout_seconds: int

    # Server
    app_host: str
    app_port: int
    log_level: str

    # Database
    db_path: Path

    # LLM Settings
    llm_provider: str
    gemini_api_key: str
    gemini_model: str
    groq_api_key: str
    groq_model: str
    anthropic_api_key: str
    anthropic_model: str
    grok_api_key: str
    grok_model: str

    @property
    def live(self) -> bool:
        return self.call_e_mode == "live"


def load_settings() -> Settings:
    mode = _val("CALL_E_MODE", "demo").lower()
    data_dir = ROOT_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    db_file = Path(_val("DB_PATH", str(data_dir / "restartai.db")))

    return Settings(
        call_e_mode=mode,
        calle_api_key=_val("CALLE_API_KEY"),
        calle_base_url=_val("CALLE_BASE_URL", "https://api.heycall-e.com").rstrip("/"),
        poll_interval_seconds=max(0.5, float(_val("CALLE_POLL_INTERVAL_SECONDS", "2"))),
        poll_timeout_seconds=max(1, int(float(_val("CALLE_POLL_TIMEOUT_SECONDS", "300")))),
        app_host=_val("APP_HOST", "127.0.0.1"),
        app_port=int(_val("APP_PORT", "8000")),
        log_level=_val("LOG_LEVEL", "INFO"),
        db_path=db_file,
        llm_provider=_val("LLM_PROVIDER", ""),
        gemini_api_key=_val("GEMINI_API_KEY"),
        gemini_model=_val("GEMINI_MODEL", "gemini-2.5-flash"),
        groq_api_key=_val("GROQ_API_KEY"),
        groq_model=_val("GROQ_MODEL", "llama-3.3-70b-versatile"),
        anthropic_api_key=_val("ANTHROPIC_API_KEY"),
        anthropic_model=_val("ANTHROPIC_MODEL", "claude-sonnet-5"),
        grok_api_key=_val("GROK_API_KEY"),
        grok_model=_val("GROK_MODEL", "grok-4.1-fast"),
    )


settings = load_settings()
