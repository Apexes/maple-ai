"""
Worker entrypoint:  python -m app.workers.worker

Consumes jobs from the Redis queue and runs them.  Also performs an initial
seed and an immediate market refresh so a fresh stack is populated.
"""
from __future__ import annotations

import json
import os
import time

from ..config import get_config
from ..db import init_db
from ..seed import seed_on_startup
from .queue import JOB_QUEUE_KEY, _redis, enqueue
from .tasks import dispatch


def _start_b2b_scheduler() -> None:
    """Enqueue the daily B2B-segment refresh on a cron schedule.

    The client wants daily B2B scraping. APScheduler (if installed) fires a
    `refresh_b2b` job every day at MAPLE_B2B_DAILY_HOUR (default 03:00). The
    cadence is deliberately separate from the retail refresh so the authenticated
    wholesale adapters run human-paced and a B2B failure never touches retail.
    """
    hour = int(os.getenv("MAPLE_B2B_DAILY_HOUR", "3"))
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception:  # apscheduler optional — fall back to documented cron
        print(
            "[worker] apscheduler not installed; schedule the daily B2B refresh "
            "externally (cron/Docker) by enqueuing the 'refresh_b2b' job."
        )
        return
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(lambda: enqueue("refresh_b2b"), CronTrigger(hour=hour, minute=0))
    sched.start()
    print(f"[worker] B2B daily refresh scheduled at {hour:02d}:00")


def main() -> None:
    init_db()
    print("[worker] starting; seeding if needed...")
    print("[worker] seed:", seed_on_startup())

    _start_b2b_scheduler()

    r = _redis()
    if r is None:
        print("[worker] REDIS_URL not set — nothing to consume. Exiting.")
        return

    cfg = get_config()
    # The backend service seeds the full market on startup, so the worker just
    # consumes queued refresh jobs (avoids racing the startup seed on `listings`).
    print(f"[worker] connected to {cfg.infra.redis_url}; waiting for jobs on {JOB_QUEUE_KEY}")

    while True:
        try:
            item = r.blpop(JOB_QUEUE_KEY, timeout=5)
            if not item:
                continue
            _, raw = item
            msg = json.loads(raw)
            print(f"[worker] running {msg['job']}")
            result = dispatch(msg["job"], msg.get("payload", {}))
            print(f"[worker] done {msg['job']}: {result}")
        except KeyboardInterrupt:
            print("[worker] shutting down")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] error: {exc}")
            time.sleep(2)


if __name__ == "__main__":
    main()
