"""Seed the payment-transaction DB with randomized synthetic data.

Usage:
    python scripts/seed_db.py                        # default: ~1000 auths + linked rows
    python scripts/seed_db.py --auth 2000 --truncate # wipe and regenerate
    python scripts/seed_db.py --recaps 50

Tables populated:
    authstattab      (--auth rows, default 1000)
    tranlogtab       (one row per auth, via --auth)
    int_control_tab  (--recaps batch headers, default 30)
    int_detail_tab   (~15-25 line items per recap; some auth_numbers reuse real approval_codes)
"""
from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import text  # noqa: E402

from agent.config import settings  # noqa: E402
from agent.db import get_engine, qualified  # noqa: E402


# ---- reference pools ----------------------------------------------------------

ISSUER_IICS = ["400011", "400012", "550033", "550034", "370099"]
ACQUIRER_IICS = ["900001", "900002", "900003", "901234"]
FORWARDING_IICS = ["900001", "900002", "900099"]
CURR_CODES = ["840", "826", "978", "392", "356"]  # USD, GBP, EUR, JPY, INR
ALT_CURRS = ["840", "978"]

MCCS = ["0742", "5411", "5812", "5999", "6011", "4121", "7011", "5967", "5732"]
ACTION_CODES = ["00", "00", "00", "00", "05", "51", "54", "91", "14"]  # weighted toward approvals
MTI_VALUES = ["0100", "0110", "0200", "0210", "0220"]
FUNC_CODES = ["200", "201", "400", "420"]
POS_IDS = ["012345678901", "051234567890", "062000000000", "811000000000"]
SWOUT_INDS = ["N", "I"]

MERCHANTS = [
    ("SAFEWAY #1234", "SAN FRANCISCO", "US-CA"),
    ("AMAZON MKTPLC", "SEATTLE", "US-WA"),
    ("STARBUCKS 412", "NEW YORK", "US-NY"),
    ("TESCO METRO", "LONDON", "GB-LND"),
    ("UBER TRIP", "MUMBAI", "IN-MH"),
    ("SHELL 7712", "HOUSTON", "US-TX"),
    ("NETFLIX.COM", "LOS GATOS", "US-CA"),
    ("APPLE.COM/BILL", "CUPERTINO", "US-CA"),
    ("TARGET T-0045", "MINNEAPOLIS", "US-MN"),
    ("WHOLE FOODS", "AUSTIN", "US-TX"),
]

MERCHANT_ADDRS = ["123 MAIN ST", "500 MARKET ST", "77 BROADWAY", "1 INFINITE LOOP", "42 QUAY ST"]

RECAP_STATUS = ["PROCESSED", "PROCESSED", "PROCESSED", "PENDING", "REJECTED"]
RECAP_TYPES = ["SALE", "REFUND", "ADJ"]


def rand_pan() -> str:
    """Generate a 16-digit PAN starting with 4 (Visa-style). Not validated; synthetic only."""
    return "4" + "".join(str(random.randint(0, 9)) for _ in range(15))


def rand_approval_code() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(6))


def rand_nrid() -> str:
    return uuid.uuid4().hex[:24].upper()


def rand_tracenum() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(6))


def rand_date(days_back: int = 30) -> date:
    return date.today() - timedelta(days=random.randint(0, days_back))


def rand_time() -> time:
    return time(random.randint(0, 23), random.randint(0, 59), random.randint(0, 59))


def rand_amount(min_cents: int = 100, max_cents: int = 500_000) -> float:
    return round(random.randint(min_cents, max_cents) / 100.0, 2)


# ---- generators ---------------------------------------------------------------


