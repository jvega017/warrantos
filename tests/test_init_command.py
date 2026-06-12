#!/usr/bin/env python3
"""Tests for the `warrantos init` scaffolding command (0.9.5).

Stdlib only, offline, deterministic. Run from the repo root:

    python -m unittest tests.test_init_command -v
"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from warrantos.cli import warrantos_cli


def _run(argv):
    """Run the CLI capturing stdout; return (exit_code, stdout)."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = warrantos_cli.main(argv)
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


class TestInitScaffold(unittest.TestCase):
    def test_writes_both_templates(self):
        with tempfile.TemporaryDirectory(prefix="warrantos-init-") as tmp:
            rc, out = _run(["init", "--dir", tmp])
            self.assertEqual(rc, 0)
            actor = Path(tmp) / "actor.json"
            context = Path(tmp) / "context.json"
            self.assertTrue(actor.is_file())
            self.assertTrue(context.is_file())
            self.assertIn("created", out)

    def test_actor_template_is_the_canonical_six_roles(self):
        with tempfile.TemporaryDirectory(prefix="warrantos-init-") as tmp:
            _run(["init", "--dir", tmp])
            actor = json.loads((Path(tmp) / "actor.json").read_text("utf-8"))
            self.assertEqual(
                set(actor),
                {
                    "context_classifier",
                    "insight_compiler",
                    "source_curator",
                    "clean_room_writer",
                    "reviewer_qa",
                    "auditor",
                },
            )
            # The default scaffold must not trip separation of duties: the
            # writer and reviewer identities are deliberately different.
            self.assertNotEqual(
                actor["clean_room_writer"], actor["reviewer_qa"]
            )

    def test_context_template_is_a_nonempty_list_of_items(self):
        with tempfile.TemporaryDirectory(prefix="warrantos-init-") as tmp:
            _run(["init", "--dir", tmp])
            context = json.loads((Path(tmp) / "context.json").read_text("utf-8"))
            self.assertIsInstance(context, list)
            self.assertTrue(context)
            self.assertIn("id", context[0])
            self.assertIn("text", context[0])

    def test_does_not_overwrite_without_force(self):
        with tempfile.TemporaryDirectory(prefix="warrantos-init-") as tmp:
            sentinel = '{"context_classifier": "human:mine"}'
            (Path(tmp) / "actor.json").write_text(sentinel, encoding="utf-8")
            rc, out = _run(["init", "--dir", tmp])
            self.assertEqual(rc, 0)
            self.assertIn("skipped", out)
            # The user's file is untouched.
            self.assertEqual(
                (Path(tmp) / "actor.json").read_text("utf-8"), sentinel
            )

    def test_force_overwrites(self):
        with tempfile.TemporaryDirectory(prefix="warrantos-init-") as tmp:
            (Path(tmp) / "actor.json").write_text("{}", encoding="utf-8")
            rc, out = _run(["init", "--dir", tmp, "--force"])
            self.assertEqual(rc, 0)
            self.assertIn("created", out)
            actor = json.loads((Path(tmp) / "actor.json").read_text("utf-8"))
            self.assertIn("clean_room_writer", actor)

    def test_scaffolded_files_are_accepted_by_check(self):
        # End-to-end: a user runs `init`, writes a draft, and `check` accepts
        # the scaffolded inputs. A valid actor identity means the verdict is
        # NOT the NOT_ASSESSABLE "no actor identity" state.
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="warrantos-init-e2e-") as tmp:
            tmp_path = Path(tmp)
            _run(["init", "--dir", str(tmp_path)])
            (tmp_path / "draft.md").write_text(
                "The agency must comply with the policy.\n", encoding="utf-8"
            )
            try:
                os.chdir(tmp_path)
                rc, out = _run([
                    "check", "draft.md",
                    "--context", "context.json",
                    "--actor-identity", "actor.json",
                    "--profile", "final-prose",
                ])
            finally:
                os.chdir(original_cwd)
            self.assertIsInstance(rc, int)
            self.assertIn("VERDICT", out)
            self.assertNotIn("NOT_ASSESSABLE", out)


if __name__ == "__main__":
    unittest.main()
