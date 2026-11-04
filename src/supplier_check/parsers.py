"""Deterministic pure-function parsers for quote fields."""

import re
from decimal import Decimal, InvalidOperation


def parse_money(text: str | None) -> Decimal | None:
    """Parse monetary amounts (handling commas, whitespace, currency prefixes).

    Examples:
        '472.00' -> Decimal('472.00')
        '5,664,000.00' -> Decimal('5664000.00')
        'BDT 183,200.00' -> Decimal('183200.00')
        '6.65' -> Decimal('6.65')
    """
    if not text:
        return None
    # Find numeric sequence with optional commas and decimal point
    cleaned = text.replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def parse_percent(text: str | None) -> Decimal | None:
    """Parse percentage value from text.

    Examples:
        '15%' -> Decimal('15.0')
        '0.5%' -> Decimal('0.5')
        '1% of order value' -> Decimal('1.0')
    """
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if not match:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:
        return None


def parse_days(text: str | None) -> int | None:
    """Parse duration in days from text expressions.

    Supports:
        '24 days' -> 24
        'within 24 days of receiving the purchase order' -> 24
        '4 weeks' -> 28
        '2 months' -> 60
    """
    if not text:
        return None

    cleaned = text.lower()

    # Check for weeks
    m_weeks = re.search(r"(\d+)\s*(?:full\s*)?weeks?", cleaned)
    if m_weeks:
        return int(m_weeks.group(1)) * 7

    # Check for months
    m_months = re.search(r"(\d+)\s*months?", cleaned)
    if m_months:
        return int(m_months.group(1)) * 30

    # Check for days (including 'within X days')
    m_days = re.search(r"(\d+)\s*days?", cleaned)
    if m_days:
        return int(m_days.group(1))

    return None


def parse_payment_days(text: str | None) -> int | None:
    """Parse agreed payment days after delivery.

    Returns an integer if a clear day/period is specified (e.g. 'within 45 days after delivery' -> 45).
    Returns None for ambiguous ranges (e.g. 'within 30 to 90 days as agreed by both parties').
    """
    if not text:
        return None

    cleaned = text.lower()

    # Detect ambiguous range like '30 to 90 days'
    if re.search(r"\d+\s*(?:to|-)\s*\d+\s*days?", cleaned):
        return None

    # Detect single day term
    m = re.search(r"(?:within\s*)?(\d+)\s*days?", cleaned)
    if m:
        return int(m.group(1))

    # Detect weeks
    m_w = re.search(r"(?:within\s*)?(\d+)\s*weeks?", cleaned)
    if m_w:
        return int(m_w.group(1)) * 7

    return None


def parse_advance(text: str | None) -> tuple[Decimal | None, bool]:
    """Parse advance payment percentage from text.

    Returns:
        (value, is_uncertain)
        - 'No advance payment required' -> (Decimal('0.0'), False)
        - '10% advance payable' -> (Decimal('10.0'), False)
        - '40% advance ... 40% advance' -> (Decimal('40.0'), False) [duplicate values collapse]
        - Conflicting percentages (e.g. '10% advance ... 20% advance') -> (None, True)
        - Missing or unrecognizable text -> (None, True)
    """
    if not text:
        return None, True

    cleaned = text.strip()
    if re.search(r"\bno\s+advance\b", cleaned, re.IGNORECASE):
        return Decimal("0.0"), False

    # Find all percentages linked to advance
    # Search for patterns like '10% advance' or 'advance ... 10%'
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*%\s*(?:advance|payable)", cleaned, re.IGNORECASE)
    if not matches:
        # Check reverse pattern: advance ... X%
        matches = re.findall(r"advance[^\d%]{0,25}(\d+(?:\.\d+)?)\s*%", cleaned, re.IGNORECASE)

    if not matches:
        return None, True

    # Parse all found percentages as Decimals
    percentages = {Decimal(m) for m in matches}
    if len(percentages) == 1:
        return percentages.pop(), False

    # Conflicting percentages
    return None, True


def parse_tin_bin(text: str | None) -> tuple[str | None, str | None, bool]:
    """Extract TIN and BIN from supplier registration text.

    Returns:
        (tin, bin, is_malformed)
        If text contains 'available on request' -> (None, None, False)
        If valid regex matches TIN and BIN digits -> (tin_str, bin_str, False)
        If TIN/BIN prefix present but malformed digits -> (None, None, True)
    """
    if not text:
        return None, None, False

    cleaned = text.strip()
    if re.search(r"available\s+on\s+request", cleaned, re.IGNORECASE):
        return None, None, False

    tin_val: str | None = None
    bin_val: str | None = None
    is_malformed = False

    # TIN pattern: e.g. TIN: 101458013391 (typically 10-14 digits)
    m_tin = re.search(r"\bTIN\s*:\s*([A-Za-z0-9\-]+)", cleaned, re.IGNORECASE)
    if m_tin:
        raw_tin = m_tin.group(1).strip()
        if re.match(r"^\d{8,15}$", raw_tin):
            tin_val = raw_tin
        else:
            is_malformed = True

    # BIN pattern: e.g. BIN: 000170141-0101 (digits and hyphens)
    m_bin = re.search(r"\bBIN\s*:\s*([A-Za-z0-9\-]+)", cleaned, re.IGNORECASE)
    if m_bin:
        raw_bin = m_bin.group(1).strip()
        if re.match(r"^\d{8,15}(?:-\d{2,6})?$", raw_bin):
            bin_val = raw_bin
        else:
            is_malformed = True

    return tin_val, bin_val, is_malformed
