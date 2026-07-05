"""
Synthetic but internally-consistent market generator.

When live scraping is blocked, the whole system still has to *work* and the
agents have to surface *real* signal.  We achieve that by generating listings
from a hidden ground-truth value model:

    true_superb_value(device, day)
        = MSRP * depreciation(age) * variant_retention

and then projecting each listing through the SAME multipliers the pricing
engine inverts:

    asking_price = true_value * condition_mult * city_mult * platform_index * noise

Because the multipliers are shared with config, the Market Pricing Agent
recovers the hidden value, the Arbitrage Agent finds the city spreads we baked
in, and the Dubai Agent finds the AED gap — i.e. the demo tells a true story.
"""
from __future__ import annotations

import math
import random
import zlib
from datetime import date, timedelta

from .catalog import Device, ExtraDevice, EXTRA_DEVICES, all_devices, iphone_devices, device_age_months
from .config import (
    DUBAI_CITIES,
    INDIA_CITIES,
    MapleConfig,
    get_config,
)

# Competitor grade vocabularies — every phrase normalizes back to the Maple
# grade it is listed under (see normalization.DEFAULT_GRADE_MAP), but platforms
# use different words, which is exactly what the normalizer has to handle.
GRADE_SYNONYMS: dict[str, list[str]] = {
    "Almost New": ["Mint", "Like New", "Pristine", "Open Box"],
    "Superb": ["Excellent", "Superb", "Very Good"],
    "Good": ["Good", "Fine"],
    "Fair": ["Fair", "Average", "Acceptable"],
}

# Relative trading liquidity, used to size listing counts (creates supply gaps).
_SERIES_LIQUIDITY = {13: 0.70, 14: 0.90, 15: 1.10, 16: 1.00, 17: 0.60}
_VARIANT_POP = {"Base": 1.0, "Plus": 0.55, "Pro": 1.0, "Pro Max": 1.25, "Mini": 0.5}
_STORAGE_POP = {"128GB": 1.0, "256GB": 1.1, "512GB": 0.6, "1TB": 0.35}
_PLATFORM_VOLUME = {
    "cashify": 1.0,
    "controlz": 0.7,
    "olx": 1.4,
    "quikr": 1.0,
    "facebook": 1.1,
    "apple_tradein": 0.5,
    "dubai_resale": 0.8,
}
_PLATFORM_SELLER = {
    "cashify": "certified_refurbisher",
    "controlz": "certified_refurbisher",
    "olx": "individual",
    "quikr": "individual",
    "facebook": "individual",
    "apple_tradein": "oem_program",
    "dubai_resale": "individual",
}

# --------------------------------------------------------------------------- #
# Publicly-scrapable listing detail (colours, warranty, seller, accessories…)
# These are derived from a per-listing *local* RNG seeded off the (already
# computed) listing URL, so they are fully deterministic but DO NOT consume the
# shared market RNG stream — prices and the index stay byte-for-byte identical.
# --------------------------------------------------------------------------- #
_PRO_COLORS: dict[int, list[str]] = {
    13: ["Graphite", "Silver", "Gold", "Sierra Blue"],
    14: ["Space Black", "Silver", "Gold", "Deep Purple"],
    15: ["Natural Titanium", "Blue Titanium", "White Titanium", "Black Titanium"],
    16: ["Black Titanium", "Natural Titanium", "White Titanium", "Desert Titanium"],
    17: ["Silver", "Cosmic Orange", "Deep Blue", "Black Titanium"],
}
_STD_COLORS: dict[int, list[str]] = {
    13: ["Midnight", "Starlight", "Blue", "Pink", "Green", "(PRODUCT)RED"],
    14: ["Midnight", "Starlight", "Blue", "Purple", "Yellow", "(PRODUCT)RED"],
    15: ["Black", "Blue", "Green", "Yellow", "Pink"],
    16: ["Black", "White", "Pink", "Teal", "Ultramarine"],
    17: ["Black", "Lavender", "Sage", "Mist Blue", "White"],
}

