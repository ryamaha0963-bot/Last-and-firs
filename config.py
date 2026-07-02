from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Railway uses environment variables directly
load_dotenv()

@dataclass
class Config:
    api_id: int
    api_hash: str
    bot_token: str
    session_string: str
    admin_id: int | None
    max_duration: int = 600
    max_threads: int = 200  # Railway VPS limit
    scan_limit: int = 50
    scan_cooldown: int = 5

    @classmethod
    def from_env(cls):
        required = ["API_ID", "API_HASH", "BOT_TOKEN", "SESSION_STRING"]
        missing = [k for k in required if not os.getenv(k)]
        if missing:
            raise ValueError(f"Missing required env vars: {missing}")
        
        return cls(
            api_id=int(os.getenv("API_ID")),
            api_hash=os.getenv("API_HASH"),
            bot_token=os.getenv("BOT_TOKEN"),
            session_string=os.getenv("SESSION_STRING"),
            admin_id=int(os.getenv("ADMIN_ID")) if os.getenv("ADMIN_ID") else None,
            max_duration=min(int(os.getenv("MAX_DURATION", "300")), 600),
            max_threads=min(int(os.getenv("MAX_THREADS", "150")), 300),
            scan_limit=max(1, min(int(os.getenv("SCAN_LIMIT", "30")), 100)),
            scan_cooldown=int(os.getenv("SCAN_COOLDOWN", "5"))
        )
