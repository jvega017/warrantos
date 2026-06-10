"""Tests for provenance.pathguard (T4 / B5 path containment).

Covers:
- Traversal attempts with ../ and ..\\ sequences.
- Absolute paths and Windows drive-letter absolutes.
- Happy paths (valid run_id, valid candidate path within base).
- MCP error shape for bad run_id and bad out_dir.

Python 3.8 compatible. Stdlib only.
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from provenance.pathguard import RUN_ID_RE, resolve_under
from provenance.mcp_server import (
    tool_warrant_check,
    tool_warrant_get_run,
    tool_warrant_record_override,
)


# ---------------------------------------------------------------------------
# RUN_ID_RE tests
# ---------------------------------------------------------------------------

class TestRunIdRe(unittest.TestCase):
    """RUN_ID_RE accepts safe identifiers and rejects path-escape characters."""

    def test_alphanum_accepted(self):
        self.assertIsNotNone(RUN_ID_RE.match("run123"))

    def test_hyphen_and_underscore_accepted(self):
        self.assertIsNotNone(RUN_ID_RE.match("run_2026-06-10"))

    def test_max_length_accepted(self):
        self.assertIsNotNone(RUN_ID_RE.match("a" * 64))

    def test_empty_rejected(self):
        self.assertIsNone(RUN_ID_RE.match(""))

    def test_too_long_rejected(self):
        self.assertIsNone(RUN_ID_RE.match("a" * 65))

    def test_dot_dot_slash_rejected(self):
        self.assertIsNone(RUN_ID_RE.match("../../etc/passwd"))

    def test_backslash_rejected(self):
        self.assertIsNone(RUN_ID_RE.match("run\\escape"))

    def test_forward_slash_rejected(self):
        self.assertIsNone(RUN_ID_RE.match("run/escape"))

    def test_space_rejected(self):
        self.assertIsNone(RUN_ID_RE.match("run id"))

    def test_null_byte_rejected(self):
        self.assertIsNone(RUN_ID_RE.match("run\x00id"))


# ---------------------------------------------------------------------------
# resolve_under tests
# ---------------------------------------------------------------------------

class TestResolveUnder(unittest.TestCase):
    """resolve_under accepts valid paths and raises ValueError on escapes."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.base = Path(self._tmp) / "base"
        self.base.mkdir()

    def test_exact_base_accepted(self):
        result = resolve_under(self.base, self.base)
        self.assertEqual(result, self.base.resolve())

    def test_child_path_accepted(self):
        child = self.base / "child_dir"
        result = resolve_under(self.base, child)
        self.assertEqual(result, child.resolve())

    def test_nested_child_accepted(self):
        nested = self.base / "a" / "b" / "c"
        result = resolve_under(self.base, nested)
        self.assertEqual(result, nested.resolve())

    def test_dot_dot_traversal_unix_rejected(self):
        traversal = self.base / ".." / "escape"
        with self.assertRaises(ValueError):
            resolve_under(self.base, traversal)

    def test_dot_dot_traversal_string_rejected(self):
        with self.assertRaises(ValueError):
            resolve_under(self.base, str(self.base) + "/../escape")

    def test_absolute_path_outside_base_rejected(self):
        # An absolute path that does not start with base should be rejected.
        with self.assertRaises(ValueError):
            resolve_under(self.base, Path(self._tmp) / "other")

    def test_root_absolute_rejected(self):
        # Passing the filesystem root should be rejected.
        root = Path(self._tmp).resolve().anchor  # "/" on POSIX, "C:\\" on Windows
        with self.assertRaises(ValueError):
            resolve_under(self.base, root)

    def test_windows_drive_absolute_rejected(self):
        # Windows drive-letter absolute paths outside the base must be refused.
        # Use a non-existent path that is unambiguously not under self.base.
        candidate = "C:\\Windows\\System32" if os.name == "nt" else "/etc/passwd"
        with self.assertRaises(ValueError):
            resolve_under(self.base, candidate)

    def test_path_not_existing_yet_accepted(self):
        # A new run directory that does not yet exist should still be accepted.
        new_dir = self.base / "new_run_dir"
        self.assertFalse(new_dir.exists())
        result = resolve_under(self.base, new_dir)
        self.assertEqual(result, new_dir.resolve())

    def test_sibling_with_shared_prefix_rejected(self):
        # /base_extra should not be accepted just because /base is the base.
        sibling = Path(self._tmp) / (self.base.name + "_extra")
        with self.assertRaises(ValueError):
            resolve_under(self.base, sibling)


