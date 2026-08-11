from __future__ import annotations

import json
from pathlib import Path

from .models import TransformResult


def export_result(result: TransformResult, output: Path, audit_path: Path | None = None) -> tuple[Path, Path]:
    if output.suffix.lower() not in {".txt", ".md"}:
        raise ValueError("Output must use .txt or .md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.rewritten_text, encoding="utf-8", newline="\n")
    audit = audit_path or output.with_suffix(output.suffix + ".audit.json")
    audit.write_text(json.dumps(result.audit.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diff_path = output.with_suffix(output.suffix + ".diff.txt")
    diff_path.write_text("\n".join(result.audit.diff.sentence_diff) + "\n", encoding="utf-8")
    return output, audit
