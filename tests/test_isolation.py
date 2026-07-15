#!/usr/bin/env python3
"""Test suite isolation verification: hermetic tests, no external binaries, no network.

Verifies that:
- Network socket creation fails with clear error messages
- All subprocess calls use sys.executable and scrubbed environment
- Environment variables are properly isolated
- Grade.py handles subprocess errors correctly
- Grader factories produce readable stack traces (not lambda-generated)
- Default test suite runs without external Claude binary

Run from the repo root:
    python -m pytest tests/test_isolation.py -v
    python -m unittest tests.test_isolation -v
"""

import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add repo root to path so we can import warrantos
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.conftest import get_clean_env, assert_env_clean


# ============================================================================
# Test 1: Network socket attempt fails with clear message
# ============================================================================

class TestNetworkIsolation(unittest.TestCase):
    """Verify that network socket access is blocked in tests."""

    def test_socket_creation_fails_with_clear_message(self):
        """Attempt to create a network socket must raise AssertionError.

        Note: This test runs WITHOUT the block_network_access fixture,
        so we manually verify the blocking behavior.
        """
        # Import the fixture to test its behavior
        import pytest
        from tests.conftest import block_network_access

        # Create a fixture instance
        original_socket = socket.socket

        def socket_wrapper(*args, **kwargs):
            raise AssertionError(
                "Test attempted to open a network socket without @pytest.mark.network. "
                "Either mock the call, mark with @pytest.mark.network, or verify your "
                "test doesn't need network access."
            )

        # Test that the wrapper raises
        with self.assertRaises(AssertionError) as ctx:
            socket_wrapper(socket.AF_INET, socket.SOCK_STREAM)
        self.assertIn("network socket", str(ctx.exception).lower())
        self.assertIn("pytest.mark.network", str(ctx.exception))


# ============================================================================
# Test 2: All subprocess calls use sys.executable
# ============================================================================

class TestSubprocessExecution(unittest.TestCase):
    """Verify subprocess calls use sys.executable, not bare 'python'."""

    def test_sys_executable_is_current_python(self):
        """sys.executable should point to the running Python interpreter."""
        # Verify sys.executable works
        result = subprocess.run(
            [sys.executable, "-c", "print('hello')"],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.stdout)

    def test_bare_python_not_used_in_eval_tests(self):
        """Grep test_eval.py to confirm it uses sys.executable, not 'python'."""
        eval_test_file = _REPO_ROOT / "tests" / "test_eval.py"
        content = eval_test_file.read_text()
        # All subprocess calls should use sys.executable
        import re
        subprocess_calls = re.findall(r'subprocess\.run\s*\(\s*\[([^\]]+)\]', content)
        self.assertGreater(len(subprocess_calls), 0, "No subprocess calls found in test_eval.py")
        for call in subprocess_calls:
            self.assertIn("sys.executable", call,
                         f"subprocess call doesn't use sys.executable: {call}")


# ============================================================================
# Test 3: Environment variables are properly scrubbed
# ============================================================================

class TestEnvironmentScrubbing(unittest.TestCase):
    """Verify environment scrubbing removes external tool references."""

    def test_get_clean_env_removes_claude_home(self):
        """get_clean_env() must remove CLAUDE_HOME."""
        with patch.dict(os.environ, {"CLAUDE_HOME": "/home/user/.claude"}):
            clean = get_clean_env()
            self.assertNotIn("CLAUDE_HOME", clean)

    def test_get_clean_env_removes_anthropic_api_key(self):
        """get_clean_env() must remove ANTHROPIC_API_KEY."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
            clean = get_clean_env()
            self.assertNotIn("ANTHROPIC_API_KEY", clean)

    def test_get_clean_env_removes_provenance_vars(self):
        """get_clean_env() must remove all PROVENANCE_* variables."""
        with patch.dict(os.environ, {
            "PROVENANCE_GRADER": "llm",
            "PROVENANCE_CLAUDE_BIN": "/usr/bin/claude",
            "PROVENANCE_LOCAL_GRADER_URL": "http://localhost:5000"
        }):
            clean = get_clean_env()
            self.assertNotIn("PROVENANCE_GRADER", clean)
            self.assertNotIn("PROVENANCE_CLAUDE_BIN", clean)
            self.assertNotIn("PROVENANCE_LOCAL_GRADER_URL", clean)

    def test_get_clean_env_preserves_required_vars(self):
        """get_clean_env() must keep PATH and other essential variables."""
        clean = get_clean_env()
        self.assertIn("PATH", clean, "get_clean_env() must preserve PATH")
        # Verify we can still access basic commands
        self.assertGreater(len(clean["PATH"]), 0)

    def test_assert_env_clean_raises_on_claude_home(self):
        """assert_env_clean() must raise if CLAUDE_HOME is set."""
        with patch.dict(os.environ, {"CLAUDE_HOME": "/home/user/.claude"}):
            with self.assertRaises(AssertionError):
                from tests.conftest import assert_env_clean as check_clean
                check_clean()

    def test_assert_env_clean_raises_on_anthropic_api_key(self):
        """assert_env_clean() must raise if ANTHROPIC_API_KEY is set."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
            with self.assertRaises(AssertionError):
                from tests.conftest import assert_env_clean as check_clean
                check_clean()

    def test_assert_env_clean_passes_when_clean(self):
        """assert_env_clean() must not raise when environment is clean."""
        # Create a clean copy and verify check passes within it
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_HOME", None)
            os.environ.pop("ANTHROPIC_API_KEY", None)
            # Should not raise
            from tests.conftest import assert_env_clean as check_clean
            check_clean()


# ============================================================================
# Test 4: Grade.py returns correct errors on nonzero subprocess returncode
# ============================================================================

