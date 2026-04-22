"""Fetch sample TfL API responses for use as test fixtures.

Run once per repo to populate ``tests/fixtures/``:

    uv run python scripts/fetch_tfl_samples.py

Requires ``TFL_APP_KEY`` to be present in the environment (typically via
the root ``.env`` file). The resulting JSON files are committed so CI and
local test runs can validate contracts without hitting the live API.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

TFL_BASE_URL = "https://api.tfl.gov.uk"
MODES = "tube,elizabeth-line,dlr,overground"
OXFORD_CIRCUS_STOP = "940GZZLUOXC"

REQUESTS: dict[str, str] = {
    "line_status_sample.json": f"/Line/Mode/{MODES}/Status",
    "arrivals_sample.json": f"/StopPoint/{OXFORD_CIRCUS_STOP}/Arrivals",
    "disruptions_sample.json": "/Line/Mode/tube/Disruption",
}

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def main() -> int:
    load_dotenv()
    app_key = os.getenv("TFL_APP_KEY")
    if not app_key:
        sys.stderr.write(
            "TFL_APP_KEY is not set. Register at api-portal.tfl.gov.uk and export it in .env.\n"
        )
        return 2

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(base_url=TFL_BASE_URL, timeout=30.0) as client:
        for filename, path in REQUESTS.items():
            response = client.get(path, params={"app_key": app_key})
            response.raise_for_status()
            output = FIXTURES_DIR / filename
            output.write_text(
                json.dumps(response.json(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"wrote {output.relative_to(FIXTURES_DIR.parent.parent)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
