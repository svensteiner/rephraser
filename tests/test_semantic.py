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