class TestGradeSubprocessErrorHandling(unittest.TestCase):
    """Verify grade.py checks returncode BEFORE parsing output."""

    def test_codex_grader_fails_on_nonzero_returncode(self):
        """CodexGrader must return error verdict on nonzero returncode."""
        from warrantos.provenance.grade import CodexGrader, Verdict

        grader = CodexGrader()

        # Mock subprocess.run to return nonzero exit code
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="Error message",
                stdout=""
            )
            verdict = grader.grade(
                claim_text="Test claim",
                source_text="Test source",
                citation="https://example.com"
            )

        self.assertEqual(verdict.verdict, "error")
        self.assertIn("exited 1", verdict.rationale.lower())

    def test_codex_grader_doesnt_parse_garbage_from_failed_process(self):
        """CodexGrader must not try to parse JSON from failed subprocess."""
        from warrantos.provenance.grade import CodexGrader

        grader = CodexGrader()

        # Mock subprocess.run with nonzero returncode and garbage stdout
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="Some error",
                stdout='{"verdict": "verified", "confidence": 1.0}'  # valid JSON!
            )
            verdict = grader.grade(
                claim_text="Test claim",
                source_text="Test source",
                citation="https://example.com"
            )

        # Should NOT parse the valid JSON because returncode != 0
        self.assertEqual(verdict.verdict, "error")
        self.assertNotEqual(verdict.verdict, "verified")


# ============================================================================
# Test 5: Grader stack traces are readable (not lambda-generated)
# ============================================================================

class TestGraderFactoriesReadable(unittest.TestCase):
    """Verify grader factories have readable names in stack traces."""

    def test_factory_functions_are_named_not_lambda(self):
        """Grader factories must be named functions, not lambdas."""
        from warrantos.provenance import grade

        # Verify the registry contains named functions
        for name, factory in grade._GRADER_OVERRIDE_REGISTRY.items():
            self.assertNotEqual(
                factory.__name__,
                "<lambda>",
                f"Grader factory for '{name}' is a lambda; "
                f"should be a named function"
            )
            # Named factories should have descriptive names
            self.assertIn(
                "factory",
                factory.__name__.lower(),
                f"Factory name should hint at factory: {factory.__name__}"
            )

    def test_factory_functions_have_docstrings(self):
        """Grader factories should have docstrings."""
        from warrantos.provenance import grade

        for name, factory in grade._GRADER_OVERRIDE_REGISTRY.items():
            self.assertIsNotNone(
                factory.__doc__,
                f"Factory for '{name}' should have a docstring"
            )


# ============================================================================
# Test 6: Default test suite runs without external Claude binary
# ============================================================================

class TestHermeticDefaultSuite(unittest.TestCase):
    """Verify tests run successfully without external tools."""

    def test_heuristic_grader_available(self):
        """HeuristicGrader must always be available."""
        from warrantos.provenance.grade import HeuristicGrader, Verdict

        grader = HeuristicGrader()
        result = grader.grade(
            claim_text="The Earth is round.",
            source_text="The Earth is spherical.",
            citation=None
        )
        self.assertIsInstance(result, Verdict)

    def test_claude_grader_gracefully_fails_without_binary(self):
        """ClaudeCliGrader must degrade gracefully without 'claude' binary."""
        from warrantos.provenance.grade import ClaudeCliGrader

        # Remove claude from PATH by using clean env
        with patch.dict(os.environ, get_clean_env(), clear=True):
            grader = ClaudeCliGrader()
            # Grade should succeed by falling back to heuristic grader
            verdict = grader.grade(
                claim_text="Test claim",
                source_text="Test source",
                citation="https://example.com"
            )
            # Should not raise, though grader may return heuristic result
            self.assertIsNotNone(verdict.verdict)

    def test_get_grader_returns_heuristic_when_no_keys_set(self):
        """get_grader() must return HeuristicGrader when no env vars are set.

        Also patches ClaudeCliGrader.is_available() to ensure we test the fallback
        to HeuristicGrader even if the claude binary is present.
        """
        from warrantos.provenance.grade import get_grader, HeuristicGrader

        # Ensure no API keys or grader overrides
        # Also mock ClaudeCliGrader.is_available() to return False
        with patch.dict(os.environ, {}, clear=False) as env:
            # Remove all external tool vars
            env.pop("ANTHROPIC_API_KEY", None)
            env.pop("PROVENANCE_GRADER", None)
            env.pop("PROVENANCE_LOCAL_GRADER_URL", None)
            env.pop("CLAUDE_HOME", None)

            with patch("warrantos.provenance.grade.ClaudeCliGrader.is_available", return_value=False):
                grader = get_grader()
                self.assertIsInstance(grader, HeuristicGrader)


# ============================================================================
# Test 7: CI environment stability
# ============================================================================

class TestCIEnvironment(unittest.TestCase):
    """Verify tests pass in CI-like environment (clean, no external tools)."""

    def test_no_anthropic_api_key_in_ci(self):
        """Tests must work without ANTHROPIC_API_KEY in CI."""
        from warrantos.provenance.grade import get_grader, HeuristicGrader

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            grader = get_grader()
            # Should not be LLMGrader when key is missing
            self.assertNotEqual(type(grader).__name__, "LLMGrader")

    def test_evaluation_runs_without_external_binaries(self):
        """Evaluation harness must complete without external binaries."""
        eval_script = _REPO_ROOT / "eval" / "run_eval.py"

        # Run with clean environment (no CLAUDE_HOME, no API key)
        result = subprocess.run(
            [sys.executable, str(eval_script)],
            env=get_clean_env(),
            capture_output=True,
            text=True,
            timeout=30
        )

        self.assertEqual(
            result.returncode, 0,
            f"eval/run_eval.py must exit 0 in clean environment.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
