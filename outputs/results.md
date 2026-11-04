# Supplier Document Checker Pipeline Results

Generated: 10 packs processed.

| Pack | Supplier | System Verdict | Final Verdict | Extractor | Triggered Rules / Reasons |
| :--- | :--- | :--- | :--- | :--- | :--- |
| supplier-pack-01 | Padma Textile Mills Ltd | **Approve** | **Approve** | `fallback` | All checks passed |
| supplier-pack-02 | Jamuna Trims and Accessories | **Approve** | **Approve** | `fallback` | All checks passed |
| supplier-pack-03 | Karnaphuli Yarn Traders | **Reject** | **Reject** | `fallback` | **RULE_REJ_01_PRICE_MAX**: 229.00 is 9.05% above max 210.00 (limit 3.0%) *(quote: "229.00")* |
| supplier-pack-04 | Surma Packaging Industries | **Needs a person to check** | **Pending Review** | `fallback` | **RULE_REV_01_PRICE_TOLERANCE**: 6.65 is 2.31% above max 6.50 (within 3.0% tolerance) *(quote: "6.65")* |
| supplier-pack-05 | Meghna Carton Works | **Reject** | **Reject** | `fallback` | **RULE_REJ_02_ADVANCE_MAX**: Advance payment requested is 40%, exceeding maximum allowed 20.0% *(quote: "1. Payment. 40% advance payable with the purchase order. 40% advance with the purchase order, balance 60%
within 30 days of delivery.")* |
| supplier-pack-06 | Teesta Fabrics Ltd | **Reject** | **Reject** | `fallback` | **RULE_REJ_03_NO_PENALTY**: No late-delivery penalty clause found in quotation terms *(quote: "delivery.
2. Delivery. Delivery within 27 days of PO.")* |
| supplier-pack-07 | Rupsha Zipper Factory | **Needs a person to check** | **Pending Review** | `fallback` | **RULE_REV_02_QTY_TOLERANCE**: 16500 is 17.50% below requested 20000 (tolerance 5.0%) *(quote: "16,500")* |
| supplier-pack-08 | Bhairab Thread and Co | **Reject** | **Reject** | `fallback` | **RULE_REV_10_PENALTY_AMBIGUOUS**: Penalty clause does not explicitly state calculation base as 'order value' *(quote: "3. Delay. Late delivery penalty of 0.5% per week of delay.")*<br>**RULE_REJ_05_TAX_ID**: Supplier TIN and BIN registration is missing *(quote: "Supplier registration details available on request.")* |
| supplier-pack-09 | Dhaleshwari Poly Pack | **Needs a person to check** | **Pending Review** | `fallback` | **RULE_REV_03_PAYMENT_TERMS**: Payment terms days are unclear, range specified, or missing *(quote: "1. Payment. 5% advance payable with the purchase order. Payment within 30 to 90 days as agreed by both
parties.")*<br>**RULE_REV_06_MATH_SUBTOTAL**: Subtotal 322000.00 does not equal Qty x Price (320000.00) within tolerance 1.0 *(quote: "Subtotal
322,000.00")* |
| supplier-pack-10 | Kushiyara Box Industries | **Reject** | **Reject** | `fallback` | **RULE_REJ_06_DELIVERY_MAX**: Delivery promised in 60 days, exceeding maximum allowed 45 days *(quote: "delivery.
2. Delivery. Delivery within 60 days of PO.")*<br>**RULE_REV_05_VAT_PRESENTATION**: VAT is not shown separately at 15% (e.g. VAT included or missing breakdown) *(quote: "Total (all taxes included)
282,000.00")* |