_FAMILY_COLORS = {
    "iPad": ["Space Gray", "Silver", "Blue", "Pink", "Purple", "Starlight", "Yellow"],
    "Mac": ["Midnight", "Starlight", "Space Gray", "Silver", "Space Black"],
    "Watch": ["Midnight", "Starlight", "Silver", "Jet Black", "Rose Gold", "Natural Titanium"],
    "AirPods": ["White"],
}

_SELLER_FIRST = [
    "Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anjali", "Karthik", "Neha",
    "Arjun", "Pooja", "Rohan", "Divya", "Sandeep", "Meera", "Faisal", "Aisha",
]
_SELLER_LAST_INITIAL = list("SKMRPGVDTNCBJ")
_UAE_SELLER_FIRST = ["Omar", "Layla", "Hassan", "Fatima", "Yusuf", "Mariam", "Bilal", "Zara"]

_MARKET_ACCESSORIES = [
    "Full box & accessories", "Box, charger & cable", "Original box only",
    "Phone + case & charger", "Phone only (no box)",
]
_REFURB_ACCESSORIES = ["Box, cable & adapter", "Box & cable", "Unboxed (cable only)"]


def _colors_for(family: str, series: int | None, variant: str | None) -> list[str]:
    """Return color options for a device. For iPhone, use series/variant tables; else use family colors."""
    if family == "iPhone":
        table = _PRO_COLORS if variant in ("Pro", "Pro Max") else _STD_COLORS
        return table.get(series, _STD_COLORS[16])
    return _FAMILY_COLORS.get(family, ["White"])


def _listing_detail(
    *, platform, device, condition, raw_grade, storage, age_days, lrng
) -> dict:
    """Synthesize the extra fields a scraper would lift off a real listing page."""
    family = getattr(device, 'family', 'iPhone')
    series = getattr(device, 'series', None)
    variant = getattr(device, 'variant', None)
    color = lrng.choice(_colors_for(family, series, variant))
    role = platform.role

    if role == "own":
        # Maple's own store: certified pre-owned with a Maple warranty.
        seller_name = "Maple Store"
        seller_rating = round(lrng.uniform(4.6, 4.9), 1)
        seller_reviews = lrng.randint(1200, 9000)
        warranty = "6-month Maple warranty"
        accessories = lrng.choice(_REFURB_ACCESSORIES)
        verified = True
        negotiable = False
        views = lrng.randint(150, 6000)
        title = f"{device.model} - {storage} - {color} - Pre-owned"
    elif role == "recommerce":
        seller_name = f"{platform.name} Certified"
        seller_rating = round(lrng.uniform(4.4, 4.9), 1)
        seller_reviews = lrng.randint(800, 16000)
        warranty = f"6-month {platform.name} warranty"
        accessories = lrng.choice(_REFURB_ACCESSORIES)
        verified = True
        negotiable = False
        views = lrng.randint(200, 9000)
        title = f"Refurbished {device.model} {storage} {color} — {raw_grade} grade"
    elif role == "tradein":
        seller_name = platform.name
        seller_rating = 5.0
        seller_reviews = 0
        warranty = "OEM trade-in quote"
        accessories = "—"
        verified = True
        negotiable = False
        views = 0
        title = f"{device.model} {storage} — instant trade-in quote"
    else:  # marketplace
        pool = _UAE_SELLER_FIRST if platform.region == "AE" else _SELLER_FIRST
        seller_name = f"{lrng.choice(pool)} {lrng.choice(_SELLER_LAST_INITIAL)}."
        seller_rating = round(lrng.uniform(3.7, 4.9), 1)
        seller_reviews = lrng.randint(2, 240)
        # Newer flagships sometimes still carry residual Apple warranty.
        if device.series >= 16 and lrng.random() < 0.35:
            warranty = f"Apple warranty · {lrng.randint(1, 9)}mo left"
        elif lrng.random() < 0.2:
            warranty = "Seller warranty · 15 days"
        else:
            warranty = "No warranty"
        accessories = lrng.choice(_MARKET_ACCESSORIES)
        verified = lrng.random() < 0.35
        negotiable = lrng.random() < 0.8
        views = lrng.randint(40, 4200)
        tag = " (Negotiable)" if negotiable else ""
        title = f"{device.model} {storage} {color} | {raw_grade}{tag}"

    return {
        "color": color,
        "listing_title": title,
        "seller_name": seller_name,
        "seller_rating": seller_rating,
        "seller_reviews": seller_reviews,
        "warranty": warranty,
        "accessories": accessories,
        "lock_status": "Factory Unlocked",
        "verified": verified,
        "negotiable": negotiable,
        "views": views,
    }


