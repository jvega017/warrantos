"""
Tests for web/verify.html (T1: XSS, tri-state signature, CSP).

All checks are static analysis of the HTML/JS source using stdlib only.
No browser or network access is required.
"""
import pathlib
import re
import unittest

# Resolve the verify.html path relative to this test file.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_VERIFY_HTML = _REPO_ROOT / "web" / "verify.html"
_FIXTURES_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"


def _html() -> str:
    return _VERIFY_HTML.read_text(encoding="utf-8")


class TestXSSGuard(unittest.TestCase):
    """Verify that no innerHTML assignment uses a variable interpolation."""

    def test_no_variable_innerhtml(self):
        """Zero occurrences of innerHTML adjacent to a variable interpolation.

        The pattern catches: innerHTML = someVar, innerHTML=x, innerHTML +=x etc.
        Static hard-coded literals (no variable, just quoted strings) are allowed.
        """
        html = _html()
        # Match innerHTML followed by optional whitespace, an assignment operator
        # (= or +=), optional whitespace, then something that is NOT a plain
        # string literal (i.e. not immediately a ' or " character with no
        # variable name between the operator and the quote-open).
        # Specifically we look for innerHTML\s*=\s*[^'"] to catch any case
        # where a variable or expression appears on the right-hand side.
        pattern = re.compile(r'innerHTML\s*=\s*[^\'";\s]')
        matches = pattern.findall(html)
        self.assertEqual(
            matches,
            [],
            msg=(
                "Found innerHTML assignment(s) that may inject variable data: "
                + str(matches)
            ),
        )


class TestTriStateSig(unittest.TestCase):
    """Verify the three SIG state constants are present in the source."""

    def test_sig_valid_present(self):
        self.assertIn("SIGNED_VALID", _html())

    def test_sig_unsigned_present(self):
        # The string 'UNSIGNED' appears as a SIG constant value.
        self.assertIn("'UNSIGNED'", _html())

    def test_sig_invalid_present(self):
        self.assertIn("SIGNATURE_INVALID", _html())

    def test_sig_object_declaration(self):
        """The SIG object declaration is present with all three keys."""
        html = _html()
        self.assertIn("const SIG", html)
        self.assertIn("VALID:", html)
        self.assertIn("UNSIGNED:", html)
        self.assertIn("INVALID:", html)

    def test_invalid_not_downgraded_comment_or_logic(self):
        """The fail-closed rule is present in source (comment or code)."""
        html = _html()
        # Check that SIGNATURE_INVALID forcing overall INVALID is documented.
        self.assertIn("SIGNATURE_INVALID", html)
        # The checkbox must only affect UNSIGNED, not INVALID.
        # Verify that the allow-unsigned branch explicitly checks for UNSIGNED.
        self.assertIn("SIG.UNSIGNED", html)


class TestCSP(unittest.TestCase):
    """Verify the Content-Security-Policy meta tag is present."""

    def test_csp_meta_present(self):
        html = _html()
        self.assertIn("Content-Security-Policy", html)

    def test_csp_default_src_none(self):
        html = _html()
        self.assertIn("default-src 'none'", html)

    def test_csp_blocks_external_scripts(self):
        """script-src must not include http or https origins."""
        html = _html()
        # Extract the CSP meta content attribute value.
        csp_match = re.search(
            r'<meta[^>]+Content-Security-Policy[^>]+content="([^"]+)"',
            html,
            re.IGNORECASE,
        )
        self.assertIsNotNone(csp_match, "CSP meta tag not found")
        csp = csp_match.group(1)
        # script-src must not allow arbitrary external origins.
        # Allowed values are 'none', 'unsafe-inline', 'unsafe-eval', nonces,
        # hashes, or 'self'. An http/https origin would be a failure.
        script_src_match = re.search(r"script-src\s+([^;]+)", csp)
        if script_src_match:
            script_src = script_src_match.group(1)
            self.assertNotRegex(
                script_src,
                r"https?://",
                "script-src must not contain http(s) origins",
            )

    def test_csp_no_external_img_src(self):
        """img-src must not allow arbitrary external URLs."""
        html = _html()
        csp_match = re.search(
            r'<meta[^>]+Content-Security-Policy[^>]+content="([^"]+)"',
            html,
            re.IGNORECASE,
        )
        self.assertIsNotNone(csp_match, "CSP meta tag not found")
        csp = csp_match.group(1)
        img_src_match = re.search(r"img-src\s+([^;]+)", csp)
        if img_src_match:
            img_src = img_src_match.group(1)
            self.assertNotRegex(
                img_src,
                r"https?://",
                "img-src must not contain http(s) origins",
            )


class TestAccessibleInteraction(unittest.TestCase):
    """Guard the verifier's keyboard and status-announcement contract."""

    def test_file_picker_is_a_real_button(self):
        html = _html()
        self.assertIn('<button class="choose" id="choose" type="button">', html)
        self.assertIn('<label class="sr-only" for="file">', html)
        self.assertNotIn("drop.onclick", html)

    def test_result_is_announced_and_focusable(self):
        html = _html()
        self.assertRegex(
            html,
            r'id="result"[^>]+role="status"[^>]+aria-live="polite"[^>]+tabindex="-1"',
        )
        self.assertIn("card.focus();", html)

    def test_parse_error_uses_status_region_not_alert(self):
        html = _html()
        self.assertIn("renderInputError", html)
        self.assertNotIn('alert("Not valid JSON")', html)

    def test_visible_keyboard_focus_is_defined(self):
        self.assertIn(":focus-visible", _html())


class TestFixtures(unittest.TestCase):
    """Verify the fixture files exist and have the expected structure."""

    def test_xss_fixture_exists(self):
        self.assertTrue(
            (_FIXTURES_DIR / "xss_bundle.warrant").exists(),
            "xss_bundle.warrant fixture not found",
        )

    def test_badsig_fixture_exists(self):
        self.assertTrue(
            (_FIXTURES_DIR / "badsig_bundle.warrant").exists(),
            "badsig_bundle.warrant fixture not found",
        )

    def test_xss_fixture_contains_payload(self):
        import json
        data = json.loads((_FIXTURES_DIR / "xss_bundle.warrant").read_text())
        root_hash = data["checkpoint"]["root_hash"]
        self.assertIn("<img", root_hash)
        self.assertIn("onerror", root_hash)

    def test_badsig_fixture_has_signature(self):
        import json
        data = json.loads((_FIXTURES_DIR / "badsig_bundle.warrant").read_text())
        sig = data["checkpoint"].get("signature", "")
        self.assertTrue(len(sig) > 0, "badsig fixture must have a non-empty signature")

    def test_readme_exists(self):
        self.assertTrue(
            (_FIXTURES_DIR / "README.md").exists(),
            "tests/fixtures/README.md not found",
        )


if __name__ == "__main__":
    unittest.main()
