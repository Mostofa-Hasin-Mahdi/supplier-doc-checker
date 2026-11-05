"""LLM client interface, Gemini client, and FakeLLMClient for testing."""

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from decimal import Decimal

from supplier_check.extract_fallback import extract_fallback_from_text
from supplier_check.llm_schema import EXTRACTION_PROMPT, FlatLLMQuote
from supplier_check.models import ExtractedQuote, FieldEvidence, FieldStatus
from supplier_check.parsers import (
    parse_advance,
    parse_days,
    parse_money,
    parse_payment_days,
    parse_percent,
    parse_tin_bin,
)

logger = logging.getLogger(__name__)


def find_enclosing_evidence(
    raw_val: str | None,
    document_text: str,
    field_name: str | None = None,
    audit_log: list[str] | None = None,
) -> tuple[str | None, str | None]:
    """Locate the raw value in document text and return the enclosing line or sentence.

    Rules:
    - Normalizes whitespace for search.
    - If raw_val cannot be found in document_text -> returns (None, None).
    - If it appears more than once, selects the first occurrence inside the relevant section
      (terms vs table) and logs any ambiguity in audit_log.
    - For terms fields, unit of enclosing text is the numbered clause or sentence.
    - For table/header fields, unit is the enclosing line.

    Returns:
        (enclosing_quote, section_name)
    """
    if not raw_val or not raw_val.strip():
        return None, None

    raw_val_clean = raw_val.strip()
    norm_val = " ".join(raw_val_clean.split())

    terms_idx = document_text.find("TERMS AND CONDITIONS")
    table_text = document_text[:terms_idx] if terms_idx != -1 else document_text
    terms_text = document_text[terms_idx:] if terms_idx != -1 else ""

    is_terms_field = field_name in {
        "advance_text",
        "payment_terms_text",
        "delivery_terms_text",
        "late_penalty_text",
        "validity_text",
    }

    # 1. In terms section: check numbered clauses or sentences
    if is_terms_field and terms_text:
        clauses = re.split(r"\n(?=[0-9]+\.\s*)", terms_text.strip())
        for clause in clauses:
            if norm_val.lower() in " ".join(clause.split()).lower():
                return clause.strip(), "terms"
        sentences = re.split(r"(?<=[.!?])\s+", terms_text.strip())
        for s in sentences:
            if norm_val.lower() in " ".join(s.split()).lower():
                return s.strip(), "terms"

    # 2. Check enclosing line in preferred section
    preferred_areas = (
        [(terms_text, "terms"), (table_text, "table")]
        if is_terms_field
        else [(table_text, "table"), (terms_text, "terms")]
    )

    matches: list[tuple[str, str]] = []
    for area_text, sec_name in preferred_areas:
        if not area_text:
            continue
        lines = [line.strip() for line in area_text.splitlines() if line.strip()]
        for line in lines:
            if norm_val.lower() in " ".join(line.split()).lower():
                matches.append((line, sec_name))

    if matches:
        if len(matches) > 1 and audit_log is not None:
            audit_log.append(
                f"Value '{raw_val_clean}' for field '{field_name}' matched {len(matches)} occurrences; "
                f"using first occurrence in section '{matches[0][1]}'."
            )
        return matches[0][0], matches[0][1]

    # 3. Fallback: check whole document lines
    all_lines = [line.strip() for line in document_text.splitlines() if line.strip()]
    for line in all_lines:
        if norm_val.lower() in " ".join(line.split()).lower():
            sec = "terms" if terms_idx != -1 and document_text.find(line) >= terms_idx else "table"
            return line, sec

    return None, None