def depreciation(age_months: float) -> float:
    """Fraction of MSRP retained by a 'Superb' used unit at a given age."""
    return 0.30 + 0.62 * math.exp(-0.030 * age_months)


def _variant_retention(variant: str) -> float:
    if variant in ("Pro", "Pro Max"):
        return 1.04
    if variant == "Mini":
        return 0.97
    return 1.0


def true_superb_value(device: Device, as_of: date) -> float:
    """Hidden ground-truth fair value (Superb grade, Delhi, retail reference)."""
    age = device_age_months(device, as_of)
    return device.msrp * depreciation(age) * _variant_retention(device.variant)


def _sentiment_series(days: int, rng: random.Random) -> list[float]:
    """Smooth market-sentiment multiplier per day, normalized so today == 1.0."""
    vals: list[float] = []
    drift = 0.0
    for t in range(days):
        cyclical = 0.012 * math.sin(2 * math.pi * t / 31.0)
        drift += rng.gauss(-0.0003, 0.0016)  # slow downward used-market drift
        drift = max(-0.05, min(0.05, drift))
        vals.append(1.0 + cyclical + drift)
    # Normalize so the most recent day is exactly 1.0 (anchors current listings).
    last = vals[-1]
    return [v / last for v in vals]


def _weighted_choice(rng: random.Random, options: list[str], weights: list[float]) -> str:
    return rng.choices(options, weights=weights, k=1)[0]


def _condition_for(age_months: float, rng: random.Random) -> str:
    newness = max(0.0, min(1.0, 1.0 - age_months / 60.0))
    weights = {
        "Almost New": 0.08 + 0.27 * newness,
        "Superb": 0.30 + 0.04 * newness,
        "Good": 0.37 - 0.12 * newness,
        "Fair": 0.25 - 0.19 * newness,
    }
    grades = list(weights.keys())
    return _weighted_choice(rng, grades, [max(0.02, weights[g]) for g in grades])


def _battery_for(condition: str, age_months: float, rng: random.Random) -> int:
    base = {"Almost New": 98, "Superb": 93, "Good": 88, "Fair": 82}[condition]
    base -= int(age_months * 0.12)
    val = base + rng.randint(-2, 2)
    return max(76, min(100, val))


def _listing_count(device: Device, platform_key: str, rng: random.Random) -> int:
    base = 4.0
    expected = (
        base
        * _SERIES_LIQUIDITY[device.series]
        * _VARIANT_POP[device.variant]
        * _STORAGE_POP[device.storage]
        * _PLATFORM_VOLUME.get(platform_key, 0.8)
    )
    # Poisson-ish via rounding with jitter; can legitimately be 0 (coverage gap).
    jitter = rng.uniform(0.7, 1.3)
    return max(0, int(round(expected * jitter)))


def _pick_city(region: str, rng: random.Random, platform_key: str) -> str:
    if platform_key == "apple_tradein":
        return "Delhi"  # OEM program quotes are national; anchor to Delhi (mult 1.0)
    if region == "AE":
        return _weighted_choice(rng, DUBAI_CITIES, [0.6, 0.2, 0.2])
    # India: bias toward metros
    weights = [1.4, 1.3, 1.3, 1.0, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5]
    return _weighted_choice(rng, INDIA_CITIES, weights)


