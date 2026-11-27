"""Uvicorn entrypoint.

Run with:  python -m app.server
Binds to HOST:PORT from config (defaults to 127.0.0.1:8787, localhost-only).
"""

from __future__ import annotations

import copy

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from .config import get_settings


def _log_config() -> dict:
    """Uvicorn's default config plus timestamps, and a root handler so app/apscheduler
    loggers (which uvicorn leaves unconfigured) are timestamped and show INFO."""
    cfg = copy.deepcopy(LOGGING_CONFIG)
    ts = "%(asctime)s "
    cfg["formatters"]["default"]["fmt"] = ts + cfg["formatters"]["default"]["fmt"]
    cfg["formatters"]["access"]["fmt"] = ts + cfg["formatters"]["access"]["fmt"]
    cfg["formatters"]["app"] = {
        "format": ts + "%(levelprefix)s %(name)s: %(message)s",
        "()": "uvicorn.logging.DefaultFormatter",
    }
    cfg["handlers"]["app"] = {
        "formatter": "app",
        "class": "logging.StreamHandler",
        "stream": "ext://sys.stderr",
    }
    cfg["root"] = {"handlers": ["app"], "level": "INFO"}
    return cfg


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
        log_config=_log_config(),
    )


if __name__ == "__main__":
    main()
