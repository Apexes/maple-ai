"""
Build the committed seed fixture (deliverable: 'pre-built database').

This runs the synthetic market generator ONCE, at build time, and freezes the
*final* database state into a JSON fixture that ships in the repo:

    backend/app/fixtures/seed_market.json

At runtime the stack loads this fixture instead of generating data (see
app/seed.py -> load_fixture). That makes the demo deterministic and identical
on every machine, and removes any runtime dependency on the generator.

Usage (from backend/):
    python -m scripts.build_seed_fixture
    python -m scripts.build_seed_fixture --as-of 2026-06-11 --out app/fixtures/seed_market.json

Regenerate this whenever the catalog, config or generator logic changes.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

DEFAULT_AS_OF = "2026-06-11"
DEFAULT_OUT = Path("app") / "fixtures" / "seed_market.json"


def _build(as_of: str, out: Path) -> None:
    # Pin the as-of date BEFORE importing anything that reads it, and route the
    # build through a throwaway SQLite DB so we capture the exact final state
    # (listing counts are filled in by seed_all after the bulk insert).
    os.environ["MAPLE_AS_OF"] = as_of
    tmp = Path(tempfile.gettempdir()) / "maple_fixture_build.db"
    if tmp.exists():
        tmp.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp.as_posix()}"
    os.environ["SEED_ON_STARTUP"] = "true"

    # Imports are deferred so the env vars above take effect first.
    from sqlalchemy import select

    from app.db import SessionLocal, engine, init_db
    from app.models import DeviceDaily, Listing, MarketDaily
    from app.seed import seed_all

    init_db()  # create the schema in the throwaway build DB

    with SessionLocal() as db:
        # force=True and ignore_fixture=True: always (re)generate from the model,
        # never read a pre-existing fixture while building one.
        result = seed_all(db, force=True, ignore_fixture=True)
        print(f"[build-fixture] generated: {result}")

        listings = [_row(r, _LISTING_FIELDS) for r in db.scalars(select(Listing))]
        market = [_row(r, _MARKET_FIELDS) for r in db.scalars(select(MarketDaily))]
        devices = [_row(r, _DEVICE_FIELDS) for r in db.scalars(select(DeviceDaily))]

    payload = {
        "meta": {
            "as_of": as_of,
            "mock_seed": int(os.getenv("MAPLE_MOCK_SEED", "42")),
            "counts": {
                "listings": len(listings),
                "market_daily": len(market),
                "device_daily": len(devices),
            },
        },
        "listings": listings,
        "market_daily": market,
        "device_daily": devices,
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str))
    size_kb = out.stat().st_size / 1024
    print(
        f"[build-fixture] wrote {out} "
        f"({len(listings)} listings, {len(market)} index days, "
        f"{len(devices)} device-days, {size_kb:.0f} KB)"
    )

    # Release the SQLite file handle before removing the throwaway build DB
    # (Windows won't unlink a file that's still open).
    engine.dispose()
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass  # best-effort cleanup of a temp file


# Columns to persist per table. `id` and `created_at` are intentionally omitted
# so the loader lets the database assign them (keeps Postgres sequences sane).
_LISTING_FIELDS = (
    "platform", "region", "segment", "sku", "series", "model", "variant", "storage",
    "battery_health", "condition", "raw_condition", "city",
    "asking_price", "asking_price_native", "currency", "seller_type", "quantity",
    "color", "listing_title", "seller_name", "seller_rating", "seller_reviews",
    "warranty", "accessories", "lock_status", "verified", "negotiable", "views",
    "listing_date", "url",
)
_MARKET_FIELDS = (
    "day", "index_value", "prev_index_value", "movement_pct", "total_active_listings",
)
_DEVICE_FIELDS = (
    "day", "sku", "series", "model", "variant", "storage", "fair_value", "listing_count",
)


def _row(obj, fields: tuple[str, ...]) -> dict:
    out: dict = {}
    for f in fields:
        v = getattr(obj, f)
        # dates/datetimes -> ISO strings (json.dumps default=str also covers this,
        # but being explicit keeps the fixture stable and readable).
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[f] = v
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=DEFAULT_AS_OF, help="Pinned as-of date (YYYY-MM-DD)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Output fixture path")
    args = ap.parse_args()
    _build(args.as_of, Path(args.out))


if __name__ == "__main__":
    main()
