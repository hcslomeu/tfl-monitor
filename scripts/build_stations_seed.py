"""Build ``dbt/seeds/tfl_stations.csv`` from the TfL Unified API.

Run once per repo (re-run only when TfL adds/renames a rail station):

    uv run python scripts/build_stations_seed.py

Requires ``TFL_APP_KEY`` in the environment (root ``.env`` is loaded
automatically). Hits ``/StopPoint/Mode/{mode}`` for the four rail modes
the dashboard cares about (tube, elizabeth-line, overground, dlr),
deduplicates by ``naptanId`` (a station can serve multiple modes), and
writes the result sorted by name.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

TFL_BASE_URL = "https://api.tfl.gov.uk"
RAIL_MODES = ("tube", "elizabeth-line", "overground", "dlr")

# ``/StopPoint/Mode/{mode}`` returns every stop attached to a mode,
# including the bus stops on the street outside an Underground entrance
# (NaPTAN ``4900*`` prefixes). The disruption payload only emits actual
# station NaPTANs, so we keep stop types that name a station building
# and discard the bus-stop fan-out.
KEEP_STOP_TYPES = frozenset(
    {
        "NaptanMetroStation",
        "NaptanRailStation",
        "NaptanRailAccessArea",
        "TransportInterchange",
    }
)

NAME_SUFFIXES_TO_STRIP = (
    " Underground Station",
    " DLR Station",
    " Rail Station",
)

SEED_PATH = Path(__file__).resolve().parent.parent / "dbt" / "seeds" / "tfl_stations.csv"


def _clean_name(common_name: str) -> str:
    name = common_name.strip()
    for suffix in NAME_SUFFIXES_TO_STRIP:
        if name.endswith(suffix):
            return name[: -len(suffix)].strip()
    return name


def _fetch_mode_stops(client: httpx.Client, mode: str, app_key: str) -> list[dict]:
    response = client.get(f"/StopPoint/Mode/{mode}", params={"app_key": app_key})
    response.raise_for_status()
    payload = response.json()
    stops = payload.get("stopPoints", [])
    if not isinstance(stops, list):
        raise RuntimeError(f"Unexpected stopPoints shape for mode={mode}")
    return stops


def main() -> int:
    load_dotenv()
    app_key = os.getenv("TFL_APP_KEY")
    if not app_key:
        sys.stderr.write(
            "TFL_APP_KEY is not set. Register at api-portal.tfl.gov.uk and export it in .env.\n"
        )
        return 2

    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)

    stations: dict[str, dict[str, set[str]]] = {}
    with httpx.Client(base_url=TFL_BASE_URL, timeout=30.0) as client:
        for mode in RAIL_MODES:
            stops = _fetch_mode_stops(client, mode, app_key)
            print(f"{mode}: {len(stops)} stops")
            for stop in stops:
                naptan_id = stop.get("naptanId")
                common_name = stop.get("commonName")
                stop_type = stop.get("stopType")
                if not naptan_id or not common_name:
                    continue
                if stop_type not in KEEP_STOP_TYPES:
                    continue
                entry = stations.setdefault(
                    naptan_id,
                    {"name": _clean_name(common_name), "line_ids": set(), "modes": set()},
                )
                for line in stop.get("lines", []) or []:
                    line_id = line.get("id")
                    if line_id:
                        entry["line_ids"].add(line_id)
                for stop_mode in stop.get("modes", []) or []:
                    if stop_mode:
                        entry["modes"].add(stop_mode)

    rows = sorted(
        (
            {
                "naptan_id": naptan_id,
                "name": data["name"],
                "line_ids": ",".join(sorted(data["line_ids"])),
                "modes": ",".join(sorted(data["modes"])),
            }
            for naptan_id, data in stations.items()
        ),
        key=lambda r: (r["name"], r["naptan_id"]),
    )

    with SEED_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["naptan_id", "name", "line_ids", "modes"],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {SEED_PATH.relative_to(SEED_PATH.parent.parent.parent)} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
