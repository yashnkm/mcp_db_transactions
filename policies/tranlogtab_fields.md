# tranlogtab — Transaction Log Table — Field Reference

The transaction log holds the raw switch message for each transaction. Use it
for debugging at the wire level, for inspecting MTI, or for pulling the
individual ISO 8583 data elements from the raw payload.

## Columns

- **txndate** — Date of the message.
- **txntime** — Time of the message.
- **mti** — Message Type Identifier (ISO 8583).
- **rawtrans** — The full transaction-log message. Contains all ISO 8583 data elements as a single string, with each element delimited by the literal five-character token `<DE>`. Parsing requires splitting on this exact literal — it is **not** a single byte, and **not** a newline.
- **acquirer** — Acquirer IIC that originated the message.
- **account_number** — Primary Account Number (PAN). Same semantics as `acctnum` in `authstattab`, but named differently here.
- **tranlog_id** — Unique identifier for each tranlog row; acts as the primary key of this table.

## Joining with `authstattab`

There is no single-column key; correlate on the tuple `(account_number = acctnum, txndate, txntime, mti)`, or use `tracenum` / `nrid` extracted from the raw payload when available.