def gen_authstattab(n: int) -> list[dict]:
    pan_pool = [rand_pan() for _ in range(max(100, n // 10))]
    rows: list[dict] = []
    for _ in range(n):
        amt = rand_amount()
        d_amt = round(amt * random.uniform(0.9, 1.1), 2)
        issuer_amt = round(amt * random.uniform(0.95, 1.05), 2)
        merch = random.choice(MERCHANTS)
        rows.append(
            {
                "acctnum": random.choice(pan_pool),
                "txndate": rand_date(),
                "txntime": rand_time(),
                "issuer": random.choice(ISSUER_IICS),
                "acquirer": random.choice(ACQUIRER_IICS),
                "tracenum": rand_tracenum(),
                "req_amount": amt,
                "curr_code": random.choice(CURR_CODES),
                "issuer_amt": issuer_amt,
                "d_amt": d_amt,
                "approval_code": rand_approval_code(),
                "mcc": random.choice(MCCS),
                "action_code": random.choice(ACTION_CODES),
                "funccode": random.choice(FUNC_CODES),
                "add_resp": random.choice(["", "CAVV_PASS", "CVV_PASS", "CVV_FAIL", "CAVV_FAIL"]),
                "response_time": random.randint(50, 2500),
                "swoutind": random.choice(SWOUT_INDS),
                "posid": random.choice(POS_IDS),
                "forwaiic": random.choice(FORWARDING_IICS),
                "merchant_num": str(random.randint(100_000_000, 999_999_999)),
                "mrch_nm": merch[0],
                "mrch_str_adr": random.choice(MERCHANT_ADDRS),
                "mrch_cty_nm": merch[1],
                "merchant_geo_cde": merch[2],
                "auth_type_code": random.choices(["2", None, "1"], weights=[0.2, 0.7, 0.1])[0],
                "nrid": rand_nrid(),
                "mti": random.choice(MTI_VALUES),
            }
        )
    return rows


def gen_tranlogtab(auth_rows: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for a in auth_rows:
        de_fields = [
            a["mti"],
            a["acctnum"],
            f"{a['req_amount']:.2f}",
            a["curr_code"],
            str(a["txndate"]).replace("-", ""),
            a["txntime"].strftime("%H%M%S"),
            a["tracenum"],
            a["approval_code"],
            a["action_code"],
            a["mcc"],
            a["mrch_nm"],
            a["mrch_cty_nm"],
            a["nrid"],
        ]
        rawtrans = "<DE>".join(de_fields)
        rows.append(
            {
                "txndate": a["txndate"],
                "txntime": a["txntime"],
                "mti": a["mti"],
                "rawtrans": rawtrans,
                "acquirer": a["acquirer"],
                "account_number": a["acctnum"],
                "tranlog_id": uuid.uuid4().hex[:16].upper(),
            }
        )
    return rows


def gen_int_control_tab(n: int) -> list[dict]:
    rows: list[dict] = []
    for i in range(1, n + 1):
        num_credits = random.randint(5, 30)
        num_debits = random.randint(5, 30)
        amt_credits = round(sum(rand_amount() for _ in range(num_credits)), 2)
        amt_debits = round(sum(rand_amount() for _ in range(num_debits)), 2)
        net = round(amt_credits - amt_debits, 2)
        gross = round(amt_credits + amt_debits, 2)
        fx = round(random.uniform(0.7, 1.3), 6)
        rows.append(
            {
                "acquirer_iic": random.choice(ACQUIRER_IICS),
                "issuer_iic": random.choice(ISSUER_IICS),
                "recap_no": f"SEQ{i:05d}",
                "currcode": random.choice(CURR_CODES),
                "recap_date": rand_date(45),
                "recap_id": f"R{i:05d}",
                "status": random.choice(RECAP_STATUS),
                "num_credits": num_credits,
                "amt_credits": amt_credits,
                "num_debits": num_debits,
                "amt_debits": amt_debits,
                "net_amt": net,
                "gross_amt": gross,
                "alt_currency": random.choice(ALT_CURRS),
                "alt_gross_amt": round(gross * fx, 2),
                "alt_net_amt": round(net * fx, 2),
                "processing_date": rand_date(40),
                "settlemnt_date": rand_date(35),
                "fx_rate": fx,
                "fx_rate_date": rand_date(35),
                "payor_stlmt_curr": random.choice(CURR_CODES),
                "payor_stlmnt_amt": round(abs(net), 2),
                "payee_stlmnt_curr": random.choice(CURR_CODES),
                "payee_stlmnt_amt": round(abs(net), 2),
                "indb_fi_id": f"FILE{random.randint(1000, 9999)}",
            }
        )
    return rows


def gen_int_detail_tab(recap_rows: list[dict], auth_rows: list[dict]) -> list[dict]:
    approval_pool = [a["approval_code"] for a in auth_rows]
    rows: list[dict] = []
    for r in recap_rows:
        lines = random.randint(15, 25)
        for _ in range(lines):
            merch = random.choice(MERCHANTS)
            # 70% of auth_numbers reuse a real approval_code (joinable back to auth)
            auth_num = (
                random.choice(approval_pool)
                if random.random() < 0.7
                else rand_approval_code()
            )
            rows.append(
                {
                    "recap_id": r["recap_id"],
                    "charge_amount": rand_amount(),
                    "charge_date": r["recap_date"],
                    "type_change": random.choice(RECAP_TYPES),
                    "auth_number": auth_num,
                    "merchant_name": merch[0],
                    "city": merch[1],
                    "geocode": merch[2],
                    "mrch_str_adr": random.choice(MERCHANT_ADDRS),
                    "mrch_cty_nm": merch[1],
                    "mcc": random.choice(MCCS),
                }
            )
    return rows


# ---- insert -------------------------------------------------------------------


def _insert(conn, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0].keys())
    placeholders = ", ".join(f":{c}" for c in cols)
    col_list = ", ".join(cols)
    conn.execute(
        text(f"INSERT INTO {qualified(table)} ({col_list}) VALUES ({placeholders})"),
        rows,
    )


def _truncate(conn) -> None:
    for t in ("int_detail_tab", "int_control_tab", "tranlogtab", "authstattab"):
        conn.execute(text(f"TRUNCATE TABLE {qualified(t)}"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth", type=int, default=1000)
    parser.add_argument("--recaps", type=int, default=30)
    parser.add_argument("--truncate", action="store_true", help="Wipe tables before inserting")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    print(f"DB: {settings.database_url}  schema={settings.db_schema}")
    t0 = datetime.now()

    auth_rows = gen_authstattab(args.auth)
    tran_rows = gen_tranlogtab(auth_rows)
    ctrl_rows = gen_int_control_tab(args.recaps)
    det_rows = gen_int_detail_tab(ctrl_rows, auth_rows)

    print(
        f"Generated: authstattab={len(auth_rows)}  "
        f"tranlogtab={len(tran_rows)}  "
        f"int_control_tab={len(ctrl_rows)}  "
        f"int_detail_tab={len(det_rows)}"
    )

    engine = get_engine()
    with engine.begin() as conn:
        if args.truncate:
            print("Truncating existing tables…")
            _truncate(conn)
        print("Inserting authstattab…")
        _insert(conn, "authstattab", auth_rows)
        print("Inserting tranlogtab…")
        _insert(conn, "tranlogtab", tran_rows)
        print("Inserting int_control_tab…")
        _insert(conn, "int_control_tab", ctrl_rows)
        print("Inserting int_detail_tab…")
        _insert(conn, "int_detail_tab", det_rows)

    print(f"Done in {(datetime.now() - t0).total_seconds():.1f}s")


if __name__ == "__main__":
    main()
