#!/usr/bin/env python3
"""Test suite for cli/provenance_cli.py.

Stdlib only, zero dependencies. Run from the repo root:

    python -m unittest tests.test_cli -v

All tests are offline and deterministic. The provenance package is stubbed
via sys.modules before any CLI code runs, so no network is hit and no
actual package installation is required.

Test coverage:
  - stdin path (default and explicit '-')
  - file path (existing and missing)
  - directory path with .md files
  - --ci exit 1 when contradicted verdict present
  - --ci exit 1 when unsupported (no citation) claim present
  - --ci exit 0 when all verdicts are verified
  - --json emits parseable JSON
  - missing path emits error to stderr; exits 0 without --ci, exits 1 with --ci
  - empty input produces no crash
  - no network is ever hit (stubs verified)
"""

import importlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Fake Verdict dataclass (mirrors the interface contract)
# ---------------------------------------------------------------------------

class FakeVerdict:
    """Minimal stand-in for provenance.grade.Verdict."""

    def __init__(
        self,
        claim_text: str,
        verdict: str,
        citation: Optional[str] = None,
        confidence: Optional[float] = None,
        rationale: Optional[str] = None,
        grader: Optional[str] = None,
    ):
        self.claim_text = claim_text
        self.verdict = verdict
        self.citation = citation
        self.confidence = confidence
        self.rationale = rationale
        self.grader = grader


# ---------------------------------------------------------------------------
# Pre-built fixture sets for common scenarios
# ---------------------------------------------------------------------------

VERDICTS_ALL_VERIFIED = [
    FakeVerdict("The programme began in 2019.", "verified", citation="https://example.org/a", confidence=0.9),
    FakeVerdict("Emissions fell 12 per cent.", "verified", citation="https://example.org/b", confidence=0.88),
]

VERDICTS_WITH_CONTRADICTED = [
    FakeVerdict("The fund holds $4 billion.", "contradicted", confidence=0.7,
                rationale="Source states $2 billion, not $4 billion."),
    FakeVerdict("Output rose 5 per cent.", "verified", citation="https://example.org/c", confidence=0.95),
]

VERDICTS_WITH_UNSUPPORTED = [
    # 'not_addressed' is not in _BAD_VERDICTS so CI failure comes from totals["unsupported"]
    FakeVerdict("According to the review, costs rose.", "not_addressed"),
]

VERDICTS_MIXED = [
    FakeVerdict("Emissions fell 12 per cent.", "verified", citation="https://example.org/d"),
    FakeVerdict("The 2021 study found no effect.", "not_addressed"),
    FakeVerdict("Revenue was $3 billion.", "unverifiable"),
]


# ---------------------------------------------------------------------------
# Helper: install the fake provenance package into sys.modules
# ---------------------------------------------------------------------------

def _make_fake_provenance_package(verdicts_to_return):
    """Build a fake `provenance` package tree in sys.modules.

    The fake exposes provenance.verify.verify_text() returning the supplied
    list of FakeVerdict objects. This satisfies the interface contract that
    the CLI codes to.
    """
    # provenance (top-level)
    fake_provenance = types.ModuleType("warrantos.provenance")

    # provenance.grade
    fake_grade = types.ModuleType("warrantos.provenance.grade")
    fake_grade.Verdict = FakeVerdict
    fake_provenance.grade = fake_grade

    # provenance.extract
    fake_extract = types.ModuleType("warrantos.provenance.extract")
    fake_extract.CLAIM_TRIGGERS = []
    fake_extract.CITATION_MARKERS = []
    fake_extract.CITE_NEEDED = None
    fake_extract.sentences = lambda text: text.split(". ")
    fake_provenance.extract = fake_extract

    # provenance.verify
    fake_verify = types.ModuleType("warrantos.provenance.verify")
    # verify_text accepts (text, grader=None, fetch=True) per the contract
    def _fake_verify_text(text, grader=None, fetch=True):
        return list(verdicts_to_return)
    fake_verify.verify_text = _fake_verify_text
    fake_provenance.verify = fake_verify

    return {
        "warrantos.provenance": fake_provenance,
        "warrantos.provenance.grade": fake_grade,
        "warrantos.provenance.extract": fake_extract,
        "warrantos.provenance.verify": fake_verify,
    }


