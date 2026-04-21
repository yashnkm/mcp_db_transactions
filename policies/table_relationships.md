# Table Relationships

Four tables model the full transaction lifecycle. There are no declared
foreign keys — the relationships below are logical.

```
           (authorization)                      (clearing / settlement)
        +-------------------+                 +---------------------+
        |   authstattab     |                 |   int_control_tab   |
        |  one row per auth |                 |  one row per recap  |
        +-------------------+                 +---------------------+
                 ^                                       |
                 |                                       | recap_id
                 |                                       v
                 | approval_code == auth_number   +---------------------+
                 +--------------------------------|    int_detail_tab   |
                                                  | one row per charge  |
                                                  +---------------------+

        +-------------------+
        |    tranlogtab     |    raw ISO 8583 wire messages (one per message)
        +-------------------+
```

## Logical keys

- `int_detail_tab.recap_id` → `int_control_tab.recap_id`
- `int_detail_tab.auth_number` → `authstattab.approval_code`
- `authstattab.nrid` — unique per transaction, strongest join key across systems.
- `authstattab.tracenum` — correlates multiple ISO 8583 messages within a single auth cycle.
- `tranlogtab` ↔ `authstattab` — correlate on `(account_number = acctnum, txndate, txntime, mti)` or parse `nrid` / `tracenum` out of `rawtrans`.

## Picking the right table

| Question is about... | Table |
|---|---|
| Approval / decline decision, merchant at auth-time, response codes | `authstattab` |
| The raw wire message, MTI inspection, extracting individual data elements | `tranlogtab` |
| Which charges are in a specific clearing batch | `int_detail_tab` |
| Batch totals, FX rate, settlement status / dates | `int_control_tab` |

Rule of thumb — if the user says "transaction" they almost always mean
`authstattab`. If they say "recap", "settlement", "batch", or "interchange",
it is one of the `int_*` tables. If they say "raw message" or "DE fields" it
is `tranlogtab`.
