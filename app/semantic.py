from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from .inspection import split_sentences
from .models import SemanticConstraints
from .protection import normalize_protected_terms

URL = r"https?://[^\s<>\])}\"”’»]+"
NUMBER = r"(?<![\w\d])(?:(?:EUR|USD|CHF|€)\s*)?[-+]?(?:\d{1,3}(?:[. ,]\d{3})+|\d+)(?:[,.]\d+)?\s*(?:(?:Mio\.|Mrd\.)\s*)?(?:%|EUR|USD|CHF|€|BTC|ETH|USDT)?(?![\w\d])"
MONTHS = r"Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember|January|February|March|April|May|June|July|August|September|October|November|December"
DATE = rf"\b(?:\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}|(?:den\s+)?\d{{1,2}}\.?(?:\s+)(?:{MONTHS})\s+\d{{4}}|(?:{MONTHS})\s+\d{{1,2}},?\s+\d{{4}})\b"
QUOTE = r"(?:\"[^\"\n]+\"|„[^“\n]+“|“[^”\n]+”|»[^«\n]+«|«[^»\n]+»|‘[^’\n]+’)"

NAME = re.compile(
    r"(?<![#@])\b[A-ZÄÖÜ][\wÄÖÜäöüß-]+(?:[ \t]+[A-ZÄÖÜ][\wÄÖÜäöüß-]+){1,3}\b"
)
ACRONYM = re.compile(r"(?<![#@\w])\b[A-ZÄÖÜ]{2,8}\b")
NON_NAME_STARTERS = {
    "am", "an", "auf", "aus", "bei", "das", "dem", "den", "der", "des", "die", "ein", "eine",
    "für", "im", "in", "mit", "ohne", "seit", "über", "um", "vom", "von", "vor", "wir", "zum", "zur",
    "a", "an", "at", "could", "dear", "for", "from", "hello", "hi", "in", "on", "please", "regarding",
    "daher", "derzeit", "weil", "thank", "that", "the", "these", "this", "those", "to", "we",
    "with", "without", "would", "you", "because", "currently",
}


# The validators deliberately use only narrow, explicit relation extractors.
# They are not a general-purpose NLP layer: an unclear relation is left for
# human review rather than guessed.  This keeps the protection useful for the
# most dangerous simple role swap (payer <-> recipient) without treating
# ordinary prose as a legal obligation.
_ENTITY_WORD = r"(?!(?:EUR|USD|CHF|GBP|Q[1-4])\b)[A-ZÄÖÜ][\wÄÖÜäöüß&.'’\-]*"
_ENTITY = rf"{_ENTITY_WORD}(?:[ \t]+{_ENTITY_WORD}){{0,3}}"
_RECIPIENT_END = r"(?=\s*(?:[,;:.!?)]|$|(?:EUR|USD|CHF|GBP)\b|[€$£]|\d))"
_MONEY_NUMBER = r"(?:\d{1,3}(?:[. ,]\d{3})+|\d+)(?:[,.]\d+)?"
_CURRENCY = r"(?:EUR|USD|CHF|GBP|€|\$|£)"
_MONEY_SCALE = (
    r"(?:thousand|million(?:s)?|billion(?:s)?|trillion(?:s)?|"
    r"tausend|mio\.?|millionen?|mrd\.?|milliarden?|bn|mn|tn|k|m)"
)

_PAYMENT_OBLIGATION_PATTERNS = (
    re.compile(
        rf"\b(?P<payer>{_ENTITY})\s+"
        rf"(?i:must|shall|will|is\s+(?:required|obliged|obligated)\s+to)\s+"
        rf"(?i:pay|remit|transfer)\s+(?:(?i:to)\s+)?(?P<payee>{_ENTITY}){_RECIPIENT_END}"
    ),
    re.compile(
        rf"\b(?P<payer>{_ENTITY})\s+"
        rf"(?i:must|shall|will|is\s+(?:required|obliged|obligated)\s+to)\s+"
        rf"(?i:pay|remit|transfer)\s+{_CURRENCY}\s*{_MONEY_NUMBER}(?:\s*{_MONEY_SCALE})?\s+"
        rf"(?i:to)\s+(?P<payee>{_ENTITY}){_RECIPIENT_END}"
    ),
    re.compile(
        rf"\b(?P<payer>{_ENTITY})\s+"
        rf"(?i:muss|müssen|soll|sollen|ist\s+verpflichtet,?|hat)\s+"
        rf"(?:(?i:an)\s+)?(?P<payee>{_ENTITY})\s+(?:(?i:zu)\s+)?(?i:zahlen|überweisen)"
    ),
)

