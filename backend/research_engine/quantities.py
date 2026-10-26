"""
Quantities in claims and snippets, compared under narrow, explicit rules.

internal/rfcs/V3.1-corpus-scope.md §9.3. The mechanical half of claim verification in a
selected-files run: a number, date or percentage a claim states must be present in the
snippets of the citations it carries, after normalisation. **Necessary, never sufficient** —
a value can match and still be attached to the wrong subject, which only the model verdict
can catch.

The rules are deliberately narrow. Every normalisation that could equate two different
values is either excluded or confined to an unambiguous form; anything ambiguous is compared
literally. A false "match" here would wave an invented figure past the one check no model
opinion can override, so when in doubt this module says "not found".

| Representation    | Rule                                                                     |
|-------------------|--------------------------------------------------------------------------|
| Thousands groups  | `1,000` = `1000` = `1 000`; a comma groups only before exactly 3 digits   |
| Scale words       | k/thousand ×10³, M/million/mn ×10⁶, bn/billion ×10⁹ (short scale)        |
| Percentages       | `12%` = `12 percent` = `12 per cent`; a ratio `0.12` is NOT `12%`        |
| Units             | identity conversions within a dimension only; never across dimensions    |
| Dates             | month names and ISO normalise; all-numeric `03/04/2021` stays literal    |
| Rounding          | a claim may round a value half-up to its own precision, never add digits |
| Calculations      | only when stated: each operand must match, and the arithmetic is redone  |
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_MONTHS = {
    name: i
    for i, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

#: Bare `m` and `b` are deliberately absent: `5 m` is five metres far more often than five
#: million, and an equivalence that is usually wrong has no place in a check this strict.
_SCALE = {
    "k": 3,
    "thousand": 3,
    "mn": 6,
    "million": 6,
    "bn": 9,
    "billion": 9,
    "trillion": 12,
}

#: (dimension, factor to the dimension's base unit). Base units: m, g, s, l, byte.
_UNITS = {
    "mm": ("length", Decimal("0.001")),
    "cm": ("length", Decimal("0.01")),
    "m": ("length", Decimal("1")),
    "km": ("length", Decimal("1000")),
    "mg": ("mass", Decimal("0.001")),
    "g": ("mass", Decimal("1")),
    "kg": ("mass", Decimal("1000")),
    "t": ("mass", Decimal("1000000")),
    "ms": ("time", Decimal("0.001")),
    "s": ("time", Decimal("1")),
    "sec": ("time", Decimal("1")),
    "min": ("time", Decimal("60")),
    "h": ("time", Decimal("3600")),
    "hr": ("time", Decimal("3600")),
    "second": ("time", Decimal("1")),
    "seconds": ("time", Decimal("1")),
    "secs": ("time", Decimal("1")),
    "minute": ("time", Decimal("60")),
    "minutes": ("time", Decimal("60")),
    "mins": ("time", Decimal("60")),
    "hour": ("time", Decimal("3600")),
    "hours": ("time", Decimal("3600")),
    "hrs": ("time", Decimal("3600")),
    "day": ("time", Decimal("86400")),
    "days": ("time", Decimal("86400")),
    "metre": ("length", Decimal("1")),
    "metres": ("length", Decimal("1")),
    "meter": ("length", Decimal("1")),
    "meters": ("length", Decimal("1")),
    "kilometres": ("length", Decimal("1000")),
    "kilometers": ("length", Decimal("1000")),
    "gram": ("mass", Decimal("1")),
    "grams": ("mass", Decimal("1")),
    "kilograms": ("mass", Decimal("1000")),
    "litre": ("volume", Decimal("1")),
    "litres": ("volume", Decimal("1")),
    "liter": ("volume", Decimal("1")),
    "liters": ("volume", Decimal("1")),
    "ml": ("volume", Decimal("0.001")),
    "l": ("volume", Decimal("1")),
    "kb": ("data", Decimal("1000")),
    "mb": ("data", Decimal("1000000")),
    "gb": ("data", Decimal("1000000000")),
    "°c": ("celsius", Decimal("1")),
    "°f": ("fahrenheit", Decimal("1")),
    "usd": ("usd", Decimal("1")),
    "$": ("usd", Decimal("1")),
    "eur": ("eur", Decimal("1")),
    "€": ("eur", Decimal("1")),
    "gbp": ("gbp", Decimal("1")),
    "£": ("gbp", Decimal("1")),
}
_UNIT_RE = "|".join(
    re.escape(u)
    for u in sorted((u for u in _UNITS if u not in {"$", "€", "£"}), key=len, reverse=True)
)


@dataclass(frozen=True)
class Quantity:
    """One value as stated: its exact decimal, its kind, and the precision it was given at.

    `kind` is `number`, `percent`, `date`, or `unit:<dimension>`. `exponent` is the place of
    the last significant digit (12.4 → -1, 12 → 0, 1,200 → 2) — rounding is judged against
    it. `literal` holds a date's normalised text, or a four-digit number's own digits when
    it may also be a year.
    """

    value: Decimal | None
    kind: str
    exponent: int = 0
    literal: str = ""


_NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?: \d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC_DATE = re.compile(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b")
_DMY = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_RE})\.?,?\s+(\d{{4}})\b", re.IGNORECASE)
_MDY = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.IGNORECASE)
_MY = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{4}})\b", re.IGNORECASE)
_VALUE = re.compile(
    rf"(?P<cur>[$€£])?\s?(?P<num>{_NUMBER})"
    rf"(?:\s?(?P<pct>%|percent\b|per cent\b))?"
    rf"(?:\s?(?P<scale>thousand|million|billion|trillion|mn|bn|k)\b)?"
    rf"(?:\s?(?P<unit>{_UNIT_RE})\b)?",
    re.IGNORECASE,
)


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", "").replace(" ", ""))


def _exponent(text: str) -> int:
    """The place of the last significant digit. Trailing zeros of an integer are not
    significant — `2,300,000` states no more than `2.3 million` does."""
    digits = text.replace(",", "").replace(" ", "")
    if "." in digits:
        return -len(digits.split(".", 1)[1])
    return len(digits) - len(digits.rstrip("0")) if digits.strip("0") else 0


def extract(text: str) -> list[Quantity]:
    """Every quantity stated in `text`, dates first so their digits are not reread."""
    found: list[Quantity] = []
    spans: list[tuple[int, int]] = []

    def taken(start: int, end: int) -> bool:
        return any(s < end and start < e for s, e in spans)

    for m in _NUMERIC_DATE.finditer(text):
        spans.append(m.span())
        found.append(Quantity(None, "date", literal=m.group(0)))
    for m in _ISO_DATE.finditer(text):
        if taken(*m.span()):
            continue
        spans.append(m.span())
        found.append(Quantity(None, "date", literal=f"{m.group(1)}-{m.group(2)}-{m.group(3)}"))
    for regex, order in ((_DMY, "dmy"), (_MDY, "mdy")):
        for m in regex.finditer(text):
            if taken(*m.span()):
                continue
            spans.append(m.span())
            if order == "dmy":
                day, month, year = m.group(1), m.group(2), m.group(3)
            else:
                month, day, year = m.group(1), m.group(2), m.group(3)
            iso = f"{int(year):04d}-{_MONTHS[month.lower().rstrip('.')]:02d}-{int(day):02d}"
            found.append(Quantity(None, "date", literal=iso))
    for m in _MY.finditer(text):
        if taken(*m.span()):
            continue
        spans.append(m.span())
        iso = f"{int(m.group(2)):04d}-{_MONTHS[m.group(1).lower().rstrip('.')]:02d}"
        found.append(Quantity(None, "date", literal=iso))

    for m in _VALUE.finditer(text):
        if taken(*m.span("num")):
            continue
        num = m.group("num")
        try:
            value = _decimal(num)
        except InvalidOperation:  # pragma: no cover — the regex admits only digits
            continue
        exponent = _exponent(num)
        scale = (m.group("scale") or "").lower()
        if scale:
            power = _SCALE[scale]
            value = value.scaleb(power)
            exponent += power
        if m.group("pct"):
            found.append(Quantity(value, "percent", exponent))
            continue
        unit = (m.group("unit") or "").lower() or (m.group("cur") or "")
        if unit:
            dimension, factor = _UNITS[unit]
            # Precision moves with the unit: 5 km is stated to the kilometre, i.e. to the
            # thousand metres, so the converted value keeps that coarseness.
            found.append(
                Quantity(value * factor, f"unit:{dimension}", exponent + factor.adjusted())
            )
            continue
        # A bare four-digit integer in year range may be a year as well as a number: it
        # keeps its value (so `2021` equals `2,021`) and carries itself as a literal, so a
        # claim stating just the year is backed by a full date in that year.
        maybe_year = num if num.isdigit() and len(num) == 4 and 1500 <= int(num) <= 2199 else ""
        found.append(Quantity(value, "number", exponent, literal=maybe_year))
    return found


def _rounds_to(claim: Quantity, snippet: Quantity) -> bool:
    """Whether the claim's value is the snippet's, rounded half-up to the claim's precision."""
    if claim.value is None or snippet.value is None:
        return False
    if claim.exponent < snippet.exponent:
        return False  # the claim is more precise than its evidence: a digit was invented
    quantum = Decimal(1).scaleb(claim.exponent)
    try:
        rounded = snippet.value.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        rounded = (snippet.value / quantum).to_integral_value(ROUND_HALF_UP) * quantum
    return rounded == claim.value


