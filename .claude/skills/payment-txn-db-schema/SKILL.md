---
name: payment-txn-db-schema
description: Schema reference and query playbook for the payment-transaction database (tables authstattab, tranlogtab, int_detail_tab, int_control_tab). Use BEFORE building any MCP server, writing SQL, or designing tools that read or join these tables — the schema has non-obvious quirks (swapped credit/debit wording, legacy xpress.* prefixes, <DE>-delimited raw payloads, column-name aliases like auth_type_cde vs auth_type_code) that break queries if ignored. Triggers on: "build an MCP for the payments DB", "query authstattab / tranlogtab / int_detail_tab / int_control_tab", "PB secured check", "recap / interchange query", "auth status lookup", "join auth to recap", "tranlog <DE> parsing".
---

# Payment Transaction DB — Schema & Query Skill

This DB has 4 tables with overlapping-but-distinct concerns. The column names are inconsistent across tables and the source spreadsheet has **known wording bugs**. Read this skill before writing any query or MCP tool definition — do not infer column meanings from names alone.

The authoritative schema lives at `schema.sql` in the project root. This file is the *playbook* for using it.

---

## 1. What each table is for — pick the right one

| Table              | Grain                              | Use when the user asks about…                                                      |
| ------------------ | ---------------------------------- | ---------------------------------------------------------------------------------- |
| `authstattab`      | 1 row per **auth attempt**         | Approval / decline, PB-secured check, MCC, merchant info at auth-time, response codes |
| `tranlogtab`       | 1 row per **raw switch message**   | Debugging the wire message, MTI inspection, pulling `<DE>`-delimited fields        |
| `int_detail_tab`   | 1 row per **charge inside a recap**| Which transactions belong to a given recap batch, per-charge settlement detail     |
| `int_control_tab`  | 1 row per **recap batch header**   | Recap status, net/gross, FX rate, settlement currency/amount, inbound file ID      |

**Rule of thumb:** if the user says "transaction" they almost always mean `authstattab`. If they say "recap," "settlement," "batch," or "interchange" → the `int_*` tables. If they say "raw message," "DE fields," or "switch log" → `tranlogtab`.

---

## 2. Joining the tables

