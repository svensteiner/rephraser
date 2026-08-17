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
# Currency words deliberately stay explicit.  A written currency plus a scale
# (``10 million euros``) is a materially different fact from a bare quantity
# (``10 million shares``), so it gets its own extractor below.
_CURRENCY = (
    r"(?:EUR|USD|CHF|GBP|€|\$|£|euros?|"
    r"U\.?S\.?\s+dollars?|dollars?|Schweizer\s+Franken|francs?|"
    r"british\s+pounds?|pounds?)"
)
_MONEY_SCALE = (
    r"(?:thousand|million(?:s)?|billion(?:s)?|trillion(?:s)?|"
    r"tausend|mio\.?|millionen?|mrd\.?|milliarden?|bn|mn|tn|k|m)"
)
_QUANTITY_UNIT = (
    r"(?:basis\s+points?|bps?|percentage\s+points?|pp|days?|months?|years?|shares?|"
    r"basispunkte?|prozentpunkte?|tage?|monate?|jahre?|aktien)"
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
    # German reporting references are often written out and inflected, for
    # example ``im ersten Quartal`` or ``des vierten Quartals``.  They carry
    # the same business meaning as Q1–Q4, so leaving them unrecognised would
    # let a rewrite exchange one quarter for another without this guard seeing
    # the change.
    re.compile(
        r"\b(erst(?:e|en|em|er|es)|zweit(?:e|en|em|er|es)|"
        r"dritt(?:e|en|em|er|es)|viert(?:e|en|em|er|es))\s+Quartal(?:s)?\b",
        re.I,
    ),
)
_ORDINAL_QUARTERS = {
    "first": "Q1",
    "second": "Q2",
    "third": "Q3",
    "fourth": "Q4",
    **{form: "Q1" for form in ("erste", "ersten", "erstem", "erster", "erstes")},
    **{form: "Q2" for form in ("zweite", "zweiten", "zweitem", "zweiter", "zweites")},
    **{form: "Q3" for form in ("dritte", "dritten", "drittem", "dritter", "drittes")},
    **{form: "Q4" for form in ("vierte", "vierten", "viertem", "vierter", "viertes")},
}
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
_QUANTIFIED_VALUE_PATTERN = re.compile(
    rf"(?<![\w\d])(?P<amount>{_MONEY_NUMBER})"
    rf"(?:\s+(?P<scale>{_MONEY_SCALE}))?\s+(?P<unit>{_QUANTITY_UNIT})(?![\w])",
    re.I,
)
_TABLE_SEPARATOR = re.compile(r":?-{3,}:?")


# These extractors intentionally recognize only direct, explicit assignments
# for business/legal roles that are particularly harmful when exchanged.  They
# do not try to infer roles from general prose.  A few narrow active/passive
# equivalents are included for common account-holder and borrower wording; the
# grammar remains deliberately constrained so a mere name/role co-occurrence
# is never treated as an assignment.
_ROLE_ASSIGNMENT_END = r"(?=\s*(?:[,;:.!?)]|$|\r?\n))"
_MATERIAL_ROLE_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("account_holder", r"account\s+holders?", r"is|remains", r"the|a|an"),
    ("beneficial_owner", r"beneficial\s+owners?", r"is|remains", r"the|a|an"),
    ("legal_owner", r"legal\s+owners?", r"is|remains", r"the|a|an"),
    ("borrower", r"borrowers?", r"is|remains", r"the|a|an"),
    ("lender", r"lenders?", r"is|remains", r"the|a|an"),
    ("guarantor", r"guarantors?", r"is|remains", r"the|a|an"),
    ("account_holder", r"kontoinhaber(?:in)?", r"ist|bleibt", r"der|die|das|ein(?:e|er|em|en|es)?"),
    (
        "beneficial_owner",
        r"wirtschaftlich(?:e|er|en|em)?\s+berechtigt(?:e|er|en|em)?",
        r"ist|bleibt",
        r"der|die|das|ein(?:e|er|em|en|es)?",
    ),
    (
        "legal_owner",
        r"rechtlich(?:e|er|en|em)?\s+eigentümer(?:in)?",
        r"ist|bleibt",
        r"der|die|das|ein(?:e|er|em|en|es)?",
    ),
    ("borrower", r"(?:darlehens|kredit)nehmer(?:in)?", r"ist|bleibt", r"der|die|das|ein(?:e|er|em|en|es)?"),
    ("lender", r"(?:darlehens|kredit)geber(?:in)?", r"ist|bleibt", r"der|die|das|ein(?:e|er|em|en|es)?"),
    ("guarantor", r"(?:bürge|bürgin)", r"ist|bleibt", r"der|die|das|ein(?:e|er|em|en|es)?"),
)


