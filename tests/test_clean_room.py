#!/usr/bin/env python3
"""Tests for provenance.clean_room (Layer 6 discipline mode)."""

import unittest

from provenance.clean_room import (
    InvocationPlan,
    list_permitted_kwargs,
    prepare_invocation,
)
from provenance.writer_pack import compile_writer_pack


class TestPrepareInvocation(unittest.TestCase):

    def setUp(self):
        self.pack = compile_writer_pack([], run_id="run_clean_room")

    def test_returns_plan_with_documented_defaults(self):
        plan = prepare_invocation(self.pack, writer_model="claude-opus-4-7")
        self.assertIsInstance(plan, InvocationPlan)
        self.assertEqual(plan.writer_model, "claude-opus-4-7")
        self.assertEqual(plan.writer_role, "clean_room_writer")
        self.assertEqual(plan.max_tokens, 4096)
        self.assertAlmostEqual(plan.temperature, 0.2)

    def test_empty_writer_model_raises(self):
        for bad in ("", "  ", "\t\n"):
            with self.subTest(model=repr(bad)):
                with self.assertRaises(ValueError):
                    prepare_invocation(self.pack, writer_model=bad)

    def test_non_writer_pack_type_raises(self):
        with self.assertRaises(TypeError):
            prepare_invocation(
                {"not": "a pack"},  # type: ignore[arg-type]
                writer_model="claude-opus-4-7",
            )

    def test_refuses_arbitrary_context_kwargs(self):
        """SPEC-L6-S001: extra context kwargs are refused at the API
        surface so process material cannot be silently threaded
        through under a 'context' or 'system_prompt' kwarg name."""
        with self.assertRaises(ValueError) as ctx:
            prepare_invocation(
                self.pack,
                writer_model="claude-opus-4-7",
                context="this is the conversation history",  # not permitted
            )
        self.assertIn("SPEC-L6-S001", str(ctx.exception))
        self.assertIn("context", str(ctx.exception))

    def test_refuses_system_prompt_kwarg(self):
        with self.assertRaises(ValueError):
            prepare_invocation(
                self.pack,
                writer_model="claude-opus-4-7",
                system_prompt="You are an assistant...",
            )

    def test_refuses_feedback_kwarg(self):
        with self.assertRaises(ValueError):
            prepare_invocation(
                self.pack,
                writer_model="claude-opus-4-7",
                feedback="Make it more commercial.",
            )

    def test_accepts_temperature_override(self):
        plan = prepare_invocation(
            self.pack,
            writer_model="claude-opus-4-7",
            temperature=0.7,
        )
        self.assertAlmostEqual(plan.temperature, 0.7)

    def test_accepts_max_tokens_override(self):
        plan = prepare_invocation(
            self.pack,
            writer_model="claude-opus-4-7",
            max_tokens=8000,
        )
        self.assertEqual(plan.max_tokens, 8000)


class TestPlanSerialisation(unittest.TestCase):

    def test_plan_to_dict_carries_pack_and_model(self):
        pack = compile_writer_pack([], run_id="run_serialise")
        plan = prepare_invocation(pack, writer_model="claude-opus-4-7")
        d = plan.to_dict()
        self.assertEqual(d["schema"], "warrantos-invocation-plan/v1")
        self.assertEqual(d["writer_model"], "claude-opus-4-7")
        self.assertEqual(d["writer_role"], "clean_room_writer")
        # Pack contents threaded through.
        self.assertEqual(d["writer_pack"]["run_id"], "run_serialise")


class TestListPermittedKwargs(unittest.TestCase):

    def test_returns_sorted_list_of_permitted_keys(self):
        keys = list_permitted_kwargs()
        self.assertIsInstance(keys, list)
        self.assertEqual(keys, sorted(keys))
        # Documented permitted keys are present.
        for k in ("writer_pack", "writer_model", "max_tokens", "temperature"):
            self.assertIn(k, keys)


