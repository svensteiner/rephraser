from app.semantic import (
    extract_monetary_amounts,
    extract_numeric_table_layouts,
    extract_payment_obligations,
    extract_quantified_values,
    extract_reporting_periods,
    extract_semantics,
)


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


def test_explicit_protected_terms_are_added_only_when_present_exactly() -> None:
    result = extract_semantics(
        "Project Aurora nutzt die Kontenabstimmung.",
        ["Project Aurora", "project aurora", "Kontenabstimmung"],
    )
    assert result.protected_terms == ["Project Aurora", "Kontenabstimmung"]
    assert all(term in result.must_preserve for term in result.protected_terms)


def test_extracts_only_explicit_payment_period_scale_and_table_markers() -> None:
    relation = extract_payment_obligations("Acme muss Beta zahlen.")
    amounts = extract_monetary_amounts("Revenue for Q1 was EUR 10 million.")
    table = extract_numeric_table_layouts(
        "| Entity | Q1 | Q2 |\n| --- | ---: | ---: |\n| Acme | 10 | 20 |"
    )

    assert [(item.payer, item.payee) for item in relation] == [("acme", "beta")]
    assert extract_reporting_periods("Revenue for first quarter was EUR 10m.") == ("Q1",)
    assert [(item.currency, item.amount, item.scale) for item in amounts] == [("eur", "10", "million")]
    assert table[0].headers == ("entity", "q1", "q2")
    assert table[0].cells == (("acme", "q1", ("10",)), ("acme", "q2", ("20",)))


def test_extracts_written_money_and_narrow_business_quantity_units() -> None:
    written_money = extract_monetary_amounts("Revenue was 10 million euros in Q1.")
    quantities = extract_quantified_values(
        "The rate rose by 10 basis points; payment is due within 30 days; "
        "the company issued 10 million shares."
    )

    assert [(item.currency, item.amount, item.scale) for item in written_money] == [
        ("eur", "10", "million")
    ]
    assert [(item.amount, item.scale, item.unit) for item in quantities] == [
        ("10", "", "basis_points"),
        ("30", "", "days"),
        ("10", "million", "shares"),
    ]
