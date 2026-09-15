"""Environment loading shared by the API and the CLI.

Reads ``.env`` from the project root (one level above ``backend/``) and
from ``backend/`` itself, without overriding variables already set in the
process. Only ``KEY=value`` lines; no interpolation. Never commit ``.env``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
REPORTS_DIR = PROJECT_DIR / "reports"


def load_env() -> None:
    for candidate in (PROJECT_DIR / ".env", BACKEND_DIR / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            os.environ.setdefault(key, value)


def ghostcart_secret() -> Optional[str]:
    load_env()
    return os.environ.get("GHOSTCART_PROBE_SECRET") or None


def ghostcart_base_url() -> str:
    load_env()
    return os.environ.get("GHOSTCART_BASE_URL", "https://ghostcart-ten.vercel.app")
