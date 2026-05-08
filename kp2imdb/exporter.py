"""Экспорт в IMDB-совместимый CSV.

IMDB для импорта оценок принимает CSV с колонками:
    Const, Your Rating, Date Rated, Title, Year, Title Type
(важен Const = tt-идентификатор; остальное — для ориентира).

Для списков (watchlist / user lists) минимально достаточно:
    Position, Const, Title, Year, Title Type
"""

from __future__ import annotations

import csv
from pathlib import Path

from rich.console import Console

from .config import OUT_DIR

console = Console()

TYPE_MAP = {
    "movie": "Movie",
    "tv-series": "TV Series",
    "tv-mini-series": "TV Mini Series",
    "mini-series": "TV Mini Series",
    "animated-series": "TV Series",
    "cartoon": "Movie",
    "anime": "TV Series",
    "tv-show": "TV Series",
    "series": "TV Series",
}


def _imdb_type(row: dict) -> str:
    raw = (row.get("match_source_type") or row.get("type") or "").lower()
    kind = (row.get("kind") or "").lower()
    if raw in TYPE_MAP:
        return TYPE_MAP[raw]
    if kind in TYPE_MAP:
        return TYPE_MAP[kind]
    return "Movie"


def write_ratings_csv(matched: list[dict], path: Path | None = None) -> Path:
    path = path or (OUT_DIR / "ratings.csv")
    fieldnames = ["Const", "Your Rating", "Date Rated", "Title", "Year", "Title Type"]

    rows = []
    for r in matched:
        rating = r.get("user_rating")
        if not rating:
            continue
        rows.append(
            {
                "Const": r["imdb_id"],
                "Your Rating": int(rating),
                "Date Rated": r.get("date_rated") or "",
                "Title": r.get("title_en") or r.get("title_ru") or "",
                "Year": r.get("year") or "",
                "Title Type": _imdb_type(r),
            }
        )

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    console.print(f"[green]Записал {len(rows)} оценок → {path}[/green]")
    return path


def write_watchlist_csv(matched: list[dict], path: Path | None = None) -> Path:
    path = path or (OUT_DIR / "watchlist.csv")
    fieldnames = ["Position", "Const", "Title", "Year", "Title Type"]

    rows = []
    for idx, r in enumerate(matched, start=1):
        rows.append(
            {
                "Position": idx,
                "Const": r["imdb_id"],
                "Title": r.get("title_en") or r.get("title_ru") or "",
                "Year": r.get("year") or "",
                "Title Type": _imdb_type(r),
            }
        )

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    console.print(f"[green]Записал {len(rows)} фильмов в watchlist → {path}[/green]")
    return path
