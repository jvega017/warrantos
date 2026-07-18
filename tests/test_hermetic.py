#!/usr/bin/env python3
"""Hermetic-suite enforcement tests.

Three guarantees, each enforced here rather than promised in prose:

1. ``get_clean_env()`` really scrubs every external-tool variable
   (CLAUDE_HOME, API keys, PROVENANCE_* overrides) while preserving
   PATH/HOME, so subprocesses run the default offline configuration.

2. Every real ``subprocess.run(...)`` / ``subprocess.Popen(...)`` call
   in the test suite passes an explicit ``env=`` keyword. Audited with
   an AST scan so a new test that forgets the rule fails CI on every
   platform, not just under the Linux booby-trap job.

3. A booby-trap ``claude`` shim placed first on PATH is never invoked
   by the representative offline pipeline (the eval harness). CI runs
   the whole suite under the same trap (.github/workflows/ci.yml,
   ``hermetic`` job); this test keeps a fast local version of the
   check so developers see the failure before pushing.
"""

import ast
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from conftest import (
        assert_env_clean,
        get_clean_env,
        scrubbed_names,
        scrubbed_prefixes,
    )
except ImportError:  # running as tests.test_* from the repo root
    from tests.conftest import (
        assert_env_clean,
        get_clean_env,
        scrubbed_names,
        scrubbed_prefixes,
    )

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent

_SUBPROCESS_LAUNCHERS = {"run", "Popen", "check_output", "check_call", "call"}


class TestGetCleanEnv(unittest.TestCase):
    """The scrubbed environment removes credentials and overrides."""

    def test_removes_exact_names(self):
        for name in scrubbed_names():
            with self.subTest(var=name):
                os.environ.setdefault(name, "sentinel")
                try:
                    env = get_clean_env()
                    self.assertNotIn(name, env)
                finally:
                    if os.environ.get(name) == "sentinel":
                        del os.environ[name]

    def test_removes_prefixed_names(self):
        probes = [p + "PROBE_LEAK" for p in scrubbed_prefixes()]
        for name in probes:
            os.environ[name] = "sentinel"
        try:
            env = get_clean_env()
            for name in probes:
                with self.subTest(var=name):
                    self.assertNotIn(name, env)
        finally:
            for name in probes:
                os.environ.pop(name, None)

    def test_preserves_path_and_home(self):
        env = get_clean_env()
        self.assertIn("PATH", env)
        # HOME is absent on some Windows shells; only assert it survives
        # scrubbing when the parent process has it.
        if "HOME" in os.environ:
            self.assertIn("HOME", env)

    def test_assert_env_clean_accepts_scrubbed(self):
        assert_env_clean(get_clean_env())

    def test_assert_env_clean_rejects_leak(self):
        env = get_clean_env()
        env["ANTHROPIC_API_KEY"] = "sk-leak"
        with self.assertRaises(AssertionError):
            assert_env_clean(env)


class TestSubprocessEnvAudit(unittest.TestCase):
    """AST audit: every subprocess launch in tests/ passes env=.

    Mocked launches (``patch("subprocess.run", ...)``) are string
    arguments, not Call nodes on the subprocess module, so they do not
    trip the audit.
    """

    def _violations_in(self, path: Path):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr in _SUBPROCESS_LAUNCHERS
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                continue
            keywords = {kw.arg for kw in node.keywords}
            if "env" not in keywords:
                violations.append("%s:%d" % (path.name, node.lineno))
        return violations

    def test_every_subprocess_call_passes_env(self):
        violations = []
        for path in sorted(_TESTS_DIR.glob("test_*.py")):
            violations.extend(self._violations_in(path))
        self.assertEqual(
            violations,
            [],
            "subprocess launches without env= (use env=get_clean_env() "
            "from conftest, adding back only the variables the test "
            "deliberately sets): %s" % violations,
        )


class TestClaudeShimNeverCalled(unittest.TestCase):
    """A booby-trap `claude` first on PATH is never invoked offline."""

    @unittest.skipIf(os.name == "nt", "POSIX shim; CI covers Linux/macOS")
    def test_eval_harness_never_invokes_claude(self):
        with tempfile.TemporaryDirectory() as td:
            trap_dir = Path(td)
            calls_log = trap_dir / "claude-calls.log"
            shim = trap_dir / "claude"
            shim.write_text(
                "#!/bin/sh\n"
                'echo "$@" >> "%s"\n'
                "exit 97\n" % calls_log,
                encoding="utf-8",
            )
            shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            env = get_clean_env()
            env["PATH"] = str(trap_dir) + os.pathsep + env.get("PATH", "")

            proc = subprocess.run(
                [sys.executable, str(_REPO_ROOT / "eval" / "run_eval.py")],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(_REPO_ROOT),
                timeout=300,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertFalse(
                calls_log.exists(),
                "the eval harness invoked the external `claude` binary: %s"
                % (calls_log.read_text(encoding="utf-8") if calls_log.exists() else ""),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
