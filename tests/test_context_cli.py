#!/usr/bin/env python3
"""CLI tests for Context Bill of Materials export."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "warrantos" / "cli" / "provenance_cli.py"


class TestContextCli(unittest.TestCase):

    def test_cbom_json_reports_context_and_boundary_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context = root / "context.json"
            final = root / "final.md"
            context.write_text(
                json.dumps(
                    [
                        {
                            "id": "feedback_017",
                            "text": "This is not commercial enough.",
                        },
                        {
                            "id": "source_001",
                            "text": "Source: official report, 2026.",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            final.write_text(
                "The product targets professional AI users.",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--cbom",
                    "--context",
                    str(context),
                    "--json",
                    str(final),
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["results"][0]["report"]["schema"], "context-bill-of-materials/v1")
            self.assertEqual(payload["results"][0]["report"]["prose_boundary"]["verdict"], "pass")

    def test_cbom_ci_fails_on_process_to_prose_leakage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context = root / "context.txt"
            final = root / "final.md"
            context.write_text("This is not commercial enough.", encoding="utf-8")
            final.write_text(
                "Based on your feedback, this version is now more commercial.",
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--cbom",
                    "--context",
                    str(context),
                    "--ci",
                    str(final),
                ],
                cwd=str(REPO_ROOT),
                text=True,
                capture_output=True,
            )

            self.assertEqual(proc.returncode, 1)
            self.assertIn("Prose boundary: blocked", proc.stdout)
            self.assertIn("based on your feedback", proc.stdout.lower())


if __name__ == "__main__":
    unittest.main()