def _material_role_assignment_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Compile narrowly explicit material-role assignment forms once."""
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for canonical_role, role, verbs, articles in _MATERIAL_ROLE_SPECS:
        role_token = rf"(?i:{role})"
        verb_token = rf"(?i:{verbs})"
        article_token = rf"(?i:{articles})"
        optional_article = rf"(?:(?:{article_token})\s+)?"
        patterns.extend(
            (
                (
                    canonical_role,
                    re.compile(
                        rf"\b(?P<entity>{_ENTITY})\s+{verb_token}\s+"
                        rf"{optional_article}{role_token}{_ROLE_ASSIGNMENT_END}"
                    ),
                ),
                (
                    canonical_role,
                    re.compile(
                        rf"\b{optional_article}{role_token}\s+{verb_token}\s+"
                        rf"(?P<entity>{_ENTITY}){_ROLE_ASSIGNMENT_END}"
                    ),
                ),
                (
                    canonical_role,
                    re.compile(
                        rf"\b{role_token}\s*:\s*(?P<entity>{_ENTITY}){_ROLE_ASSIGNMENT_END}"
                    ),
                ),
            )
        )
    # A limited set of ordinary phrasing variants is safe to normalize to an
    # assignment because both the action and the object are explicit.  Do not
    # loosen these to generic ``holds``, ``owns``, or ``took out`` patterns:
    # those verbs alone do not establish the high-impact role reliably.
    patterns.extend(
        (
            (
                "account_holder",
                re.compile(
                    rf"\b(?P<entity>{_ENTITY})\s+(?i:holds?)\s+"
                    rf"(?i:the)\s+(?i:accounts?){_ROLE_ASSIGNMENT_END}"
                ),
            ),
            (
                "account_holder",
                re.compile(
                    rf"\b(?i:the)\s+(?i:accounts?)\s+(?i:is|are)\s+"
                    rf"(?i:held)\s+(?i:by)\s+(?P<entity>{_ENTITY}){_ROLE_ASSIGNMENT_END}"
                ),
            ),
            (
                "borrower",
                re.compile(
                    rf"\b(?P<entity>{_ENTITY})\s+(?i:took|has\s+taken)\s+"
                    rf"(?i:out)\s+(?i:the|a)\s+(?i:loans?|credits?){_ROLE_ASSIGNMENT_END}"
                ),
            ),
            (
                "borrower",
                re.compile(
                    rf"\b(?i:the|a)\s+(?i:loans?|credits?)\s+(?i:was|were)\s+"
                    rf"(?i:taken)\s+(?i:out)\s+(?i:by)\s+(?P<entity>{_ENTITY})"
                    rf"{_ROLE_ASSIGNMENT_END}"
                ),
            ),
        )
    )
    return tuple(patterns)


_MATERIAL_ROLE_ASSIGNMENT_PATTERNS = _material_role_assignment_patterns()


@dataclass(frozen=True)
class PaymentObligation:
    """A narrowly recognised payer-to-recipient obligation."""

    payer: str
    payee: str


@dataclass(frozen=True)
class MaterialRoleAssignment:
    """A directly stated high-impact business or legal role assignment."""

    role: str
    entity: str


@dataclass(frozen=True)
class MonetaryAmount:
    """A currency amount whose written magnitude is explicit."""

    currency: str
    amount: str
    scale: str


@dataclass(frozen=True)
class QuantifiedValue:
    """A narrow, explicit number-plus-unit statement used for safety checks."""

    amount: str
    scale: str
    unit: str


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
    compact = _normalise_semantic_text(value).replace(".", "")
    aliases = {
        "€": "eur",
        "eur": "eur",
        "euro": "eur",
        "euros": "eur",
        "$": "usd",
        "usd": "usd",
        "us dollar": "usd",
        "us dollars": "usd",
        "£": "gbp",
        "gbp": "gbp",
        "pound": "gbp",
        "pounds": "gbp",
        "british pound": "gbp",
        "british pounds": "gbp",
        "chf": "chf",
        "schweizer franken": "chf",
        "franc": "chf",
        "francs": "chf",
    }
    # A bare ``dollar`` is intentionally not assumed to be USD.  It remains a
    # stable generic currency label, which is enough to catch a scale change.
    return aliases.get(compact, compact)


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


def _normalise_quantity_unit(value: str) -> str:
    compact = re.sub(r"\s+", " ", unicodedata.normalize("NFC", value).strip()).casefold()
    aliases = {
        "bp": "basis_points",
        "bps": "basis_points",
        "basis point": "basis_points",
        "basis points": "basis_points",
        "basispunkt": "basis_points",
        "basispunkte": "basis_points",
        "pp": "percentage_points",
        "percentage point": "percentage_points",
        "percentage points": "percentage_points",
        "prozentpunkt": "percentage_points",
        "prozentpunkte": "percentage_points",
        "day": "days",
        "days": "days",
        "tag": "days",
        "tage": "days",
        "month": "months",
        "months": "months",
        "monat": "months",
        "monate": "months",
        "year": "years",
        "years": "years",
        "jahr": "years",
        "jahre": "years",
        "share": "shares",
        "shares": "shares",
        "aktie": "shares",
        "aktien": "shares",
    }
    return aliases.get(compact, compact)


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


def extract_material_role_assignments(text: str) -> list[MaterialRoleAssignment]:
    """Return only direct assignments for a small set of material roles.

    A role is emitted only when the text uses one of three clear forms, such as
    ``Austria is the account holder``, ``The borrower is Acme``, or
    ``Guarantor: Beta``.  It also recognizes a few exact equivalents such as
    ``Austria holds the account`` and ``Acme took out the loan``.  This is
    deliberately not a general entity-role NLP extractor: uncertain wording
    is left for human review rather than guessed.
    """
    matched_assignments: list[tuple[int, int, MaterialRoleAssignment]] = []
    for role, pattern in _MATERIAL_ROLE_ASSIGNMENT_PATTERNS:
        for match in pattern.finditer(text):
            entity = _normalise_semantic_text(match.group("entity").strip(".,;:"))
            if not entity:
                continue
            assignment = MaterialRoleAssignment(role=role, entity=entity)
            matched_assignments.append((match.start(), match.end(), assignment))
    assignments: list[MaterialRoleAssignment] = []
    for _start, _end, assignment in sorted(matched_assignments, key=lambda item: item[:2]):
        if assignment not in assignments:
            assignments.append(assignment)
    return assignments


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


def extract_quantified_values(text: str) -> list[QuantifiedValue]:
    """Return clear units whose change alters a quantity's business meaning.

    This is purposefully narrower than generic unit parsing.  It protects the
    common high-impact units that can change a legal deadline, a rate, or a
    stated magnitude while retaining the same digits.
    """
    values: list[QuantifiedValue] = []
    for match in _QUANTIFIED_VALUE_PATTERN.finditer(text):
        value = QuantifiedValue(
            amount=_normalise_semantic_text(match.group("amount")),
            scale=_normalise_scale(match.group("scale")) if match.group("scale") else "",
            unit=_normalise_quantity_unit(match.group("unit")),
        )
        if value not in values:
            values.append(value)
    return values


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
