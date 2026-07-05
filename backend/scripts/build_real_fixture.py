"""
Build the committed REAL-data fixture (deliverable: live-scraped demo data).

Scrapes the live market ONCE at build time and freezes it into a committed
fixture so the demo runs identically and offline in real mode:

    backend/app/fixtures/seed_market_real.json   (listings + back-cast history)
    backend/app/fixtures/price_model_real.joblib  (ML model trained on real data)

Pipeline:
  1. Run the real scraper layer (maplestore.in via Shopify JSON = real Maple
     inventory; competitors best-effort with mock fallback).
  2. Compute today's per-device market fair value (competitor-only).
  3. Back-cast a credible (modeled) market history anchored to those values.
  4. Train the ML pricing model on the real competitor data.
  5. Write the JSON fixture.

Usage (from backend/):
    python -m scripts.build_real_fixture
    python -m scripts.build_real_fixture --as-of 2026-06-16
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

DEFAULT_OUT = Path("app") / "fixtures" / "seed_market_real.json"


def _build(as_of: str, out: Path) -> None:
    os.environ["MAPLE_AS_OF"] = as_of
    os.environ["MAPLE_DATA_SOURCE"] = "real"
    tmp = Path(tempfile.gettempdir()) / "maple_real_fixture_build.db"
    if tmp.exists():
        tmp.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp.as_posix()}"

    # Deferred imports so the env vars above take effect first.
    from sqlalchemy import delete, select

    from app.agents.base import Agent
    from app.config import get_config
    from app.db import SessionLocal, engine, init_db
    from app.ml.train import train_from_listings
    from app.mock_data import (
        build_rng,
        build_extra_rng,
        generate_history_real,
        generate_extended_listings,
    )
    from app.models import DeviceDaily, Listing, MarketDaily
    from app.scrapers import run_all_scrapers, run_b2b_scrapers
    from app.seed import _insert_listings, _update_today_counts
    from app.util import as_of_date

    cfg = get_config()
    as_of_d = as_of_date()
    init_db()

    # 1. Live scrape (Maple real + competitors best-effort/mock).
    print("[build-real] scraping live sources …")
    listings, report = run_all_scrapers(as_of_d)
    for r in report:
        print(f"    {r['platform']:<14} {r['source']:<5} {r['count']}")

    # Non-iPhone Apple extras (IN) are synthesized on their own RNG stream
    # (retail benchmark untouched) so real mode keeps full catalogue coverage.
    listings += generate_extended_listings(cfg, as_of_d, build_extra_rng(cfg))

    # B2B wholesale segment: scraped LIVE (gsmExchange trading floor +
    # IndiaMART directory). Each adapter falls back to its synthetic slice on
    # failure, so the build always completes.
    print("[build-real] scraping live B2B wholesale sources …")
    b2b_listings, b2b_report = run_b2b_scrapers(as_of_d)
    for r in b2b_report:
        print(f"    {r['platform']:<18} {r['source']:<5} {r['count']}")
    listings += b2b_listings
    report = report + b2b_report
    print(f"[build-real] + extras + B2B -> {len(listings)} total listings")

    with SessionLocal() as db:
        db.execute(delete(Listing))
        db.execute(delete(MarketDaily))
        db.execute(delete(DeviceDaily))
        db.commit()
        _insert_listings(db, listings)
        db.commit()

        # 2. Today's real fair value per SKU (competitor-only; own excluded).
        valuations = Agent(cfg).valuations(db, region="IN")
        fair_today = {sku: v.fair.fair_value for sku, v in valuations.items() if v.fair.fair_value}
        print(f"[build-real] fair values computed for {len(fair_today)} SKUs")

        # 3. Back-cast history anchored to the real values.
        market_daily, device_daily = generate_history_real(cfg, as_of_d, fair_today, build_rng(cfg))
        db.bulk_insert_mappings(MarketDaily, market_daily)
        db.bulk_insert_mappings(DeviceDaily, device_daily)
        db.commit()
        _update_today_counts(db, as_of_d)
        db.commit()

        # 4. Train the ML model on the real competitor market.
        comp_listings = Agent(cfg).load_listings(db, region="IN")  # own excluded
        model = train_from_listings(comp_listings, as_of=as_of_d, cfg=cfg)
        print(f"[build-real] ML model trained: {model.metrics}")

        # 5. Export rows for the committed fixture.
        listings_rows = [_row(r, _LISTING_FIELDS) for r in db.scalars(select(Listing))]
        market_rows = [_row(r, _MARKET_FIELDS) for r in db.scalars(select(MarketDaily))]
        device_rows = [_row(r, _DEVICE_FIELDS) for r in db.scalars(select(DeviceDaily))]

    payload = {
        "meta": {
            "as_of": as_of,
            "data_source": "real",
            "scrape_report": report,
            "counts": {
                "listings": len(listings_rows),
                "market_daily": len(market_rows),
                "device_daily": len(device_rows),
            },
        },
        "listings": listings_rows,
        "market_daily": market_rows,
        "device_daily": device_rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str))
    size_kb = out.stat().st_size / 1024
    print(
        f"[build-real] wrote {out} "
        f"({len(listings_rows)} listings, {len(market_rows)} index days, "
        f"{len(device_rows)} device-days, {size_kb:.0f} KB)"
    )

    engine.dispose()
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass


_LISTING_FIELDS = (
    "platform", "region", "segment", "sku", "series", "model", "variant", "storage",
    "battery_health", "condition", "raw_condition", "city",
    "asking_price", "asking_price_native", "currency", "seller_type", "quantity",
    "color", "listing_title", "seller_name", "seller_rating", "seller_reviews",
    "warranty", "accessories", "lock_status", "verified", "negotiable", "views",
    "listing_date", "url",
)
_MARKET_FIELDS = ("day", "index_value", "prev_index_value", "movement_pct", "total_active_listings")
_DEVICE_FIELDS = ("day", "sku", "series", "model", "variant", "storage", "fair_value", "listing_count")


def _row(obj, fields: tuple[str, ...]) -> dict:
    out: dict = {}
    for f in fields:
        v = getattr(obj, f)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[f] = v
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=os.getenv("MAPLE_AS_OF", "2026-06-16"))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    _build(args.as_of, Path(args.out))


if __name__ == "__main__":
    main()
