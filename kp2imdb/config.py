"""Конфигурация и пути. Читает .env один раз при импорте."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
OUT_DIR = DATA_DIR / "out"
STATE_PATH = DATA_DIR / "storage_state.json"
CACHE_PATH = DATA_DIR / "imdb_cache.json"
UNMATCHED_PATH = DATA_DIR / "unmatched.json"

for d in (DATA_DIR, RAW_DIR, OUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    kp_user_id: str
    kinopoisk_dev_token: str | None
    omdb_api_key: str | None
    headless: bool
    scrape_delay_sec: float
    proxy_url: str | None
    public_mode: bool


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings() -> Settings:
    user_id = os.environ.get("KP_USER_ID", "").strip()
    return Settings(
        kp_user_id=user_id,
        kinopoisk_dev_token=(os.environ.get("KINOPOISK_DEV_TOKEN") or "").strip() or None,
        omdb_api_key=(os.environ.get("OMDB_API_KEY") or "").strip() or None,
        headless=_as_bool(os.environ.get("HEADLESS"), default=False),
        scrape_delay_sec=float(os.environ.get("SCRAPE_DELAY_SEC", "1.5")),
        proxy_url=(os.environ.get("PROXY_URL") or "").strip() or None,
        public_mode=_as_bool(os.environ.get("KP_PUBLIC_MODE"), default=False),
    )


def playwright_proxy(proxy_url: str | None) -> dict | None:
    """Преобразует строку PROXY_URL в словарь, который понимает Playwright.

    Поддерживает http://, https://, socks5://. Basic-auth в URL
    (user:pass@host:port) разбирается и выносится в отдельные поля.
    """
    if not proxy_url:
        return None

    from urllib.parse import urlparse

    parsed = urlparse(proxy_url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Не понимаю PROXY_URL: {proxy_url!r}")

    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"

    result: dict = {"server": server}
    if parsed.username:
        result["username"] = parsed.username
    if parsed.password:
        result["password"] = parsed.password
    return result
