"""python -m submissions.api [--host 127.0.0.1] [--port 5000]  (local development server)

Serves the API under /api and, with SUBMISSIONS_FRONTEND_DIR=frontend, the static frontend at /. Run the polling
worker beside it (python -m submissions.worker). Use SUBMISSIONS_AUTH=none locally (no sign-in).
"""

from __future__ import annotations

import argparse
import logging

from submissions.api import create_app
from submissions.config import Settings
from submissions.logging_config import configure_logging


def main() -> None:
    ap = argparse.ArgumentParser(description="Bureau submissions API (development server)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    args = ap.parse_args()
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    app = create_app(settings)
    logging.getLogger("submissions.api").info("Downloads are read from %s",
                                              app.extensions["submissions"].store.describe())
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