def matches(claim: Quantity, snippet: Quantity) -> bool:
    """Whether one snippet quantity backs one claim quantity, under the rules above."""
    if claim.kind == "date" or snippet.kind == "date":
        if claim.kind == "date" and snippet.kind == "date":
            return claim.literal == snippet.literal or (
                # "March 2021" (YYYY-MM) is backed by any date in that month.
                len(claim.literal) == 7 and snippet.literal.startswith(claim.literal + "-")
            )
        if claim.kind == "number" and claim.literal and snippet.kind == "date":
            return snippet.literal.startswith(claim.literal + "-")
        return False
    if claim.kind != snippet.kind:
        return False
    return _rounds_to(claim, snippet)


def unsupported(claim_text: str, snippets: str) -> list[str]:
    """The quantities `claim_text` states that no quantity in `snippets` backs.

    Empty means every stated quantity is present. A claim with no quantities is never
    rejected here — whether its words are supported is the model verdict's question.
    """
    available = extract(snippets)
    missing: list[str] = []
    for quantity in extract(claim_text):
        if not any(matches(quantity, s) for s in available):
            missing.append(quantity.literal or str(quantity.value))
    return missing


_OPS = {
    "add": lambda a, b: a + b,
    "subtract": lambda a, b: a - b,
    "multiply": lambda a, b: a * b,
    "divide": lambda a, b: a / b if b else None,
    "percent_change": lambda a, b: (b - a) / a * 100 if a else None,
}


def calculation_holds(op: str, operands: list[str], result: str, snippets: str) -> bool:
    """A stated calculation: each operand is in the snippets and the arithmetic is right.

    `operands` and `result` are the values as the claim states them. The result is
    recomputed here, to the result's own precision, rather than taken from the model.
    """
    func = _OPS.get(op)
    if func is None or len(operands) != 2:
        return False
    parsed = [extract(o) for o in operands]
    outcome = extract(result)
    if any(len(p) != 1 for p in parsed) or len(outcome) != 1:
        return False
    a, b = parsed[0][0], parsed[1][0]
    if unsupported(operands[0], snippets) or unsupported(operands[1], snippets):
        return False
    if a.value is None or b.value is None or outcome[0].value is None:
        return False
    computed = func(a.value, b.value)
    if computed is None:
        return False
    return _rounds_to(outcome[0], Quantity(computed, outcome[0].kind, -28))
