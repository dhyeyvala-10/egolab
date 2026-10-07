"""
Container start-up: apply migrations and create storage buckets, then exit.

Run before the API starts (`python -m egolabs.bootstrap`). Safe to run repeatedly.
"""

import logging
import os
import time
from collections.abc import Callable

from alembic import command
from alembic.config import Config

from egolabs.config import get_settings
from egolabs.logs import configure_logging
from egolabs.storage import ensure_buckets

log = logging.getLogger("egolabs.bootstrap")
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _retry(what: str, fn: Callable[[], object], attempts: int = 30, delay: float = 2.0) -> object:
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts:
                raise
            log.warning(f"{what} not ready, retrying", extra={"attempt": attempt, "error": str(exc)})
            time.sleep(delay)
    raise AssertionError("unreachable")


def alembic_ini() -> str:
    """alembic.ini sits next to the package in a checkout, and in the working directory in the image."""
    for base in (os.getcwd(), BACKEND_DIR):
        path = os.path.join(base, "alembic.ini")
        if os.path.exists(path):
            return path
    raise FileNotFoundError("alembic.ini not found: run from the backend directory")


def migrate() -> None:
    ini = alembic_ini()
    cfg = Config(ini)
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(ini), "alembic"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def main() -> None:
    configure_logging(get_settings().log_level)
    _retry("database", migrate)
    log.info("migrations applied")
    created = _retry("object storage", ensure_buckets)
    log.info("storage buckets ready", extra={"buckets_created": created})


if __name__ == "__main__":
    main()
