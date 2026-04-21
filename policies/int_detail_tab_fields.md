# int_detail_tab — Interchange / Recap Detail — Field Reference

One row per **charge inside a recap batch**. Use it for questions about the
individual line items within a settlement / clearing batch — which
transactions belong to a given recap, their amounts, and the merchant
associated with each charge.

## Columns

- **recap_id** — Recap ID. Unique ID assigned for each recap entry. Foreign key back to `int_control_tab.recap_id`.
- **charge_amount** — Transaction amount for this line item.
- **charge_date** — Date of the charge.
- **type_change** — Type of recap submitted (e.g. `SALE`, `REFUND`, `ADJ`).
- **auth_number** — Same value as the originating authorization's `approval_code` in `authstattab`. Use it to bridge from a recap line item back to the original auth.
- **merchant_name** — Establishment (merchant) name for this line.
- **city** — City of the merchant.
- **geocode** — Geocode of the merchant.
- **mrch_str_adr** — Merchant street address.
- **mrch_cty_nm** — Merchant city name (may duplicate `city`).
- **mcc** — Merchant category code.

## Joining

- `int_detail_tab.recap_id` ↔ `int_control_tab.recap_id` — to the batch header.
- `int_detail_tab.auth_number` ↔ `authstattab.approval_code` — back to the auth that originated this clearing.