def map_flat_to_extracted_quote(
    flat: FlatLLMQuote,
    document_text: str,
    audit_log: list[str] | None = None,
) -> ExtractedQuote:
    """Map FlatLLMQuote (raw string outputs from LLM) into validated internal ExtractedQuote.

    Evidence quotes are built by code by locating raw values in the document text.
    Values are normalised via deterministic parsers from the code-built quotes.
    """
    log = audit_log if audit_log is not None else []

    # Helper: build evidence quote by locating raw value
    def get_ev_quote(raw_val: str | None, name: str) -> tuple[str | None, bool]:
        if not raw_val or not raw_val.strip():
            return None, False
        q, _ = find_enclosing_evidence(raw_val, document_text, name, log)
        if q is None:
            # Hallucination guard: raw value proposed by LLM is not grounded in text
            log.append(
                f"Field '{name}': proposed raw value '{raw_val}' not found in document text (hallucination guard)."
            )
            return None, False
        return q, True

    # 1. Direct string fields
    def mk_str_fe(val: str | None, name: str) -> FieldEvidence[str]:
        quote, found = get_ev_quote(val, name)
        if found and quote and val:
            return FieldEvidence[str](
                status=FieldStatus.FOUND,
                value=val.strip(),
                evidence_quote=quote,
                grounded=True,
            )
        if val and not found:
            return FieldEvidence[str](
                status=FieldStatus.UNCERTAIN,
                value=None,
                absence_note=f"{name} raw value not grounded in text",
            )
        return FieldEvidence[str](
            status=FieldStatus.UNCERTAIN,
            absence_note=f"{name} not found",
        )

    fe_supplier = mk_str_fe(flat.supplier_name, "supplier_name")
    fe_qt = mk_str_fe(flat.quotation_no, "quotation_no")
    fe_date = mk_str_fe(flat.quote_date, "quote_date")
    fe_pr = mk_str_fe(flat.reference_pr, "reference_pr")
    fe_item_code = mk_str_fe(flat.item_code, "item_code")
    fe_desc = mk_str_fe(flat.description, "description")
    fe_unit = mk_str_fe(flat.unit, "unit")

    # 2. Money / Number fields: normalise via deterministic parsers from code-built quote
    def mk_decimal_fe(val_str: str | None, name: str) -> FieldEvidence[Decimal]:
        quote, found = get_ev_quote(val_str, name)
        if not found and val_str:
            return FieldEvidence[Decimal](
                status=FieldStatus.UNCERTAIN,
                value=None,
                absence_note=f"{name} raw value not grounded in document text",
            )
        if not quote:
            return FieldEvidence[Decimal](
                status=FieldStatus.UNCERTAIN,
                value=None,
                absence_note=f"{name} missing",
            )
        parsed = parse_money(quote) or parse_money(val_str)
        if parsed is not None:
            return FieldEvidence[Decimal](
                status=FieldStatus.FOUND,
                value=parsed,
                evidence_quote=quote,
                grounded=True,
            )
        return FieldEvidence[Decimal](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote=quote,
            absence_note=f"{name} unparseable as money",
        )

    fe_qty = mk_decimal_fe(flat.quantity, "quantity")
    fe_price = mk_decimal_fe(flat.unit_price, "unit_price")
    fe_total = mk_decimal_fe(flat.total, "total")

    # Subtotal
    sub_quote, sub_found = get_ev_quote(flat.subtotal, "subtotal")
    if sub_found and sub_quote:
        parsed_sub = parse_money(sub_quote) or parse_money(flat.subtotal)
        if parsed_sub is not None:
            fe_subtotal = FieldEvidence[Decimal](
                status=FieldStatus.FOUND,
                value=parsed_sub,
                evidence_quote=sub_quote,
                grounded=True,
            )
        else:
            fe_subtotal = FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN, evidence_quote=sub_quote)
    elif flat.subtotal and not sub_found:
        fe_subtotal = FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN, absence_note="Subtotal not grounded")
    else:
        fe_subtotal = FieldEvidence[Decimal](
            status=FieldStatus.ABSENT,
            value=None,
            evidence_quote=None,
            absence_note="No subtotal row found in quotation",
        )

    # 3. VAT Fields
    has_tax_included = (
        "vat included" in document_text.lower() or "all taxes included" in document_text.lower()
    )
    vat_amt_quote, vat_amt_found = get_ev_quote(flat.vat_amount, "vat_amount")
    vat_pct_quote, vat_pct_found = get_ev_quote(flat.vat_percent, "vat_percent")

    if (
        vat_amt_found
        and vat_pct_found
        and vat_amt_quote
        and vat_pct_quote
        and not has_tax_included
    ):
        parsed_vat_pct = parse_percent(vat_pct_quote) or parse_percent(flat.vat_percent)
        parsed_vat_amt = parse_money(vat_amt_quote) or parse_money(flat.vat_amount)
        if parsed_vat_pct is not None and parsed_vat_amt is not None:
            fe_vat_percent = FieldEvidence[Decimal](
                status=FieldStatus.FOUND,
                value=parsed_vat_pct,
                evidence_quote=vat_pct_quote,
                grounded=True,
            )
            fe_vat_amount = FieldEvidence[Decimal](
                status=FieldStatus.FOUND,
                value=parsed_vat_amt,
                evidence_quote=vat_amt_quote,
                grounded=True,
            )
            fe_vat_shown = FieldEvidence[bool](
                status=FieldStatus.DERIVED,
                value=True,
                evidence_quote=vat_pct_quote,
                grounded=True,
            )
        else:
            fe_vat_percent = FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN)
            fe_vat_amount = FieldEvidence[Decimal](status=FieldStatus.UNCERTAIN)
            fe_vat_shown = FieldEvidence[bool](status=FieldStatus.UNCERTAIN)
    else:
        fe_vat_percent = FieldEvidence[Decimal](
            status=FieldStatus.ABSENT,
            value=None,
            evidence_quote=None,
            absence_note="VAT not shown separately at 15%",
        )
        fe_vat_amount = FieldEvidence[Decimal](
            status=FieldStatus.ABSENT,
            value=None,
            evidence_quote=None,
            absence_note="VAT not shown separately at 15%",
        )
        fe_vat_shown = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=False,
            evidence_quote=fe_total.evidence_quote or "Total",
            absence_note="VAT included / all taxes included",
            grounded=True,
        )

    # 4. TIN / BIN
    tin_quote, tin_found = get_ev_quote(flat.tin, "tin")
    bin_quote, bin_found = get_ev_quote(flat.bin, "bin")
    reg_quote = tin_quote or bin_quote

    tin_val, bin_val, is_malformed = parse_tin_bin(
        f"TIN: {flat.tin or ''} BIN: {flat.bin or ''}" if (flat.tin or flat.bin) else document_text
    )

    if flat.tin and not tin_found:
        fe_tin = FieldEvidence[str](status=FieldStatus.UNCERTAIN, absence_note="TIN not grounded in text")
    elif tin_val and tin_found:
        fe_tin = FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=tin_val,
            evidence_quote=reg_quote,
            grounded=True,
        )
    elif is_malformed:
        fe_tin = FieldEvidence[str](status=FieldStatus.UNCERTAIN, evidence_quote=reg_quote)
    else:
        fe_tin = FieldEvidence[str](
            status=FieldStatus.ABSENT,
            value=None,
            evidence_quote=None,
            absence_note="TIN missing or available on request",
        )

    if flat.bin and not bin_found:
        fe_bin = FieldEvidence[str](status=FieldStatus.UNCERTAIN, absence_note="BIN not grounded in text")
    elif bin_val and bin_found:
        fe_bin = FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=bin_val,
            evidence_quote=reg_quote,
            grounded=True,
        )
    elif is_malformed:
        fe_bin = FieldEvidence[str](status=FieldStatus.UNCERTAIN, evidence_quote=reg_quote)
    else:
        fe_bin = FieldEvidence[str](
            status=FieldStatus.ABSENT,
            value=None,
            evidence_quote=None,
            absence_note="BIN missing or available on request",
        )

    # 5. Terms: Advance & Payment Days
    adv_quote, adv_found = get_ev_quote(flat.advance_text, "advance_text")
    pay_quote, pay_found = get_ev_quote(flat.payment_terms_text, "payment_terms_text")
    combined_pay_quote = adv_quote or pay_quote

    adv_target_text = adv_quote or pay_quote or flat.advance_text or flat.payment_terms_text
    adv_val, adv_uncertain = parse_advance(adv_target_text)

    if not adv_uncertain and adv_val is not None and combined_pay_quote:
        fe_adv = FieldEvidence[Decimal](
            status=FieldStatus.FOUND,
            value=adv_val,
            evidence_quote=combined_pay_quote,
            grounded=True,
        )
    else:
        fe_adv = FieldEvidence[Decimal](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote=combined_pay_quote,
            absence_note="Advance payment percentage uncertain or unstated",
        )

    fe_pay_terms = (
        FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=flat.payment_terms_text.strip(),
            evidence_quote=pay_quote,
            grounded=True,
        )
        if (flat.payment_terms_text and pay_found and pay_quote)
        else FieldEvidence[str](status=FieldStatus.UNCERTAIN, absence_note="Payment terms not found")
    )

    pay_days_target = pay_quote or flat.payment_terms_text
    pay_days = parse_payment_days(pay_days_target)
    if pay_days is not None and pay_quote:
        fe_pay_days = FieldEvidence[int](
            status=FieldStatus.FOUND,
            value=pay_days,
            evidence_quote=pay_quote,
            grounded=True,
        )
    else:
        fe_pay_days = FieldEvidence[int](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote=pay_quote,
            absence_note="Payment days unclear or range specified",
        )

    # 6. Delivery
    del_quote, del_found = get_ev_quote(flat.delivery_terms_text, "delivery_terms_text")
    fe_del_terms = (
        FieldEvidence[str](
            status=FieldStatus.FOUND,
            value=flat.delivery_terms_text.strip(),
            evidence_quote=del_quote,
            grounded=True,
        )
        if (flat.delivery_terms_text and del_found and del_quote)
        else FieldEvidence[str](status=FieldStatus.UNCERTAIN, absence_note="Delivery terms not found")
    )

    del_days_target = del_quote or flat.delivery_terms_text
    del_days = parse_days(del_days_target)
    if del_days is not None and del_quote:
        fe_del_days = FieldEvidence[int](
            status=FieldStatus.FOUND,
            value=del_days,
            evidence_quote=del_quote,
            grounded=True,
        )
    else:
        fe_del_days = FieldEvidence[int](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote=del_quote,
            absence_note="Delivery days missing or unparseable",
        )

    # 7. Late Penalty Clause
    pen_quote, pen_found = get_ev_quote(flat.late_penalty_text, "late_penalty_text")
    has_delay_keywords = "penalt" in document_text.lower() or "delay" in document_text.lower()

    if flat.late_penalty_text and pen_found and pen_quote:
        pen_rate = parse_percent(pen_quote) or parse_percent(flat.late_penalty_text)
        specifies_order_val = "order value" in pen_quote.lower()
        fe_pen_present = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=True,
            evidence_quote=pen_quote,
            grounded=True,
        )
        fe_pen_rate = FieldEvidence[Decimal](
            status=FieldStatus.FOUND if pen_rate is not None else FieldStatus.UNCERTAIN,
            value=pen_rate,
            evidence_quote=pen_quote,
            grounded=True,
        )
        fe_pen_specifies = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=specifies_order_val,
            evidence_quote=pen_quote,
            grounded=True,
        )
    elif not has_delay_keywords:
        fe_pen_present = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=False,
            evidence_quote=None,
            absence_note="No late delivery penalty clause found in terms and conditions",
            grounded=True,
        )
        fe_pen_rate = FieldEvidence[Decimal](
            status=FieldStatus.ABSENT,
            value=None,
            evidence_quote=None,
            absence_note="No late delivery penalty clause present",
        )
        fe_pen_specifies = FieldEvidence[bool](
            status=FieldStatus.DERIVED,
            value=False,
            evidence_quote=None,
            absence_note="No late delivery penalty clause present",
            grounded=True,
        )
    else:
        fe_pen_present = FieldEvidence[bool](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote=pen_quote,
            absence_note="Delay clause missing or ungrounded",
        )
        fe_pen_rate = FieldEvidence[Decimal](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote=pen_quote,
        )
        fe_pen_specifies = FieldEvidence[bool](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote=pen_quote,
        )

    # 8. Validity
    val_quote, val_found = get_ev_quote(flat.validity_text, "validity_text")
    val_days_target = val_quote or flat.validity_text
    val_days = parse_days(val_days_target)
    if val_days is not None and val_quote:
        fe_val_days = FieldEvidence[int](
            status=FieldStatus.FOUND,
            value=val_days,
            evidence_quote=val_quote,
            grounded=True,
        )
    else:
        fe_val_days = FieldEvidence[int](
            status=FieldStatus.UNCERTAIN,
            value=None,
            evidence_quote=val_quote,
            absence_note="Validity days missing or unparseable",
        )

    line_item_count = 1 if fe_item_code.status == FieldStatus.FOUND else None

    return ExtractedQuote(
        supplier_name=fe_supplier,
        quotation_no=fe_qt,
        quote_date=fe_date,
        reference_pr=fe_pr,
        line_item_count=line_item_count,
        item_code=fe_item_code,
        description=fe_desc,
        quantity=fe_qty,
        unit=fe_unit,
        unit_price=fe_price,
        subtotal=fe_subtotal,
        vat_amount=fe_vat_amount,
        vat_percent=fe_vat_percent,
        vat_shown_separately=fe_vat_shown,
        total=fe_total,
        tin=fe_tin,
        bin=fe_bin,
        advance_percent=fe_adv,
        payment_terms_text=fe_pay_terms,
        payment_days=fe_pay_days,
        delivery_terms_text=fe_del_terms,
        delivery_days=fe_del_days,
        late_penalty_percent_per_week=fe_pen_rate,
        late_penalty_clause_present=fe_pen_present,
        late_penalty_specifies_order_value=fe_pen_specifies,
        validity_days=fe_val_days,
    )


