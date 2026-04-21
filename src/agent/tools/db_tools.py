"""Task-shaped DB tools for the agent.

Per the `payment-txn-db-schema` skill:
- Do NOT expose a generic run_sql tool — the schema quirks mean a naive LLM
  will produce wrong joins. Shape tools around concrete questions instead.
- Amounts / account numbers / codes are strings — never cast.
- Always parameterize.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from agent.db import fetch_all, qualified


@tool
def lookup_auth(
    acctnum: str,
    txndate: str,
    req_amount: str | None = None,
) -> list[dict[str, Any]]:
    """Look up specific authorization attempts in authstattab for a single account/date.

    DO NOT use this tool for aggregates, counts, ratios, or "how many" questions —
    use count_pb_secured / auth_summary for those.

    Args:
        acctnum: Concrete PAN (partial OK with '%' wildcard, e.g. '4111%1111'). Must NOT be just '%'.
        txndate: A real date like '2026-04-10' or 'DD-MON-YY'. Must NOT be '%' or empty.
        req_amount: Optional requested amount as a string — do not cast to number.
    """
    if not acctnum or acctnum.strip() in {"%", "%%"}:
        raise ValueError(
            "lookup_auth requires a concrete acctnum (not just '%'). "
            "If you don't have one, use auth_summary or count_pb_secured instead."
        )
    if not txndate or txndate.strip() in {"%", ""}:
        raise ValueError(
            "lookup_auth requires a concrete txndate (YYYY-MM-DD). "
            "If you don't have one, use auth_summary or count_pb_secured with a date range."
        )
    tbl = qualified("authstattab")
    clauses = ["acctnum LIKE :acctnum", "txndate = :txndate"]
    params: dict[str, Any] = {"acctnum": acctnum, "txndate": txndate}
    if req_amount is not None:
        clauses.append("req_amount = :req_amount")
        params["req_amount"] = req_amount
    sql = f"SELECT * FROM {tbl} WHERE {' AND '.join(clauses)} LIMIT 50"
    return fetch_all(sql, params)


@tool
def check_pb_secured(
    acctnum: str,
    txndate: str,
    req_amount: str,
) -> dict[str, Any]:
    """Check whether a specific transaction is PB-secured.

    Returns the raw auth_type_code plus an interpretation:
      - '2' -> PB secured
      - NULL -> NOT PB secured
      - anything else -> unknown (flag back to caller)

    Args:
        acctnum: Full or partial PAN.
        txndate: Transaction date.
        req_amount: Requested amount as a string.
    """
    tbl = qualified("authstattab")
    sql = (
        f"SELECT acctnum, txndate, req_amount, auth_type_code "
        f"FROM {tbl} "
        f"WHERE acctnum LIKE :acctnum AND txndate = :txndate AND req_amount = :req_amount "
        f"LIMIT 10"
    )
    rows = fetch_all(
        sql,
        {"acctnum": acctnum, "txndate": txndate, "req_amount": req_amount},
    )
    if not rows:
        return {"found": False, "rows": []}

    def interpret(code: Any) -> str:
        if code is None:
            return "not_pb_secured"
        if str(code) == "2":
            return "pb_secured"
        return "unknown"

    return {
        "found": True,
        "rows": [{**r, "pb_status": interpret(r.get("auth_type_code"))} for r in rows],
    }


@tool
def get_recap(recap_id: str) -> dict[str, Any]:
    """Fetch a recap batch: header from int_control_tab + all line items from int_detail_tab."""
    ctrl = qualified("int_control_tab")
    det = qualified("int_detail_tab")

    header = fetch_all(
        f"SELECT * FROM {ctrl} WHERE recap_id = :recap_id LIMIT 1",
        {"recap_id": recap_id},
    )
    details = fetch_all(
        f"SELECT * FROM {det} WHERE recap_id = :recap_id ORDER BY charge_date",
        {"recap_id": recap_id},
    )
    return {
        "header": header[0] if header else None,
        "details": details,
        "detail_count": len(details),
    }


@tool
def get_tranlog(tranlog_id: str, parse_de: bool = False) -> dict[str, Any]:
    """Fetch a raw transaction log row by tranlog_id.

    Args:
        tranlog_id: Unique ID of the tranlog row.
        parse_de: If True, split `rawtrans` on the literal token '<DE>' and
            return the data elements as a list under `de_fields`.
    """
    tbl = qualified("tranlogtab")
    rows = fetch_all(
        f"SELECT * FROM {tbl} WHERE tranlog_id = :tranlog_id LIMIT 1",
        {"tranlog_id": tranlog_id},
    )
    if not rows:
        return {"found": False}
    row = rows[0]
    if parse_de and isinstance(row.get("rawtrans"), str):
        row = {**row, "de_fields": row["rawtrans"].split("<DE>")}
    return {"found": True, "row": row}


@tool
def find_auth_by_nrid(nrid: str) -> list[dict[str, Any]]:
    """Look up an authorization by its Network Reference ID (unique per txn)."""
    tbl = qualified("authstattab")
    return fetch_all(
        f"SELECT * FROM {tbl} WHERE nrid = :nrid LIMIT 10",
        {"nrid": nrid},
    )


@tool
def find_auth_by_approval_code(approval_code: str, txndate: str | None = None) -> list[dict[str, Any]]:
    """Look up authorizations by approval_code.

    Useful as a bridge from int_detail_tab.auth_number (same value) back to
    the originating authorization row.
    """
    tbl = qualified("authstattab")
    clauses = ["approval_code = :approval_code"]
    params: dict[str, Any] = {"approval_code": approval_code}
    if txndate:
        clauses.append("txndate = :txndate")
        params["txndate"] = txndate
    return fetch_all(
        f"SELECT * FROM {tbl} WHERE {' AND '.join(clauses)} LIMIT 20",
        params,
    )


@tool
def count_pb_secured(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Count PB-secured vs not-PB-secured vs unknown authorizations.

    Use for aggregate / ratio / "how many" questions about PB-secured transactions.
    Interpretation: auth_type_code='2' -> PB-secured; NULL -> not PB-secured;
    anything else -> unknown.

    Args:
        start_date: Optional inclusive lower bound on txndate (YYYY-MM-DD).
        end_date: Optional inclusive upper bound on txndate (YYYY-MM-DD).
    """
    tbl = qualified("authstattab")
    clauses = []
    params: dict[str, Any] = {}
    if start_date:
        clauses.append("txndate >= :start_date")
        params["start_date"] = start_date
    if end_date:
        clauses.append("txndate <= :end_date")
        params["end_date"] = end_date
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        f"SELECT "
        f"  SUM(CASE WHEN auth_type_code = '2' THEN 1 ELSE 0 END) AS pb_secured, "
        f"  SUM(CASE WHEN auth_type_code IS NULL THEN 1 ELSE 0 END) AS not_pb_secured, "
        f"  SUM(CASE WHEN auth_type_code IS NOT NULL AND auth_type_code <> '2' THEN 1 ELSE 0 END) AS unknown, "
        f"  COUNT(*) AS total "
        f"FROM {tbl} {where}"
    )
    rows = fetch_all(sql, params)
    if not rows:
        return {"pb_secured": 0, "not_pb_secured": 0, "unknown": 0, "total": 0, "ratio": None}
    r = rows[0]
    pb = int(r.get("pb_secured") or 0)
    npb = int(r.get("not_pb_secured") or 0)
    unk = int(r.get("unknown") or 0)
    total = int(r.get("total") or 0)
    ratio = round(pb / npb, 4) if npb else None
    return {
        "pb_secured": pb,
        "not_pb_secured": npb,
        "unknown": unk,
        "total": total,
        "ratio_pb_to_not_pb": ratio,
        "pct_pb_secured": round(100 * pb / total, 2) if total else 0.0,
    }


