from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"

PLATFORM_LABELS = {"baemin": "배달의민족", "coupangeats": "쿠팡이츠"}


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")


@dataclass
class Account:
    platform: str
    name: str
    env_prefix: str
    reviews_url: str | None = None

    @property
    def label(self) -> str:
        return f"{PLATFORM_LABELS.get(self.platform, self.platform)}/{self.name}"

    @property
    def session_dir(self) -> Path:
        return DATA_DIR / "sessions" / self.env_prefix.lower()

    def credentials(self) -> tuple[str, str] | None:
        user = os.environ.get(f"{self.env_prefix}_ID", "").strip()
        pw = os.environ.get(f"{self.env_prefix}_PW", "").strip()
        return (user, pw) if user and pw else None


@dataclass
class Settings:
    raw: dict

    @classmethod
    def load(cls) -> "Settings":
        return cls(load_yaml("settings.yaml"))

    @property
    def accounts(self) -> list[Account]:
        return [Account(**a) for a in self.raw.get("accounts", [])]

    @property
    def dry_run(self) -> bool:
        return bool(self.raw.get("dry_run", True))

    @property
    def headless(self) -> bool:
        return bool(self.raw.get("headless", False))

    @property
    def max_replies(self) -> int:
        return int(self.raw.get("max_replies_per_account", 50))

    @property
    def delay_range(self) -> tuple[float, float]:
        lo, hi = self.raw.get("delay_seconds", [2, 5])
        return float(lo), float(hi)

    @property
    def schedule_time(self) -> str:
        return str(self.raw.get("schedule_time", "08:30"))

    def folder(self, key: str) -> Path:
        return ROOT / self.raw["folders"][key]

    def find_accounts(self, name: str | None) -> list[Account]:
        if not name:
            return self.accounts
        return [a for a in self.accounts if name in (a.name, a.env_prefix)]


def save_schedule_time(value: str) -> None:
    """settings.yaml 의 주석을 보존한 채 schedule_time 한 줄만 바꾼다."""
    path = CONFIG_DIR / "settings.yaml"
    text = path.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'^schedule_time:.*$', f'schedule_time: "{value}"', text, count=1, flags=re.M
    )
    if n == 0:
        new_text = f'schedule_time: "{value}"\n' + text
    path.write_text(new_text, encoding="utf-8")
