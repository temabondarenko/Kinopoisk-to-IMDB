"""Сопоставление kinopoisk_id -> IMDB ID (tt...).

Основной путь: kinopoisk.dev — бесплатный API, возвращает externalId.imdb
прямо в ответе по Kinopoisk ID. Без токена или при исчерпании квоты —
пробуем OMDb по названию+году (точность ниже). Все успешные ответы
кешируются в data/imdb_cache.json, неудачные — в data/unmatched.json.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from .config import CACHE_PATH, UNMATCHED_PATH, Settings, load_settings
from .scraper import KPItem

console = Console()

KP_DEV_URL = "https://api.kinopoisk.dev/v1.4/movie/{id}"
OMDB_URL = "https://www.omdbapi.com/"


def _load_cache() -> dict[str, dict]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict[str, dict]) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _lookup_kinopoisk_dev(
    client: httpx.Client, token: str, kp_id: int
) -> dict | None:
    try:
        r = client.get(
            KP_DEV_URL.format(id=kp_id),
            headers={"X-API-KEY": token, "accept": "application/json"},
            timeout=20,
        )
    except httpx.HTTPError as e:
        console.print(f"  [yellow]kinopoisk.dev: {e}[/yellow]")
        return None

    if r.status_code == 403:
        console.print("  [red]kinopoisk.dev: 403 — лимит или невалидный токен[/red]")
        return None
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        console.print(f"  [yellow]kinopoisk.dev {kp_id}: {r.status_code}[/yellow]")
        return None

    data = r.json()
    imdb_id = None
    ext = data.get("externalId") or {}
    if isinstance(ext, dict):
        imdb_id = ext.get("imdb")

    if not imdb_id:
        return None

    return {
        "imdb_id": imdb_id,
        "type": data.get("type"),
        "year": data.get("year"),
        "title_en": (data.get("alternativeName") or data.get("enName")),
        "title_ru": data.get("name"),
        "source": "kinopoisk.dev",
    }


def _lookup_omdb(
    client: httpx.Client, api_key: str, title: str, year: int | None
) -> dict | None:
    if not title:
        return None
    params: dict[str, str] = {"apikey": api_key, "t": title}
    if year:
        params["y"] = str(year)
    try:
        r = client.get(OMDB_URL, params=params, timeout=15)
    except httpx.HTTPError as e:
        console.print(f"  [yellow]OMDb: {e}[/yellow]")
        return None
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("Response") != "True":
        return None
    imdb_id = data.get("imdbID")
    if not imdb_id:
        return None
    return {
        "imdb_id": imdb_id,
        "type": data.get("Type"),
        "year": data.get("Year"),
        "title_en": data.get("Title"),
        "title_ru": None,
        "source": "omdb",
    }


def match_items(
    items: list[KPItem],
    settings: Settings | None = None,
    *,
    sleep_between: float = 0.4,
) -> tuple[list[dict], list[dict]]:
    """Возвращает (matched, unmatched). Каждое matched-значение содержит
    оригинальный KPItem + найденный imdb_id в поле `imdb_id`."""
    settings = settings or load_settings()
    cache = _load_cache()

    if not (settings.kinopoisk_dev_token or settings.omdb_api_key):
        raise SystemExit(
            "Нужен хотя бы один ключ: KINOPOISK_DEV_TOKEN или OMDB_API_KEY"
        )

    matched: list[dict] = []
    unmatched: list[dict] = []

    client_kwargs: dict = {}
    if settings.proxy_url:
        client_kwargs["proxy"] = settings.proxy_url

    with httpx.Client(**client_kwargs) as client, Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Маппинг в IMDB", total=len(items))

        for it in items:
            key = str(it.kinopoisk_id)
            info: dict | None = cache.get(key)

            if info is None or not info.get("imdb_id"):
                if settings.kinopoisk_dev_token:
                    info = _lookup_kinopoisk_dev(
                        client, settings.kinopoisk_dev_token, it.kinopoisk_id
                    )
                    if info:
                        cache[key] = info
                        _save_cache(cache)

                if (not info or not info.get("imdb_id")) and settings.omdb_api_key:
                    title = it.title_en or it.title_ru
                    info2 = _lookup_omdb(client, settings.omdb_api_key, title, it.year)
                    if info2:
                        info = info2
                        cache[key] = info
                        _save_cache(cache)

                time.sleep(sleep_between)

            row = asdict(it)
            if info and info.get("imdb_id"):
                row["imdb_id"] = info["imdb_id"]
                row["match_source"] = info.get("source")
                matched.append(row)
            else:
                unmatched.append(row)

            progress.advance(task)

    UNMATCHED_PATH.write_text(
        json.dumps(unmatched, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    console.print(
        f"[green]Сопоставлено: {len(matched)}/{len(items)}[/green]"
        f"  [yellow](не нашлось: {len(unmatched)} → {UNMATCHED_PATH})[/yellow]"
    )
    return matched, unmatched
