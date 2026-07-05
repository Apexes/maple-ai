"""
Scraper base class — modular, BrightData-compatible architecture.

Each adapter declares WHERE and HOW to scrape a platform (search URL template,
DOM selectors, pagination) and implements ``fetch_raw()`` using Playwright,
optionally routed through a BrightData "Web Unlocker" / proxy.

Reality of the pre-owned market: most of these sites aggressively block bots.
So every adapter is wrapped in a resilience contract:

    scrape() -> fetch_raw()         # real listings, normalized
              -> on ANY failure     # blocked, captcha, layout change, no network
              -> mock fallback       # synthetic-but-consistent listings

This is exactly what keeps the pilot "always functional" for a live demo.

Output of every scraper is a list of normalized listing dicts:
    {
        platform, model, variant, storage, battery_health, condition,
        city, asking_price, listing_date, url,
        # plus enrichment used downstream:
        region, sku, series, raw_condition, asking_price_native, currency, seller_type
    }
"""
from __future__ import annotations

import json
import os
import random
import zlib
from datetime import date
from pathlib import Path

from ..config import MapleConfig, get_config
from ..mock_data import generate_platform_listings
from ..normalization import normalize_grade
from ..util import as_of_date


class ScrapeBlocked(RuntimeError):
    """Raised by fetch_raw() when the platform blocks the scrape."""


# --------------------------------------------------------------------------- #
# Authenticated-session store (cookie injection for gated B2B sources)
# --------------------------------------------------------------------------- #
# Gated sources (IndiaMART, gsmExchange, Cashify SuperSale) are scraped through
# a logged-in session belonging to a real account. We NEVER commit credentials:
# a per-platform session blob (cookie jar / Playwright storage_state) is read at
# runtime from either an env var or a gitignored file, keyed by platform_key.
#
#   env:  MAPLE_SESSION_<PLATFORM_KEY_UPPER>   (raw JSON)
#   file: $MAPLE_SESSION_DIR/<platform_key>.json   (default ./secrets/sessions)
#
# A human logs in once to seed the blob; daily scraping keeps the session warm,
# persisting any rotated cookie back. A missing/expired session simply raises
# ScrapeBlocked, so the resilience contract falls back to mock-and-flag.
def _session_dir() -> Path:
    return Path(os.getenv("MAPLE_SESSION_DIR", "secrets/sessions"))


def load_session(platform_key: str) -> dict | None:
    """Return {cookies, storage_state, captured_at, …} for a platform, or None."""
    env = os.getenv(f"MAPLE_SESSION_{platform_key.upper()}")
    if env:
        try:
            return json.loads(env)
        except Exception:  # noqa: BLE001 - malformed env blob => treat as absent
            return None
    path = _session_dir() / f"{platform_key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            return None
    return None


def save_session(platform_key: str, session: dict) -> None:
    """Persist a (refreshed) session blob back to the gitignored store."""
    d = _session_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{platform_key}.json").write_text(json.dumps(session, indent=2, default=str))


class BaseScraper:
    platform_key: str = ""
    platform_name: str = ""
    region: str = "IN"
    base_url: str = ""
    # Per-platform selector map — illustrative, the real values live here.
    selectors: dict[str, str] = {}
    # Gated sources set this True; fetch_raw() then needs an authenticated session.
    requires_auth: bool = False

    def __init__(self, cfg: MapleConfig | None = None):
        self.cfg = cfg or get_config()

    # --- authenticated session (cookie injection) ------------------------ #
    def session(self) -> dict | None:
        """The logged-in session blob for this platform (None if not seeded)."""
        return load_session(self.platform_key)

    # --- BrightData / Playwright wiring ---------------------------------- #
    @property
    def brightdata_enabled(self) -> bool:
        return bool(os.getenv("BRIGHTDATA_API_KEY")) or bool(os.getenv("BRIGHTDATA_WSS"))

    @property
    def proxy_endpoint(self) -> str | None:
        # e.g. wss://brd-customer-XXX:pass@brd.superproxy.io:9222 (CDP) for Playwright
        return os.getenv("BRIGHTDATA_WSS") or None

    def fetch_raw(self, devices: list | None = None) -> list[dict]:
        """Real scrape. Override in adapters.

        Default raises ScrapeBlocked so the resilience contract kicks in and the
        pilot stays functional even with zero network / no Playwright install.
        """
        raise ScrapeBlocked(
            f"{self.platform_key}: live scraping not available in this environment"
        )

    # --- public entrypoint ----------------------------------------------- #
    def scrape(self, as_of: date | None = None) -> tuple[list[dict], str]:
        """Return (listings, source) where source in {'live','mock'}."""
        as_of = as_of or as_of_date()
        try:
            raw = self.fetch_raw()
            if raw:
                return [self._postprocess(r) for r in raw], "live"
            raise ScrapeBlocked(f"{self.platform_key}: empty result")
        except Exception as exc:  # noqa: BLE001 - resilience by design
            return self._mock_listings(as_of), "mock"

    def _mock_listings(self, as_of: date) -> list[dict]:
        """Synthetic-but-consistent listings used when the live scrape fails.

        Overridable so a platform with bespoke economics (e.g. Maple's own
        certified store) can supply its own generator.
        """
        # Seed derived from platform so each scraper's mock stream is stable
        # yet distinct (crc32: str hash() is randomized per process).
        seed = self.cfg.infra.mock_seed + (zlib.crc32(self.platform_key.encode()) % 9973)
        rng = random.Random(seed)
        return generate_platform_listings(self.cfg, self.platform_key, as_of, rng)

    def _postprocess(self, raw: dict) -> dict:
        """Normalize a raw scraped record into the canonical schema.

        Maps the platform's grade vocabulary into the Maple Condition System.
        """
        raw = dict(raw)
        raw.setdefault("platform", self.platform_key)
        raw.setdefault("region", self.region)
        raw["condition"] = normalize_grade(
            raw.get("raw_condition") or raw.get("condition"),
            raw.get("battery_health"),
        )
        return raw


class B2BWholesaleScraper(BaseScraper):
    """Base for gated B2B wholesale sources scraped via an authenticated session.

    Concrete adapters (IndiaMART, gsmExchange, SuperSale) inherit this. Until a
    real parser is wired AND a session is seeded, ``fetch_raw`` raises so the
    resilience contract falls back to this source's synthetic B2B slice — which
    is exactly how the POC stays live with the adapters dormant.
    """

    requires_auth = True

    def fetch_raw(self, devices: list | None = None) -> list[dict]:
        sess = self.session()
        if not sess:
            raise ScrapeBlocked(
                f"{self.platform_key}: no authenticated session (seed a cookie blob)"
            )
        # A real session is present, but the live HTML/JSON parser for this
        # gated source is not implemented in the POC — fall back to mock.
        raise ScrapeBlocked(
            f"{self.platform_key}: live parser not implemented (POC); using mock"
        )

    def _mock_listings(self, as_of: date) -> list[dict]:
        """This source's slice of the deterministic synthetic B2B market."""
        from ..mock_data import build_b2b_rng, generate_b2b_listings

        rows = generate_b2b_listings(self.cfg, as_of, build_b2b_rng(self.cfg))
        return [r for r in rows if r["platform"] == self.platform_key]