def _noise(rng: random.Random) -> float:
    n = math.exp(rng.gauss(0.0, 0.05))
    if rng.random() < 0.05:  # occasional outlier (scam / typo / desperate seller)
        n *= rng.choice([0.78, 1.22])
    return n


def generate_platform_listings(
    cfg: MapleConfig, platform_key: str, as_of: date, rng: random.Random
) -> list[dict]:
    """Generate mock listings for a single platform (used as scraper fallback)."""
    platform = cfg.platform(platform_key)
    if platform is None:
        return []
    listings: list[dict] = []
    for device in iphone_devices():
        # Dubai resale skews to newer flagships; skip oldest series there.
        if platform.key == "dubai_resale" and device.series <= 13:
            continue
        true_val = true_superb_value(device, as_of)
        count = _listing_count(device, platform.key, rng)
        for _ in range(count):
            listings.append(
                _make_listing(cfg, device, platform, true_val, as_of, rng)
            )
    return listings


def _make_listing(cfg, device, platform, true_val, as_of, rng, condition=None) -> dict:
    if condition is None:
        condition = _condition_for(device_age_months(device, as_of), rng)
    city = _pick_city(platform.region, rng, platform.key)
    cond_mult = cfg.condition_multipliers[condition]
    city_mult = cfg.city_multipliers.get(city, 1.0)
    inr_price = true_val * cond_mult * city_mult * platform.index * _noise(rng)
    inr_price = round(inr_price / 50) * 50  # round to ₹50

    if platform.currency == "AED":
        native = round(inr_price / cfg.aed_to_inr / 5) * 5
        inr_for_storage = round(native * cfg.aed_to_inr)
    else:
        native = inr_price
        inr_for_storage = inr_price

    battery = _battery_for(condition, device_age_months(device, as_of), rng)
    # Stable per-platform pick (crc32, not hash(): str hash is randomized per
    # process and would break demo reproducibility). Also leaves the rng stream
    # untouched so seeded numbers stay identical.
    raw_grade = GRADE_SYNONYMS[condition][
        (zlib.crc32(platform.key.encode()) >> 3) % len(GRADE_SYNONYMS[condition])
    ]
    age_days = int(rng.triangular(0, 45, 6))  # recency-skewed
    listing_date = as_of - timedelta(days=age_days)

    url = f"https://demo.maple.local/{platform.key}/{device.sku}/{rng.randint(10000, 99999)}"

    # Per-listing deterministic detail, seeded off the (already-drawn) URL so it
    # never touches the shared market RNG stream (keeps prices/index identical).
    lrng = random.Random(zlib.crc32(url.encode()))
    detail = _listing_detail(
        platform=platform,
        device=device,
        condition=condition,
        raw_grade=raw_grade,
        storage=device.storage,
        age_days=age_days,
        lrng=lrng,
    )

    return {
        "platform": platform.key,
        "region": platform.region,
        "sku": device.sku,
        "series": device.series,
        "model": device.model,
        "variant": device.variant,
        "storage": device.storage,
        "battery_health": battery,
        "condition": condition,
        "raw_condition": raw_grade,
        "city": city,
        "asking_price": float(inr_for_storage),
        "asking_price_native": float(native),
        "currency": platform.currency,
        "seller_type": _PLATFORM_SELLER.get(platform.key, "individual"),
        "listing_date": listing_date,
        "url": url,
        **detail,
    }


