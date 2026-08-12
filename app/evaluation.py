"""Deterministic DE/EN quality regression suite for the local editing pipeline."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any

from app.models import TransformOptions
from app.pipeline import run_pipeline


CORPUS_PATH = Path(__file__).with_name("evaluation_cases.json")


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    id: str
    language: str
    category: str
    provider: str
    input: str
    expected_output: str
    must_preserve: tuple[str, ...]
    expected_warning_kinds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CaseResult:
    id: str
    passed: bool
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    schema_version: int
    total: int
    passed: int
    failed: int
    language_counts: dict[str, int]
    category_counts: dict[str, int]
    results: tuple[CaseResult, ...]

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.total > 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.ok
        return payload


def load_corpus(path: Path = CORPUS_PATH) -> tuple[int, tuple[EvaluationCase, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema_version = payload.get("schema_version")
    raw_cases = payload.get("cases")
    if schema_version != 1 or not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("Evaluation corpus must use schema_version 1 and contain cases.")
    cases: list[EvaluationCase] = []
    seen: set[str] = set()
    for raw in raw_cases:
        case = EvaluationCase(
            id=raw["id"],
            language=raw["language"],
            category=raw["category"],
            provider=raw["provider"],
            input=raw["input"],
            expected_output=raw["expected_output"],
            must_preserve=tuple(raw.get("must_preserve", [])),
            expected_warning_kinds=tuple(raw.get("expected_warning_kinds", [])),
        )
        if case.id in seen:
            raise ValueError(f"Duplicate evaluation case id: {case.id}")
        seen.add(case.id)
        cases.append(case)
    return schema_version, tuple(cases)


def evaluate_case(case: EvaluationCase) -> CaseResult:
    language = {"de": "German", "en": "English"}.get(case.language, "auto-detect")
    result = run_pipeline(
        case.input,
        TransformOptions(provider=case.provider, language=language),
    )
    failures: list[str] = []
    if result.rewritten_text != case.expected_output:
        failures.append(
            "output mismatch: "
            f"expected={case.expected_output!r}; actual={result.rewritten_text!r}"
        )
    for value in case.must_preserve:
        if case.input.count(value) != result.rewritten_text.count(value):
            failures.append(
                f"protected value count changed: {value!r} "
                f"({case.input.count(value)} -> {result.rewritten_text.count(value)})"
            )
    actual_warning_kinds = tuple(
        sorted(warning.kind for warning in result.audit.fact_preservation_warnings)
    )
    expected_warning_kinds = tuple(sorted(case.expected_warning_kinds))
    if actual_warning_kinds != expected_warning_kinds:
        failures.append(
            f"warning kinds differ: expected={expected_warning_kinds!r}; actual={actual_warning_kinds!r}"
        )
    if result.audit.applied_provider != case.provider:
        failures.append(
            f"provider fallback: expected={case.provider!r}; actual={result.audit.applied_provider!r}"
        )
    return CaseResult(case.id, not failures, tuple(failures))


def run_evaluation(cases: tuple[EvaluationCase, ...] | None = None) -> EvaluationReport:
    schema_version, loaded = load_corpus()
    selected = loaded if cases is None else cases
    results = tuple(evaluate_case(case) for case in selected)
    languages = Counter(case.language for case in selected)
    categories = Counter(case.category for case in selected)
    passed = sum(result.passed for result in results)
    return EvaluationReport(
        schema_version=schema_version,
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        language_counts=dict(sorted(languages.items())),
        category_counts=dict(sorted(categories.items())),
        results=results,
    )


def main() -> int:
    report = run_evaluation()
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
