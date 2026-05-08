"""Интерактивный логин в Кинопоиск и сохранение состояния сессии.

Запускаем браузер в headed-режиме, пользователь логинится вручную
(в т.ч. проходит SMS / капчу / Яндекс-щит), затем жмёт Enter в терминале
и мы сохраняем cookies + localStorage в storage_state.json.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright
from rich.console import Console

from .config import STATE_PATH, load_settings, playwright_proxy

console = Console()

LOGIN_URL = "https://www.kinopoisk.ru/"
PROFILE_URL = "https://www.kinopoisk.ru/mykp/"


def _is_logged_in(page) -> bool:
    """Простая эвристика: на /mykp/ залогиненного редиректит в профиль,
    незалогиненного — на страницу логина Яндекса (passport.yandex)."""
    url = page.url
    return "kinopoisk.ru" in url and "passport" not in url and "auth" not in url


def login_interactive(state_path: Path = STATE_PATH) -> Path:
    """Открывает браузер, ждёт пока пользователь войдёт, сохраняет storage_state."""
    console.print("[bold]Открываю браузер.[/bold] Войди в аккаунт Кинопоиска вручную.")
    console.print("Когда увидишь свой профиль — вернись в терминал и нажми Enter.\n")

    settings = load_settings()
    proxy = playwright_proxy(settings.proxy_url)
    if proxy:
        console.print(f"[dim]  · использую прокси: {proxy['server']}[/dim]")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, proxy=proxy) if proxy else p.chromium.launch(headless=False)
        context = browser.new_context(
            locale="ru-RU",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        input("Нажми Enter после того, как залогинишься в браузере... ")

        page.goto(PROFILE_URL, wait_until="domcontentloaded")
        if not _is_logged_in(page):
            console.print(
                "[yellow]Похоже, ты ещё не залогинен (URL: "
                f"{page.url}). Попробуй ещё раз.[/yellow]"
            )
            browser.close()
            raise SystemExit(1)

        state_path.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_path))
        browser.close()

    console.print(f"[green]Ок, сессия сохранена в {state_path}[/green]")
    return state_path


def ensure_logged_in(state_path: Path = STATE_PATH) -> Path:
    if not state_path.exists():
        console.print("[yellow]storage_state.json не найден, запускаю логин...[/yellow]")
        return login_interactive(state_path)
    return state_path
