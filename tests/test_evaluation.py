from app.evaluation import EvaluationCase, evaluate_case, load_corpus, run_evaluation


def test_curated_quality_corpus_is_complete_and_green() -> None:
    schema_version, cases = load_corpus()
    report = run_evaluation(cases)

    assert schema_version == 1
    assert report.ok, {
        result.id: result.failures for result in report.results if not result.passed
    }
    assert report.total >= 14
    assert report.language_counts["de"] >= 8
    assert report.language_counts["en"] >= 5
    assert report.category_counts["business-email"] >= 1
    assert report.category_counts["negative-control"] >= 1
    assert report.category_counts["unicode"] >= 2


def test_evaluator_reports_output_preservation_warning_and_provider_failures(monkeypatch) -> None:
    from app.models import ValidationWarning

    case = EvaluationCase(
        id="deliberate-failure",
        language="de",
        category="test",
        provider="fast-editor",
        input="Wert 12,5 %.",
        expected_output="Wert 12,5 %.",
        must_preserve=("12,5 %",),
        expected_warning_kinds=(),
    )

    class Audit:
        fact_preservation_warnings = [
            ValidationWarning(kind="missing_number", severity="high", value="12,5 %", message="missing")
        ]
        applied_provider = "rules"

    class Result:
        rewritten_text = "Wert entfernt."
        audit = Audit()

    monkeypatch.setattr("app.evaluation.run_pipeline", lambda *args, **kwargs: Result())
    result = evaluate_case(case)

    assert result.passed is False
    assert any("output mismatch" in failure for failure in result.failures)
    assert any("protected value count changed" in failure for failure in result.failures)
    assert any("warning kinds differ" in failure for failure in result.failures)
    assert any("provider fallback" in failure for failure in result.failures)


def test_corpus_ids_are_unique_and_required_values_exist_in_source() -> None:
    _, cases = load_corpus()

    assert len({case.id for case in cases}) == len(cases)
    for case in cases:
        assert case.id
        assert case.input
        assert case.expected_output
        assert all(value in case.input for value in case.must_preserve)
