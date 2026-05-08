"""CLI: python -m kp2imdb <команда>

Команды:
    login    — интерактивный логин в Кинопоиск, сохраняет сессию.
    scrape   — парсинг оценок + watchlist, пишет data/raw/*.json.
    match    — маппинг kinopoisk_id -> IMDB ID, пишет data/imdb_cache.json.
    export   — генерирует CSV для IMDB в data/out/.
    all      — scrape + match + export.
"""

from __future__ import annotations

import typer
from rich.console import Console

from .auth import login_interactive
from .config import load_settings
from .exporter import write_ratings_csv, write_watchlist_csv
from .matcher import match_items
from .scraper import load_raw, scrape_all

app = typer.Typer(add_completion=False, help="Kinopoisk → IMDB экспортёр")
console = Console()


@app.command()
def login() -> None:
    """Интерактивный логин в Кинопоиск (сохраняет cookies)."""
    login_interactive()


@app.command()
def scrape() -> None:
    """Собрать оценки и watchlist с Кинопоиска."""
    scrape_all()


@app.command()
def match() -> None:
    """Сопоставить kinopoisk_id -> IMDB ID (tt...)."""
    settings = load_settings()

    votes = load_raw("votes.json")
    watchlist = load_raw("watchlist.json")

    if not votes and not watchlist:
        raise SystemExit("Сначала запусти `scrape` — нет сырых данных.")

    console.print("\n[bold]Маппинг оценок...[/bold]")
    matched_votes, _ = match_items(votes, settings)
    _write_json("votes_matched.json", matched_votes)

    console.print("\n[bold]Маппинг watchlist...[/bold]")
    matched_wl, _ = match_items(watchlist, settings)
    _write_json("watchlist_matched.json", matched_wl)


@app.command()
def export() -> None:
    """Сгенерировать IMDB CSV из замапленных данных."""
    from .config import RAW_DIR
    import json

    votes_path = RAW_DIR / "votes_matched.json"
    wl_path = RAW_DIR / "watchlist_matched.json"

    if not votes_path.exists() or not wl_path.exists():
        raise SystemExit("Сначала запусти `match` — нет *_matched.json.")

    matched_votes = json.loads(votes_path.read_text(encoding="utf-8"))
    matched_wl = json.loads(wl_path.read_text(encoding="utf-8"))

    write_ratings_csv(matched_votes)
    write_watchlist_csv(matched_wl)


@app.command()
def web(
    host: str = "127.0.0.1",
    port: int = 8765,
    reload: bool = False,
) -> None:
    """Запустить локальный веб-интерфейс."""
    import uvicorn

    console.print(
        f"\n[bold]Web UI:[/bold] [cyan]http://{host}:{port}[/cyan]\n"
        "[dim]Ctrl+C чтобы выключить[/dim]\n"
    )
    uvicorn.run(
        "kp2imdb.web.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command("all")
def run_all() -> None:
    """scrape + match + export одной командой."""
    settings = load_settings()

    votes, watchlist = scrape_all(settings)

    console.print("\n[bold]Маппинг оценок...[/bold]")
    matched_votes, _ = match_items(votes, settings)
    _write_json("votes_matched.json", matched_votes)

    console.print("\n[bold]Маппинг watchlist...[/bold]")
    matched_wl, _ = match_items(watchlist, settings)
    _write_json("watchlist_matched.json", matched_wl)

    write_ratings_csv(matched_votes)
    write_watchlist_csv(matched_wl)


def _write_json(name: str, rows: list[dict]) -> None:
    import json

    from .config import RAW_DIR

    path = RAW_DIR / name
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"  сохранил {path}")


if __name__ == "__main__":
    app()
