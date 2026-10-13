You are reading a merchant processing statement issued by a card processor or acquirer.
Merchants often submit statements from their previous processor during onboarding, so layouts
and labels vary (e.g. "Gross Sales", "Total Volume", "Sales Amount").

Guidance:
- gross_volume is total card SALES before refunds, chargebacks and fees. Do not use net deposits.
- transaction_count counts sales transactions only, not refunds or chargebacks.
- chargeback_count and chargeback_volume may be labelled "disputes"; if only one of them appears, leave the other null.
- statement_period: return ISO dates. If only a month is given (e.g. "August 2026"), use the first and last day.
- mid: copy digits exactly as printed; it is not a card number.
- Amounts in parentheses are negative in accounting notation; report refunds as a positive number.
