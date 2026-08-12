from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from .exporters import export_result
from .models import TransformRequest, TransformResult
from .pipeline import run_pipeline
from .providers.base import ProviderError

app = FastAPI(title="Editorial Transformer", version="1.8.2",
    description="Local-first editorial rewriting and semantic-preservation auditing. No AI detector score.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "default_provider": "fast-editor"}


@app.post("/transform", response_model=TransformResult)
def transform(request: TransformRequest) -> TransformResult:
    try:
        return run_pipeline(request.text, request.options)
    except ProviderError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/transform/text", response_class=PlainTextResponse)
def transform_text(request: TransformRequest) -> str:
    return transform(request).rewritten_text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local-first editorial transformer")
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--provider", choices=["fast-editor", "rules", "mistral-local"], default="fast-editor")
    parser.add_argument("--tone", default="professional")
    parser.add_argument("--strength", choices=["light", "medium", "substantial"], default="medium")
    parser.add_argument("--language", choices=["German", "English", "auto-detect"], default="auto-detect")
    parser.add_argument("--author-style", default="")
    return parser


def cli(argv: list[str] | None = None) -> int:
    from .models import TransformOptions
    parser = _parser()
    args = parser.parse_args(argv)
    if bool(args.input) == bool(args.stdin):
        parser.error("provide exactly one input file or --stdin")
    if args.input and args.input.suffix.lower() not in {".txt", ".md"}:
        parser.error("input must be .txt or .md")
    try:
        text = sys.stdin.read() if args.stdin else args.input.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        print(f"error: cannot read input: {error}", file=sys.stderr)
        return 2
    if len(text) > 2_000_000:
        print("error: input exceeds 2,000,000 characters", file=sys.stderr)
        return 2
    options = TransformOptions(provider=args.provider, tone=args.tone, rewrite_strength=args.strength,
        language=args.language, custom_author_style=args.author_style)
    try:
        result = run_pipeline(text, options)
    except ProviderError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.output:
        try:
            if args.input and args.input.resolve() == args.output.resolve():
                raise ValueError("input and output paths must differ")
            export_result(result, args.output)
        except (OSError, ValueError) as error:
            print(f"error: cannot export result: {error}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(result.rewritten_text)
        print("\n--- audit ---", file=sys.stderr)
        print(json.dumps(result.audit.model_dump(mode="json"), ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
