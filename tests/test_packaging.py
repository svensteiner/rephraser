from pathlib import Path
import re

from app import __version__


ROOT = Path(__file__).parents[1]


def test_windows_bundle_is_onedir_with_matching_version_metadata() -> None:
    spec = (ROOT / "packaging" / "TextVerbessern.spec").read_text(encoding="utf-8")
    version_info = (ROOT / "packaging" / "windows_version_info.txt").read_text(encoding="utf-8")
    assert "exclude_binaries=True" in spec
    assert "COLLECT(" in spec
    assert 'name="TextVerbessern"' in spec
    assert f"StringStruct('ProductVersion', '{__version__}')" in version_info
    assert f"StringStruct('FileVersion', '{__version__}')" in version_info
    numeric_version = ", ".join((*__version__.split("."), "0"))
    assert f"filevers=({numeric_version})" in version_info
    assert f"prodvers=({numeric_version})" in version_info


def test_all_public_version_fields_match() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pipeline = (ROOT / "app" / "pipeline.py").read_text(encoding="utf-8")
    api = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert re.search(rf'^version = "{re.escape(__version__)}"$', pyproject, re.MULTILINE)
    assert f'PIPELINE_VERSION = "{__version__}"' in pipeline
    assert f'version="{__version__}"' in api


def test_release_workflow_packages_entire_folder_and_manifest() -> None:
    workflow = (ROOT / ".github" / "workflows" / "windows-portable.yml").read_text(encoding="utf-8")
    assert "dist\\TextVerbessern\\TextVerbessern.exe" in workflow
    assert "Copy-Item dist\\TextVerbessern\\* portable -Recurse -Force" in workflow
    assert "release-manifest.json" in workflow
    assert "Get-FileHash -Algorithm SHA256" in workflow
    assert "Verify exact downloadable archive" in workflow
    assert "[IO.Path]::IsPathRooted" in workflow
    assert "'..' -in $components" in workflow
    assert "Archive hash mismatch" in workflow
    assert "Extracted application self-test" in workflow
    assert "Verify published stable download" in workflow
    assert "Published download hash mismatch" in workflow
    assert "timeout-minutes: 20" in workflow


def test_ci_runs_quality_gate_for_every_supported_python_version() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'python-version: ["3.12", "3.13"]' in workflow
    assert "fail-fast: false" in workflow
    assert "timeout-minutes: 15" in workflow
    assert "python -m app.evaluation" in workflow
    assert 'app = ["evaluation_cases.json"]' in pyproject
