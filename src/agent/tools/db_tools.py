"""Plain Python DB query functions.

These are the *implementation* of the schema-aware queries. They are exposed to
the agent by `mcp_server.py` (at the repo root), which wraps each as an MCP
tool. Do not register them as LangChain @tools here — the agent consumes them
through MCP.

Per the `payment-txn-db-schema` skill:
- No generic run_sql — the tools are shaped around the schema's quirks.
- Amounts / account numbers / codes are strings — never cast.
- Always parameterize.
"""
from __future__ import annotations

from typing import Any

from agent.db import fetch_all, qualified


def lookup_auth(
    acctnum: str,
    txndate: str,
    req_amount: str | None = None,
) -> list[dict[str, Any]]:
    """Look up specific authorization attempts in authstattab for a single account/date.

    DO NOT use for aggregates, counts, ratios, or "how many" questions —
    use count_pb_secured / auth_summary for those.

    Args:
        acctnum: Concrete PAN (partial OK with '%' wildcard, e.g. '4111%1111'). Must NOT be just '%'.
        txndate: A real date like '2026-04-10' or 'DD-MON-YY'. Must NOT be '%' or empty.
        req_amount: Optional requested amount as a string — do not cast to number.
    """
    if not acctnum or acctnum.strip() in {"%", "%%"}:
        raise ValueError(
            "lookup_auth requires a concrete acctnum (not just '%'). "
            "Use auth_summary or count_pb_secured if you don't have one."
        )
    if not txndate or txndate.strip() in {"%", ""}:
        raise ValueError(
            "lookup_auth requires a concrete txndate (YYYY-MM-DD). "
            "Use auth_summary or count_pb_secured with a date range if you don't have one."
        )
    tbl = qualified("authstattab")
    clauses = ["acctnum LIKE :acctnum", "txndate = :txndate"]
    params: dict[str, Any] = {"acctnum": acctnum, "txndate": txndate}
    if req_amount is not None:
        clauses.append("req_amount = :req_amount")
        params["req_amount"] = req_amount
    sql = f"SELECT * FROM {tbl} WHERE {' AND '.join(clauses)} LIMIT 50"
    return fetch_all(sql, params)


def check_pb_secured(
    acctnum: str,
    txndate: str,
    req_amount: str,
) -> dict[str, Any]:
    """Check whether a specific transaction is PB-secured.

    Returns the raw auth_type_code plus interpretation:
      - '2' -> PB secured
      - NULL -> NOT PB secured
      - anything else -> unknown

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
    rows = fetch_all(sql, {"acctnum": acctnum, "txndate": txndate, "req_amount": req_amount})
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


def get_recap(recap_id: str) -> dict[str, Any]:
    """Fetch a recap batch: header (int_control_tab) + all line items (int_detail_tab)."""
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


def get_tranlog(tranlog_id: str, parse_de: bool = False) -> dict[str, Any]:
    """Fetch a raw transaction log row by tranlog_id.

    Args:
        tranlog_id: Unique ID of the tranlog row.
        parse_de: If True, split `rawtrans` on the literal token '<DE>' and return
            the data elements as a list under `de_fields`.
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


def find_auth_by_nrid(nrid: str) -> list[dict[str, Any]]:
    """Look up an authorization by its Network Reference ID (unique per txn)."""
    tbl = qualified("authstattab")
    return fetch_all(
        f"SELECT * FROM {tbl} WHERE nrid = :nrid LIMIT 10",
        {"nrid": nrid},
    )


def find_auth_by_approval_code(
    approval_code: str, txndate: str | None = None
) -> list[dict[str, Any]]:
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


