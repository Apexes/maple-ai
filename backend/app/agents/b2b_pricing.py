"""
B2B Pricing Agent — the wholesale segment brain.

Where the retail agents answer "what is a device worth to a consumer?", this
agent answers Maple's B2B question: **"what is the device worth in the trade,
in bulk, and how does that compare to retail?"** — modeled on the Cashify
SuperSale / gsmExchange / IndiaMART wholesale market.

It assembles:
  * a per-device wholesale view: observed B2B market value vs the B2C retail
    fair value, and the wholesale discount between them
  * a volume-tier price ladder (per-unit price drops as the lot grows)
  * a bulk-lot quote (mixed grades × quantities -> total + per-unit + margin)
  * the B2C↔B2B spread (the cross-segment opportunity of trading both sides)
  * a global price map (gsmExchange listings by region — the live world view)

The B2B segment is loaded with ``segment="b2b"`` so it is completely separate
from the retail benchmark (which never sees these listings).
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from sqlalchemy.orm import Session

from ..catalog import device_by_sku
from ..geo import COUNTRY_COORDS, country_latlng, country_name
from ..pricing import b2b_unit_economics, cost_breakdown, fair_market_value
from .base import Agent


class B2BPricingAgent(Agent):
    name = "b2b_pricing"
    title = "B2B Pricing Agent"

    def run(self, db: Session) -> dict:
        return self.overview(db)

    # ---- retail fair value lookup (the B2C reference) ------------------- #
    def _retail_fair(self, db: Session) -> dict[str, float]:
        vals = self.valuations(db, region="IN")  # retail, own excluded
        return {sku: v.fair.fair_value for sku, v in vals.items()}

    # ---- per-device wholesale overview ---------------------------------- #
    def overview(self, db: Session) -> dict:
        retail = self._retail_fair(db)
        b2b = self.load_listings(db, segment="b2b")
        by_sku = self.group_by_sku(b2b)

        devices = []
        for sku, rows in by_sku.items():
            device = device_by_sku(sku)
            if device is None:
                continue
            fv = fair_market_value(self.observations(rows), self.cfg)
            if fv is None:
                continue
            retail_fair = retail.get(sku)
            asks = [r.asking_price for r in rows]
            discount = (
                round((1 - fv.fair_value / retail_fair) * 100, 1)
                if retail_fair else None
            )
            devices.append(
                {
                    "sku": sku,
                    "model": device.model,
                    "family": getattr(device, "family", "iPhone"),
                    "series": getattr(device, "series", 0),
                    "storage": device.storage,
                    "retail_fair_value": retail_fair,
                    "b2b_market_value": fv.fair_value,        # normalized (Superb)
                    "b2b_market_median": round(statistics.median(asks)),  # raw per-unit
                    "wholesale_discount_pct": discount,        # how far below retail
                    "sources": len({r.platform for r in rows}),
                    "regions": len({r.region for r in rows}),
                    "lots": len(rows),
                    "units_available": sum(r.quantity for r in rows),
                    "confidence": fv.confidence,
                }
            )
        devices.sort(key=lambda d: (d["family"], -(d["retail_fair_value"] or 0)))
        return {
            "agent": self.title,
            "device_count": len(devices),
            "total_lots": len(b2b),
            "total_units": sum(r.quantity for r in b2b),
            "sources": sorted({r.platform for r in b2b}),
            "devices": devices,
        }

    # ---- volume-tier price ladder for one device ------------------------ #
    def volume_ladder(self, db: Session, sku: str, condition: str = "Superb") -> dict | None:
        device = device_by_sku(sku)
        if device is None:
            return None
        retail_fair = self._retail_fair(db).get(sku)
        if not retail_fair:
            return None
        ladder = [
            b2b_unit_economics(retail_fair, condition, int(tier[0]), self.cfg).to_dict()
            for tier in sorted(self.cfg.b2b.volume_tiers, key=lambda t: t[0])
        ]
        return {
            "sku": sku,
            "model": device.model,
            "condition": condition,
            "retail_fair_value": retail_fair,
            "ladder": ladder,
        }

    # ---- bulk-lot quote (the quote builder backend) --------------------- #
    def lot_quote(self, db: Session, items: list[dict]) -> dict:
        """items: [{sku, condition?, quantity}]. Returns per-line + totals."""
        retail = self._retail_fair(db)
        lines = []
        total_units = 0
        total_value = 0.0
        total_margin = 0.0
        for item in items:
            sku = item.get("sku")
            qty = int(item.get("quantity", 1) or 1)
            condition = item.get("condition", "Superb")
            device = device_by_sku(sku)
            retail_fair = retail.get(sku)
            if device is None or not retail_fair or qty <= 0:
                continue
            econ = b2b_unit_economics(retail_fair, condition, qty, self.cfg)
            line_total = econ.wholesale_unit * qty
            line_margin = econ.expected_gross_margin * qty
            lines.append(
                {
                    "sku": sku,
                    "model": device.model,
                    "condition": condition,
                    "quantity": qty,
                    "unit_price": econ.wholesale_unit,
                    "volume_discount_pct": econ.volume_discount_pct,
                    "line_total": round(line_total),
                    "unit_margin": econ.expected_gross_margin,
                    "line_margin": round(line_margin),
                }
            )
            total_units += qty
            total_value += line_total
            total_margin += line_margin
        return {
            "lines": lines,
            "total_units": total_units,
            "total_value": round(total_value),
            "total_margin": round(total_margin),
            "blended_margin_pct": round(total_margin / total_value, 4) if total_value else 0.0,
        }

    # ---- B2C ↔ B2B spread (the cross-segment opportunity) --------------- #
    def spread(self, db: Session, top_n: int = 15) -> dict:
        ov = self.overview(db)
        rows = [
            {
                "sku": d["sku"],
                "model": d["model"],
                "family": d["family"],
                "retail_fair_value": d["retail_fair_value"],
                "b2b_market_value": d["b2b_market_value"],
                "wholesale_discount_pct": d["wholesale_discount_pct"],
                # absolute per-unit gap (buy in trade, sell at retail) before costs
                "gross_spread": (
                    round(d["retail_fair_value"] - d["b2b_market_value"])
                    if d["retail_fair_value"] else None
                ),
                "units_available": d["units_available"],
            }
            for d in ov["devices"]
            if d["retail_fair_value"]
        ]
        rows.sort(key=lambda r: (r["gross_spread"] or 0), reverse=True)
        return {
            "agent": self.title,
            "opportunities": rows[:top_n],
            "device_count": len(rows),
        }

    # ---- global price map (gsmExchange, by region) ---------------------- #
    def global_map(self, db: Session) -> dict:
        """Live world view: B2B price level by region (the global exposure map)."""
        b2b = self.load_listings(db, segment="b2b")
        # Region rollup.
        by_region: dict[str, list] = defaultdict(list)
        for r in b2b:
            by_region[r.region].append(r)

        regions = []
        for region, rows in by_region.items():
            asks_native = [r.asking_price_native for r in rows]
            asks_inr = [r.asking_price for r in rows]
            currencies = {r.currency for r in rows}
            regions.append(
                {
                    "region": region,
                    "lots": len(rows),
                    "units": sum(r.quantity for r in rows),
                    "median_price_inr": round(statistics.median(asks_inr)),
                    "median_price_native": round(statistics.median(asks_native)),
                    "currency": currencies.pop() if len(currencies) == 1 else "mixed",
                    "sources": sorted({r.platform for r in rows}),
                }
            )
        regions.sort(key=lambda x: x["median_price_inr"], reverse=True)

        # Per-device × region matrix for the most GLOBALLY-traded devices —
        # ranked by how many regions carry the device (gsmExchange spans markets;
        # IndiaMART-only items like MacBooks would be India-only and make a sparse
        # row), then by value. This keeps the world map populated and meaningful.
        retail = self._retail_fair(db)
        sku_regions: dict[str, set] = defaultdict(set)
        for r in b2b:
            sku_regions[r.sku].add(r.region)
        ranked = sorted(
            sku_regions.items(),
            key=lambda kv: (len(kv[1]), retail.get(kv[0], 0)),
            reverse=True,
        )
        top_skus = [sku for sku, regions in ranked if len(regions) >= 3][:12]
        region_keys = [r["region"] for r in regions]
        matrix = []
        for sku in top_skus:
            device = device_by_sku(sku)
            if device is None:
                continue
            cells = {}
            for region in region_keys:
                vals = [
                    r.asking_price for r in b2b if r.sku == sku and r.region == region
                ]
                cells[region] = round(statistics.median(vals)) if vals else None
            if any(v is not None for v in cells.values()):
                matrix.append({"sku": sku, "model": device.model, "by_region": cells})

        return {
            "agent": self.title,
            "regions": regions,
            "region_keys": region_keys,
            "matrix": matrix,
        }

    # ---- globe: country-level world view (the Bloomberg globe) ---------- #
    def globe(self, db: Session) -> dict:
        """Per-country B2B price picture, geo-coded for the 3D globe.

        Price index per country is mix-corrected: for every SKU we compare the
        country's median against that SKU's GLOBAL median, then take the median
        of those ratios — so a country dealing only in Pro Max units doesn't
        read as 'expensive'. Arcs are sourcing opportunities: countries whose
        stock lands in India (duty + freight in) below India retail fair value.
        """
        b2b = self.load_listings(db, segment="b2b")
        retail = self._retail_fair(db)

        # Global per-SKU medians (INR, per-unit) as the reference surface.
        by_sku: dict[str, list[float]] = defaultdict(list)
        for r in b2b:
            by_sku[r.sku].append(r.asking_price)
        global_sku_median = {
            sku: statistics.median(v) for sku, v in by_sku.items() if v
        }

        by_country: dict[str, list] = defaultdict(list)
        for r in b2b:
            by_country[r.region].append(r)

        countries = []
        arcs = []
        p = self.cfg.pricing
        for iso, rows in by_country.items():
            coords = country_latlng(iso)
            if coords is None:
                continue  # unknown / 'GL' rows still count elsewhere
            lat, lng = coords

            # Mix-corrected price index vs the global surface.
            ratios = []
            sku_meds: dict[str, float] = {}
            for sku in {r.sku for r in rows}:
                vals = [r.asking_price for r in rows if r.sku == sku]
                med = statistics.median(vals)
                sku_meds[sku] = med
                g = global_sku_median.get(sku)
                if g:
                    ratios.append(med / g)
            price_index = round(statistics.median(ratios), 3) if ratios else 1.0

            usd_prices = [
                r.asking_price_native if r.currency == "USD"
                else r.asking_price / self.cfg.usd_to_inr
                for r in rows
            ]

            # Top traded devices by units on offer.
            units_by_model: dict[str, int] = defaultdict(int)
            for r in rows:
                units_by_model[r.model] += r.quantity
            top_models = sorted(
                units_by_model.items(), key=lambda kv: kv[1], reverse=True
            )[:3]

            countries.append(
                {
                    "iso": iso,
                    "name": country_name(iso),
                    "lat": lat,
                    "lng": lng,
                    "lots": len(rows),
                    "units": sum(r.quantity for r in rows),
                    "median_price_usd": round(statistics.median(usd_prices)),
                    "price_index": price_index,
                    "top_models": [
                        {"model": m, "units": u} for m, u in top_models
                    ],
                    "sources": sorted({r.platform for r in rows}),
                }
            )

            # Sourcing arc: best landed-cost spread into India retail.
            if iso != "IN":
                best = None
                for sku, med in sku_meds.items():
                    fair = retail.get(sku)
                    if not fair:
                        continue
                    landed = med * (1 + p.import_duty_pct) + p.cross_border_logistics
                    spread = (fair - landed) / fair
                    if best is None or spread > best["spread_pct"]:
                        device = device_by_sku(sku)
                        best = {
                            "sku": sku,
                            "model": device.model if device else sku,
                            "spread_pct": round(spread, 4),
                            "landed_cost": round(landed),
                            "india_fair_value": fair,
                        }
                if best and best["spread_pct"] > 0.05:
                    in_lat, in_lng = country_latlng("IN")
                    arcs.append(
                        {
                            "from_iso": iso,
                            "from_name": country_name(iso),
                            "start_lat": lat,
                            "start_lng": lng,
                            "end_lat": in_lat,
                            "end_lng": in_lng,
                            **best,
                        }
                    )

        countries.sort(key=lambda c: c["units"], reverse=True)
        arcs.sort(key=lambda a: a["spread_pct"], reverse=True)
        return {
            "agent": self.title,
            "countries": countries,
            "arcs": arcs[:12],
            "total_countries": len(countries),
            "total_units": sum(c["units"] for c in countries),
            "total_lots": sum(c["lots"] for c in countries),
            "known_countries": len(COUNTRY_COORDS),
        }

    # ---- full cost waterfall for one device (costing view) -------------- #
    def costing(self, db: Session, sku: str, condition: str = "Superb", quantity: int = 25) -> dict | None:
        device = device_by_sku(sku)
        retail_fair = self._retail_fair(db).get(sku)
        if device is None or not retail_fair:
            return None
        return {
            "sku": sku,
            "model": device.model,
            "retail_fair_value": retail_fair,
            "retail": cost_breakdown(retail_fair, condition, "retail", 1, self.cfg).to_dict(),
            "b2b": cost_breakdown(retail_fair, condition, "b2b", quantity, self.cfg).to_dict(),
        }
