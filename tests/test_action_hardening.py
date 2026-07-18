#!/usr/bin/env python3
"""Regression tests for the hardened GitHub Action (action.yml).

Issue 5 (Phase 2 P1): the composite action must never interpolate
`${{ inputs.* }}` into a shell `run:` block (shell injection), must
parse the newline-delimited `paths` input safely (spaced filenames,
multi-path inputs), and must install warrantos with
`pip install --require-hashes` against the committed
action-requirements.txt lock file.

The bash parsing loop is executed for real here (against a recording
`warrantos` shim) so the quoting behaviour is tested, not assumed. The
end-to-end workflow leg lives in .github/workflows/ci.yml
(`action-integration` job).
"""

import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    from conftest import get_clean_env
except ImportError:  # running as tests.test_* from the repo root
    from tests.conftest import get_clean_env

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ACTION = _REPO_ROOT / "action.yml"
_LOCK = _REPO_ROOT / "action-requirements.txt"


def _run_blocks(text):
    """Yield (step_start_line, block_text) for each run: | block scalar."""
    lines = text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)run:\s*\|", lines[i])
        if not m:
            # A single-line run: is also a run block.
            m1 = re.match(r"^(\s*)run:\s*(\S.*)$", lines[i])
            if m1 and not m1.group(2).startswith("|"):
                blocks.append((i + 1, m1.group(2)))
            i += 1
            continue
        indent = len(m.group(1))
        body = []
        j = i + 1
        while j < len(lines):
            line = lines[j]
            if line.strip() == "":
                body.append("")
                j += 1
                continue
            if len(line) - len(line.lstrip()) <= indent:
                break
            body.append(line)
            j += 1
        blocks.append((i + 1, "\n".join(body)))
        i = j
    return blocks


class TestNoInputInterpolationInRunBlocks(unittest.TestCase):
    """No `${{ ... }}` expression may appear inside any run: block."""

    def test_run_blocks_are_expression_free(self):
        text = _ACTION.read_text(encoding="utf-8")
        offenders = []
        for lineno, block in _run_blocks(text):
            if "${{" in block:
                offenders.append("run block at line %d" % lineno)
        self.assertEqual(
            offenders,
            [],
            "action.yml interpolates a workflow expression inside a shell "
            "run block (shell-injection surface). Pass inputs via env: "
            "instead: %s" % offenders,
        )

    def test_inputs_only_reach_shell_via_env_or_with(self):
        """Every `${{ inputs.* }}` occurrence is an env: value, an if:
        condition, or a with: value - never shell text."""
        for lineno, line in enumerate(
            _ACTION.read_text(encoding="utf-8").splitlines(), 1
        ):
            if "${{ inputs." not in line:
                continue
            ok = re.match(
                r"^\s*("
                r"#"  # documentation comment
                r"|if:"  # step condition (not shell)
                r"|[A-Z][A-Z0-9_]*:"  # env: variable assignment
                r"|python-version:"  # with: value for setup-python
                r")",
                line,
            )
            self.assertIsNotNone(
                ok,
                "action.yml line %d passes an input somewhere other than "
                "env:/if:/with: %r" % (lineno, line),
            )


class TestRequireHashesInstall(unittest.TestCase):
    """The action's pip install is version- and hash-pinned."""

    def test_install_step_uses_require_hashes(self):
        text = _ACTION.read_text(encoding="utf-8")
        self.assertIn("--require-hashes", text)
        self.assertIn("action-requirements.txt", text)
        self.assertNotIn(
            "pip install --upgrade pip warrantos",
            text,
            "unpinned `pip install warrantos` reintroduced",
        )

    def test_lock_file_pins_warrantos_with_hashes(self):
        self.assertTrue(_LOCK.is_file(), "action-requirements.txt missing")
        text = _LOCK.read_text(encoding="utf-8")
        # Logical requirement lines (continuation-joined), comments stripped.
        logical = re.sub(r"\\\n", " ", text)
        req_lines = [
            ln.strip()
            for ln in logical.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        self.assertTrue(req_lines, "lock file has no requirement lines")
        pinned = [ln for ln in req_lines if ln.startswith("warrantos==")]
        self.assertEqual(
            len(pinned), 1, "lock file must pin exactly one warrantos version"
        )
        for ln in req_lines:
            self.assertIn(
                "==", ln.split("--hash")[0],
                "unpinned requirement in lock file: %r" % ln,
            )
            self.assertIn(
                "--hash=sha256:", ln,
                "requirement without sha256 hash in lock file: %r" % ln,
            )


@unittest.skipIf(shutil.which("bash") is None, "bash not available")
class TestPathsParsingLoop(unittest.TestCase):
    """Execute the action's real slop run block against a recording shim."""

    def _extract_slop_script(self):
        text = _ACTION.read_text(encoding="utf-8")
        blocks = [b for _, b in _run_blocks(text) if "warrantos slop" in b]
        self.assertEqual(len(blocks), 1, "expected exactly one slop run block")
        # Dedent the block scalar.
        lines = [ln for ln in blocks[0].splitlines()]
        indents = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
        cut = min(indents)
        return "\n".join(ln[cut:] if ln.strip() else "" for ln in lines)

    def _run_script(self, paths_value, fail_over="0"):
        script = self._extract_slop_script()
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            argv_log = tdir / "argv.log"
            shim = tdir / "warrantos"
            shim.write_text(
                "#!/bin/sh\n"
                'for a in "$@"; do printf \'%%s\\n\' "$a"; done > "%s"\n'
                "exit 0\n" % argv_log,
                encoding="utf-8",
            )
            shim.chmod(
                shim.stat().st_mode
                | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            )
            env = get_clean_env()
            env["PATH"] = str(tdir) + os.pathsep + env.get("PATH", "")
            env["WARRANTOS_INPUT_PATHS"] = paths_value
            env["WARRANTOS_INPUT_FAIL_OVER"] = fail_over
            proc = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            argv = (
                argv_log.read_text(encoding="utf-8").splitlines()
                if argv_log.exists()
                else []
            )
            return proc, argv

    def test_spaced_filenames_and_multi_path_stay_intact(self):
        proc, argv = self._run_script(
            "/tmp/action it/file with space.md\n/tmp/action it/dir with space\n"
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(
            argv,
            [
                "slop",
                "/tmp/action it/file with space.md",
                "/tmp/action it/dir with space",
                "--fail-over",
                "0",
            ],
        )

    def test_injection_string_is_one_literal_argument(self):
        proc, argv = self._run_script("README.md; touch /tmp/pwned")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(
            argv,
            ["slop", "README.md; touch /tmp/pwned", "--fail-over", "0"],
            "the injection payload must arrive as ONE literal argv entry",
        )

    def test_empty_input_defaults_to_current_directory(self):
        proc, argv = self._run_script("")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(argv, ["slop", ".", "--fail-over", "0"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