def count_pb_secured(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Count PB-secured vs not-PB-secured vs unknown authorizations.

    Interpretation: auth_type_code='2' -> PB-secured; NULL -> not PB-secured;
    anything else -> unknown.

    Args:
        start_date: Optional inclusive lower bound on txndate (YYYY-MM-DD).
        end_date: Optional inclusive upper bound on txndate (YYYY-MM-DD).
    """
    tbl = qualified("authstattab")
    clauses: list[str] = []
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
        return {"pb_secured": 0, "not_pb_secured": 0, "unknown": 0, "total": 0, "ratio_pb_to_not_pb": None, "pct_pb_secured": 0.0}
    r = rows[0]
    pb = int(r.get("pb_secured") or 0)
    npb = int(r.get("not_pb_secured") or 0)
    unk = int(r.get("unknown") or 0)
    total = int(r.get("total") or 0)
    return {
        "pb_secured": pb,
        "not_pb_secured": npb,
        "unknown": unk,
        "total": total,
        "ratio_pb_to_not_pb": round(pb / npb, 4) if npb else None,
        "pct_pb_secured": round(100 * pb / total, 2) if total else 0.0,
    }


_AUTH_SUMMARY_COLS = {
    "action_code", "mcc", "issuer", "acquirer", "curr_code",
    "auth_type_code", "swoutind", "mrch_nm", "merchant_num",
    "mrch_cty_nm", "merchant_geo_cde", "region",
}


def auth_summary(
    group_by: str = "action_code",
    start_date: str | None = None,
    end_date: str | None = None,
    action_code: str | None = None,
    action_code_not: str | None = None,
    declines_only: bool = False,
    mcc: str | None = None,
    issuer: str | None = None,
    acquirer: str | None = None,
    auth_type_code: str | None = None,
    region: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Flexible aggregate over authstattab — group by any allowed column with optional filters.

    Use for ANY "top/breakdown/count by X" question (e.g. "top 3 merchants for
    declined code 91" -> group_by='mrch_nm', action_code='91', limit=3).

    Args:
        group_by: Column to bucket by. One of: action_code, mcc, issuer, acquirer,
            curr_code, auth_type_code, swoutind, mrch_nm, merchant_num,
            mrch_cty_nm, merchant_geo_cde.
        start_date: Optional inclusive lower bound on txndate (YYYY-MM-DD).
        end_date: Optional inclusive upper bound on txndate (YYYY-MM-DD).
        action_code: Filter to this exact action_code (e.g. '91').
        action_code_not: Filter to rows where action_code <> this value.
        declines_only: If True, filter to action_code <> '00' (all declines).
            Ignored if action_code or action_code_not is also set.
        mcc: Filter to this MCC.
        issuer: Filter by issuer IIC.
        acquirer: Filter by acquirer IIC.
        auth_type_code: Filter by auth_type_code (e.g. '2' for PB-secured only).
        limit: Max number of grouped rows to return (default 50).
    """
    if group_by not in _AUTH_SUMMARY_COLS:
        raise ValueError(
            f"group_by must be one of {sorted(_AUTH_SUMMARY_COLS)}, got {group_by!r}"
        )
    tbl = qualified("authstattab")
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if start_date:
        clauses.append("txndate >= :start_date")
        params["start_date"] = start_date
    if end_date:
        clauses.append("txndate <= :end_date")
        params["end_date"] = end_date
    if action_code is not None:
        clauses.append("action_code = :action_code")
        params["action_code"] = action_code
    elif action_code_not is not None:
        clauses.append("action_code <> :action_code_not")
        params["action_code_not"] = action_code_not
    elif declines_only:
        clauses.append("action_code <> '00'")
    if mcc is not None:
        clauses.append("mcc = :mcc")
        params["mcc"] = mcc
    if issuer is not None:
        clauses.append("issuer = :issuer")
        params["issuer"] = issuer
    if acquirer is not None:
        clauses.append("acquirer = :acquirer")
        params["acquirer"] = acquirer
    if auth_type_code is not None:
        clauses.append("auth_type_code = :auth_type_code")
        params["auth_type_code"] = auth_type_code
    if region is not None:
        clauses.append("region = :region")
        params["region"] = region
    clauses.append(f"{group_by} IS NOT NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = max(1, min(int(limit), 500))
    sql = (
        f"SELECT {group_by} AS bucket, COUNT(*) AS n, "
        f"       SUM(req_amount) AS sum_req_amount "
        f"FROM {tbl} {where} "
        f"GROUP BY {group_by} ORDER BY n DESC LIMIT {limit}"
    )
    return fetch_all(sql, params)


def recap_summary(status: str | None = None) -> list[dict[str, Any]]:
    """Aggregate int_control_tab by status and currency."""
    tbl = qualified("int_control_tab")
    where = "WHERE status = :status" if status else ""
    params = {"status": status} if status else {}
    sql = (
        f"SELECT status, currcode, COUNT(*) AS n, "
        f"       SUM(net_amt) AS sum_net, SUM(gross_amt) AS sum_gross "
        f"FROM {tbl} {where} GROUP BY status, currcode ORDER BY n DESC"
    )
    return fetch_all(sql, params)


# List of all callables — used by mcp_server.py and anywhere else that needs
# to iterate over them. NOT a LangChain tool list.
ALL_DB_FUNCTIONS = [
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