_REPORTING_PERIOD_PATTERNS = (
    re.compile(r"\bQ([1-4])\b", re.I),
    re.compile(r"\b([1-4])\.\s*Quartal\b", re.I),
    re.compile(r"\b(first|second|third|fourth)\s+quarter\b", re.I),
)
_ORDINAL_QUARTERS = {"first": "Q1", "second": "Q2", "third": "Q3", "fourth": "Q4"}
_MONETARY_AMOUNT_PATTERNS = (
    re.compile(
        rf"(?P<currency>{_CURRENCY})\s*(?P<amount>{_MONEY_NUMBER})\s*(?P<scale>{_MONEY_SCALE})(?![\w])",
        re.I,
    ),
    re.compile(
        rf"(?P<amount>{_MONEY_NUMBER})\s*(?P<scale>{_MONEY_SCALE})\s*(?P<currency>{_CURRENCY})(?![\w])",
        re.I,
    ),
)
_TABLE_SEPARATOR = re.compile(r":?-{3,}:?")


@dataclass(frozen=True)
class PaymentObligation:
    """A narrowly recognised payer-to-recipient obligation."""

    payer: str
    payee: str


@dataclass(frozen=True)
class MonetaryAmount:
    """A currency amount whose written magnitude is explicit."""

    currency: str
    amount: str
    scale: str


@dataclass(frozen=True)
class NumericTableLayout:
    """Normalized numeric cells and their visible Markdown-table context."""

    headers: tuple[str, ...]
    cells: tuple[tuple[str, str, tuple[str, ...]], ...]


def _unique(matches: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in matches if item.strip()))


def _normalise_semantic_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value).strip()).casefold()


def _normalise_currency(value: str) -> str:
    return {"€": "eur", "$": "usd", "£": "gbp"}.get(value, value.casefold())


def _normalise_scale(value: str) -> str:
    compact = value.casefold().replace(".", "")
    if compact in {"k", "thousand", "tausend"}:
        return "thousand"
    if compact in {"m", "mn", "mio", "million", "millions", "millionen"}:
        return "million"
    if compact in {"bn", "mrd", "billion", "billions", "milliarde", "milliarden"}:
        return "billion"
    if compact in {"tn", "trillion", "trillions"}:
        return "trillion"
    return compact


def extract_payment_obligations(text: str) -> list[PaymentObligation]:
    """Return only clear payer-to-recipient relations in simple payment claims.

    The patterns intentionally require both a capitalized payer and recipient,
    an explicit payment verb, and an obligation or future-payment formulation.
    Ambiguous passive wording and generic actions are not inferred.
    """
    relations: list[PaymentObligation] = []
    for pattern in _PAYMENT_OBLIGATION_PATTERNS:
        for match in pattern.finditer(text):
            payer = _normalise_semantic_text(match.group("payer").strip(".,;:"))
            payee = _normalise_semantic_text(match.group("payee").strip(".,;:"))
            if not payer or not payee or payer == payee:
                continue
            relation = PaymentObligation(payer=payer, payee=payee)
            if relation not in relations:
                relations.append(relation)
    return relations


def extract_reporting_periods(text: str) -> tuple[str, ...]:
    """Normalize explicit quarter references without guessing a reporting period."""
    periods: list[str] = []
    for pattern in _REPORTING_PERIOD_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(1).casefold()
            period = _ORDINAL_QUARTERS.get(value, f"Q{value}")
            if period not in periods:
                periods.append(period)
    return tuple(periods)


def extract_monetary_amounts(text: str) -> list[MonetaryAmount]:
    """Return currency amounts that explicitly state a magnitude scale.

    A bare number is deliberately excluded: this guard is for a change such as
    ``EUR 10 million`` to ``EUR 10 billion`` that ordinary exact-number checks
    cannot see.
    """
    amounts: list[MonetaryAmount] = []
    for pattern in _MONETARY_AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            amount = MonetaryAmount(
                currency=_normalise_currency(match.group("currency")),
                amount=_normalise_semantic_text(match.group("amount")),
                scale=_normalise_scale(match.group("scale")),
            )
            if amount not in amounts:
                amounts.append(amount)
    return amounts


def _pipe_cells(line: str) -> tuple[str, ...]:
    stripped = line.strip()
    cells = stripped.split("|")
    if stripped.startswith("|"):
        cells = cells[1:]
    if stripped.endswith("|"):
        cells = cells[:-1]
    return tuple(cell.strip() for cell in cells)


