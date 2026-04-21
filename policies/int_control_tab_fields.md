# int_control_tab — Interchange / Recap Control — Field Reference

One row per **recap batch header**. Use it for settlement / clearing batch
totals, FX rate, batch status, and the inbound file the recap was submitted
in. For per-line detail see `int_detail_tab`.

## Columns

- **acquirer_iic** — Acquirer IIC.
- **issuer_iic** — Issuer IIC.
- **recap_no** — Sequence number identifying the recap.
- **currcode** — Currency code of the recap amounts.
- **recap_date** — Recap date.
- **recap_id** — Unique recap identifier. Primary key for this table; referenced by `int_detail_tab`.
- **status** — Status of the recap (e.g. `PROCESSED`, `PENDING`, `REJECTED`).
- **num_credits** — Number of transactions credited in this recap.
- **amt_credits** — Amount of transactions credited in this recap. *(The source spreadsheet description swaps the wording between credits/debits. Treat the column name as authoritative: `amt_credits` is the credit amount.)*
- **num_debits** — Number of transactions debited in this recap.
- **amt_debits** — Amount of transactions debited in this recap. *(Same note: column name is authoritative.)*
- **net_amt** — Net amount of the recap (credits minus debits, or as defined by the source).
- **gross_amt** — Gross amount.
- **alt_currency** — Alternate currency (if the batch is reported in two currencies).
- **alt_gross_amt** — Alternate gross amount.
- **alt_net_amt** — Alternate net amount.
- **processing_date** — Processing date of the recap.
- **settlemnt_date** — Settlement date of the recap.
- **fx_rate** — Exchange rate applied.
- **fx_rate_date** — Date of the exchange rate.
- **payor_stlmt_curr** — Payor settlement currency.
- **payor_stlmnt_amt** — Payor settlement amount.
- **payee_stlmnt_curr** — Payee settlement currency.
- **payee_stlmnt_amt** — Payee settlement amount.
- **indb_fi_id** — Inbound file ID (the file in which the recap was submitted).