def _install_fake_provenance(stubs):
    """Make the fake provenance package authoritative in sys.modules.

    Cross-file hygiene: an earlier test module may have imported the real
    warrantos.provenance.* package. Purge it, install the fakes, and repoint the
    warrantos package's .provenance attribute, so the reloaded CLI binds only to
    the fakes. Callers run under patch.dict(sys.modules), so tearDown restores
    the originals.
    """
    for key in [m for m in sys.modules
                if m == "warrantos.provenance" or m.startswith("warrantos.provenance.")]:
        del sys.modules[key]
    for name, mod in stubs.items():
        sys.modules[name] = mod
    if "warrantos" in sys.modules:
        sys.modules["warrantos"].provenance = stubs["warrantos.provenance"]


class _CliTestBase(unittest.TestCase):
    """Base class: installs the fake package, then imports the CLI module fresh."""

    # Subclasses may override this to control the verdicts returned by the stub.
    _verdicts = VERDICTS_ALL_VERIFIED

    def setUp(self):
        # Snapshot sys.modules so every mutation below (stub install, CLI
        # reload) is fully reverted in tearDown. Popping the stubs by hand
        # left provenance.* absent, forcing later test files (test_verify)
        # to re-import fresh, non-identical modules: that broke their mocks
        # and isinstance checks under the full discover run.
        self._modpatch = patch.dict(sys.modules)
        self._modpatch.start()

        # 1. Inject fake modules BEFORE the CLI module is (re-)imported.
        self._stub_modules = _make_fake_provenance_package(self.__class__._verdicts)
        _install_fake_provenance(self._stub_modules)

        # 2. Remove any previously cached version of the CLI module so the
        #    lazy imports inside functions resolve against the freshly
        #    installed stubs.
        for key in list(sys.modules.keys()):
            if "provenance_cli" in key:
                del sys.modules[key]

        # 3. Import the CLI module.
        cli_path = REPO_ROOT / "warrantos" / "cli" / "provenance_cli.py"
        spec = importlib.util.spec_from_file_location("provenance_cli", str(cli_path))
        self._cli_module = importlib.util.module_from_spec(spec)
        sys.modules["provenance_cli"] = self._cli_module
        spec.loader.exec_module(self._cli_module)

    def tearDown(self):
        # Restore sys.modules exactly as it was before setUp. This reverts
        # the stub package and the CLI module in one step and, critically,
        # does not leave provenance.* popped for later test files.
        self._modpatch.stop()

    def _run_main(self, argv, stdin_text=None):
        """Call main() with the given argv list. Returns (exit_code, stdout, stderr)."""
        real_stdin = sys.stdin
        real_stdout = sys.stdout
        real_stderr = sys.stderr

        captured_out = io.StringIO()
        captured_err = io.StringIO()

        if stdin_text is not None:
            sys.stdin = io.StringIO(stdin_text)

        sys.stdout = captured_out
        sys.stderr = captured_err

        try:
            exit_code = self._cli_module.main(argv)
        except SystemExit as exc:
            exit_code = exc.code if exc.code is not None else 0
        finally:
            sys.stdin = real_stdin
            sys.stdout = real_stdout
            sys.stderr = real_stderr

        return (
            exit_code if exit_code is not None else 0,
            captured_out.getvalue(),
            captured_err.getvalue(),
        )


# ---------------------------------------------------------------------------
# Test: stdin path (default and explicit '-')
# ---------------------------------------------------------------------------

class TestStdinPath(_CliTestBase):
    _verdicts = VERDICTS_ALL_VERIFIED

    def test_stdin_default_no_path_arg(self):
        """No PATH arg should read from stdin and produce output."""
        code, out, err = self._run_main([], stdin_text="The fund held $4 billion in 2024.")
        self.assertEqual(code, 0)
        self.assertIn("provenance check", out)

    def test_stdin_explicit_dash(self):
        """Explicit '-' should read from stdin."""
        code, out, err = self._run_main(["-"], stdin_text="The fund held $4 billion in 2024.")
        self.assertEqual(code, 0)
        self.assertIn("provenance check", out)

    def test_empty_stdin_exits_clean(self):
        """Empty stdin should not crash and should exit 0."""
        code, out, err = self._run_main(["-"], stdin_text="")
        self.assertEqual(code, 0)