# ---------------------------------------------------------------------------
# MCP tool_warrant_check path validation tests
# ---------------------------------------------------------------------------

class TestMcpPathValidation(unittest.TestCase):
    """tool_warrant_check returns structured errors for bad run_id and out_dir."""

    _MINIMAL_DRAFT = None  # path string; set in setUpClass

    @classmethod
    def setUpClass(cls):
        # Write a minimal draft file so the pipeline can be entered even
        # though it will be short-circuited by the path validation before
        # any pipeline logic runs.
        cls._tmp_dir = tempfile.mkdtemp()
        draft = Path(cls._tmp_dir) / "draft.md"
        draft.write_text("Test draft content.", encoding="utf-8")
        cls._MINIMAL_DRAFT = str(draft)

    def test_bad_run_id_returns_error_key(self):
        result = tool_warrant_check({
            "draft_path": self._MINIMAL_DRAFT,
            "run_id": "../../evil",
        })
        self.assertEqual(result.get("error"), "invalid_run_id")
        self.assertIn("run_id", result.get("detail", ""))

    def test_bad_run_id_with_slash_returns_error(self):
        result = tool_warrant_check({
            "draft_path": self._MINIMAL_DRAFT,
            "run_id": "run/escape",
        })
        self.assertEqual(result.get("error"), "invalid_run_id")

    def test_bad_out_dir_traversal_returns_error(self):
        result = tool_warrant_check({
            "draft_path": self._MINIMAL_DRAFT,
            "run_id": "run_valid",
            "out_dir": ".warrant/runs/../../escape",
        })
        self.assertEqual(result.get("error"), "invalid_out_dir")
        self.assertIn("detail", result)

    def test_bad_out_dir_absolute_outside_base_returns_error(self):
        # An absolute path that cannot possibly be under .warrant/runs.
        outside = str(Path(self._tmp_dir) / "outside")
        result = tool_warrant_check({
            "draft_path": self._MINIMAL_DRAFT,
            "run_id": "run_valid",
            "out_dir": outside,
        })
        self.assertEqual(result.get("error"), "invalid_out_dir")

    def test_valid_run_id_passes_validation_gate(self):
        # A valid run_id and no out_dir override: the error key must not be
        # "invalid_run_id" or "invalid_out_dir".  The call may succeed or fail
        # further into the pipeline (e.g. file-not-found), but the path
        # validation itself must not block it.
        result = tool_warrant_check({
            "draft_path": self._MINIMAL_DRAFT,
            "run_id": "run_goodid",
        })
        self.assertNotIn(result.get("error"), ("invalid_run_id", "invalid_out_dir"))

    def test_error_shape_has_error_and_detail_keys(self):
        result = tool_warrant_check({
            "draft_path": self._MINIMAL_DRAFT,
            "run_id": "bad/id",
        })
        self.assertIn("error", result)
        self.assertIn("detail", result)


# ---------------------------------------------------------------------------
# MCP tool_warrant_record_override path validation tests
# ---------------------------------------------------------------------------

