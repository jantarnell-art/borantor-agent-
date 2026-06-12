#!/usr/bin/env python3
"""
Scheduler – kör den dagliga insamlingen automatiskt kl. 07:00 svensk tid.

Körning:
  python scheduler.py

Eller som systemd-service (se README.md för fullständig instruktion).

För cron (alternativ):
  0 7 * * * cd /path/to/borantor-agent && python main.py run >> data/borantor.log 2>&1
"""

import logging
import sys
import time
import zoneinfo
from datetime import datetime

import schedule

from config import SCHEDULE_TIME, TIMEZONE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("scheduler")


def _run_daily():
    tz = zoneinfo.ZoneInfo(TIMEZONE)
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z")
    logger.info("Daglig körning startar (%s)", now)
    try:
        from main import cmd_run, init_db
        from storage.database import init_db as db_init
        db_init()
        cmd_run()
    except Exception as exc:
        logger.exception("Fel vid daglig körning: %s", exc)


def main():
    logger.info(
        "Scheduler startad – daglig körning schemalagd kl. %s %s",
        SCHEDULE_TIME, TIMEZONE,
    )
    schedule.every().day.at(SCHEDULE_TIME, TIMEZONE).do(_run_daily)

    # Show next run time
    next_run = schedule.next_run()
    if next_run:
        logger.info("Nästa körning: %s", next_run.strftime("%Y-%m-%d %H:%M"))

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
