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
    assert "TextVerbessern-Browser.html" in workflow
    assert "Verify offline browser edition" in workflow
    assert "canonical LF line endings" in workflow
    assert "timeout-minutes: 20" in workflow


def test_release_workflow_publishes_an_immutable_version_before_latest_pointer() -> None:
    workflow = (ROOT / ".github" / "workflows" / "windows-portable.yml").read_text(encoding="utf-8")

    immutable_start = workflow.index("- name: Publish immutable version release")
    immutable_verify = workflow.index("- name: Verify published immutable version release")
    latest_update = workflow.index("- name: Update portable-latest convenience release")
    latest_verify = workflow.index("- name: Verify published portable-latest download")
    immutable_section = workflow[immutable_start:immutable_verify]
    immutable_verify_section = workflow[immutable_verify:latest_update]
    latest_update_section = workflow[latest_update:latest_verify]

    assert immutable_start < immutable_verify < latest_update < latest_verify
    assert "SHA256SUMS.txt" in workflow
    assert "Set-Content SHA256SUMS.txt -Encoding ascii" in workflow
    assert '"v$version"' in immutable_section
    assert "Resolve-TagCommit" in immutable_section
    assert "Refusing to replace an immutable release" in immutable_section
    assert "gh release create $versionTag" in immutable_section
    assert '--target "$env:GITHUB_SHA"' in immutable_section
    assert "--prerelease" not in immutable_section
    assert "standard published immutable version release" in immutable_section
    assert "id: publish_immutable" in immutable_section
    assert '"release_asset_source=$releaseAssetSource"' in immutable_section
    assert "RELEASE_ASSET_SOURCE: ${{ steps.publish_immutable.outputs.release_asset_source }}" in immutable_verify_section
    assert "if ($env:RELEASE_ASSET_SOURCE -eq 'local')" in immutable_verify_section
    assert "elseif ($env:RELEASE_ASSET_SOURCE -ne 'immutable')" in immutable_verify_section
    assert "Copy-Item \"$directory\\TextVerbessern-Windows.zip\"" in immutable_verify_section
    assert "release-assets" in immutable_verify_section
    assert "Verified immutable release asset is missing" in latest_update_section
    assert "gh release upload portable-latest $zip $browser $checksums --clobber" in latest_update_section
    assert "gh release create portable-latest $zip $browser $checksums" in latest_update_section
    assert "Immutable SHA256SUMS does not match the ZIP download." in workflow
    assert "Immutable SHA256SUMS does not match the browser download." in workflow
    assert "portable-latest SHA256SUMS does not match the ZIP download." in workflow
    assert "portable-latest SHA256SUMS does not match the browser download." in workflow
    assert "portable-latest does not target $env:GITHUB_SHA" in workflow
    assert "--prerelease" in workflow[latest_update:latest_verify]


def test_release_workflow_reuses_verified_immutable_assets_on_rerun() -> None:
    workflow = (ROOT / ".github" / "workflows" / "windows-portable.yml").read_text(encoding="utf-8")

    immutable_start = workflow.index("- name: Publish immutable version release")
    immutable_verify = workflow.index("- name: Verify published immutable version release")
    latest_update = workflow.index("- name: Update portable-latest convenience release")
    immutable_section = workflow[immutable_start:immutable_verify]
    immutable_verify_section = workflow[immutable_verify:latest_update]
    latest_update_section = workflow[latest_update:]

    assert '$releaseAssetSource = "local"' in immutable_section
    assert '$releaseAssetSource = "immutable"' in immutable_section
    assert '"release_asset_source=$releaseAssetSource" | Out-File -FilePath $env:GITHUB_OUTPUT' in immutable_section
    assert "RELEASE_ASSET_SOURCE: ${{ steps.publish_immutable.outputs.release_asset_source }}" in immutable_verify_section

    local_hash_branch = immutable_verify_section.index("if ($env:RELEASE_ASSET_SOURCE -eq 'local')")
    unknown_source_branch = immutable_verify_section.index("elseif ($env:RELEASE_ASSET_SOURCE -ne 'immutable')")
    fresh_hash = immutable_verify_section.index(
        "$zipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath TextVerbessern-Windows.zip)"
    )
    copied_assets = immutable_verify_section.index("Copy-Item \"$directory\\TextVerbessern-Windows.zip\"")
    assert local_hash_branch < fresh_hash < unknown_source_branch < copied_assets
    assert "release-assets" in immutable_verify_section

    assert "$zip = Join-Path $assetDirectory 'TextVerbessern-Windows.zip'" in latest_update_section
    assert "gh release upload portable-latest $zip $browser $checksums --clobber" in latest_update_section
    assert "gh release create portable-latest $zip $browser $checksums" in latest_update_section


def test_ci_runs_quality_gate_for_every_supported_python_version() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'python-version: ["3.12", "3.13"]' in workflow
    assert "fail-fast: false" in workflow
    assert "timeout-minutes: 15" in workflow
    assert "python -m app.evaluation" in workflow
    assert 'app = ["evaluation_cases.json"]' in pyproject
