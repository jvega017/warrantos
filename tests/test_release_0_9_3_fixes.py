#!/usr/bin/env python3
"""Regression tests for the 0.9.3 correctness/packaging fixes.

Stdlib only, offline, deterministic. Run from the repo root:

    python -m unittest tests.test_release_0_9_3_fixes -v

Each test pins a specific fix so it cannot silently regress:
  - version single-source-of-truth (packaged metadata == module __version__)
  - WARRANTOS_DB actually sets the `check --db` default
  - `warrantos --version` prints the version
  - `warrantos demo` runs the bundled honest demo and returns a BLOCK verdict
  - the CLI no longer crashes writing non-Latin-1 report content on a cp1252
    console (the Windows UnicodeEncodeError fixed by the UTF-8 reconfigure)
"""

import io
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import warrantos
from warrantos.cli import warrantos_cli


class TestVersionSingleSource(unittest.TestCase):
    def test_packaged_metadata_matches_module(self):
        # The 0.9.1/0.9.3 desync this release fixes: pyproject now reads the
        # version dynamically from warrantos.__version__, so the two must agree.
        # Skip cleanly when the package is not installed (source-tree-only run).
        from importlib import metadata
        try:
            packaged = metadata.version("warrantos")
        except metadata.PackageNotFoundError:
            self.skipTest("warrantos is not installed; metadata unavailable")
        self.assertEqual(packaged, warrantos.__version__)

    def test_wheel_declares_browser_verifier_data_files(self):
        root = Path(__file__).resolve().parents[1]
        configuration = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        data_files = configuration["tool"]["setuptools"]["data-files"]
        self.assertEqual(
            data_files["share/warrantos/web"],
            ["web/verify.html", "web/README.md"],
        )


class TestWarrantosDbEnvDefault(unittest.TestCase):
    def test_env_var_sets_check_db_default(self):
        sentinel = str(Path("custom-dir") / "ledger.db")
        old = os.environ.get("WARRANTOS_DB")
        os.environ["WARRANTOS_DB"] = sentinel
        try:
            parser = warrantos_cli.build_parser()
            args = parser.parse_args(["check", "draft.md"])
        finally:
            if old is None:
                os.environ.pop("WARRANTOS_DB", None)
            else:
                os.environ["WARRANTOS_DB"] = old
        self.assertEqual(args.db, sentinel)


class TestVersionFlag(unittest.TestCase):
    def test_version_flag_prints_version(self):
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            with self.assertRaises(SystemExit) as ctx:
                warrantos_cli.main(["--version"])
        finally:
            sys.stdout = old
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(warrantos.__version__, buf.getvalue())


class TestDemoCommand(unittest.TestCase):
    def test_demo_returns_block(self):
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "retained demo with spaces"
            try:
                rc = warrantos_cli.main(["demo", "--output", str(output)])
            finally:
                sys.stdout = old
            self.assertTrue((output / "demo.warrant").is_file())
            self.assertTrue((output / "draft.md").is_file())
            self.assertEqual(len(list((output / ".warrant" / "runs").iterdir())), 1)
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("BLOCK", out)
        self.assertIn("OVERALL:   VALID", out)
        self.assertIn("Retained demo:", out)
        # The bundled demo must surface the unsupported-claim signal, not just
        # boundary residue, so it stays a faithful end-to-end demonstration.
        self.assertIn("claims detected", out)

    def test_demo_refuses_to_mix_with_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "existing"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                warrantos_cli.main(["demo", "--output", str(output)])
            self.assertEqual(list(output.iterdir()), [])


class TestUnicodeReportNoCrash(unittest.TestCase):
    def test_non_latin1_content_does_not_crash_on_cp1252_stream(self):
        # Reproduces the Windows crash: a cp1252 stdout plus a report containing
        # a Greek tau and maths symbols. The UTF-8 reconfigure in main() must
        # flip the stream so the write succeeds instead of raising
        # UnicodeEncodeError. Without the fix this test raises.
        # A BLOCK draft: the assistant-opener residue is echoed back in the
        # report excerpt, so the non-Latin-1 characters (tau, the maths symbols,
        # the accented vowels) are actually written to the cp1252 stream.
        draft_text = (
            "Certainly! The bound is τ ≤ 0.5 ≥ 0 for the naïve café model.\n"
        )
        original_cwd = os.getcwd()
        original_stdout = sys.stdout
        with tempfile.TemporaryDirectory(prefix="warrantos-unicode-") as tmp:
            tmp_path = Path(tmp)
            draft = tmp_path / "draft.md"
            draft.write_text(draft_text, encoding="utf-8")
            sink = io.BytesIO()
            cp1252_stream = io.TextIOWrapper(sink, encoding="cp1252", newline="")
            try:
                os.chdir(tmp_path)
                sys.stdout = cp1252_stream
                rc = warrantos_cli.main(
                    ["check", "draft.md", "--profile", "final-prose"]
                )
                cp1252_stream.flush()
            finally:
                sys.stdout = original_stdout
                os.chdir(original_cwd)
        # The run completed without raising UnicodeEncodeError.
        self.assertIsInstance(rc, int)
        # The fix: main() reconfigured the cp1252 stream to UTF-8. Without it,
        # the stream stays cp1252 and a non-Latin-1 write raises.
        self.assertEqual(cp1252_stream.encoding, "utf-8")
        # Prove the reconfigured stream now genuinely accepts non-Latin-1 output.
        cp1252_stream.write("τ ≤ 0.5\n")
        cp1252_stream.flush()
        emitted = sink.getvalue().decode("utf-8", errors="replace")
        self.assertIn("≤", emitted)


if __name__ == "__main__":
    unittest.main()
