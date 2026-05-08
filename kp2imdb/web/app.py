"""FastAPI web UI для управления парсером.

Запуск: python -m kp2imdb web
Открой: http://127.0.0.1:8765
"""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import dotenv_values, set_key
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import (
    CACHE_PATH,
    OUT_DIR,
    RAW_DIR,
    ROOT,
    STATE_PATH,
    UNMATCHED_PATH,
    load_settings,
)
from .tasks import TaskRunner

WEB_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))

app = FastAPI(title="kp2imdb")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

runner = TaskRunner(project_root=ROOT)

ENV_PATH = ROOT / ".env"
ENV_FIELDS = [
    ("KP_USER_ID", "Kinopoisk User ID", "12345678", "number"),
    ("PROXY_URL", "Proxy URL (SOCKS5/HTTP)", "socks5://127.0.0.1:1080", "text"),
    ("KINOPOISK_DEV_TOKEN", "kinopoisk.dev token", "…", "password"),
    ("OMDB_API_KEY", "OMDb API key (fallback)", "", "password"),
    ("KP_PUBLIC_MODE", "Публичный профиль (без логина)", "false", "checkbox"),
    ("HEADLESS", "Headless browser", "false", "checkbox"),
    ("SCRAPE_DELAY_SEC", "Задержка между страницами, сек", "1.5", "text"),
]
ALLOWED_COMMANDS = {"login", "scrape", "match", "export", "all"}


def _env_values() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {k: "" for k, *_ in ENV_FIELDS}
    raw = dotenv_values(ENV_PATH)
    return {k: (raw.get(k) or "") for k, *_ in ENV_FIELDS}


def _status_snapshot() -> dict:
    s = load_settings()
    votes_path = RAW_DIR / "votes.json"
    watch_path = RAW_DIR / "watchlist.json"
    votes_matched = RAW_DIR / "votes_matched.json"
    watch_matched = RAW_DIR / "watchlist_matched.json"
    ratings_csv = OUT_DIR / "ratings.csv"
    watchlist_csv = OUT_DIR / "watchlist.csv"

    return {
        "logged_in": STATE_PATH.exists(),
        "public_mode": s.public_mode,
        "kp_user_id_set": bool(s.kp_user_id),
        "proxy_set": bool(s.proxy_url),
        "kp_dev_set": bool(s.kinopoisk_dev_token),
        "omdb_set": bool(s.omdb_api_key),
        "counts": {
            "votes": _count_json(votes_path),
            "watchlist": _count_json(watch_path),
            "votes_matched": _count_json(votes_matched),
            "watchlist_matched": _count_json(watch_matched),
            "unmatched": _count_json(UNMATCHED_PATH),
            "cache": _count_json(CACHE_PATH, is_dict=True),
        },
        "files": {
            "ratings_csv": ratings_csv.exists(),
            "watchlist_csv": watchlist_csv.exists(),
            "state": STATE_PATH.exists(),
        },
        "task": {
            "name": runner.state.name,
            "running": runner.is_running(),
            "waiting_for_input": runner.state.waiting_for_input,
            "exit_code": runner.state.exit_code,
            "logs_len": len(runner.state.logs),
        },
    }


def _count_json(path: Path, is_dict: bool = False) -> int:
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if is_dict and isinstance(data, dict):
        return len(data)
    if isinstance(data, list):
        return len(data)
    return 0


# ----- routes -----


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        "index.html",
        {
            "request": request,
            "status": _status_snapshot(),
            "env_fields": ENV_FIELDS,
            "env_values": _env_values(),
            "logs": runner.state.logs[-300:],
        },
    )


@app.get("/partials/panel", response_class=HTMLResponse)
def partial_panel(request: Request) -> HTMLResponse:
    """Правая панель: статус + логи. Опрашивается HTMX каждую секунду."""
    return TEMPLATES.TemplateResponse(
        "_panel.html",
        {
            "request": request,
            "status": _status_snapshot(),
            "logs": runner.state.logs[-500:],
        },
    )


@app.get("/partials/data/{name}", response_class=HTMLResponse)
def partial_data(request: Request, name: str) -> HTMLResponse:
    """Таблица данных (votes / watchlist / unmatched / matched_votes / matched_watchlist / cache)."""
    file_map: dict[str, Path] = {
        "votes": RAW_DIR / "votes.json",
        "watchlist": RAW_DIR / "watchlist.json",
        "matched_votes": RAW_DIR / "votes_matched.json",
        "matched_watchlist": RAW_DIR / "watchlist_matched.json",
        "unmatched": UNMATCHED_PATH,
    }
    if name not in file_map:
        raise HTTPException(404)
    path = file_map[name]
    rows: list[dict] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                rows = data
        except json.JSONDecodeError:
            rows = []

    return TEMPLATES.TemplateResponse(
        "_table.html",
        {
            "request": request,
            "name": name,
            "rows": rows[:500],
            "total": len(rows),
            "truncated": len(rows) > 500,
        },
    )


@app.post("/run/{command}")
def run(command: str) -> JSONResponse:
    if command not in ALLOWED_COMMANDS:
        raise HTTPException(400, f"unknown command: {command}")
    ok, msg = runner.start(command)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=409)
    return JSONResponse({"ok": True})


@app.post("/input/enter")
def send_enter() -> JSONResponse:
    ok = runner.send_enter()
    return JSONResponse({"ok": ok})


@app.post("/kill")
def kill() -> JSONResponse:
    ok = runner.kill()
    return JSONResponse({"ok": ok})


@app.post("/settings")
async def save_settings(request: Request) -> RedirectResponse:
    form = await request.form()
    ENV_PATH.touch(exist_ok=True)

    checkbox_keys = {k for k, _, _, t in ENV_FIELDS if t == "checkbox"}

    for key, *_rest in ENV_FIELDS:
        if key in checkbox_keys:
            value = "true" if form.get(key) else "false"
        else:
            raw = form.get(key, "")
            value = str(raw).strip() if raw is not None else ""
        set_key(str(ENV_PATH), key, value, quote_mode="never")

    return RedirectResponse("/", status_code=303)


@app.get("/download/{what}")
def download(what: str):
    mapping: dict[str, Path] = {
        "ratings": OUT_DIR / "ratings.csv",
        "watchlist": OUT_DIR / "watchlist.csv",
        "votes_raw": RAW_DIR / "votes.json",
        "watchlist_raw": RAW_DIR / "watchlist.json",
        "unmatched": UNMATCHED_PATH,
    }
    if what not in mapping:
        raise HTTPException(404)
    path = mapping[what]
    if not path.exists():
        raise HTTPException(404, "file not found yet — сначала запусти нужную команду")
    return FileResponse(path, filename=path.name)