def _is_table_separator(cells: tuple[str, ...]) -> bool:
    return bool(cells) and all(_TABLE_SEPARATOR.fullmatch(cell.replace(" ", "")) for cell in cells)


def _numeric_cell_values(cell: str) -> tuple[str, ...]:
    return tuple(
        _normalise_semantic_text(match.group(0)).replace("\u00a0", " ").replace("\u202f", " ")
        for match in re.finditer(NUMBER, cell, re.I)
    )


def extract_numeric_table_layouts(text: str) -> tuple[NumericTableLayout, ...]:
    """Describe numeric Markdown/pipe-table cells with row and column context.

    Cosmetic cell spacing and alignment separator changes are ignored.  Header,
    row, column, and numeric-cell order remain visible, because moving a number
    between them can materially change a financial statement while retaining
    every original numeric token.
    """
    blocks: list[list[tuple[str, ...]]] = []
    current: list[tuple[str, ...]] = []
    for line in text.splitlines():
        cells = _pipe_cells(line) if line.count("|") >= 2 else ()
        if len(cells) >= 2:
            current.append(cells)
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    layouts: list[NumericTableLayout] = []
    for block in blocks:
        data_rows = [cells for cells in block if not _is_table_separator(cells)]
        if len(data_rows) < 2:
            continue
        headers = tuple(_normalise_semantic_text(cell) for cell in data_rows[0])
        cells_with_context: list[tuple[str, str, tuple[str, ...]]] = []
        for row_index, row in enumerate(data_rows[1:], start=1):
            row_label = _normalise_semantic_text(row[0]) if row and row[0] else f"row {row_index}"
            for column_index, cell in enumerate(row):
                values = _numeric_cell_values(cell)
                if not values:
                    continue
                column_label = (
                    headers[column_index]
                    if column_index < len(headers) and headers[column_index]
                    else f"column {column_index + 1}"
                )
                cells_with_context.append((row_label, column_label, values))
        if cells_with_context:
            layouts.append(NumericTableLayout(headers=headers, cells=tuple(cells_with_context)))
    return tuple(layouts)


def _mask_matches(text: str, pattern: str, flags: int = 0) -> str:
    """Replace matched characters with spaces while preserving line topology."""
    characters = list(text)
    for match in re.finditer(pattern, text, flags):
        for position in range(match.start(), match.end()):
            if characters[position] not in "\r\n":
                characters[position] = " "
    return "".join(characters)


def _extract_names(text: str) -> list[str]:
    candidates = []
    for match in NAME.finditer(text):
        candidate = match.group(0)
        if candidate.split()[0].casefold() not in NON_NAME_STARTERS:
            candidates.append(candidate)
    candidates.extend(match.group(0) for match in ACRONYM.finditer(text))
    return _unique(candidates)


def extract_semantics(text: str, protected_terms: list[str] | tuple[str, ...] = ()) -> SemanticConstraints:
    sentences = split_sentences(text)
    citations = _unique([item.rstrip(".,;:") for item in re.findall(URL, text)])
    quotes = _unique(re.findall(QUOTE, text))
    dates = _unique(re.findall(DATE, text, re.I))
    numbers = _unique(re.findall(NUMBER, _mask_matches(text, DATE, re.I)))
    names = _extract_names(text)
    uncertain = [s for s in sentences if re.search(
        r"\b(?:may|might|could|possibly|probably|perhaps|likely|appears?|suggests?|"
        r"könnte|möglicherweise|vermutlich|wohl|dürfte|eventuell|unter Umständen)\b",
        s,
        re.I,
    )]
    facts = [s for s in sentences if re.search(NUMBER + "|" + DATE + "|" + URL, s, re.I)]
    claims = [s for s in sentences if s not in uncertain]
    structure = [re.sub(r"^#{1,6}\s*", "", line).strip() for line in text.splitlines()
                 if re.match(r"^#{1,6}\s+", line)] or [f"Paragraph {i + 1}" for i, p in enumerate(re.split(r"\n\s*\n", text)) if p.strip()]
    explicit_terms = [term for term in normalize_protected_terms(protected_terms) if term in text]
    must = _unique(numbers + dates + quotes + citations + names + explicit_terms)
    return SemanticConstraints(core_claims=claims, facts=facts, numbers=numbers, names=names,
        dates=dates, quotations=quotes, citations=citations, argument_structure=structure,
        uncertainties=uncertain, protected_terms=explicit_terms, must_preserve=must)
