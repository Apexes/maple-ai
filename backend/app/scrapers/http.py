"""
Shared HTTP layer for the live scrapers.

Plain stdlib HTTP (urllib) with the three things every adapter needs:

  * a browser User-Agent + optional cookie injection from the per-platform
    session store (secrets/sessions/<platform>.json — see base.load_session)
  * polite throttling + retry-with-backoff on 429/5xx (IndiaMART rate-limits
    aggressively; gsmExchange does not, but the same contract costs nothing)
  * raw-payload archival: every successful fetch is gzipped into the
    ``scrape_raw`` table so a parser bug or site redesign never loses data —
    listings can always be re-parsed from the archive.

Archival is strictly best-effort: a DB hiccup must never break a scrape.
"""
from __future__ import annotations

import gzip
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Statuses worth retrying (rate-limit / transient upstream).
_RETRYABLE = {429, 500, 502, 503, 504}


def _cookie_header(session: dict | None) -> str | None:
    """Build a Cookie header from a session blob (Playwright storage_state or
    a plain {name: value} dict), if one is seeded for the platform."""
    if not session:
        return None
    cookies = session.get("cookies")
    if isinstance(cookies, list):  # Playwright storage_state format
        pairs = [
            f"{c['name']}={c['value']}"
            for c in cookies
            if isinstance(c, dict) and c.get("name")
        ]
        return "; ".join(pairs) if pairs else None
    if isinstance(cookies, dict):
        return "; ".join(f"{k}={v}" for k, v in cookies.items()) or None
    return None


def archive_raw(platform_key: str, url: str, status: int, body: bytes) -> None:
    """Persist the raw payload into scrape_raw (best-effort, never raises)."""
    try:
        from ..db import SessionLocal
        from ..models import ScrapeRaw

        with SessionLocal() as db:
            db.add(
                ScrapeRaw(
                    platform=platform_key,
                    url=url[:500],
                    status=int(status),
                    content_gz=gzip.compress(body),
                    content_bytes=len(body),
                )
            )
            db.commit()
    except Exception:  # noqa: BLE001 - archival must never break a scrape
        pass


def fetch_html(
    url: str,
    platform_key: str,
    *,
    session: dict | None = None,
    params: dict | None = None,
    timeout: float = 25.0,
    retries: int = 3,
    backoff: float = 20.0,
    throttle: float = 0.0,
    archive: bool = True,
) -> str:
    """GET a page as text, with retry/backoff and raw archival.

    Raises the last error if every attempt fails — the caller's resilience
    contract (scrape() -> mock fallback) handles that.
    """
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    cookie = _cookie_header(session)
    if cookie:
        headers["Cookie"] = cookie

    if throttle > 0:
        time.sleep(throttle)

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                if archive:
                    archive_raw(platform_key, url, resp.status, body)
                return body.decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRYABLE and attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
                continue
            raise
        except Exception as exc:  # network-level (DNS, timeout, reset)
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(min(5.0, backoff / 4))
                continue
            raise
    raise last_exc if last_exc else RuntimeError(f"fetch failed: {url}")
