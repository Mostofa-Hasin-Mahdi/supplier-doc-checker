# Supplier Document Checker Pipeline Results

Generated: 4 packs processed.

| Pack | Supplier | System Verdict | Final Verdict | Extractor | Triggered Rules / Reasons |
| :--- | :--- | :--- | :--- | :--- | :--- |
| supplier-pack-01 | Padma Textile Mills Ltd | **Approve** | **Approve** | `gemini+fallback (agreed)` | All checks passed |
| supplier-pack-04 | Surma Packaging Industries | **Needs a person to check** | **Needs a person to check** | `gemini+fallback (agreed)` | **RULE_REV_01_PRICE_TOLERANCE**: 6.65 is 2.31% above max 6.50 (within 3.0% tolerance) *(quote: "6.65")* |
| supplier-pack-07 | Rupsha Zipper Factory | **Needs a person to check** | **Needs a person to check** | `gemini+fallback (agreed)` | **RULE_REV_02_QTY_TOLERANCE**: 16500 is 17.50% below requested 20000 (tolerance 5.0%) *(quote: "16,500")* |
| supplier-pack-09 | Dhaleshwari Poly Pack | **Needs a person to check** | **Needs a person to check** | `gemini+fallback (agreed)` | **RULE_REV_03_PAYMENT_TERMS**: Payment terms days are unclear, range specified, or missing *(quote: "1. Payment. 5% advance payable with the purchase order. Payment within 30 to 90 days as agreed by both parties.")*<br>**RULE_REV_06_MATH_SUBTOTAL**: Subtotal 322000.00 does not equal Qty x Price (320000.00) within tolerance 1.0 *(quote: "322,000.00")* |
