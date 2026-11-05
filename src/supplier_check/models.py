"""Data models for supplier quotation extraction, rules evaluation, and decisions."""

from decimal import Decimal
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class FieldStatus(StrEnum):
    """Extraction status for an individual field."""

    FOUND = "FOUND"
    ABSENT = "ABSENT"
    UNCERTAIN = "UNCERTAIN"
    DERIVED = "DERIVED"


class Severity(StrEnum):
    """Rule evaluation outcome severity."""

    PASS = "PASS"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class Verdict(StrEnum):
    """Pipeline final verdict."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    NEEDS_REVIEW = "NEEDS_REVIEW"

    @property
    def display_name(self) -> str:
        """User-facing verdict string."""
        mapping = {
            Verdict.APPROVE: "Approve",
            Verdict.REJECT: "Reject",
            Verdict.NEEDS_REVIEW: "Needs a person to check",
        }
        return mapping[self]


class FieldEvidence(BaseModel, Generic[T]):
    """Container wrapping an extracted value with status and supporting verbatim quote."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: FieldStatus = Field(
        ...,
        description="Status of the extraction: FOUND, ABSENT, or UNCERTAIN.",
    )
    value: T | None = Field(
        default=None,
        description="Extracted value, or None if ABSENT or UNCERTAIN.",
    )
    evidence_quote: str | None = Field(
        default=None,
        description="Verbatim quote from the document supporting this field.",
    )
    absence_note: str | None = Field(
        default=None,
        description="Explanation note used when status is ABSENT (not checked for grounding).",
    )
    grounded: bool = Field(
        default=False,
        description="Code-computed flag: True only if evidence_quote is verified in document text.",
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> "FieldEvidence[T]":
        """Enforce invariants based on extraction status.

        - FOUND: strictly requires value is not None (and non-empty for str) AND non-empty evidence_quote.
                 Ordinary extracted fields MUST carry a non-empty verbatim quote.
        - DERIVED: code-derived boolean fields; requires non-None boolean value. Can have evidence_quote
                   or an absence_note explaining why it was derived.
        - ABSENT: requires value to be None.
        - UNCERTAIN: may carry anything.
        """
        if self.status == FieldStatus.FOUND:
            if self.value is None:
                raise ValueError("status FOUND requires a non-None value")
            if isinstance(self.value, str) and not self.value.strip():
                raise ValueError("status FOUND requires a non-empty string value")
            if not self.evidence_quote or not self.evidence_quote.strip():
                raise ValueError("status FOUND requires a non-empty evidence_quote")
        elif self.status == FieldStatus.DERIVED:
            if self.value is None:
                raise ValueError("status DERIVED requires a non-None value")
            if not isinstance(self.value, bool):
                raise ValueError("status DERIVED is reserved for code-derived boolean fields")
            if not self.evidence_quote and not self.absence_note:
                raise ValueError(
                    "status DERIVED requires either an evidence_quote or an absence_note"
                )
        elif self.status == FieldStatus.ABSENT:
            if self.value is not None:
                raise ValueError("status ABSENT requires value to be None")
        # UNCERTAIN may carry anything
        return self


class PurchaseRequestItem(BaseModel):
    """Purchase request line item from purchase-request.csv."""

    pr_number: str
    item_code: str
    description: str
    unit: str
    quantity_requested: Decimal
    max_unit_price: Decimal


class ExtractedQuote(BaseModel):
    """Structured supplier quotation extracted from supplier pack."""

    supplier_name: FieldEvidence[str]
    quotation_no: FieldEvidence[str]
    quote_date: FieldEvidence[str]  # ISO date string YYYY-MM-DD
    reference_pr: FieldEvidence[str]
    line_item_count: int | None = Field(
        default=None,
        ge=0,
        description="Total count of line items in the quotation table, or None if undetermined.",
    )
    item_code: FieldEvidence[str]
    description: FieldEvidence[str]
    quantity: FieldEvidence[Decimal]
    unit: FieldEvidence[str]
    unit_price: FieldEvidence[Decimal]
    subtotal: FieldEvidence[Decimal]
    vat_amount: FieldEvidence[Decimal]
    vat_percent: FieldEvidence[Decimal]
    vat_shown_separately: FieldEvidence[bool]
    total: FieldEvidence[Decimal]
    tin: FieldEvidence[str]
    bin: FieldEvidence[str]
    advance_percent: FieldEvidence[Decimal]
    payment_terms_text: FieldEvidence[str]
    payment_days: FieldEvidence[int]
    delivery_terms_text: FieldEvidence[str]
    delivery_days: FieldEvidence[int]
    late_penalty_percent_per_week: FieldEvidence[Decimal]
    late_penalty_clause_present: FieldEvidence[bool]
    late_penalty_specifies_order_value: FieldEvidence[bool]
    validity_days: FieldEvidence[int]


class RuleResult(BaseModel):
    """Result of evaluating a single procurement rule."""

    rule_id: str
    severity: Severity  # PASS, REVIEW, REJECT
    message: str
    evidence_quote: str


class Decision(BaseModel):
    """Final deterministic pipeline verdict with all triggered rules."""

    verdict: Verdict
    triggered_rules: list[RuleResult] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    @property
    def display_verdict(self) -> str:
        """Formatted verdict name for display."""
        return self.verdict.display_name