No PKs/FKs are declared in `schema.sql` (the source sheets don't specify them). Use these logical joins:

- `int_detail_tab.recap_id` → `int_control_tab.recap_id`  (detail ↔ batch header)
- `int_detail_tab.auth_number` → `authstattab.approval_code`  (recap line ↔ originating auth)
- `authstattab.nrid` is the **Network Reference ID**, unique per transaction — prefer this when joining auth rows across systems
- `authstattab.tracenum` (System Trace Audit Number) is useful for correlating with `tranlogtab` when NRID isn't available
- `tranlogtab` ↔ `authstattab`: join on `(account_number = acctnum, txndate, txntime, mti)`; there is no clean single-column key

---

## 3. Quirks you MUST handle (this is why the skill exists)

### 3.1 Credit/debit wording is swapped in the source sheet
In `int_control_tab`, the source spreadsheet descriptions say:
- `amt_credits` = "amount of transactions that were **debited** in that recap"
- `amt_debits`  = "amount of transactions that were **credited** in that recap"

That is backwards. **Trust the column name, not the sheet's description.** `amt_credits` holds credit amounts; `amt_debits` holds debit amounts. If a user's question hinges on this, flag the ambiguity and confirm before reporting numbers.

### 3.2 `action_code` — `'00'` = APPROVED, everything else = DECLINED

In `authstattab.action_code`:
- `'00'` -> **approved** transaction.
- **Any other value** (e.g. `'05'`, `'51'`, `'54'`, `'91'`, `'14'`, etc.) -> **declined** transaction. The specific non-`'00'` code indicates the decline reason.

This follows the ISO 8583 convention. No wildcard "unknown" bucket — if it isn't `'00'`, treat it as a decline.

Practical implications:
- For approved-vs-declined splits: `action_code = '00'` is the **approved** bucket; `action_code <> '00'` (and NOT NULL) is the **declined** bucket.
- `auth_summary(group_by='action_code')` returns raw codes; the `'00'` row is approvals, every other row is a specific decline reason.
- When filtering "declines only", use `WHERE action_code <> '00'` rather than enumerating known decline codes (new codes may appear).

### 3.3 PB-secured check uses `auth_type_code`
- `auth_type_code = '2'` → transaction IS PB-secured
- `auth_type_code IS NULL` → transaction is NOT PB-secured
- Any other value → unknown / flag back to the user

The sample playbook in the source workbook calls the column `auth_type_cde` (no `o`); `schema.sql` uses `auth_type_code`. If the target DB uses the legacy `xpress.*` namespace with `auth_type_cde`, adjust accordingly — don't silently guess.

### 3.4 Legacy `xpress.*` schema prefix
Production queries in the source sheet look like `SELECT * FROM xpress.authstattab ...`. If the MCP connects to the real `xpress` schema, column names may differ slightly from `schema.sql`:
- `auth_type_code` ↔ legacy `auth_type_cde`
- `req_amount` ↔ legacy `reqamt`
- `swoutind` ↔ legacy `swoutIND` (case may matter depending on DB)

**Before writing the first query, run `\d xpress.authstattab` (or equivalent) to confirm the real column names.** Do not assume.

### 3.5 `tranlogtab.rawtrans` is `<DE>`-delimited
`rawtrans` is the full switch message as a single string, with data elements separated by the literal 5-character token `<DE>` (not a single byte, not a newline). To extract field N, split on `<DE>` and index. Do not try regex-matching individual DEs from the raw blob — the token is literal.

### 3.6 MCC / account number / amount are strings, not numbers
`acctnum`, `mcc`, `approval_code`, `action_code`, and similar codes are **VARCHAR** even when they look numeric. Leading zeros matter (e.g. MCC `0742` ≠ `742`). Always quote them in WHERE clauses, never cast to int.

---

## 4. Sample-issue playbook (from sheet 5 of source workbook)

**Issue:** "Check whether a given transaction is PB-secured or not."
**Table:** `authstattab` (or `xpress.authstattab` in prod)
**Query shape:**
```sql
SELECT acctnum, txndate, req_amount, auth_type_code
  FROM xpress.authstattab
 WHERE acctnum  LIKE 'XXX%XXXX'
   AND req_amount = 'XXX'
   AND txndate    = 'XX-XXX-XX';
```
**Interpretation:**
- `auth_type_code = '2'` → PB-secured
- `auth_type_code IS NULL` → not PB-secured

---

## 5. Checklist — building an MCP server for this DB

When the user asks you to build / scaffold / add tools to an MCP server that queries this DB, walk through this list **before writing code**:

1. **Confirm the target schema name.** Is it `public`, `xpress`, or something else? Column names differ (see §3.3).
2. **Confirm dialect.** `schema.sql` is PostgreSQL-flavored; if the real DB is Oracle / Teradata / MS-SQL, `DATE`/`TIME` splitting, `LIKE` wildcards, and quoting change.
3. **Decide the tool surface.** Do not expose one generic `run_sql(query)` tool if avoidable — the schema quirks above mean a naive LLM will produce wrong joins. Prefer task-shaped tools:
   - `lookup_auth(acctnum, txndate, [req_amount])` → row(s) from `authstattab`
   - `check_pb_secured(acctnum, txndate, req_amount)` → boolean + raw `auth_type_code`
   - `get_recap(recap_id)` → `int_control_tab` + joined `int_detail_tab`
   - `get_tranlog(tranlog_id)` with an optional `parse_de=true` that splits `<DE>` fields
4. **Index cardinality.** `acctnum` + `txndate` is the universal lookup key — make sure the real DB has an index on this, or queries will table-scan.
5. **Amount typing.** If amounts come in as strings from the wire, cast explicitly in SQL; don't trust client-side parsing.
6. **Parameterize everything.** Never string-concatenate `acctnum`, `approval_code`, `nrid`, or date literals into SQL — always bind.
7. **Return raw + interpreted.** For flag columns like `auth_type_code`, return both the raw value and the human interpretation. This lets the calling model explain surprises instead of silently collapsing them.

---

## 6. Column-name quick reference (worst offenders)

Copy these exactly — don't retype from memory:

- `authstattab`: `acctnum`, `txndate`, `txntime`, `issuer`, `acquirer`, `tracenum`, `req_amount`, `curr_code`, `issuer_amt`, `d_amt`, `approval_code`, `mcc`, `action_code`, `funccode`, `add_resp`, `response_time`, `swoutind`, `posid`, `forwaiic`, `merchant_num`, `mrch_nm`, `mrch_str_adr`, `mrch_cty_nm`, `merchant_geo_cde`, `auth_type_code`, `nrid`, `mti`
- `tranlogtab`: `txndate`, `txntime`, `mti`, `rawtrans`, `acquirer`, `account_number`, `tranlog_id`  *(note: `account_number`, not `acctnum`)*
- `int_detail_tab`: `recap_id`, `charge_amount`, `charge_date`, `type_change`, `auth_number`, `merchant_name`, `city`, `geocode`, `mrch_str_adr`, `mrch_cty_nm`, `mcc`
- `int_control_tab`: `acquirer_iic`, `issuer_iic`, `recap_no`, `currcode`, `recap_date`, `recap_id`, `status`, `num_credits`, `amt_credits`, `num_debits`, `amt_debits`, `net_amt`, `gross_amt`, `alt_currency`, `alt_gross_amt`, `alt_net_amt`, `processing_date`, `settlemnt_date`, `fx_rate`, `fx_rate_date`, `payor_stlmt_curr`, `payor_stlmnt_amt`, `payee_stlmnt_curr`, `payee_stlmnt_amt`, `indb_fi_id`

Watch for the inconsistent naming: `acctnum` vs `account_number`, `approval_code` vs `auth_number`, `curr_code` vs `currcode`, `mrch_str_adr` (same in two tables but named differently elsewhere), `settlemnt_date` (typo preserved from source), `alt_net_amt` (source sheet writes it as `alt_net-amt` with a hyphen — schema uses underscore).

---

## 7. When to stop and ask

Ask the user before running a query or shipping an MCP tool if:
- The target schema / dialect is unconfirmed.
- The question depends on the credit/debit interpretation (§3.1).
- The user references a column that doesn't exist in `schema.sql` — it may be a legacy `xpress.*` name; confirm rather than guess-map it.
- The query would scan `tranlogtab.rawtrans` with `LIKE '%…%'` on a big table — that's a full scan and should be a conscious choice.
