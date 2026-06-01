"""Background scheduler — runs sync on a configurable interval."""
from __future__ import annotations

import logging
import signal
import sys
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import get_settings
from .sync import run_sync

logger = logging.getLogger(__name__)


def _sync_job() -> None:
    try:
        result = run_sync()
        logger.info(
            "Scheduled sync: +%d tweets, +%d articles, +%d embeddings",
            result.new_tweets, result.new_articles, result.new_embeddings,
        )
    except Exception as exc:
        logger.error("Scheduled sync failed: %s", exc, exc_info=True)


def start_scheduler() -> None:
    cfg = get_settings()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if cfg.sync_cron:
        trigger = CronTrigger.from_crontab(cfg.sync_cron)
        logger.info("Starting scheduler (cron=%s)", cfg.sync_cron)
    else:
        trigger = IntervalTrigger(minutes=cfg.sync_interval_minutes)
        logger.info("Starting scheduler (every %dmin)", cfg.sync_interval_minutes)

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _sync_job,
        trigger=trigger,
        id="bookmark_sync",
        next_run_time=__import__("datetime").datetime.now(),  # run immediately on start
    )
    scheduler.start()

    def _shutdown(signum, frame):
        logger.info("Shutting down scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        while True:
            time.sleep(30)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    start_scheduler()
