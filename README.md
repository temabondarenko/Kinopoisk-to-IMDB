# kinopoisk-to-imdb

A local parser designed for movie buffs who have accumulated many ratings on Kinopoisk over the years and want to migrate their data to IMDb.

This tool allows you to export:

- All your **movie and TV show ratings** from Kinopoisk,
- Your **"Watchlist"** (Буду смотреть),

with automatic matching to **IMDb IDs (tt...)** and generation of **CSV files ready for import into IMDb**.

## How it Works

1. **Login** — A browser window opens (Playwright, headed mode) for you to manually log in to Kinopoisk (handling SMS/captcha if needed). The session is saved to `data/storage_state.json`, and everything else is automated.
2. **Scrape** — The parser crawls your `/votes/` and "Watchlist" pages, collecting titles (RU + EN), years, ratings, kinopoisk_ids, links, and rating dates.
3. **Match** — For each movie, it queries [kinopoisk.dev](https://kinopoisk.dev) (a free API that returns `externalId.imdb` directly). Responses are cached in `data/imdb_cache.json`.
4. **Export** — Two CSV files are generated in IMDb-compatible format:
   - `data/out/ratings.csv` — Your ratings (can be imported at `https://www.imdb.com/list/ratings/`).
   - `data/out/watchlist.csv` — Your watchlist (import via IMDb → Your Lists → Create list → Import).

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cp config.example.env .env
```

Next, choose your preferred interface:

### Option 1: Web UI (Recommended)

```bash
python -m kp2imdb web
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). On the page:

- Left side: Settings form (edits `.env` directly from the browser).
- Buttons: **Login / Scrape / Match / Export / All**.
- Right side: Status indicators (logged in? proxy active? movies found?).
- Live log: Real-time progress updates.
- Data tables and download buttons for `ratings.csv` / `watchlist.csv`.

**Login:** Click "Login" → Chromium opens in a separate window → Log in to Kinopoisk **manually** (including email/SMS codes if Yandex asks) → Return to the kp2imdb tab → Click **"Done, I'm logged in"** (the button appears automatically when the script is waiting).

### Option 2: CLI

```bash
python -m kp2imdb login     # Run once
python -m kp2imdb all       # Scrape + Match + Export
```

Final files (common for both options):

- `data/out/ratings.csv`
- `data/out/watchlist.csv`
- `data/raw/votes.json`, `data/raw/watchlist.json` — Raw data for manual adjustments.

## Getting a kinopoisk.dev Token

Get a free token via the Telegram bot: [@kinopoiskdev_bot](https://t.me/kinopoiskdev_bot). The quota is ~200 requests/day (enough for several hundred movies, especially with caching).

If no token is provided, the tool falls back to OMDb (requires your own key from `https://www.omdbapi.com/apikey.aspx`), but matching is less accurate (based on title and year).

## How to Find Your Kinopoisk User ID

Open your Kinopoisk profile. The URL looks like `https://www.kinopoisk.ru/user/12345678/` — you need the numeric ID.

## Bypassing Blocks (Ukraine / Commercial VPNs)

Yandex detects and blocks IPs from most public VPNs (Surfshark, Nord, Mullvad, etc.). Here are working alternatives:

### A) Public Profile — Easiest

If your Kinopoisk profile is set to **Public**, the `/user/{id}/votes/` and `/user/{id}/movies/list/type/3111/` pages are accessible without authorization. Any proxy that can open the site will work:

```env
KP_PUBLIC_MODE=true
PROXY_URL=socks5://127.0.0.1:1080
```

Verification: Open `https://www.kinopoisk.ru/user/YOUR_ID/votes/` in an incognito window without logging in. If you can see your ratings, the profile is public.

### B) Personal VPS + SSH SOCKS5 (Cheap and Reliable)

1. Get a VPS in a country where Kinopoisk is not blocked (Kazakhstan, Armenia, Georgia, Uzbekistan, Kyrgyzstan — ~$3–5/month from Aeza, VDSina, Hostinger, Timeweb, etc.).
2. Verify access from the VPS: `ssh user@vps "curl -sI https://www.kinopoisk.ru | head -1"` — should return `200 OK`.
3. Start SSH with dynamic port forwarding (instant SOCKS5 proxy):

   ```bash
   ssh -D 1080 -N user@vps
   ```

4. In `.env`:

   ```env
   PROXY_URL=socks5://127.0.0.1:1080
   ```

5. Both Playwright (login/scrape) and httpx (kinopoisk.dev) will route through this tunnel.

### C) Residential / Mobile Proxy

If you don't want to manage a VPS, buy residential proxies (IPRoyal, ProxyEmpire, Soax, Smartproxy, Oxylabs). They appear as regular home/mobile connections and are rarely banned by Yandex.

```env
PROXY_URL=http://user:pass@proxy-host.example.com:12323
```

Traffic-based plans are usually sufficient; the parser uses at most 100–200 MB.

### D) A Friend with Access

If neither VPS nor residential proxies work:

- Give this repository to a friend with access.
- They run it (if your profile is public, they don't even need to log in, just enter your `KP_USER_ID`).
- They send you back the `data/raw/*.json` files and/or the final CSVs.

The code also handles captchas: if a Yandex challenge appears, the parser will pause and ask you to solve it in the open browser window.

## Importing to IMDb

- **Ratings:** Go to https://www.imdb.com/list/ratings → click the "..." button → Import. Upload `ratings.csv`.
- **Watchlist:** Go to https://www.imdb.com/list/watchlist → "..." → Edit → Import. Alternatively, create a new list and import there.

> IMDb occasionally silently drops rows without a `Const` (tt-id). Check `data/unmatched.json` for movies that couldn't be matched; these can be added manually.

## Project Structure

```
kp2imdb/
  __init__.py
  auth.py        # Interactive login via Playwright
  scraper.py     # Parsing /votes/ and Watchlist
  matcher.py     # KP -> IMDb matching via kinopoisk.dev / OMDb
  exporter.py    # IMDb CSV generation
  __main__.py    # CLI
main.py          # Alias: python main.py == python -m kp2imdb
```