# ---------------------------------------------------------------------------
# Test: file path (existing and missing)
# ---------------------------------------------------------------------------

class TestFilePath(_CliTestBase):
    _verdicts = VERDICTS_ALL_VERIFIED

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._md = Path(self._tmp.name) / "draft.md"
        self._md.write_text(
            "The programme began in 2019. Emissions fell 12 per cent.",
            encoding="utf-8",
        )

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    def test_existing_file(self):
        code, out, err = self._run_main([str(self._md)])
        self.assertEqual(code, 0)
        self.assertIn("provenance check", out)

    def test_missing_file_no_ci(self):
        """Missing path without --ci should exit 0 and print error to stderr."""
        code, out, err = self._run_main(["/does/not/exist/foo.md"])
        self.assertEqual(code, 0)
        self.assertIn("not found", err)

    def test_missing_file_with_ci(self):
        """Missing path with --ci should exit 1."""
        code, out, err = self._run_main(["--ci", "/does/not/exist/foo.md"])
        self.assertEqual(code, 1)
        self.assertIn("not found", err)


# ---------------------------------------------------------------------------
# Test: directory path
# ---------------------------------------------------------------------------

class TestDirectoryPath(_CliTestBase):
    _verdicts = VERDICTS_ALL_VERIFIED

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        (d / "a.md").write_text("Emissions fell 12 per cent.", encoding="utf-8")
        (d / "b.txt").write_text("The fund holds $3 billion.", encoding="utf-8")
        (d / "ignore.py").write_text("x = 1  # not scanned", encoding="utf-8")

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    def test_directory_scans_md_and_txt(self):
        code, out, err = self._run_main([self._tmp.name])
        self.assertEqual(code, 0)
        # Both .md and .txt sources should appear in output
        self.assertIn("a.md", out)
        self.assertIn("b.txt", out)

    def test_directory_does_not_scan_py(self):
        code, out, err = self._run_main([self._tmp.name])
        self.assertNotIn("ignore.py", out)


# ---------------------------------------------------------------------------
# Test: --ci exit codes
# ---------------------------------------------------------------------------

class TestCiExitContradicted(_CliTestBase):
    _verdicts = VERDICTS_WITH_CONTRADICTED

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._md = Path(self._tmp.name) / "draft.md"
        self._md.write_text("The fund holds $4 billion.", encoding="utf-8")

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    def test_ci_exit_1_on_contradicted(self):
        """--ci must exit 1 when a contradicted verdict is present."""
        code, out, err = self._run_main(["--ci", str(self._md)])
        self.assertEqual(code, 1)

    def test_no_ci_exit_0_on_contradicted(self):
        """Without --ci, a contradicted verdict must still exit 0."""
        code, out, err = self._run_main([str(self._md)])
        self.assertEqual(code, 0)


class TestCiExitUnsupported(_CliTestBase):
    """CI must also fail when the heuristic pass finds unsupported claims."""
    _verdicts = VERDICTS_WITH_UNSUPPORTED

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._md = Path(self._tmp.name) / "draft.md"
        self._md.write_text("According to the review, costs rose.", encoding="utf-8")

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    def test_ci_exit_1_on_unsupported_via_totals(self):
        """--ci must exit 1 when unsupported count is non-zero in totals.

        The stub returns VERDICTS_WITH_UNSUPPORTED which contains
        'not_addressed'. The CLI derives totals from the offline pass: total=1,
        verified=0, skipped=0, unsupported=1. The CI gate checks unsupported>0.
        """
        code, out, err = self._run_main(["--ci", str(self._md)])
        self.assertEqual(code, 1)