def generate_listings(cfg: MapleConfig, as_of: date, rng: random.Random) -> list[dict]:
    """Generate the full mock market across every configured COMPETITOR platform.

    Maple's own store (role == 'own') is generated separately by
    ``generate_maple_listings`` on a dedicated RNG, so it never perturbs the
    competitor RNG stream and is excluded from the competitor benchmark.
    """
    listings: list[dict] = []
    for platform in cfg.platforms:
        # Own store and B2B wholesale sources run on their OWN RNG streams
        # (generate_maple_listings / generate_b2b_listings) so the competitor
        # stream — and the 96.43 index it drives — stays byte-identical.
        if platform.role in ("own", "b2b_wholesale"):
            continue
        listings.extend(generate_platform_listings(cfg, platform.key, as_of, rng))
    return listings


def generate_history(
    cfg: MapleConfig, as_of: date, rng: random.Random
) -> tuple[list[dict], list[dict]]:
    """Return (market_daily_rows, device_daily_rows)."""
    days = max(1, cfg.infra.history_days)
    sentiment = _sentiment_series(days, rng)
    start = as_of - timedelta(days=days - 1)
    devices = iphone_devices()

    device_daily: list[dict] = []
    basket_by_day: list[float] = []

    for i in range(days):
        d = start + timedelta(days=i)
        s = sentiment[i]
        basket = 0.0
        for device in devices:
            fv = true_superb_value(device, d) * s
            # light idiosyncratic wiggle per device-day
            fv *= math.exp(rng.gauss(0.0, 0.006))
            fv = round(fv, 0)
            device_daily.append(
                {
                    "day": d,
                    "sku": device.sku,
                    "series": device.series,
                    "model": device.model,
                    "variant": device.variant,
                    "storage": device.storage,
                    "fair_value": fv,
                    "listing_count": 0,  # filled by seed from live listings for today
                }
            )
            basket += fv
        basket_by_day.append(basket)

    base = basket_by_day[0] or 1.0
    market_daily: list[dict] = []
    prev_index = 0.0
    for i in range(days):
        d = start + timedelta(days=i)
        index_value = round(100.0 * basket_by_day[i] / base, 2)
        movement = round((index_value - prev_index) / prev_index * 100, 2) if prev_index else 0.0
        market_daily.append(
            {
                "day": d,
                "index_value": index_value,
                "prev_index_value": round(prev_index, 2),
                "movement_pct": movement,
                "total_active_listings": 0,  # filled by seed
            }
        )
        prev_index = index_value
    return market_daily, device_daily


def generate_history_real(
    cfg: MapleConfig, as_of: date, fair_today: dict[str, float], rng: random.Random
) -> tuple[list[dict], list[dict]]:
    """Back-cast market history anchored to TODAY's real fair values.

    A one-shot scrape has no past, so we reconstruct a credible (and clearly
    *modeled*) history: today's per-device fair value is the real scraped value;
    earlier days apply the same gentle market sentiment and the depreciation
    shape (older = slightly more retained value), so the trend charts read
    honestly without pretending we scraped the past.
    """
    days = max(1, cfg.infra.history_days)
    sentiment = _sentiment_series(days, rng)  # normalized so today == 1.0
    start = as_of - timedelta(days=days - 1)
    devices = [d for d in iphone_devices() if d.sku in fair_today]

    device_daily: list[dict] = []
    basket_by_day: list[float] = []
    for i in range(days):
        d = start + timedelta(days=i)
        s = sentiment[i]
        basket = 0.0
        for dev in devices:
            anchor = fair_today[dev.sku]
            # Aging factor relative to today (units were younger in the past).
            age_factor = depreciation(device_age_months(dev, d)) / depreciation(
                device_age_months(dev, as_of)
            )
            fv = round(anchor * s * age_factor * math.exp(rng.gauss(0.0, 0.006)), 0)
            device_daily.append({
                "day": d, "sku": dev.sku, "series": dev.series, "model": dev.model,
                "variant": dev.variant, "storage": dev.storage,
                "fair_value": fv, "listing_count": 0,
            })
            basket += fv
        basket_by_day.append(basket)

    base = basket_by_day[0] or 1.0
    market_daily: list[dict] = []
    prev_index = 0.0
    for i in range(days):
        d = start + timedelta(days=i)
        index_value = round(100.0 * basket_by_day[i] / base, 2)
        movement = round((index_value - prev_index) / prev_index * 100, 2) if prev_index else 0.0
        market_daily.append({
            "day": d, "index_value": index_value, "prev_index_value": round(prev_index, 2),
            "movement_pct": movement, "total_active_listings": 0,
        })
        prev_index = index_value
    return market_daily, device_daily


