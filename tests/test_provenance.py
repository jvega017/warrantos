#!/usr/bin/env python3
"""Test suite for claude-provenance.

Stdlib only, zero dependencies, matching the plugin itself. Run from the
repo root:

    python -m unittest discover -s tests -v

The suite is deliberately strict about the claims the README makes:
every trigger type, inline and adjacent sourcing, the closed v0 false
negative (a source two sentences away must not rescue a claim), the
Stop-loop guard, enforce-mode blocking, and the absolute rule that an
internal error must never break the session.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "hooks" / "provenance_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("provenance_check", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pc = _load_module()


class AnalyseHeuristics(unittest.TestCase):
    """Pure-function behaviour of analyse(): the heart of the detector."""

    def _one(self, text):
        rows, totals = pc.analyse(text)
        self.assertEqual(totals["total"], 1, "expected exactly one claim row")
        return rows[0], totals

    def test_unsupported_year(self):
        (status, trigger, _), t = self._one("The programme began in 2019.")
        self.assertEqual(status, "unsupported")
        self.assertEqual(trigger, "year")
        self.assertEqual(t["unsupported"], 1)

    def test_unsupported_percentage(self):
        (status, trigger, _), _ = self._one("Emissions fell 12 per cent.")
        self.assertEqual(status, "unsupported")
        self.assertEqual(trigger, "percentage")

    def test_unsupported_magnitude(self):
        (status, trigger, _), _ = self._one("The fund holds $4 billion.")
        self.assertEqual(status, "unsupported")
        self.assertEqual(trigger, "magnitude")

    def test_unsupported_statute(self):
        (status, trigger, _), _ = self._one(
            "Disclosure is required under section 12 of the Act."
        )
        self.assertEqual(status, "unsupported")
        self.assertEqual(trigger, "statute")

    def test_unsupported_attribution(self):
        (status, trigger, _), _ = self._one(
            "According to the review, the model underperformed."
        )
        self.assertEqual(status, "unsupported")
        self.assertEqual(trigger, "attribution")

    def test_supported_inline_url(self):
        (status, _, _), _ = self._one(
            "Emissions fell 12 per cent (see https://example.org/data)."
        )
        self.assertEqual(status, "supported")

    def test_supported_inline_source_note(self):
        (status, _, _), _ = self._one(
            "The fund holds $4 billion (Source: Treasury annual report)."
        )
        self.assertEqual(status, "supported")

    def test_supported_apa(self):
        (status, _, _), _ = self._one(
            "The reform cut average processing time (Vega, 2026)."
        )
        self.assertEqual(status, "supported")

    def test_supported_by_following_citation_lead(self):
        rows, totals = pc.analyse(
            "Emissions fell 12 per cent.\nSource: https://example.org/data"
        )
        self.assertEqual(totals["total"], 1)
        self.assertEqual(rows[0][0], "supported")

    def test_v0_false_negative_stays_closed(self):
        # A source two sentences away must NOT rescue the claim.
        rows, totals = pc.analyse(
            "Emissions fell 12 per cent.\n"
            "The decline continued into the next quarter.\n"
            "Source: https://example.org/data"
        )
        claim = next(r for r in rows if r[1] == "percentage")
        self.assertEqual(
            claim[0],
            "unsupported",
            "a citation two sentences away must not bleed onto the claim",
        )

    def test_cite_needed_is_tagged_not_unsupported(self):
        (status, _, _), t = self._one(
            "Spending reached $4 billion last year [CITE NEEDED]."
        )
        self.assertEqual(status, "tagged")
        self.assertEqual(t["tagged"], 1)
        self.assertEqual(t["unsupported"], 0)

    def test_no_factual_trigger_yields_no_rows(self):
        rows, totals = pc.analyse(
            "This sentence makes no checkable factual assertion at all."
        )
        self.assertEqual(totals["total"], 0)
        self.assertEqual(rows, [])

    def test_totals_add_up(self):
        rows, totals = pc.analyse(
            "Output rose 5 per cent (https://example.org/a). "
            "Costs were $2 billion [CITE NEEDED]. "
            "The 2021 review was inconclusive."
        )
        self.assertEqual(
            totals["total"],
            totals["supported"] + totals["tagged"] + totals["unsupported"],
        )
        self.assertEqual(totals["supported"], 1)
        self.assertEqual(totals["tagged"], 1)
        self.assertEqual(totals["unsupported"], 1)


class HookIntegration(unittest.TestCase):
    """End-to-end behaviour of the hook process via stdin/stdout/exit code."""

    def _run(self, event, mode=None):
        env = dict(os.environ)
        env["PROVENANCE_DB"] = self.db_path
        if mode is not None:
            env["PROVENANCE_MODE"] = mode
        else:
            env.pop("PROVENANCE_MODE", None)
        proc = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(event) if event is not None else "",
            capture_output=True,
            text=True,
            env=env,
        )
        return proc

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "provenance.db")

    def tearDown(self):
        self._tmp.cleanup()

    def _post_event(self, content):
        return {
            "hook_event_name": "PostToolUse",
            "session_id": "test-session",
            "tool_input": {"file_path": "draft.md", "content": content},
        }

    def test_report_mode_is_nonblocking_and_surfaces(self):
        p = self._run(self._post_event("The fund held $4 billion in 2024."))
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), "", "report mode must not block")
        self.assertIn("Provenance Loop", p.stderr)
        self.assertIn("UNSUPPORTED: 1", p.stderr)

    def test_enforce_mode_blocks_on_unsupported(self):
        p = self._run(
            self._post_event("The fund held $4 billion in 2024."),
            mode="enforce",
        )
        self.assertEqual(p.returncode, 0)
        payload = json.loads(p.stdout)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("Unsupported", payload["reason"])

    def test_enforce_mode_passes_when_all_supported(self):
        p = self._run(
            self._post_event(
                "The fund held $4 billion (Source: https://example.org/r)."
            ),
            mode="enforce",
        )
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), "", "no unsupported claim, no block")

    def test_off_mode_is_inert(self):
        p = self._run(self._post_event("Spending hit $9 billion."), mode="off")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), "")
        self.assertEqual(p.stderr.strip(), "")

    def test_stop_loop_guard_short_circuits(self):
        # Even in enforce mode, a second pass in the same turn must not block.
        event = {
            "hook_event_name": "Stop",
            "session_id": "test-session",
            "stop_hook_active": True,
            "transcript_path": "does-not-exist.jsonl",
        }
        p = self._run(event, mode="enforce")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), "", "stop-loop guard must not block")

    def test_garbage_stdin_never_crashes(self):
        env = dict(os.environ)
        env["PROVENANCE_DB"] = self.db_path
        env["PROVENANCE_MODE"] = "enforce"
        proc = subprocess.run(
            [sys.executable, str(HOOK)],
            input="this is not json {{{",
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, "a hook must never break a session")
        self.assertEqual(proc.stdout.strip(), "")

    def test_empty_stdin_never_crashes(self):
        p = self._run(None, mode="enforce")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), "")

    def test_ledger_is_written(self):
        self._run(self._post_event("Revenue rose 7 per cent in 2023."))
        self.assertTrue(
            Path(self.db_path).is_file(), "the ledger file should exist"
        )
        import sqlite3

        con = sqlite3.connect(self.db_path)
        runs = con.execute("SELECT COUNT(*) FROM provenance_run").fetchone()[0]
        claims = con.execute(
            "SELECT COUNT(*) FROM provenance_claim"
        ).fetchone()[0]
        con.close()
        self.assertEqual(runs, 1)
        self.assertEqual(claims, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
