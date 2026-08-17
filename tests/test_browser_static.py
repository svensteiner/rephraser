"""Static privacy and deployment contract for the no-install browser edition."""

from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
WEB = ROOT / "web"


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
    assert "MAX_INPUT_FILE_BYTES" in source
    assert (WEB / ".nojekyll").is_file()


def test_pages_workflow_is_least_privilege_and_tests_static_assets() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "contents: read" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
    assert "actions: read" in workflow
    assert "group: pages-${{ github.ref }}" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "node --test tests/web_editor.test.mjs" in workflow
    assert "python tests/test_browser_static.py" in workflow
    assert "path: web" in workflow
    assert "actions/deploy-pages@v4" in workflow


if __name__ == "__main__":
    test_browser_page_uses_only_relative_assets_and_a_strict_csp()
    test_browser_code_has_no_network_or_persistent_text_storage()
    test_pages_workflow_is_least_privilege_and_tests_static_assets()