class TestMcpRecordOverridePathValidation(unittest.TestCase):
    """tool_warrant_record_override refuses bad run_id and db_path escapes."""

    _OUTSIDE_DB = None  # set in setUpClass

    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.mkdtemp()
        cls._OUTSIDE_DB = str(Path(cls._tmp_dir) / "outside.db")

    def _valid_args(self, **overrides):
        base = {
            "db_path": str(Path(".warrant") / "test_override.db"),
            "run_id": "run_valid",
            "reviewer": "human:director.so",
            "gate_id": "G1",
            "failure_class": "boundary",
            "risk_accepted": "Accepted.",
            "compensating_control": "Control applied.",
        }
        base.update(overrides)
        return base

    def test_traversal_run_id_dot_dot_slash_returns_error(self):
        result = tool_warrant_record_override(self._valid_args(run_id="../../evil"))
        self.assertEqual(result.get("error"), "invalid_run_id")
        self.assertIn("detail", result)

    def test_absolute_run_id_returns_error(self):
        candidate = "C:\\Windows\\evil" if os.name == "nt" else "/etc/evil"
        result = tool_warrant_record_override(self._valid_args(run_id=candidate))
        self.assertEqual(result.get("error"), "invalid_run_id")

    def test_windows_drive_letter_run_id_returns_error(self):
        result = tool_warrant_record_override(self._valid_args(run_id="C:\\evil"))
        self.assertEqual(result.get("error"), "invalid_run_id")

    def test_traversal_db_path_returns_error(self):
        result = tool_warrant_record_override(
            self._valid_args(db_path=".warrant/../../escape.db")
        )
        self.assertEqual(result.get("error"), "invalid_db_path")
        self.assertIn("detail", result)

    def test_absolute_db_path_outside_warrant_returns_error(self):
        result = tool_warrant_record_override(
            self._valid_args(db_path=self._OUTSIDE_DB)
        )
        self.assertEqual(result.get("error"), "invalid_db_path")

    def test_windows_drive_db_path_returns_error(self):
        candidate = "C:\\Windows\\evil.db" if os.name == "nt" else "/etc/evil.db"
        result = tool_warrant_record_override(
            self._valid_args(db_path=candidate)
        )
        self.assertEqual(result.get("error"), "invalid_db_path")


# ---------------------------------------------------------------------------
# MCP tool_warrant_get_run path validation tests
# ---------------------------------------------------------------------------

class TestMcpGetRunPathValidation(unittest.TestCase):
    """tool_warrant_get_run refuses out_dir escapes (arbitrary file read)."""

    _OUTSIDE_DIR = None  # set in setUpClass

    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.mkdtemp()
        cls._OUTSIDE_DIR = str(Path(cls._tmp_dir) / "outside")

    def test_traversal_out_dir_dot_dot_slash_returns_error(self):
        result = tool_warrant_get_run({"out_dir": ".warrant/runs/../../escape"})
        self.assertEqual(result.get("error"), "invalid_out_dir")
        self.assertIn("detail", result)

    def test_absolute_out_dir_outside_warrant_returns_error(self):
        result = tool_warrant_get_run({"out_dir": self._OUTSIDE_DIR})
        self.assertEqual(result.get("error"), "invalid_out_dir")

    def test_windows_drive_out_dir_returns_error(self):
        candidate = "C:\\Windows\\System32" if os.name == "nt" else "/etc"
        result = tool_warrant_get_run({"out_dir": candidate})
        self.assertEqual(result.get("error"), "invalid_out_dir")

    def test_valid_warrant_subpath_passes_validation(self):
        # A path under .warrant must not be rejected by the guard itself.
        # It may return nulls (files absent) but must not return invalid_out_dir.
        result = tool_warrant_get_run({"out_dir": str(Path(".warrant") / "runs" / "run_abc")})
        self.assertNotEqual(result.get("error"), "invalid_out_dir")


# ---------------------------------------------------------------------------
# CLI check path validation tests
# ---------------------------------------------------------------------------

