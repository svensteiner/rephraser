from app.semantic import extract_semantics


def test_extracts_german_financial_crypto_constraints() -> None:
    text = ('Anna Müller schrieb: „Bitcoin bleibt volatil.“ Am 12.03.2026 lag BTC bei '
            '63.500 EUR; die Rendite betrug 4,25 %. Quelle: https://example.org/a')
    result = extract_semantics(text)
    assert "12.03.2026" in result.dates
    assert "https://example.org/a" in result.citations
    assert "„Bitcoin bleibt volatil.“" in result.quotations
    assert any("63.500 EUR" in n for n in result.numbers)
    assert any("4,25 %" in n for n in result.numbers)
    assert any("Anna Müller" in n for n in result.names)


def test_german_dates_currency_crypto_curly_quotes_and_url_punctuation() -> None:
    text = 'Am 3. März 2026 waren es EUR 1.234,56 und 0,005 BTC. “Quote.” https://example.org/a.'
    result = extract_semantics(text)
    assert "3. März 2026" in result.dates
    assert "EUR 1.234,56" in result.numbers
    assert "0,005 BTC" in result.numbers
    assert "“Quote.”" in result.quotations
    assert result.citations == ["https://example.org/a"]


def test_date_components_are_not_duplicated_as_numbers() -> None:
    result = extract_semantics("Die Marge betrug am 3. März 2026 exakt 12,5 %.")
    assert result.dates == ["3. März 2026"]
    assert result.numbers == ["12,5 %"]


def test_names_are_conservative_and_do_not_cross_lines() -> None:
    text = (
        "# Quartalsanalyse\n\nDie Marge blieb stabil. Der Ausblick ist vorsichtig. "
        "Jörg Müller kontaktierte DAI Global Belgium und UniCredit BulBank."
    )
    result = extract_semantics(text)
    assert "Jörg Müller" in result.names
    assert "DAI Global Belgium" in result.names
    assert "UniCredit BulBank" in result.names
    assert "Die Marge" not in result.names
    assert "Der Ausblick" not in result.names
    assert all("\n" not in name for name in result.names)


def test_editorial_sentence_starters_are_not_misclassified_as_names() -> None:
    result = extract_semantics(
        "Weil Beleg 17 fehlt, bleibt die Prüfung offen. Because Evidence 4 is missing, review continues."
    )
    assert "Weil Beleg" not in result.names
    assert "Because Evidence" not in result.names


def test_all_non_uncertain_claims_are_retained() -> None:
    text = " ".join(f"Claim {index} is confirmed." for index in range(1, 13))
    result = extract_semantics(text)
    assert len(result.core_claims) == 12


def test_expanded_uncertainty_language_is_not_treated_as_certain_claim() -> None:
    text = "Die Marge dürfte steigen. The result likely improves. Der Umsatz ist bestätigt."
    result = extract_semantics(text)
    assert len(result.uncertainties) == 2
    assert result.core_claims == ["Der Umsatz ist bestätigt."]
