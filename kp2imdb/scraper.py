"""Парсер оценок и watchlist с Кинопоиска.

Использует сохранённую сессию (storage_state.json). Запускает Playwright,
листает страницы `/user/{id}/votes/` и `/user/{id}/movies/list/type/3111/`
(«Буду смотреть»), парсит HTML каждой страницы через BeautifulSoup.

Если на странице обнаружена капча/щит — останавливаемся и просим
пользователя пройти её в открытом окне (если HEADLESS=false), после чего
продолжаем с той же страницы.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright
from rich.console import Console

from .auth import ensure_logged_in
from .config import RAW_DIR, STATE_PATH, Settings, load_settings, playwright_proxy

console = Console()

FILM_URL_RE = re.compile(r"/(?:film|series)/(\d+)")
YEAR_RE = re.compile(r"(19|20)\d{2}")
DATE_RE = re.compile(r"(\d{1,2})\.(\d{2})\.(\d{4})")


@dataclass
class KPItem:
    """Одна запись — фильм/сериал."""

    kinopoisk_id: int
    title_ru: str
    title_en: str | None = None
    year: int | None = None
    user_rating: int | None = None
    date_rated: str | None = None
    url: str | None = None
    kind: str = "movie"
    extra: dict = field(default_factory=dict)


VOTES_URL_TPL = (
    "https://www.kinopoisk.ru/user/{user_id}/votes/list/"
    "ord/date/perpage/200/page/{page}/"
)
MUSTSEE_URL_TPL = (
    "https://www.kinopoisk.ru/user/{user_id}/movies/list/type/3111/"
    "ord/adddate/perpage/200/page/{page}/"
)


def _looks_like_challenge(html: str) -> bool:
    markers = (
        "showcaptcha",
        "captcha.yandex",
        "SmartCaptcha",
        "Доступ ограничен",
        "Подтвердите, что запросы отправляли вы",
    )
    return any(m in html for m in markers)


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _parse_items(html: str, with_rating: bool) -> list[KPItem]:
    """Вытаскиваем карточки фильмов с .profileFilmsList (старая разметка)
    или .item (универсально). Разметка Кинопоиска менялась много раз —
    поэтому делаем несколько попыток."""

    soup = BeautifulSoup(html, "lxml")
    items: list[KPItem] = []

    cards = soup.select("div.profileFilmsList div.item")
    if not cards:
        cards = soup.select("div.item.even, div.item.odd, div.item")

    for card in cards:
        link = card.select_one("div.nameRus a, .name a, a[href*='/film/'], a[href*='/series/']")
        if not link:
            continue
        href = link.get("href") or ""
        m = FILM_URL_RE.search(href)
        if not m:
            continue
        kp_id = int(m.group(1))

        title_ru_raw = _text(link)
        year_match = YEAR_RE.search(title_ru_raw)
        year = int(year_match.group(0)) if year_match else None
        title_ru = re.sub(r"\s*\(\d{4}\)\s*$", "", title_ru_raw).strip()

        eng_el = card.select_one("div.nameEng, .nameEng")
        title_en = _text(eng_el) or None
        if title_en:
            title_en = re.sub(r"\s*,?\s*\d{4}\s*$", "", title_en).strip() or None

        kind = "series" if "/series/" in href else "movie"

        user_rating = None
        if with_rating:
            vote_el = card.select_one("div.vote, .myVote, span.myVote, div.rating")
            vote_text = _text(vote_el)
            if vote_text:
                digits = re.search(r"\b(10|[1-9])\b", vote_text)
                if digits:
                    user_rating = int(digits.group(1))

        date_rated = None
        date_el = card.select_one("div.date")
        if date_el:
            m_date = DATE_RE.search(_text(date_el))
            if m_date:
                d, mo, y = m_date.groups()
                date_rated = f"{y}-{mo}-{d.zfill(2)}"

        url = f"https://www.kinopoisk.ru/{'series' if kind == 'series' else 'film'}/{kp_id}/"

        items.append(
            KPItem(
                kinopoisk_id=kp_id,
                title_ru=title_ru,
                title_en=title_en,
                year=year,
                user_rating=user_rating,
                date_rated=date_rated,
                url=url,
                kind=kind,
            )
        )

    return items


def _scrape_pages(
    page: Page,
    url_template: str,
    user_id: str,
    *,
    with_rating: bool,
    delay: float,
) -> list[KPItem]:
    all_items: list[KPItem] = []
    seen_ids: set[int] = set()
    page_n = 1

    while True:
        url = url_template.format(user_id=user_id, page=page_n)
        console.print(f"[cyan]  · страница {page_n}[/cyan] → {url}")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(int(delay * 1000))

        html = page.content()

        if _looks_like_challenge(html):
            console.print(
                "[yellow]Похоже, Кинопоиск показывает капчу/щит. "
                "Пройди её в открытом окне браузера и нажми Enter.[/yellow]"
            )
            input()
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(int(delay * 1000))
            html = page.content()

        page_items = _parse_items(html, with_rating=with_rating)
        if not page_items:
            break

        new_items = [it for it in page_items if it.kinopoisk_id not in seen_ids]
        if not new_items:
            break

        for it in new_items:
            seen_ids.add(it.kinopoisk_id)
        all_items.extend(new_items)
        console.print(f"    нашёл {len(new_items)} (всего {len(all_items)})")

        if len(page_items) < 200:
            break

        page_n += 1
        time.sleep(delay)

    return all_items


def scrape_all(settings: Settings | None = None) -> tuple[list[KPItem], list[KPItem]]:
    settings = settings or load_settings()
    if not settings.kp_user_id:
        raise SystemExit("KP_USER_ID не задан в .env")

    proxy = playwright_proxy(settings.proxy_url)
    if proxy:
        console.print(f"[dim]  · использую прокси: {proxy['server']}[/dim]")

    if not settings.public_mode:
        ensure_logged_in(STATE_PATH)
    else:
        console.print("[cyan]KP_PUBLIC_MODE=true — парсю без авторизации (публичный профиль).[/cyan]")

    with sync_playwright() as p:
        launch_kwargs: dict = {"headless": settings.headless}
        if proxy:
            launch_kwargs["proxy"] = proxy
        browser = p.chromium.launch(**launch_kwargs)

        context_kwargs: dict = {
            "locale": "ru-RU",
            "viewport": {"width": 1280, "height": 900},
        }
        if not settings.public_mode and STATE_PATH.exists():
            context_kwargs["storage_state"] = str(STATE_PATH)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        console.print("\n[bold]Скрейплю оценки (/votes/)...[/bold]")
        votes = _scrape_pages(
            page,
            VOTES_URL_TPL,
            settings.kp_user_id,
            with_rating=True,
            delay=settings.scrape_delay_sec,
        )

        console.print("\n[bold]Скрейплю «Буду смотреть» (mustsee)...[/bold]")
        watchlist = _scrape_pages(
            page,
            MUSTSEE_URL_TPL,
            settings.kp_user_id,
            with_rating=False,
            delay=settings.scrape_delay_sec,
        )

        if not settings.public_mode:
            context.storage_state(path=str(STATE_PATH))
        browser.close()

    _save_raw("votes.json", votes)
    _save_raw("watchlist.json", watchlist)

    console.print(
        f"\n[green]Готово: оценок — {len(votes)}, "
        f"в watchlist — {len(watchlist)}[/green]"
    )
    return votes, watchlist


def _save_raw(name: str, items: Iterable[KPItem]) -> Path:
    path = RAW_DIR / name
    path.write_text(
        json.dumps([asdict(x) for x in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    console.print(f"  сохранил {path}")
    return path


def load_raw(name: str) -> list[KPItem]:
    path = RAW_DIR / name
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [KPItem(**row) for row in data]
