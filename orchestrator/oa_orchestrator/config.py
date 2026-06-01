"""Runtime configuration, sourced from environment / orchestrator/.env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# orchestrator/oa_orchestrator/config.py -> repo root is parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = REPO_ROOT / ".runtime" / "orchestrator"


def _load_dotenv() -> None:
    """Load orchestrator/.env if python-dotenv is present (optional)."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    env_path = ORCHESTRATOR_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path)


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    node_base_url: str
    executor: str
    oa_platform: str
    deepseek_api_key: str
    deepseek_model: str
    deepseek_base_url: str
    max_retries: int
    runtime_dir: Path

    @property
    def store_path(self) -> Path:
        return self.runtime_dir / "store.sqlite"

    @property
    def checkpoint_path(self) -> Path:
        return self.runtime_dir / "checkpoints.sqlite"

    def ensure_runtime_dir(self) -> Path:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        return self.runtime_dir


def get_settings() -> Settings:
    """Read environment at call time (so CLI/env overrides take effect)."""
    return Settings(
        node_base_url=os.getenv("NODE_BASE_URL", "http://127.0.0.1:8787"),
        executor=os.getenv("EXECUTOR", "http-node"),
        oa_platform=os.getenv("OA_PLATFORM", "mac"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        max_retries=int(os.getenv("MAX_RETRIES", "2")),
        runtime_dir=RUNTIME_DIR,
    )