class TestCliCheckPathValidation(unittest.TestCase):
    """warrantos check exits non-zero when out_dir or --db escapes cwd."""

    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.mkdtemp()
        draft = Path(cls._tmp_dir) / "draft.md"
        draft.write_text("Neutral test content.", encoding="utf-8")
        cls._draft = str(draft)

    def _run_check(self, extra_args):
        """Invoke warrantos_cli.main() with standard args plus extra_args."""
        from cli.warrantos_cli import main
        return main(["check", self._draft] + extra_args)

    def test_traversal_out_dir_exits_nonzero(self):
        rc = self._run_check(["--out-dir", "../../../escape_out"])
        self.assertNotEqual(rc, 0)

    def test_absolute_out_dir_outside_cwd_exits_nonzero(self):
        outside = str(Path(self._tmp_dir) / "outside_out")
        rc = self._run_check(["--out-dir", outside])
        self.assertNotEqual(rc, 0)

    def test_windows_drive_out_dir_exits_nonzero(self):
        candidate = "C:\\Windows\\evil_out" if os.name == "nt" else "/tmp/evil_out"
        rc = self._run_check(["--out-dir", candidate])
        self.assertNotEqual(rc, 0)

    def test_traversal_db_exits_nonzero(self):
        rc = self._run_check(["--db", "../../escape.db"])
        self.assertNotEqual(rc, 0)

    def test_absolute_db_outside_cwd_exits_nonzero(self):
        outside = str(Path(self._tmp_dir) / "outside.db")
        rc = self._run_check(["--db", outside])
        self.assertNotEqual(rc, 0)

    def test_windows_drive_db_exits_nonzero(self):
        candidate = "C:\\Windows\\evil.db" if os.name == "nt" else "/tmp/evil.db"
        rc = self._run_check(["--db", candidate])
        self.assertNotEqual(rc, 0)

    def test_invalid_run_id_exits_nonzero(self):
        rc = self._run_check(["--run-id", "../../evil"])
        self.assertNotEqual(rc, 0)


# ---------------------------------------------------------------------------
# CLI attest path validation tests
# ---------------------------------------------------------------------------

class TestCliAttestPathValidation(unittest.TestCase):
    """warrantos attest exits non-zero when --db or --out escapes cwd."""

    @classmethod
    def setUpClass(cls):
        cls._tmp_dir = tempfile.mkdtemp()
        # Create a minimal run dir with a cbom.json so attest reaches the guard.
        run_dir = Path(cls._tmp_dir) / "run_attest"
        run_dir.mkdir()
        cbom = {"schema": "warrantos-cbom/v1", "artefact_id": "test.md"}
        (run_dir / "cbom.json").write_text(
            __import__("json").dumps(cbom), encoding="utf-8"
        )
        prose = Path(cls._tmp_dir) / "prose.md"
        prose.write_text("Final prose.", encoding="utf-8")
        cls._run_dir = str(run_dir)
        cls._prose = str(prose)

    def _run_attest(self, extra_args):
        from cli.warrantos_cli import main
        return main(["attest", self._prose, "--run-dir", self._run_dir] + extra_args)

    def test_traversal_db_exits_nonzero(self):
        rc = self._run_attest(["--db", "../../escape.db"])
        self.assertNotEqual(rc, 0)

    def test_absolute_db_outside_cwd_exits_nonzero(self):
        outside = str(Path(self._tmp_dir) / "outside.db")
        rc = self._run_attest(["--db", outside])
        self.assertNotEqual(rc, 0)

    def test_windows_drive_db_exits_nonzero(self):
        candidate = "C:\\Windows\\evil.db" if os.name == "nt" else "/tmp/evil.db"
        rc = self._run_attest(["--db", candidate])
        self.assertNotEqual(rc, 0)

    def test_traversal_out_exits_nonzero(self):
        rc = self._run_attest(["--out", "../../../escape.warrant"])
        self.assertNotEqual(rc, 0)

    def test_absolute_out_outside_cwd_exits_nonzero(self):
        outside = str(Path(self._tmp_dir) / "outside.warrant")
        rc = self._run_attest(["--out", outside])
        self.assertNotEqual(rc, 0)

    def test_windows_drive_out_exits_nonzero(self):
        candidate = "C:\\Windows\\evil.warrant" if os.name == "nt" else "/tmp/evil.warrant"
        rc = self._run_attest(["--out", candidate])
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