class TestRunCleanRoomSubprocess(unittest.TestCase):
    """SPEC-L6-R001 Level 2: env scrubbed to allowlist, plan delivered
    via stdin, subprocess result captured."""

    def setUp(self):
        import os
        import sys

        self.pack = compile_writer_pack([], run_id="run_subprocess")
        self.plan = prepare_invocation(
            self.pack, writer_model="claude-opus-4-7"
        )
        self.python = sys.executable
        self.os = os

    def test_subprocess_receives_plan_via_stdin(self):
        from provenance.clean_room import run_clean_room_subprocess

        # The subprocess echoes its stdin to stdout. We assert the plan
        # JSON is delivered intact.
        result = run_clean_room_subprocess(
            self.plan,
            command=[self.python, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
            timeout=15.0,
        )
        self.assertEqual(result.exit_code, 0, msg=result.stderr)
        self.assertFalse(result.timed_out)
        # The stdout is the plan JSON; check a known field is present.
        self.assertIn("warrantos-invocation-plan/v1", result.stdout)
        self.assertIn("claude-opus-4-7", result.stdout)

    def test_subprocess_env_is_scrubbed(self):
        """An env var that is NOT in the allowlist is suppressed."""
        from provenance.clean_room import run_clean_room_subprocess

        # Set a sentinel env var in the parent. It must NOT reach the
        # subprocess.
        self.os.environ["WARRANTOS_TEST_LEAK"] = "should_not_be_visible"
        try:
            result = run_clean_room_subprocess(
                self.plan,
                command=[
                    self.python, "-c",
                    "import os, sys; sys.stdout.write(os.environ.get('WARRANTOS_TEST_LEAK', 'absent'))",
                ],
                timeout=15.0,
            )
        finally:
            del self.os.environ["WARRANTOS_TEST_LEAK"]

        self.assertEqual(result.exit_code, 0, msg=result.stderr)
        # The subprocess reports 'absent' because WARRANTOS_TEST_LEAK
        # was scrubbed by the allowlist.
        self.assertEqual(result.stdout.strip(), "absent")
        self.assertGreater(result.scrubbed_env_keys, 0)

    def test_extra_env_allowlist_lets_a_named_key_through(self):
        from provenance.clean_room import run_clean_room_subprocess

        self.os.environ["WARRANTOS_TEST_ALLOWED"] = "deliberate"
        try:
            result = run_clean_room_subprocess(
                self.plan,
                command=[
                    self.python, "-c",
                    "import os, sys; sys.stdout.write(os.environ.get('WARRANTOS_TEST_ALLOWED', 'absent'))",
                ],
                timeout=15.0,
                extra_env_allowlist=["WARRANTOS_TEST_ALLOWED"],
            )
        finally:
            del self.os.environ["WARRANTOS_TEST_ALLOWED"]

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), "deliberate")

    def test_subprocess_timeout_sets_timed_out_flag(self):
        from provenance.clean_room import run_clean_room_subprocess

        result = run_clean_room_subprocess(
            self.plan,
            command=[self.python, "-c", "import time; time.sleep(5)"],
            timeout=0.5,
        )
        self.assertTrue(result.timed_out)
        self.assertEqual(result.exit_code, -1)

    def test_non_plan_type_raises(self):
        from provenance.clean_room import run_clean_room_subprocess

        with self.assertRaises(TypeError):
            run_clean_room_subprocess(
                {"not": "a plan"},  # type: ignore[arg-type]
                command=[self.python, "-c", "pass"],
            )

    def test_empty_command_raises(self):
        from provenance.clean_room import run_clean_room_subprocess

        with self.assertRaises(ValueError):
            run_clean_room_subprocess(self.plan, command=[])


class TestListDefaultEnvAllowlist(unittest.TestCase):

    def test_returns_documented_keys(self):
        from provenance.clean_room import list_default_env_allowlist

        keys = list_default_env_allowlist()
        # PATH is essential on every platform; assert it is allowlisted.
        self.assertIn("PATH", keys)
        # Sorted return.
        self.assertEqual(keys, sorted(keys))


if __name__ == "__main__":
    unittest.main(verbosity=2)
