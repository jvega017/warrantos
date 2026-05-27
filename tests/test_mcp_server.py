#!/usr/bin/env python3
"""Tests for provenance.mcp_server (Path X4-A).

The MCP transport is exercised only at the structure level (tool
definitions). The tool handlers are tested in-process via
call_tool_in_process so the suite does not require the MCP SDK to be
installed at test time.
"""

import json
import tempfile
import unittest
from pathlib import Path

from provenance.mcp_server import (
    TOOL_DEFINITIONS,
    call_tool_in_process,
    tool_warrant_check,
    tool_warrant_classify,
    tool_warrant_get_run,
    tool_warrant_record_override,
)


_FINAL_ACTOR = {
    "context_classifier": "agent:auto",
    "insight_compiler": "human:juan.vega",
    "source_curator": "human:juan.vega",
    "clean_room_writer": "model:claude-opus-4-7",
    "reviewer_qa": "agent:policy-red-team",
    "auditor": "human:director.so",
}


class TestToolDefinitions(unittest.TestCase):
    """The four tools are declared with the expected names and schemas."""

    def test_four_tools_defined(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        self.assertEqual(
            names,
            {
                "warrant_check",
                "warrant_classify",
                "warrant_record_override",
                "warrant_get_run",
            },
        )

    def test_every_tool_has_description_and_schema(self):
        for tool in TOOL_DEFINITIONS:
            with self.subTest(tool=tool["name"]):
                self.assertTrue(tool["description"], "description required")
                self.assertEqual(tool["inputSchema"]["type"], "object")
                self.assertIn("properties", tool["inputSchema"])

    def test_warrant_check_required_fields(self):
        check = next(t for t in TOOL_DEFINITIONS if t["name"] == "warrant_check")
        self.assertEqual(check["inputSchema"]["required"], ["draft_path"])

    def test_warrant_record_override_required_fields(self):
        rec = next(
            t for t in TOOL_DEFINITIONS if t["name"] == "warrant_record_override"
        )
        # SPEC-L8-S004 normatives translate to required schema fields.
        for f in (
            "db_path",
            "run_id",
            "reviewer",
            "gate_id",
            "failure_class",
            "risk_accepted",
            "compensating_control",
        ):
            self.assertIn(f, rec["inputSchema"]["required"])


class TestToolDispatch(unittest.TestCase):
    """call_tool_in_process routes by name and raises on unknown."""

    def test_unknown_tool_raises(self):
        with self.assertRaises(ValueError):
            call_tool_in_process("warrant_unknown", {})


class TestWarrantClassifyTool(unittest.TestCase):
    """Tool-level wrapper around Layer 1 classification."""

    def test_classifies_review_role_output_via_source_agent(self):
        result = tool_warrant_classify(
            {
                "text": "Severity: P0\n# Findings\nA1 chain of thought attack.",
                "source_agent": "policy-red-team",
                "context_id": "ctx_a1",
            }
        )
        self.assertEqual(result["context_id"], "ctx_a1")
        self.assertEqual(result["context_type"], "review_finding")
        self.assertNotEqual(result["context_type"], "private_reasoning")
        self.assertEqual(result["ledger_bucket"], "synthesised")

    def test_classifies_empirical_evidence_by_text(self):
        result = tool_warrant_classify(
            {"text": "Source: Queensland Health strategy, 2026, page 4."}
        )
        self.assertEqual(result["context_type"], "empirical_evidence")
        self.assertEqual(result["ledger_bucket"], "empirical")
        self.assertTrue(result["can_appear_in_final_prose"])


class TestWarrantRecordOverrideTool(unittest.TestCase):
    """Tool-level wrapper around SPEC-L8-S004 override recording."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "overrides.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_override_round_trip(self):
        result = tool_warrant_record_override(
            {
                "db_path": str(self.db_path),
                "run_id": "run_mcp_demo",
                "reviewer": "human:director.so",
                "gate_id": "G1",
                "failure_class": "boundary",
                "risk_accepted": "Quoted source string flagged as narration.",
                "compensating_control": "Reviewer cross-checked the quote.",
            }
        )
        self.assertIn("id", result)
        self.assertEqual(result["gate_id"], "G1")
        self.assertEqual(result["run_id"], "run_mcp_demo")
        self.assertFalse(result["single_actor"])

    def test_empty_rationale_is_rejected(self):
        with self.assertRaises(ValueError):
            tool_warrant_record_override(
                {
                    "db_path": str(self.db_path),
                    "run_id": "run_bad",
                    "reviewer": "human:director.so",
                    "gate_id": "G1",
                    "failure_class": "boundary",
                    "risk_accepted": "",
                    "compensating_control": "Some control.",
                }
            )


class TestWarrantCheckTool(unittest.TestCase):
    """Tool-level wrapper around the full pipeline."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.draft = self.tmp / "draft.md"
        self.draft.write_text(
            "# Clean note\n\nA neutral paragraph with no claims.\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_pass_path_with_actor_identity(self):
        result = tool_warrant_check(
            {
                "draft_path": str(self.draft),
                "actor_identity": _FINAL_ACTOR,
                "profile": "final-prose",
                "out_dir": str(self.tmp / "out"),
                "db_path": str(self.tmp / "overrides.db"),
            }
        )
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["cbom_schema"], "warrantos-cbom/v1")
        self.assertEqual(result["boundary_verdict"], "pass")

    def test_not_assessable_without_actor_identity(self):
        result = tool_warrant_check(
            {
                "draft_path": str(self.draft),
                "profile": "final-prose",
                "out_dir": str(self.tmp / "out2"),
                "db_path": str(self.tmp / "overrides.db"),
            }
        )
        self.assertEqual(result["verdict"], "NOT_ASSESSABLE")

    def test_block_on_boundary_violation(self):
        leaky = self.tmp / "leaky.md"
        leaky.write_text(
            "# Note\n\nBased on your feedback this is now clearer.\n",
            encoding="utf-8",
        )
        result = tool_warrant_check(
            {
                "draft_path": str(leaky),
                "actor_identity": _FINAL_ACTOR,
                "profile": "final-prose",
                "out_dir": str(self.tmp / "out3"),
                "db_path": str(self.tmp / "overrides.db"),
            }
        )
        self.assertEqual(result["verdict"], "BLOCK")
        self.assertGreater(result["boundary_violations"], 0)


class TestWarrantGetRunTool(unittest.TestCase):
    """get_run reads back what warrant_check wrote."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.draft = self.tmp / "draft.md"
        self.draft.write_text(
            "# Read-back demo\n\nNeutral.\n", encoding="utf-8"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip(self):
        check_result = tool_warrant_check(
            {
                "draft_path": str(self.draft),
                "actor_identity": _FINAL_ACTOR,
                "profile": "final-prose",
                "out_dir": str(self.tmp / "round"),
                "db_path": str(self.tmp / "overrides.db"),
            }
        )
        out_dir = check_result["out_dir"]

        read_back = tool_warrant_get_run({"out_dir": out_dir})
        self.assertIn("verdict", read_back)
        self.assertIn("cbom", read_back)
        self.assertEqual(read_back["verdict"]["verdict"], check_result["verdict"])
        self.assertEqual(
            read_back["cbom"]["schema"], "warrantos-cbom/v1"
        )

    def test_missing_dir_returns_nulls(self):
        result = tool_warrant_get_run(
            {"out_dir": str(self.tmp / "nonexistent")}
        )
        self.assertIsNone(result["verdict"])
        self.assertIsNone(result["cbom"])
        self.assertIsNone(result["footer_md"])


class TestMcpSdkOptional(unittest.TestCase):
    """The module imports without the SDK; run_stdio_server() raises if absent."""

    def test_module_imports_without_running_server(self):
        from provenance import mcp_server
        # If the import succeeded, the test passes. The SDK may or may
        # not be installed; either way, importing the module SHALL not
        # raise.
        self.assertTrue(hasattr(mcp_server, "TOOL_DEFINITIONS"))
        self.assertTrue(hasattr(mcp_server, "run_stdio_server"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
