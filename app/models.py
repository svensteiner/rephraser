from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.protection import normalize_protected_terms


class Tone(StrEnum):
    PROFESSIONAL = "professional"
    ANALYTICAL = "analytical"
    CONCISE = "concise"
    OPINIONATED = "opinionated"
    ACADEMIC = "academic"
    LINKEDIN_ARTICLE = "LinkedIn/article"


class RewriteStrength(StrEnum):
    LIGHT = "light"
    MEDIUM = "medium"
    SUBSTANTIAL = "substantial"


class Language(StrEnum):
    GERMAN = "German"
    ENGLISH = "English"
    AUTO = "auto-detect"


class TransformOptions(BaseModel):
    tone: Tone = Tone.PROFESSIONAL
    rewrite_strength: RewriteStrength = RewriteStrength.MEDIUM
    language: Language = Language.AUTO
    preserve_citations: bool = True
    preserve_numbers: bool = True
    preserve_quotations: bool = True
    custom_author_style: str = ""
    protected_terms: list[str] = Field(default_factory=list, max_length=50)
    provider: str = "fast-editor"

    @field_validator("protected_terms")
    @classmethod
    def validate_protected_terms(cls, value: list[str]) -> list[str]:
        return normalize_protected_terms(value)


class CharacterFinding(BaseModel):
    position: int
    code_point: str
    name: str
    category: str
    kind: str


class CharacterSummary(BaseModel):
    code_point: str
    name: str
    category: str
    kind: str
    count: int
    positions: list[int]


class InspectionReport(BaseModel):
    characters: list[CharacterFinding] = Field(default_factory=list)
    character_summary: list[CharacterSummary] = Field(default_factory=list)
    paragraphs: int
    sentences: int
    sentence_lengths: list[int]
    repeated_phrases: dict[str, int]
    lexical_repetition: dict[str, int]
    transition_phrases: dict[str, int]
    uniform_sentence_pattern: bool
    headings: list[str]
    list_items: int


class SemanticConstraints(BaseModel):
    core_claims: list[str]
    facts: list[str]
    numbers: list[str]
    names: list[str]
    dates: list[str]
    quotations: list[str]
    citations: list[str]
    argument_structure: list[str]
    uncertainties: list[str]
    protected_terms: list[str] = Field(default_factory=list)
    must_preserve: list[str]


class QualityMetrics(BaseModel):
    sentence_count: int
    sentence_length_min: int
    sentence_length_max: int
    sentence_length_mean: float
    sentence_length_stdev: float
    paragraph_lengths: list[int]
    lexical_diversity: float
    repeated_word_count: int
    filler_phrase_count: int
    passive_voice_indicators: int
    readability: float


class ValidationWarning(BaseModel):
    kind: str
    severity: str
    value: str
    message: str


class DiffReport(BaseModel):
    word_diff: list[str]
    sentence_diff: list[str]
    lexical_similarity: float
    surface_diversity: float
    added_sentences: list[str]
    removed_sentences: list[str]
    substantially_rewritten_sentences: list[dict[str, Any]]
    # A complete SequenceMatcher comparison is deliberately bounded for large
    # or highly repetitive inputs. These fields make that limit visible in the
    # JSON audit instead of presenting an excerpt as a complete diff.
    detail_truncated: bool = False
    comparison_complete: bool = True
    comparison_method: str = "full_sequence"
    truncation_reason: str | None = None
    original_word_count: int = 0
    rewritten_word_count: int = 0
    original_sentence_count: int = 0
    rewritten_sentence_count: int = 0


class Transformation(BaseModel):
    kind: str
    before: str
    after: str
    reason: str
    code_points_before: list[str] = Field(default_factory=list)
    code_points_after: list[str] = Field(default_factory=list)
    original_start: int
    original_end: int
    rewritten_start: int
    rewritten_end: int


class TransformRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    options: TransformOptions = Field(default_factory=TransformOptions)


class AuditReport(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    original_hash: str
    output_hash: str
    timestamp: datetime
    pipeline_version: str
    requested_provider: str
    applied_provider: str
    options: dict[str, Any]
    inspection: InspectionReport
    inspection_after: InspectionReport
    semantic_constraints: SemanticConstraints
    transformations: list[Transformation]
    fact_preservation_warnings: list[ValidationWarning]
    quality_metrics_before: QualityMetrics
    quality_metrics_after: QualityMetrics
    diff: DiffReport
    safeguard: str


class TransformResult(BaseModel):
    rewritten_text: str
    audit: AuditReport