def build_rng(cfg: MapleConfig | None = None) -> random.Random:
    cfg = cfg or get_config()
    return random.Random(cfg.infra.mock_seed)


def build_extra_rng(cfg: MapleConfig | None = None) -> random.Random:
    """Separate RNG for extended devices, so iPhone RNG stream stays identical."""
    cfg = cfg or get_config()
    return random.Random(cfg.infra.mock_seed + 1)


def build_maple_rng(cfg: MapleConfig | None = None) -> random.Random:
    """Separate RNG for Maple's own-store listings (keeps competitor stream identical)."""
    cfg = cfg or get_config()
    return random.Random(cfg.infra.mock_seed + 2)


# Maple sells CERTIFIED pre-owned, so its condition mix skews high (no 'Fair').
_MAPLE_CONDITION_WEIGHTS = {"Almost New": 0.28, "Superb": 0.52, "Good": 0.20}


def _maple_condition(rng: random.Random) -> str:
    grades = list(_MAPLE_CONDITION_WEIGHTS)
    return _weighted_choice(rng, grades, [_MAPLE_CONDITION_WEIGHTS[g] for g in grades])


def generate_maple_listings(cfg: MapleConfig, as_of: date, rng: random.Random) -> list[dict]:
    """Synthesize Maple's OWN-store iPhone inventory (mock mode).

    Mirrors what the real maplestore.in Shopify scrape produces: certified
    pre-owned units priced at Maple's retail level (platform.index). Excluded
    from the competitor benchmark; consumed only by the Maple comparison tab.
    """
    platform = cfg.own_platform()
    if platform is None:
        return []
    listings: list[dict] = []
    for device in iphone_devices():
        true_val = true_superb_value(device, as_of)
        # Maple stocks the catalogue but not every SKU deeply.
        expected = (
            2.6
            * _SERIES_LIQUIDITY[device.series]
            * _VARIANT_POP[device.variant]
            * _STORAGE_POP[device.storage]
        )
        count = max(0, int(round(expected * rng.uniform(0.6, 1.3))))
        for _ in range(count):
            listing = _make_listing(
                cfg, device, platform, true_val, as_of, rng,
                condition=_maple_condition(rng),
            )
            # Present like a real maplestore.in product.
            listing["raw_condition"] = "Pre-owned"
            listing["seller_type"] = "maple_store"
            listing["url"] = (
                f"https://maplestore.in/products/"
                f"{device.model.lower().replace(' ', '-')}-{device.storage.lower()}-{rng.randint(1000, 9999)}"
            )
            listings.append(listing)
    return listings


# Family popularity weights for listing count estimation.
_FAMILY_POPULARITY = {
    "iPad": 1.0,
    "Mac": 0.8,
    "Watch": 0.7,
    "AirPods": 0.9,
}


def _extended_listing_count(device: ExtraDevice, platform_key: str, rng: random.Random) -> int:
    """Estimate listing count for a non-iPhone device."""
    base = 3.0
    family_pop = _FAMILY_POPULARITY.get(device.family, 0.8)
    platform_vol = _PLATFORM_VOLUME.get(platform_key, 0.8)
    expected = base * family_pop * platform_vol
    # Add jitter and storage-based variation
    jitter = rng.uniform(0.6, 1.3)
    return max(0, int(round(expected * jitter)))