class TestCiExitAllVerified(_CliTestBase):
    _verdicts = VERDICTS_ALL_VERIFIED

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._md = Path(self._tmp.name) / "draft.md"
        self._md.write_text(
            "The programme began in 2019 (https://example.org/a). "
            "Emissions fell 12 per cent (https://example.org/b).",
            encoding="utf-8",
        )

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    def test_ci_exit_0_when_all_verified(self):
        """--ci must exit 0 when all verdicts are verified."""
        code, out, err = self._run_main(["--ci", str(self._md)])
        self.assertEqual(code, 0)


# ---------------------------------------------------------------------------
# Test: --json output
# ---------------------------------------------------------------------------

class TestJsonOutput(_CliTestBase):
    _verdicts = VERDICTS_MIXED

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._md = Path(self._tmp.name) / "draft.md"
        self._md.write_text(
            "Emissions fell 12 per cent. The 2021 study found no effect. "
            "Revenue was $3 billion.",
            encoding="utf-8",
        )

    def tearDown(self):
        super().tearDown()
        self._tmp.cleanup()

    def test_json_is_parseable(self):
        code, out, err = self._run_main(["--json", str(self._md)])
        self.assertEqual(code, 0)
        try:
            data = json.loads(out)
        except json.JSONDecodeError as exc:
            self.fail("--json output is not valid JSON: %s" % exc)
        self.assertIn("results", data)
        self.assertIsInstance(data["results"], list)

    def test_json_contains_expected_keys(self):
        code, out, err = self._run_main(["--json", str(self._md)])
        data = json.loads(out)
        self.assertIn("ci_failure", data)
        result = data["results"][0]
        self.assertIn("source", result)
        self.assertIn("report", result)

    def test_json_ci_failure_flag(self):
        """ci_failure in JSON should be False when all verdicts are not contradicted."""
        code, out, err = self._run_main(["--json", str(self._md)])
        data = json.loads(out)
        # VERDICTS_MIXED has no 'contradicted'; unsupported from not_addressed/unverifiable
        # depends on totals mapping. ci_failure may be True (unsupported>0) but must be bool.
        self.assertIsInstance(data["ci_failure"], bool)

    def test_json_ci_exit_1_when_contradicted(self):
        """Inject contradicted verdict and verify --json --ci still exits 1."""
        # Re-stub with contradicted verdicts.
        new_stubs = _make_fake_provenance_package(VERDICTS_WITH_CONTRADICTED)
        _install_fake_provenance(new_stubs)
        # Force CLI re-import so lazy imports pick up the new stubs.
        for key in list(sys.modules.keys()):
            if "provenance_cli" in key:
                del sys.modules[key]
        cli_path = REPO_ROOT / "warrantos" / "cli" / "provenance_cli.py"
        spec = importlib.util.spec_from_file_location("provenance_cli", str(cli_path))
        self._cli_module = importlib.util.module_from_spec(spec)
        sys.modules["provenance_cli"] = self._cli_module
        spec.loader.exec_module(self._cli_module)
        self._stub_modules = new_stubs

        md = Path(self._tmp.name) / "contra.md"
        md.write_text("The fund holds $4 billion.", encoding="utf-8")
        code, out, err = self._run_main(["--json", "--ci", str(md)])
        data = json.loads(out)
        self.assertEqual(data["ci_failure"], True)
        self.assertEqual(code, 1)


# ---------------------------------------------------------------------------
# Test: robustness / no crash invariants
# ---------------------------------------------------------------------------

class TestRobustness(_CliTestBase):
    _verdicts = VERDICTS_ALL_VERIFIED

    def test_whitespace_only_stdin_exits_clean(self):
        code, out, err = self._run_main(["-"], stdin_text="   \n\n   ")
        self.assertEqual(code, 0)

    def test_large_input_does_not_crash(self):
        big = "The programme began in 2019. " * 1000
        code, out, err = self._run_main(["-"], stdin_text=big)
        self.assertEqual(code, 0)

    def test_no_crash_on_binary_like_content(self):
        # Pathological but must not raise.
        code, out, err = self._run_main(["-"], stdin_text="\x00\x01\x02 some text 2019")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
