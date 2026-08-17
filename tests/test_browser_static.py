"""Static privacy and deployment contract for the no-install browser edition."""

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).parents[1]
WEB = ROOT / "web"
STANDALONE = WEB / "TextVerbessern-Browser.html"
STANDALONE_BUILDER = ROOT / "scripts" / "build_browser_standalone.py"


def test_browser_page_uses_only_relative_assets_and_a_strict_csp() -> None:
    page = (WEB / "index.html").read_text(encoding="utf-8")

    assert 'href="./styles.css"' in page
    assert 'src="./app.js"' in page
    assert "connect-src 'none'" in page
    assert "script-src 'self'" in page
    assert "style-src 'self'" in page
    assert "worker-src 'none'" in page
    assert "object-src 'none'" in page
    assert "base-uri 'none'" in page
    assert "form-action 'none'" in page
    assert "http://" not in page
    assert "https://" not in page
    assert page.count('spellcheck="false" autocomplete="off"') == 2
    assert '<noscript>' in page
    assert 'id="result-heading" tabindex="-1"' in page
    assert '<input type="radio" name="mode" value="safe" checked>' in page
    assert '<input type="radio" name="mode" value="fast">' in page
    assert 'id="file-button" type="button"' in page
    assert '<label class="button button-secondary" for="file-input">' not in page
    assert 'id="review-confirmation" hidden' in page
    assert 'id="review-checkbox" type="checkbox" autocomplete="off"' in page
    assert 'id="copy-button" type="button" disabled' in page
    assert "Diese Anwendung verarbeitet deinen Text lokal." in page
    assert "Browser, Betriebssystem und Erweiterungen können eigene Einstellungen haben." in page
    assert not re.search(r"<script(?![^>]*\bsrc=)", page, flags=re.I)
    assert not re.search(r"\son[a-z]+\s*=", page, flags=re.I)


def test_browser_code_has_no_network_or_persistent_text_storage() -> None:
    source = "\n".join(
        (WEB / name).read_text(encoding="utf-8")
        for name in ("editor.js", "app.js")
    )

    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "sendBeacon",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "caches.",
    ):
        assert forbidden not in source
    assert "content_included: false" in source
    assert "input_sha256" in source
    assert r"\p{Cf}" in source
    assert "MAX_PROTECTED_TERM_MATCHES" in source
    assert "requestAnimationFrame" in source
    assert "createTransformationRequest" in source
    assert "isCurrentRequest" in source
    assert "inputVersion" in source
    assert "discardStaleRequest" in source
    assert "readOnly = isBusy" in source
    assert "MAX_INPUT_FILE_BYTES" in source
    assert "fileButton" in source
    assert (WEB / ".nojekyll").is_file()


def test_offline_browser_file_is_current_and_has_no_external_runtime_dependency() -> None:
    check = subprocess.run(
        [sys.executable, str(STANDALONE_BUILDER), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr

    page = STANDALONE.read_text(encoding="utf-8")
    assert "OFFLINE-AUSGABE" in page
    assert "connect-src 'none'" in page
    assert "script-src 'self' 'unsafe-inline'" in page
    assert page.index("<script>") > page.index("</main>")
    assert page.index("<script>") < page.index("</body>")
    assert page.count('spellcheck="false" autocomplete="off"') == 2
    assert "Diese Anwendung verarbeitet deinen Text lokal." in page
    assert "Diese lokale Datei verbindet sich nicht mit GitHub oder anderen Diensten." in page
    assert '<link rel="stylesheet" href="./styles.css">' not in page
    assert '<script type="module" src="./app.js"></script>' not in page
    assert "import {" not in page
    assert "export const" not in page
    assert "GitHub Pages liefert nur die Programmdateien aus." not in page


def test_pages_workflow_is_least_privilege_and_tests_static_assets() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    verify_job, pages_status_and_after = workflow.split("  pages_status:\n", maxsplit=1)
    pages_status_job, prepare_pages_and_after = pages_status_and_after.split(
        "  prepare_pages:\n", maxsplit=1
    )
    prepare_pages_job, deploy_job = prepare_pages_and_after.split("  deploy:\n", maxsplit=1)

    assert "pull_request:" in workflow
    assert "contents: read" in workflow
    assert "pages: read" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "actions: read" not in workflow
    assert "group: pages-${{ github.ref }}" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "  verify:" in workflow
    assert "  pages_status:" in workflow
    assert "  prepare_pages:" in workflow
    assert "actions/configure-pages" not in verify_job
    assert "actions/upload-pages-artifact" not in verify_job
    assert "needs: verify" in workflow
    assert "needs: pages_status" in workflow
    assert "needs: [pages_status, prepare_pages]" in workflow
    assert "if: needs.pages_status.outputs.enabled == 'true'" in workflow
    assert "node --test tests/web_editor.test.mjs tests/web_standalone.test.mjs" in workflow
    assert "python tests/test_browser_static.py" in workflow
    assert "python scripts/build_browser_standalone.py --check" in workflow
    assert "github.rest.repos.getPages" in workflow
    assert 'response.data.build_type !== "workflow"' in workflow
    assert "error.status === 404" in workflow
    assert 'core.setOutput("enabled", "false")' in workflow
    assert 'core.setOutput("enabled", "true")' in workflow
    assert "Browser verification passed; deployment was skipped." in workflow
    assert "Settings > Pages > Source to GitHub Actions to publish." in workflow
    assert "continue-on-error" not in workflow
    assert "throw error;" in workflow
    assert "permissions:\n      pages: read" in pages_status_job
    assert "actions/checkout@v6" in prepare_pages_job
    assert "actions/configure-pages@v5" in prepare_pages_job
    assert "actions/upload-pages-artifact@v4" in prepare_pages_job
    assert "contents: read" not in deploy_job
    assert "actions: read" not in deploy_job
    assert "actions/deploy-pages@v4" in deploy_job
    assert "path: web" in workflow
    assert "actions/deploy-pages@v4" in workflow


if __name__ == "__main__":
    test_browser_page_uses_only_relative_assets_and_a_strict_csp()
    test_browser_code_has_no_network_or_persistent_text_storage()
    test_offline_browser_file_is_current_and_has_no_external_runtime_dependency()
    test_pages_workflow_is_least_privilege_and_tests_static_assets()