@tool
def auth_summary(
    start_date: str | None = None,
    end_date: str | None = None,
    group_by: str = "action_code",
) -> list[dict[str, Any]]:
    """Group authstattab rows and return counts. Use for 'how many by X' questions.

    Args:
        start_date: Optional inclusive lower bound on txndate (YYYY-MM-DD).
        end_date: Optional inclusive upper bound on txndate (YYYY-MM-DD).
        group_by: One of: action_code, mcc, issuer, acquirer, curr_code, auth_type_code, swoutind.
    """
    allowed = {
        "action_code", "mcc", "issuer", "acquirer",
        "curr_code", "auth_type_code", "swoutind",
    }
    if group_by not in allowed:
        raise ValueError(
            f"group_by must be one of {sorted(allowed)}, got {group_by!r}"
        )
    tbl = qualified("authstattab")
    clauses = []
    params: dict[str, Any] = {}
    if start_date:
        clauses.append("txndate >= :start_date")
        params["start_date"] = start_date
    if end_date:
        clauses.append("txndate <= :end_date")
        params["end_date"] = end_date
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        f"SELECT {group_by} AS bucket, COUNT(*) AS n, "
        f"       SUM(req_amount) AS sum_req_amount "
        f"FROM {tbl} {where} "
        f"GROUP BY {group_by} ORDER BY n DESC LIMIT 50"
    )
    return fetch_all(sql, params)


@tool
def recap_summary(status: str | None = None) -> list[dict[str, Any]]:
    """Aggregate int_control_tab by status or currency.

    Args:
        status: Optional filter on the recap status string (e.g. 'PROCESSED').
    """
    tbl = qualified("int_control_tab")
    where = "WHERE status = :status" if status else ""
    params = {"status": status} if status else {}
    sql = (
        f"SELECT status, currcode, COUNT(*) AS n, "
        f"       SUM(net_amt) AS sum_net, SUM(gross_amt) AS sum_gross "
        f"FROM {tbl} {where} GROUP BY status, currcode ORDER BY n DESC"
    )
    return fetch_all(sql, params)


ALL_DB_TOOLS = [
    lookup_auth,
    check_pb_secured,
    get_recap,
    get_tranlog,
    find_auth_by_nrid,
    find_auth_by_approval_code,
    count_pb_secured,
    auth_summary,
    recap_summary,
]
