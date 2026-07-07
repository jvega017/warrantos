#!/usr/bin/env python3
"""Tests for warrantos/provenance/slop.py and the `warrantos slop` wiring.

Coverage:

- score is 0.0 on clean text (unit and end-to-end)
- each of the five categories fires on its trigger text
- --json report shape (schema, score, counts, findings, badge_url)
- --badge URL for both the zero-findings and findings cases
- --fail-over exit-code contract
- skip-directory behaviour (.git, node_modules, dist, build, .venv,
  __pycache__ are never scanned)
- matched text is truncated to the documented limit
- score formula properties (monotonic, bounded, 5.0 at one per file)

The CLI is exercised in-process through warrantos.cli.warrantos_cli.main
so the tests stay fast; the slop command has no subprocess-only behaviour.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from warrantos.cli.warrantos_cli import main as cli_main
from warrantos.provenance.slop import (
    MATCH_TRUNCATE,
    badge_url,
    scan_paths,
    scan_text,
    slop_score,
)


CLEAN_TEXT = (
    "# Open data policy\n\n"
    "The framework underpins administrative decisions.\n"
    "Implementation follows the published guidance.\n"
)

# One trigger line per category.
CATEGORY_TRIGGERS = {
    "chat bleed": "Certainly, the analysis below covers all three options.\n",
    "identity leak": "As an AI language model, my view is limited.\n",
    "sign-off residue": "I hope this helps with the submission.\n",
    "scaffold": "Here is the revised version of the policy brief.\n",
    "placeholder": "[TODO: add the costing table here]\n",
}


class _SlopHarness:
    """Temp-directory scaffolding shared by the slop tests."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def write(self, relative: str, content: str) -> Path:
        p = self.tmp / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def run_cli(self, *args: str):
        """Run `warrantos slop` in-process; return (exit_code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(["slop"] + list(args))
        return code, out.getvalue(), err.getvalue()


class TestScoreFormula(unittest.TestCase):
    def test_zero_findings_is_zero(self):
        self.assertEqual(slop_score(0, 5), 0.0)

    def test_zero_files_is_zero(self):
        self.assertEqual(slop_score(0, 0), 0.0)

    def test_one_finding_per_file_is_five(self):
        self.assertEqual(slop_score(5, 5), 5.0)

    def test_monotonic_in_findings(self):
        scores = [slop_score(n, 4) for n in range(0, 40, 4)]
        self.assertEqual(scores, sorted(scores))
        self.assertLess(scores[0], scores[-1])

    def test_bounded_below_ten(self):
        self.assertLessEqual(slop_score(10_000, 1), 10.0)


class TestScanText(unittest.TestCase):
    def test_clean_text_no_findings(self):
        self.assertEqual(scan_text(CLEAN_TEXT, "clean.md"), [])

    def test_each_category_fires(self):
        for category, trigger in CATEGORY_TRIGGERS.items():
            findings = scan_text(trigger, "doc.md")
            self.assertTrue(findings, msg="no finding for %r" % category)
            self.assertIn(
                category,
                {f.category for f in findings},
                msg="expected category %r for %r" % (category, trigger),
            )

    def test_line_numbers_are_one_based(self):
        text = "First line is clean.\n\n" + CATEGORY_TRIGGERS["placeholder"]
        findings = scan_text(text, "doc.md")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line, 3)

    def test_match_is_truncated(self):
        text = "[TODO: " + "x" * 200 + "]\n"
        findings = scan_text(text, "doc.md")
        self.assertEqual(len(findings), 1)
        self.assertLessEqual(len(findings[0].match), MATCH_TRUNCATE)
        self.assertTrue(findings[0].match.endswith("..."))


class TestBadgeUrl(unittest.TestCase):
    def test_zero_findings_green(self):
        url = badge_url(0.0, 0)
        self.assertEqual(url, "https://img.shields.io/badge/slop-free-brightgreen")

    def test_findings_red_and_encoded(self):
        url = badge_url(5.0, 5)
        self.assertTrue(url.startswith("https://img.shields.io/badge/"))
        self.assertIn("red", url)
        # The slash in "5.0/10" must be URL-encoded.
        self.assertIn("5.0%2F10", url)
        self.assertNotIn("5.0/10", url)


class TestDirectorySkips(unittest.TestCase):
    def setUp(self):
        self.h = _SlopHarness()

    def tearDown(self):
        self.h.cleanup()

    def test_skip_dirs_never_scanned(self):
        sloppy = CATEGORY_TRIGGERS["identity leak"]
        for skip_dir in (".git", "node_modules", "dist", "build", ".venv", "__pycache__"):
            self.h.write(skip_dir + "/leak.md", sloppy)
        self.h.write("kept.md", CLEAN_TEXT)
        findings, files_scanned = scan_paths([str(self.h.tmp)])
        self.assertEqual(files_scanned, 1)
        self.assertEqual(findings, [])

    def test_non_text_suffixes_ignored_in_directory_walk(self):
        self.h.write("residue.py", CATEGORY_TRIGGERS["identity leak"])
        self.h.write("kept.txt", CLEAN_TEXT)
        findings, files_scanned = scan_paths([str(self.h.tmp)])
        self.assertEqual(files_scanned, 1)
        self.assertEqual(findings, [])

    def test_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            scan_paths([str(self.h.tmp / "does-not-exist")])


class TestCliSlop(unittest.TestCase):
    def setUp(self):
        self.h = _SlopHarness()

    def tearDown(self):
        self.h.cleanup()

    def _write_sloppy_tree(self):
        self.h.write("clean.md", CLEAN_TEXT)
        self.h.write("docs/residue.md", "".join(CATEGORY_TRIGGERS.values()))

    def test_clean_tree_scores_zero_exit_zero(self):
        self.h.write("clean.md", CLEAN_TEXT)
        code, out, _err = self.h.run_cli(str(self.h.tmp))
        self.assertEqual(code, 0)
        self.assertIn("SLOP SCORE: 0.0/10", out)
        self.assertIn("No AI scaffold residue detected.", out)

    def test_score_line_first_and_findings_listed(self):
        self._write_sloppy_tree()
        code, out, _err = self.h.run_cli(str(self.h.tmp))
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("SLOP SCORE: "))
        for category in CATEGORY_TRIGGERS:
            self.assertIn(category, out)

    def test_json_shape(self):
        self._write_sloppy_tree()
        code, out, _err = self.h.run_cli(str(self.h.tmp), "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["schema"], "warrantos-slop/v1")
        self.assertEqual(data["files_scanned"], 2)
        self.assertEqual(data["findings_count"], len(data["findings"]))
        self.assertGreater(data["findings_count"], 0)
        self.assertGreater(data["score"], 0.0)
        self.assertLessEqual(data["score"], 10.0)
        self.assertTrue(data["badge_url"].startswith("https://img.shields.io/badge/"))
        for finding in data["findings"]:
            self.assertEqual(
                sorted(finding), ["category", "line", "match", "path", "rule_id"]
            )
            self.assertIsInstance(finding["line"], int)
            self.assertGreaterEqual(finding["line"], 1)

    def test_badge_output_zero_findings(self):
        self.h.write("clean.md", CLEAN_TEXT)
        code, out, _err = self.h.run_cli(str(self.h.tmp), "--badge")
        self.assertEqual(code, 0)
        self.assertEqual(
            out.strip(), "https://img.shields.io/badge/slop-free-brightgreen"
        )

    def test_badge_output_with_findings(self):
        self._write_sloppy_tree()
        code, out, _err = self.h.run_cli(str(self.h.tmp), "--badge")
        self.assertEqual(code, 0)
        self.assertIn("-red", out)
        self.assertIn("%2F10", out)

    def test_fail_over_exceeded_exits_one(self):
        self._write_sloppy_tree()
        code, _out, _err = self.h.run_cli(str(self.h.tmp), "--fail-over", "0.5")
        self.assertEqual(code, 1)

    def test_fail_over_not_exceeded_exits_zero(self):
        self._write_sloppy_tree()
        code, _out, _err = self.h.run_cli(str(self.h.tmp), "--fail-over", "10")
        self.assertEqual(code, 0)

    def test_missing_path_exits_two(self):
        code, _out, err = self.h.run_cli(str(self.h.tmp / "nope"))
        self.assertEqual(code, 2)
        self.assertIn("path not found", err)

    def test_explicit_file_argument_is_scanned(self):
        target = self.h.write("residue.md", CATEGORY_TRIGGERS["placeholder"])
        code, out, _err = self.h.run_cli(str(target), "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["files_scanned"], 1)
        self.assertEqual(data["findings_count"], 1)
        self.assertEqual(data["findings"][0]["category"], "placeholder")


FENCED_QUOTED_RESIDUE = (
    "# Demo transcript\n\n"
    "The scanner output is shown below.\n\n"
    "```\n" + CATEGORY_TRIGGERS["identity leak"] + "```\n\n"
    "Fenced examples are documentation, not residue.\n"
)


class TestFenceHandling(unittest.TestCase):
    """Fenced code blocks are skipped by default (opt in via flag)."""

    def setUp(self):
        self.h = _SlopHarness()
        self.addCleanup(self.h.cleanup)

    def test_fenced_residue_skipped_by_default(self):
        self.assertEqual(scan_text(FENCED_QUOTED_RESIDUE, "demo.md"), [])

    def test_include_fences_scans_fenced_lines(self):
        findings = scan_text(
            FENCED_QUOTED_RESIDUE, "demo.md", include_fences=True
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "identity leak")

    def test_tilde_fence_skipped(self):
        text = "~~~\n" + CATEGORY_TRIGGERS["sign-off residue"] + "~~~\n"
        self.assertEqual(scan_text(text, "t.md"), [])

    def test_unclosed_fence_skips_to_end_of_document(self):
        text = "```\n" + CATEGORY_TRIGGERS["scaffold"]
        self.assertEqual(scan_text(text, "t.md"), [])

    def test_residue_outside_fence_still_fires(self):
        text = (
            "```\nquoted example block\n```\n"
            + CATEGORY_TRIGGERS["placeholder"]
        )
        findings = scan_text(text, "t.md")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "placeholder")

    def test_cli_include_fences_flag(self):
        self.h.write("demo.md", FENCED_QUOTED_RESIDUE)
        code, out, _err = self.h.run_cli(str(self.h.tmp), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["findings_count"], 0)
        code, out, _err = self.h.run_cli(
            str(self.h.tmp), "--json", "--include-fences"
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["findings_count"], 1)


if __name__ == "__main__":
    unittest.main()