def generate_extended_listings(cfg: MapleConfig, as_of: date, rng: random.Random) -> list[dict]:
    """Generate mock listings for non-iPhone devices (IN region only)."""
    listings: list[dict] = []
    for platform in cfg.platforms:
        # Only include IN-region platforms (skip Dubai for extended devices).
        # Maple's own store and B2B wholesale sources are handled separately
        # (generate_maple_listings / generate_b2b_listings) on their own RNGs.
        if platform.region != "IN" or platform.role in ("own", "b2b_wholesale"):
            continue
        for device in EXTRA_DEVICES:
            true_val = true_superb_value(device, as_of)
            count = _extended_listing_count(device, platform.key, rng)
            for _ in range(count):
                listings.append(
                    _make_listing(cfg, device, platform, true_val, as_of, rng)
                )
    return listings


# --------------------------------------------------------------------------- #
# B2B / wholesale segment (separate RNG stream — keeps the retail index at 96.43)
# --------------------------------------------------------------------------- #
# Each B2B source covers a different slice of the catalogue, mirroring reality:
#   gsmExchange      -> phones + tablets + accessories (NOT laptops), global.
#   IndiaMART        -> everything incl. MacBooks/laptops, India.
#   Cashify SuperSale-> phones (dormant adapter; modeled floor only).
_B2B_FAMILY_COVERAGE: dict[str, set[str]] = {
    "gsmexchange": {"iPhone", "iPad", "Watch", "AirPods"},
    "indiamart": {"iPhone", "iPad", "Mac", "Watch", "AirPods"},
    "cashify_supersale": {"iPhone"},
}

# Hub city used to label a B2B lot per region (B2B doesn't feed city arbitrage —
# that's retail-only and excludes b2b via load_listings — so this is just a tag).
_REGION_HUB: dict[str, str] = {
    "IN": "Mumbai", "AE": "Dubai", "US": "New York",
    "GB": "London", "SG": "Singapore", "HK": "Hong Kong",
}

_B2B_SUPPLIERS_GLOBAL = [
    "Shenzhen Cellular Co", "HK Tech Distribution", "Dubai Re-Export FZE",
    "Gulf Mobile Trading", "Pacific Wholesale Inc", "EuroStock Traders",
]
_B2B_SUPPLIERS_IN = [
    "Remac Mumbai", "Delhi Mobile Traders", "Nehru Place Distributors",
    "SP Road Wholesale", "Chennai Gadget Hub",
]

# Lot sizes a wholesaler offers, weighted toward small/medium lots.
_B2B_LOT_SIZES = [5, 10, 25, 50, 100, 250]
_B2B_LOT_WEIGHTS = [0.30, 0.27, 0.20, 0.13, 0.07, 0.03]


def build_b2b_rng(cfg: MapleConfig | None = None) -> random.Random:
    """Separate RNG for the B2B segment (seed+3) — retail streams stay identical."""
    cfg = cfg or get_config()
    return random.Random(cfg.infra.mock_seed + 3)


def _b2b_volume_discount(cfg: MapleConfig, qty: int) -> float:
    """Discount off single-unit wholesale for a given lot size."""
    disc = 0.0
    for tier in sorted(cfg.b2b.volume_tiers, key=lambda t: t[0]):
        if qty >= tier[0]:
            disc = tier[1]
    return disc


def _b2b_listing_count(device, platform, rng: random.Random) -> int:
    """How many distinct lot offers exist for a device on a source (often 0–2)."""
    family = getattr(device, "family", "iPhone")
    base = 0.9 if family == "iPhone" else 0.6 * _FAMILY_POPULARITY.get(family, 0.7)
    return max(0, int(round(base * rng.uniform(0.0, 1.8))))