class LLMClient(ABC):
    """Abstract client interface for quotation field extraction."""

    @abstractmethod
    def extract(self, document_text: str) -> dict:
        """Extract flat quotation fields proposal from document text."""
        pass


class GeminiClient(LLMClient):
    """Production client using Google GenAI SDK (google-genai) with JSON output and temperature 0."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        # Default to active, free-tier available Gemini 3.5 Flash-Lite
        self.model_name = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured. Calls to GeminiClient.extract will raise.")

    def extract(self, document_text: str) -> dict:
        """Call Gemini API requesting JSON output strictly conforming to FlatLLMQuote schema."""
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")

        import time

        from google import genai
        from google.genai import types

        # Configure 30-second timeout per call via HttpOptions (timeout is in milliseconds)
        http_options = types.HttpOptions(timeout=self.timeout_seconds * 1000)
        client = genai.Client(api_key=self.api_key, http_options=http_options)
        prompt = EXTRACTION_PROMPT.format(document_text=document_text)

        config = types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=FlatLLMQuote,
        )

        last_err: Exception | None = None
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )
                raw_text = response.text or "{}"
                return json.loads(raw_text)
            except Exception as e:
                last_err = e
                logger.warning("Gemini extract attempt %d error: %s", attempt + 1, e)
                if attempt < 1:
                    time.sleep(2)

        if last_err:
            raise last_err
        return {}


class FakeLLMClient(LLMClient):
    """Canned mock LLM client for tests."""

    def __init__(self, canned_response: dict | str) -> None:
        self.canned_response = canned_response
        self.calls: list[str] = []

    def extract(self, document_text: str) -> dict:
        self.calls.append(document_text)
        if isinstance(self.canned_response, str):
            return json.loads(self.canned_response)
        return self.canned_response


def extract_quote_with_llm_or_fallback(
    document_text: str,
    llm_client: LLMClient | None = None,
) -> tuple[ExtractedQuote, str]:
    """Extract quote proposing via LLM (with 1 retry on invalid JSON) or deterministic fallback.

    Returns:
        (extracted_quote, extractor_used_name)
    """
    if llm_client is not None:
        for attempt in range(2):
            try:
                raw_dict = llm_client.extract(document_text)
                flat = FlatLLMQuote.model_validate(raw_dict)
                quote = map_flat_to_extracted_quote(flat, document_text)
                return quote, "llm"
            except Exception as e:
                logger.warning("LLM extraction attempt %d failed: %s", attempt + 1, e)

    fallback_quote = extract_fallback_from_text(document_text)
    return fallback_quote, "fallback"
