"""Daglig schemaläggare – kör main.py run varje morgon."""
import logging
import time
from zoneinfo import ZoneInfo

import schedule

from config import SCHEDULE_TIME, TIMEZONE
from main import cmd_run
from storage.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def job():
    logger.info("Schemalagd körning startar")
    try:
        cmd_run()
    except Exception as e:
        logger.error(f"Schemalagd körning misslyckades: {e}", exc_info=True)


def main():
    init_db()
    schedule.every().day.at(SCHEDULE_TIME, ZoneInfo(TIMEZONE)).do(job)
    logger.info(f"Schemaläggare startad – kör dagligen kl {SCHEDULE_TIME} ({TIMEZONE})")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
