#!/usr/bin/env python3
"""Tests for provenance.status (the per-layer conformance dashboard)."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

try:
    from conftest import get_clean_env
except ImportError:  # running as tests.test_* from the repo root
    from tests.conftest import get_clean_env

from warrantos.provenance.status import (
    LayerStatus,
    collect_status,
    render_markdown,
    render_text,
)


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLI = _REPO_ROOT / "warrantos" / "cli" / "warrantos_cli.py"


class TestCollectStatus(unittest.TestCase):
    """The status list covers every documented layer and uses only the
    four documented status values."""

    def test_every_layer_has_a_status_row(self):
        rows = collect_status()
        layer_ids = {r.layer_id for r in rows}
        for required in (
            "L1", "L2", "L3", "L4", "L5", "L6",
            "L7-G1", "L7-G2", "L7-G3", "L7-G4", "L7-G5",
            "L8",
            "F-policy", "F-classification", "F-audit", "F-integrity",
            "F-retention", "F-compliance", "F-override", "F-metrics",
        ):
            self.assertIn(required, layer_ids, msg="missing layer: " + required)

    def test_status_values_are_documented_set(self):
        valid = {"BUILT", "PARTIAL", "STARTER", "NOT_BUILT"}
        for r in collect_status():
            self.assertIn(r.status, valid, msg=r.layer_id + " has unknown status")

    def test_f_policy_built_requires_registry_and_spec(self):
        # F-policy is BUILT only when the role registry resolves and the
        # normative SPEC document is committed. Guard the flip so removing
        # either artefact would surface here.
        rows = {r.layer_id: r for r in collect_status()}
        self.assertEqual(rows["F-policy"].status, "BUILT")
        from warrantos.provenance import roles
        self.assertEqual(len(roles.REQUIRED_ACTOR_ROLE_IDS), 6)
        self.assertTrue((_REPO_ROOT / "docs" / "SPEC.md").is_file())

    def test_f_compliance_built_requires_spec_and_mapping(self):
        # F-compliance is BUILT only when BOTH the normative SPEC and the
        # control-mapping document are committed. BUILT here is the
        # documented-mapping ceiling, never certified conformance. Guard the
        # flip so removing either artefact would surface here.
        rows = {r.layer_id: r for r in collect_status()}
        self.assertEqual(rows["F-compliance"].status, "BUILT")
        self.assertTrue((_REPO_ROOT / "docs" / "SPEC.md").is_file())
        self.assertTrue((_REPO_ROOT / "docs" / "COMPLIANCE.md").is_file())
        # The notes must not overclaim certification.
        notes = rows["F-compliance"].notes.lower()
        self.assertIn("not certified", notes)

    def test_layer_status_to_dict_is_serialisable(self):
        rows = collect_status()
        # Round-trip through JSON.
        text = json.dumps([r.to_dict() for r in rows])
        roundtrip = json.loads(text)
        self.assertEqual(len(roundtrip), len(rows))


class TestRenderers(unittest.TestCase):

    def test_text_renderer_lists_every_layer_and_summary(self):
        out = render_text()
        self.assertIn("WarrantOS layer status", out)
        # Every layer id appears.
        for required in ("L1", "L7-G1", "L8", "F-override"):
            self.assertIn(required, out)
        # Summary counts present.
        self.assertIn("BUILT", out)

    def test_markdown_renderer_has_table_header(self):
        out = render_markdown()
        self.assertIn("# WarrantOS layer status", out)
        self.assertIn("| Layer | Status | Module | Notes |", out)
        self.assertIn("BUILT", out)


class TestStatusCli(unittest.TestCase):
    """The `warrantos status` subcommand runs and produces output in
    the three formats."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_CLI)] + list(args),
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            env=get_clean_env(),
        )

    def test_text_default(self):
        proc = self._run("status")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("WarrantOS layer status", proc.stdout)

    def test_json_output_parses(self):
        proc = self._run("status", "--json")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        data = json.loads(proc.stdout)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 15)
        for row in data:
            self.assertIn("layer_id", row)
            self.assertIn("status", row)

    def test_markdown_output_starts_with_heading(self):
        proc = self._run("status", "--markdown")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertTrue(proc.stdout.startswith("# WarrantOS layer status"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
