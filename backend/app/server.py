"""Uvicorn entrypoint.

Run with:  python -m app.server
Binds to HOST:PORT from config (defaults to 127.0.0.1:8787, localhost-only).
"""

from __future__ import annotations

import uvicorn

from .config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
