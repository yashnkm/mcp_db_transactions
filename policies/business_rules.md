# Business Rules — Transaction Analysis

This document captures the semantics of specific column values. These rules
are the source of truth — prefer them over any assumption drawn from the raw
column values alone.

## 1. Approval vs Decline — `authstattab.action_code`

The `action_code` column indicates whether a transaction was **approved** or
**declined**.

- `action_code = '00'` → **APPROVED**
- `action_code <> '00'` → **DECLINED** (anything that is not `'00'`)

The non-`'00'` code is itself the decline reason. Common values:

| Code | Meaning                            |
|------|------------------------------------|
| `05` | Do not honor                       |
| `14` | Invalid card number                |
| `51` | Insufficient funds                 |
| `54` | Expired card                       |
| `91` | Issuer or switch inoperative       |

When filtering "declines only", the correct predicate is
`action_code <> '00'` — do not enumerate specific codes, because new decline
reasons may be added over time.

## 2. PB-secured — `authstattab.auth_type_code`

The `auth_type_code` column indicates whether a transaction is PB secured.

- `auth_type_code = '2'` → **PB-secured**
- `auth_type_code IS NULL` → **not PB-secured**
- any other value → **unknown** (flag explicitly; do not assume either way)

When reporting PB status, show both the raw `auth_type_code` value and the
interpretation.

## 3. Raw ISO 8583 payload — `tranlogtab.rawtrans`

`rawtrans` contains the full ISO 8583 message as a single string. Data
elements are separated by the literal five-character token `<DE>` (not a
single byte, not a newline). To extract data element `N`, split on `<DE>` and
index. Do not use regex to match DEs inside the blob — the token is literal.

## 4. Data types — codes are strings, not numbers

All identifier / code fields are strings even when they look numeric:
`acctnum`, `mcc`, `approval_code`, `action_code`, `nrid`, `tracenum`,
`approval_code`, `tranlog_id`, `recap_id`, `merchant_num`, `forwaiic`.

Leading zeros are significant. Never cast these to integers. Always quote
them in SQL predicates.

## 5. int_control_tab credit / debit columns

The source spreadsheet description lines for `amt_credits` and `amt_debits`
swap the wording (describing `amt_credits` as the debit amount and vice
versa). The column **name is authoritative**: `amt_credits` holds credit
amounts, `amt_debits` holds debit amounts. If a business answer hinges on
this, flag the ambiguity and confirm.
