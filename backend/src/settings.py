from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_DIR / ".env"


def load_environment() -> None:
    loaded = load_dotenv(ENV_PATH)
    if loaded:
        logger.info("Loaded environment variables from %s", ENV_PATH)
    else:
        logger.warning("No .env file loaded from %s", ENV_PATH)
