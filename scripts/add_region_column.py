"""Add `region` column to authstattab and backfill existing rows.

Usage:
    python scripts/add_region_column.py              # add + backfill (idempotent)
    python scripts/add_region_column.py --drop       # remove the column

Regions: APAC, EMEA, AMER.
Backfill is derived from `merchant_geo_cde` when possible, otherwise random.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import text  # noqa: E402

from agent.config import settings  # noqa: E402
from agent.db import get_engine, qualified  # noqa: E402

REGIONS = ("APAC", "EMEA", "AMER")

# Geo-code prefix -> region. Maps the synthetic geo_cde values that seed_db.py uses.
REGION_BY_PREFIX = {
    # AMER — North & South America
    "US": "AMER", "CA": "AMER", "MX": "AMER", "BR": "AMER", "AR": "AMER",
    # EMEA — Europe, Middle East, Africa
    "GB": "EMEA", "IE": "EMEA", "DE": "EMEA", "FR": "EMEA", "ES": "EMEA",
    "IT": "EMEA", "NL": "EMEA", "SE": "EMEA", "AE": "EMEA", "SA": "EMEA",
    "ZA": "EMEA", "EG": "EMEA",
    # APAC — Asia Pacific
    "IN": "APAC", "CN": "APAC", "JP": "APAC", "KR": "APAC", "SG": "APAC",
    "AU": "APAC", "NZ": "APAC", "HK": "APAC", "TH": "APAC", "ID": "APAC",
    "MY": "APAC", "VN": "APAC",
}


def _region_for_geo(geo: str | None) -> str:
    if not geo:
        return random.choice(REGIONS)
    prefix = geo.strip().upper().split("-", 1)[0][:2]
    return REGION_BY_PREFIX.get(prefix, random.choice(REGIONS))


def add_column(conn) -> None:
    conn.execute(
        text(
            f"ALTER TABLE {qualified('authstattab')} "
            f"ADD COLUMN IF NOT EXISTS region VARCHAR(8)"
        )
    )


def backfill(conn) -> int:
    rows = conn.execute(
        text(
            f"SELECT ctid, merchant_geo_cde FROM {qualified('authstattab')} "
            f"WHERE region IS NULL"
        )
    ).fetchall()
    if not rows:
        return 0

    # Update in-place by ctid; ctid is stable within a single transaction.
    params = [
        {"ctid": str(r.ctid), "region": _region_for_geo(r.merchant_geo_cde)}
        for r in rows
    ]
    conn.execute(
        text(
            f"UPDATE {qualified('authstattab')} "
            f"SET region = :region WHERE ctid = CAST(:ctid AS tid)"
        ),
        params,
    )
    return len(rows)


def drop_column(conn) -> None:
    conn.execute(
        text(f"ALTER TABLE {qualified('authstattab')} DROP COLUMN IF EXISTS region")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop", action="store_true", help="Drop the region column")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    engine = get_engine()
    print(f"DB: {settings.database_url}  schema={settings.db_schema}")

    with engine.begin() as conn:
        if args.drop:
            drop_column(conn)
            print("Dropped column region.")
            return

        add_column(conn)
        n = backfill(conn)
        print(f"Column ensured. Backfilled {n} row(s).")

    # Show distribution
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT region, COUNT(*) AS n FROM {qualified('authstattab')} "
                f"GROUP BY region ORDER BY n DESC"
            )
        ).fetchall()
    print("\nRegion distribution:")
    for r in rows:
        print(f"  {r.region or '(null)':6s}  {r.n}")


if __name__ == "__main__":
    main()
