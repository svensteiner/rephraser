from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .models import TransformResult


def _write_text_atomic(path: Path, content: str) -> None:
    """Write a complete UTF-8 file and atomically replace an existing target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def export_result(
    result: TransformResult,
    output: Path,
    audit_path: Path | None = None,
    diff_path: Path | None = None,
) -> tuple[Path, Path, Path]:
    if output.suffix.lower() not in {".txt", ".md"}:
        raise ValueError("Output must use .txt or .md")
    _write_text_atomic(output, result.rewritten_text)
    audit = audit_path or output.with_suffix(output.suffix + ".audit.json")
    diff = diff_path or output.with_suffix(output.suffix + ".diff.txt")
    _write_text_atomic(
        audit,
        json.dumps(result.audit.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
    )
    _write_text_atomic(diff, "\n".join(result.audit.diff.sentence_diff) + "\n")
    return output, audit, diff
