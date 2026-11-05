# Evaluation Report: Supplier Document Checker Pipeline

**Accuracy:** 10/10 (100.0%) verdicts matching expected golden dataset.

## Pack Verdict Evaluation

| Pack | Expected Verdict | Actual Verdict | Verdict Match | Expected Rules Present | Actual Triggered Rules |
| :--- | :--- | :--- | :---: | :---: | :--- |
| supplier-pack-01 | `APPROVE` | `APPROVE` | **PASS** | Yes | *(none)* |
| supplier-pack-02 | `APPROVE` | `APPROVE` | **PASS** | Yes | *(none)* |
| supplier-pack-03 | `REJECT` | `REJECT` | **PASS** | Yes | RULE_REJ_01_PRICE_MAX |
| supplier-pack-04 | `NEEDS_REVIEW` | `NEEDS_REVIEW` | **PASS** | Yes | RULE_REV_01_PRICE_TOLERANCE |
| supplier-pack-05 | `REJECT` | `REJECT` | **PASS** | Yes | RULE_REJ_02_ADVANCE_MAX |
| supplier-pack-06 | `REJECT` | `REJECT` | **PASS** | Yes | RULE_REJ_03_NO_PENALTY |
| supplier-pack-07 | `NEEDS_REVIEW` | `NEEDS_REVIEW` | **PASS** | Yes | RULE_REV_02_QTY_TOLERANCE |
| supplier-pack-08 | `REJECT` | `REJECT` | **PASS** | Yes | RULE_REJ_05_TAX_ID, RULE_REV_10_PENALTY_AMBIGUOUS |
| supplier-pack-09 | `NEEDS_REVIEW` | `NEEDS_REVIEW` | **PASS** | Yes | RULE_REV_03_PAYMENT_TERMS, RULE_REV_06_MATH_SUBTOTAL |
| supplier-pack-10 | `REJECT` | `REJECT` | **PASS** | Yes | RULE_REJ_06_DELIVERY_MAX, RULE_REV_05_VAT_PRESENTATION |

## Confusion Matrix

| Expected \ Actual | APPROVE | REJECT | NEEDS_REVIEW |
| :--- | :---: | :---: | :---: |
| **APPROVE** | 2 | 0 | 0 |
| **REJECT** | 0 | 5 | 0 |
| **NEEDS_REVIEW** | 0 | 0 | 3 |