def _make_b2b_listing(cfg, device, platform, true_val, region, region_level, as_of, rng) -> dict:
    """One wholesale lot offer: a per-unit price, a grade and a lot quantity."""
    b2b = cfg.b2b
    qty = rng.choices(_B2B_LOT_SIZES, weights=_B2B_LOT_WEIGHTS, k=1)[0]
    grade = _weighted_choice(
        rng, list(b2b.lot_grade_mix), [b2b.lot_grade_mix[g] for g in b2b.lot_grade_mix]
    )
    cond_mult = cfg.condition_multipliers.get(grade, 1.0)
    disc = _b2b_volume_discount(cfg, qty)

    # Wholesale per-unit price: source level (platform.index) × region level ×
    # grade × volume discount × noise. Always stored in INR for comparability.
    unit_inr = true_val * platform.index * region_level * cond_mult * (1 - disc) * _noise(rng)
    unit_inr = round(unit_inr / 50) * 50

    if platform.currency == "USD":
        native = round(unit_inr / cfg.usd_to_inr, 0)
    elif platform.currency == "AED":
        native = round(unit_inr / cfg.aed_to_inr, 0)
    else:
        native = unit_inr

    city = _REGION_HUB.get(region, "Mumbai")
    supplier_pool = _B2B_SUPPLIERS_GLOBAL if platform.region == "GL" else _B2B_SUPPLIERS_IN
    supplier = rng.choice(supplier_pool)
    age_days = int(rng.triangular(0, 21, 4))
    listing_date = as_of - timedelta(days=age_days)
    url = f"https://demo.maple.local/b2b/{platform.key}/{device.sku}/{rng.randint(10000, 99999)}"

    return {
        "platform": platform.key,
        "region": region,
        "segment": "b2b",
        "sku": device.sku,
        "series": getattr(device, "series", 0),
        "model": device.model,
        "variant": getattr(device, "variant", ""),
        "storage": device.storage,
        "battery_health": {"Almost New": 98, "Superb": 92, "Good": 87, "Fair": 81}.get(grade, 90),
        "condition": grade,
        "raw_condition": f"{grade} (wholesale lot)",
        "city": city,
        "asking_price": float(unit_inr),         # per-unit INR
        "asking_price_native": float(native),     # per-unit, source currency
        "currency": platform.currency,
        "quantity": int(qty),                      # lot size on offer
        "seller_type": "wholesaler",
        "seller_name": supplier,
        "seller_rating": round(rng.uniform(4.0, 4.9), 1),
        "seller_reviews": rng.randint(5, 400),
        "warranty": "Trade terms (no consumer warranty)",
        "accessories": "Bulk packed",
        "lock_status": "Factory Unlocked",
        "verified": rng.random() < 0.7,
        "negotiable": True,
        "views": 0,
        "color": "",
        "listing_title": f"{device.model} {device.storage} · {grade} · lot of {qty} ({_REGION_HUB.get(region, region)})",
        "listing_date": listing_date,
        "url": url,
    }


def generate_b2b_listings(cfg: MapleConfig, as_of: date, rng: random.Random) -> list[dict]:
    """Synthesize the B2B wholesale market across every b2b_wholesale source.

    Spread over global regions for gsmExchange (the live global price map);
    India-only for IndiaMART / SuperSale. Covers iPhones AND the non-phone Apple
    families (MacBooks, iPads, Watch, AirPods) per each source's real coverage.
    """
    listings: list[dict] = []
    devices = iphone_devices() + EXTRA_DEVICES
    for platform in cfg.b2b_platforms():
        coverage = _B2B_FAMILY_COVERAGE.get(platform.key, {"iPhone"})
        if platform.region == "GL":
            region_levels = dict(cfg.b2b.global_regions)
        else:
            region_levels = {platform.region: 1.0}
        for device in devices:
            if getattr(device, "family", "iPhone") not in coverage:
                continue
            true_val = true_superb_value(device, as_of)
            for region, region_level in region_levels.items():
                for _ in range(_b2b_listing_count(device, platform, rng)):
                    listings.append(
                        _make_b2b_listing(
                            cfg, device, platform, true_val, region, region_level, as_of, rng
                        )
                    )
    return listings
