"""Placeholder for warehouse fixture seeding.

Real implementation arrives in TM-A1 when docker-compose Postgres is
populated with sample rows for local UI development. Until then, invoking
this script fails fast so the Makefile target does not silently succeed.
"""

import sys


def main() -> None:
    sys.stderr.write("seed_fixtures is not implemented yet. See work package TM-A1.\n")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
