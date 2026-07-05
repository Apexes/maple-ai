"""
Database seeding.

On startup we materialize a full, internally-consistent mock market:
  * listings      — current cross-platform listings (India + Dubai)
  * market_daily  — the Maple Used-iPhone Index history
  * device_daily  — per-device fair-value history (trend charts)

By default the data is loaded from a committed fixture
(app/fixtures/seed_market.json) so the demo is identical on every machine and
does not depend on the generator running at startup. If the fixture is absent
(or MAPLE_SEED_SOURCE=generate), we fall back to generating it on the fly.
Rebuild the fixture with:  python -m scripts.build_seed_fixture

refresh_market() re-runs the scraper layer (which falls back to mock) and
replaces the live listings — this is what the "Refresh market" demo button and
the Redis worker call.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .config import get_config
from .db import SessionLocal, init_db
from .models import DeviceDaily, Listing, MarketDaily
from .mock_data import (
    build_rng,
    build_extra_rng,
    build_maple_rng,
    build_b2b_rng,
    generate_history,
    generate_listings,
    generate_extended_listings,
    generate_maple_listings,
    generate_b2b_listings,
)
from .scrapers import run_all_scrapers, run_b2b_scrapers
from .util import as_of_date

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_PATH = FIXTURE_DIR / "seed_market.json"            # mock (default)
REAL_FIXTURE_PATH = FIXTURE_DIR / "seed_market_real.json"  # real (scraped)


def fixture_path(cfg=None) -> Path:
    """The fixture for the active data mode."""
    cfg = cfg or get_config()
    return REAL_FIXTURE_PATH if cfg.infra.data_source == "real" else FIXTURE_PATH

# Columns stored as dates in the fixture, by table key, that must be parsed back
# into date objects before bulk insert.
_DATE_FIELDS = {
    "listings": ("listing_date",),
    "market_daily": ("day",),
    "device_daily": ("day",),
}


def _use_fixture(cfg=None) -> bool:
    """Prefer the committed fixture (for the active mode) unless told to generate."""
    if os.getenv("MAPLE_SEED_SOURCE", "").strip().lower() == "generate":
        return False
    return fixture_path(cfg).exists()


def _parse_dates(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
    for r in rows:
        for f in fields:
            v = r.get(f)
            if isinstance(v, str):
                r[f] = datetime.strptime(v, "%Y-%m-%d").date()
    return rows


def load_fixture(db: Session, cfg=None) -> dict:
    """Load the pre-built market fixture (for the active mode) into the wiped DB."""
    path = fixture_path(cfg)
    data = json.loads(path.read_text())
    listings = _parse_dates(list(data["listings"]), _DATE_FIELDS["listings"])
    market = _parse_dates(list(data["market_daily"]), _DATE_FIELDS["market_daily"])
    devices = _parse_dates(list(data["device_daily"]), _DATE_FIELDS["device_daily"])

    db.bulk_insert_mappings(Listing, listings)
    db.bulk_insert_mappings(MarketDaily, market)
    db.bulk_insert_mappings(DeviceDaily, devices)
    db.commit()
    return {
        "seeded": True,
        "source": f"fixture:{(cfg or get_config()).infra.data_source}",
        "listings": len(listings),
        "market_days": len(market),
        "device_days": len(devices),
    }


def _insert_listings(db: Session, rows: list[dict]) -> None:
    db.bulk_insert_mappings(Listing, rows)


def _update_today_counts(db: Session, as_of: date) -> None:
    """Fill today's listing counts on market_daily / device_daily from listings.

    Counts the RETAIL segment only — the index history and per-device counts
    describe the B2C market; B2B lot counts are surfaced separately by the B2B
    agent, so they must not inflate these (keeps retail KPIs byte-identical).
    """
    today_row = db.scalar(select(MarketDaily).where(MarketDaily.day == as_of))
    listing_total = (
        db.scalar(
            select(func.count()).select_from(Listing).where(Listing.segment == "retail")
        )
        or 0
    )
    if today_row is not None:
        today_row.total_active_listings = int(listing_total)

    counts = Counter(
        r[0] for r in db.execute(
            select(Listing.sku).where(Listing.segment == "retail")
        ).all()
    )
    for sku, c in counts.items():
        db.execute(
            update(DeviceDaily)
            .where(DeviceDaily.day == as_of, DeviceDaily.sku == sku)
            .values(listing_count=int(c))
        )


def seed_all(db: Session, force: bool = False, ignore_fixture: bool = False) -> dict:
    cfg = get_config()
    as_of = as_of_date()

    existing = db.scalar(select(MarketDaily).limit(1))
    if existing is not None and not force:
        n = db.scalar(select(func.count()).select_from(Listing))
        return {"seeded": False, "listings": int(n or 0)}

    # wipe
    db.execute(delete(Listing))
    db.execute(delete(MarketDaily))
    db.execute(delete(DeviceDaily))
    db.commit()

    # Preferred path: load the committed pre-built fixture (deterministic, no
    # runtime generation). The fixture already includes the filled-in listing
    # counts, so there's no _update_today_counts step.
    if not ignore_fixture and _use_fixture(cfg):
        return load_fixture(db, cfg)

    rng = build_rng(cfg)
    listings = generate_listings(cfg, as_of, rng)
    listings += generate_extended_listings(cfg, as_of, build_extra_rng(cfg))
    listings += generate_maple_listings(cfg, as_of, build_maple_rng(cfg))
    # B2B wholesale segment — own RNG (seed+3), excluded from the retail benchmark.
    listings += generate_b2b_listings(cfg, as_of, build_b2b_rng(cfg))
    market_daily, device_daily = generate_history(cfg, as_of, rng)

    _insert_listings(db, listings)
    db.bulk_insert_mappings(MarketDaily, market_daily)
    db.bulk_insert_mappings(DeviceDaily, device_daily)
    db.commit()

    _update_today_counts(db, as_of)
    db.commit()

    return {"seeded": True, "source": "generated", "listings": len(listings),
            "market_days": len(market_daily), "device_days": len(device_daily)}


def refresh_market(db: Session) -> dict:
    """Re-build current listings.

    * real mode -> re-run the live scraper layer (per-platform mock fallback).
    * mock mode -> regenerate the deterministic mock market offline (no network),
      so the demo's "Refresh" stays instant and reproducible.
    """
    cfg = get_config()
    as_of = as_of_date()

    if cfg.infra.data_source == "real":
        # Retail refresh only — the scraped B2B segment is owned by the daily
        # refresh_b2b cycle and must NOT be overwritten with synthetic rows.
        listings, report = run_all_scrapers(as_of)
        listings += generate_extended_listings(cfg, as_of, build_extra_rng(cfg))
        live = sum(r["count"] for r in report if r["source"] == "live")
        mock = sum(r["count"] for r in report if r["source"] == "mock")

        db.execute(delete(Listing).where(Listing.segment == "retail"))
        db.commit()
        _insert_listings(db, listings)
        db.commit()
        _update_today_counts(db, as_of)
        db.commit()
        return {
            "refreshed": True,
            "data_source": cfg.infra.data_source,
            "total_listings": len(listings),
            "live_listings": live,
            "mock_listings": mock,
            "platforms": report,
        }
    else:
        listings = generate_listings(cfg, as_of, build_rng(cfg))
        listings += generate_extended_listings(cfg, as_of, build_extra_rng(cfg))
        listings += generate_maple_listings(cfg, as_of, build_maple_rng(cfg))
        listings += generate_b2b_listings(cfg, as_of, build_b2b_rng(cfg))
        report = [{"platform": "mock", "source": "mock", "count": len(listings)}]
        live, mock = 0, len(listings)

    db.execute(delete(Listing))
    db.commit()
    _insert_listings(db, listings)
    db.commit()

    _update_today_counts(db, as_of)
    db.commit()

    return {
        "refreshed": True,
        "data_source": cfg.infra.data_source,
        "total_listings": len(listings),
        "live_listings": live,
        "mock_listings": mock,
        "platforms": report,
    }


def refresh_b2b(db: Session) -> dict:
    """Re-scrape ONLY the B2B wholesale segment (the daily B2B job).

    Replaces every segment=='b2b' listing. In real mode this drives the
    authenticated B2B adapters (gsmExchange / IndiaMART / SuperSale via cookie
    injection), each falling back to its synthetic slice when no session is
    present. In mock mode it regenerates the deterministic synthetic B2B market.
    Retail listings are left untouched, so the B2C index/KPIs never move.
    """
    cfg = get_config()
    as_of = as_of_date()

    if cfg.infra.data_source == "real":
        listings, report = run_b2b_scrapers(as_of)
        live = sum(r["count"] for r in report if r["source"] == "live")
        mock = sum(r["count"] for r in report if r["source"] == "mock")
    else:
        listings = generate_b2b_listings(cfg, as_of, build_b2b_rng(cfg))
        report = [{"platform": "b2b_mock", "source": "mock", "count": len(listings)}]
        live, mock = 0, len(listings)

    db.execute(delete(Listing).where(Listing.segment == "b2b"))
    db.commit()
    if listings:
        _insert_listings(db, listings)
        db.commit()

    return {
        "refreshed": True,
        "segment": "b2b",
        "data_source": cfg.infra.data_source,
        "b2b_listings": len(listings),
        "live_listings": live,
        "mock_listings": mock,
        "platforms": report,
    }


def seed_on_startup() -> dict:
    init_db()
    cfg = get_config()
    if not cfg.infra.seed_on_startup:
        return {"seeded": False, "reason": "SEED_ON_STARTUP=false"}
    with SessionLocal() as db:
        return seed_all(db, force=False)
