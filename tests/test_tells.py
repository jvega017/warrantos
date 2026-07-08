#!/usr/bin/env python3
"""Tests for warrantos/provenance/tells.py and the `warrantos tells` wiring.

Coverage:

- each rule family fires on a positive control
- false-positive traps stay silent: "not only ... but"-adjacent legitimate
  prose, a single hedge, a lone sentence-initial Furthermore, bare
  "rather than", unspaced en-dash number ranges
- hedge-stacking reports the sentence's own line, never the preceding one
- explicit file arguments display a real path, never "."
- fenced code blocks are skipped by default; --include-fences opts in
- --json report shape, --badge URL, --fail-over exit-code contract
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from warrantos.cli.warrantos_cli import main as cli_main
from warrantos.provenance.tells import badge_url, scan_text, tell_score


POSITIVE_CONTROLS = {
    "contrastive-negation": (
        "It is not a tax. It is a levy.\n",
        "It's not about speed, it's about proof.\n",
        "This is not a drill, this is the real audit.\n",
        "The gate isn't a formality, it's the control.\n",
        "The change is less about tooling and more about culture.\n",
        "The panel was not just advisory but binding.\n",
    ),
    "hedge-stacking": (
        "The outcome may perhaps arguably improve.\n",
        "The measure could potentially reduce costs, it seems, and "
        "possibly demand.\n",
    ),
    "dash-punctuation": (
        "The gate fired—twice in one run.\n",
        "The gate fired – twice in one run.\n",
    ),
    "filler-lexicon": (
        "Let's dive in.\n",
        "The review will delve into the rich tapestry of controls.\n",
        "It is important to note that the ledger is append-only.\n",
    ),
    "formulaic-transition": (
        "Furthermore, costs fell.\nFurthermore, demand rose.\n",
        "Moreover, the audit passed.\nAdditionally, the badge went green.\n",
    ),
}

TRAPS = (
    "not only did the committee meet, it voted the same day.\n",
    "She may attend.\n",
    "Furthermore, the committee endorsed the plan.\n",
    "rather than delaying, the team shipped early.\n",
    "The 2020–2021 reporting period closed on time.\n",
    "The report below is a summary of consultations.\n",
)


class _TellsHarness:
    """Temp-directory scaffolding shared by the tells CLI tests."""

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
        """Run `warrantos tells` in-process; return (exit_code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(["tells"] + list(args))
        return code, out.getvalue(), err.getvalue()


class TestPositiveControls(unittest.TestCase):
    def test_each_family_fires(self):
        for category, samples in POSITIVE_CONTROLS.items():
            for sample in samples:
                findings = scan_text(sample, "doc.md")
                self.assertIn(
                    category,
                    {f.category for f in findings},
                    msg="expected %r to fire on %r" % (category, sample),
                )


class TestFalsePositiveTraps(unittest.TestCase):
    def test_traps_stay_silent(self):
        for trap in TRAPS:
            findings = scan_text(trap, "doc.md")
            self.assertEqual(
                findings, [], msg="false positive on %r: %r" % (trap, findings)
            )

    def test_single_formulaic_opener_is_silent_two_fire_once(self):
        one = "Furthermore, costs fell.\n"
        self.assertEqual(scan_text(one, "doc.md"), [])
        two = "Furthermore, costs fell.\nFurthermore, demand rose.\n"
        findings = scan_text(two, "doc.md")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "formulaic-transition")
        self.assertEqual(findings[0].line, 2)


class TestLineAttribution(unittest.TestCase):
    def test_hedge_sentence_reports_its_own_line(self):
        text = (
            "It is a levy under the Act.\n"
            "The outcome may perhaps arguably improve.\n"
        )
        findings = [
            f for f in scan_text(text, "doc.md") if f.category == "hedge-stacking"
        ]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line, 2)


class TestFenceHandling(unittest.TestCase):
    FENCED = "```\nLet's dive in.\n```\nOrdinary prose follows.\n"

    def test_fenced_tells_skipped_by_default(self):
        self.assertEqual(scan_text(self.FENCED, "doc.md"), [])

    def test_include_fences_scans_fenced_lines(self):
        findings = scan_text(self.FENCED, "doc.md", include_fences=True)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "filler-lexicon")


class TestScoreAndBadge(unittest.TestCase):
    def test_zero_findings_is_zero(self):
        self.assertEqual(tell_score(0, 3), 0.0)

    def test_badge_clean_and_scored(self):
        self.assertIn("tells-clean-brightgreen", badge_url(0.0, 0))
        scored = badge_url(7.5, 3)
        self.assertIn("-red", scored)
        self.assertIn("7.5%2F10", scored)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.h = _TellsHarness()
        self.addCleanup(self.h.cleanup)

    def test_json_report_shape(self):
        self.h.write("doc.md", "Let's dive in.\n")
        code, out, _err = self.h.run_cli(str(self.h.tmp), "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["schema"], "warrantos-tells/v1")
        self.assertEqual(data["files_scanned"], 1)
        self.assertEqual(data["findings_count"], 1)
        self.assertEqual(data["findings"][0]["category"], "filler-lexicon")
        self.assertIn("badge_url", data)

    def test_explicit_file_displays_real_path_not_dot(self):
        target = self.h.write("doc.md", "Let's dive in.\n")
        code, out, _err = self.h.run_cli(str(target), "--json")
        self.assertEqual(code, 0)
        path = json.loads(out)["findings"][0]["path"]
        self.assertNotEqual(path, ".")
        self.assertTrue(path.endswith("doc.md"), msg=path)

    def test_fail_over_contract(self):
        self.h.write("doc.md", "Let's dive in.\n")
        code, _out, _err = self.h.run_cli(str(self.h.tmp), "--fail-over", "0")
        self.assertEqual(code, 1)
        code, _out, _err = self.h.run_cli(str(self.h.tmp), "--fail-over", "10")
        self.assertEqual(code, 0)

    def test_missing_path_exits_two(self):
        code, _out, err = self.h.run_cli(str(self.h.tmp / "nope"))
        self.assertEqual(code, 2)
        self.assertIn("path not found", err)

    def test_clean_tree_scores_zero(self):
        self.h.write("doc.md", "The framework underpins the decision.\n")
        code, out, _err = self.h.run_cli(str(self.h.tmp), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["findings_count"], 0)


if __name__ == "__main__":
    unittest.main()
