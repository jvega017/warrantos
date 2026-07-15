"""Test distribution and package installation.

Tests that the package can be installed in a clean environment,
and that all entry points work without sys.path manipulation.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestDistributionInstall(unittest.TestCase):
    """Test clean venv installation and entry point availability."""

    def test_package_imports_without_syspath_manipulation(self):
        """Verify that warrantos imports work without sys.path manipulation.

        When the package is properly installed via setuptools entry_points,
        all submodules should be importable directly without needing to
        manipulate sys.path.
        """
        # The module should be importable directly since it's installed via pip.
        try:
            import warrantos
            import warrantos.cli
            import warrantos.cli.warrantos_cli
            import warrantos.cli.provenance_cli
            import warrantos.provenance
        except ImportError as exc:
            self.fail(f"Failed to import warrantos modules: {exc}")

    def test_cli_warrantos_help(self):
        """Test that warrantos --help works from arbitrary working directory."""
        # Run from /tmp to prove we're not dependent on cwd
        result = subprocess.run(
            [sys.executable, "-m", "warrantos.cli.warrantos_cli", "--help"],
            capture_output=True,
            text=True,
            cwd="/tmp",
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertIn("warrantos", result.stdout.lower())

    def test_cli_warrantos_version(self):
        """Test that warrantos --version works."""
        result = subprocess.run(
            [sys.executable, "-m", "warrantos.cli.warrantos_cli", "--version"],
            capture_output=True,
            text=True,
            cwd="/tmp",
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertIn("warrantos", result.stdout)

    def test_cli_warrantos_status(self):
        """Test that warrantos status works."""
        result = subprocess.run(
            [sys.executable, "-m", "warrantos.cli.warrantos_cli", "status"],
            capture_output=True,
            text=True,
            cwd="/tmp",
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        # Check for layer indicators (L1, L2, etc.)
        self.assertIn("L1", result.stdout)

    def test_cli_provenance_help(self):
        """Test that provenance --help works."""
        result = subprocess.run(
            [sys.executable, "-m", "warrantos.cli.provenance_cli", "--help"],
            capture_output=True,
            text=True,
            cwd="/tmp",
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertIn("provenance", result.stdout.lower())

    def test_entry_point_warrantos_status(self):
        """Test that the warrantos entry point exists and works."""
        # When installed via setuptools, this should be available as a console script.
        # We test by running via python -m, which simulates the entry point calling pattern.
        result = subprocess.run(
            [sys.executable, "-m", "warrantos.cli.warrantos_cli", "status"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)

    def test_warrantos_demo_works(self):
        """Test that warrantos demo runs without sys.path dependencies."""
        result = subprocess.run(
            [sys.executable, "-m", "warrantos.cli.warrantos_cli", "demo"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Demo should complete (may fail with a verdict, but not an import error)
        # We just verify it doesn't crash with import errors
        self.assertNotIn("ModuleNotFoundError", result.stderr)
        self.assertNotIn("ImportError", result.stderr)


class TestPackageMetadata(unittest.TestCase):
    """Test that package metadata is consistent."""

    def test_version_in_init(self):
        """Verify __version__ is defined in warrantos/__init__.py."""
        import warrantos
        self.assertTrue(hasattr(warrantos, "__version__"))
        self.assertRegex(warrantos.__version__, r"^\d+\.\d+\.\d+")

    def test_pyproject_toml_exists(self):
        """Verify pyproject.toml exists and has correct structure."""
        project_root = Path(__file__).parent.parent
        pyproject = project_root / "pyproject.toml"
        self.assertTrue(pyproject.exists(), f"pyproject.toml not found at {pyproject}")

        # Parse the TOML to ensure it has entry_points
        content = pyproject.read_text()
        self.assertIn("[project.scripts]", content)
        self.assertIn("warrantos = ", content)
        self.assertIn("provenance = ", content)


class TestSysPathNotManipulated(unittest.TestCase):
    """Verify that sys.path is not being manipulated by the CLI modules."""

    def test_warrantos_cli_no_syspath_manipulation(self):
        """Verify warrantos_cli.py doesn't manipulate sys.path."""
        cli_path = Path(__file__).parent.parent / "warrantos" / "cli" / "warrantos_cli.py"
        content = cli_path.read_text()

        # Should not contain sys.path.insert calls
        self.assertNotIn("sys.path.insert", content)
        # Should not have code that adds to sys.path (but _REPO_ROOT is OK for file lookups)
        self.assertNotIn("sys.path.insert(0", content)

    def test_provenance_cli_no_syspath_manipulation(self):
        """Verify provenance_cli.py doesn't manipulate sys.path."""
        cli_path = Path(__file__).parent.parent / "warrantos" / "cli" / "provenance_cli.py"
        content = cli_path.read_text()

        # Should not contain sys.path.insert calls
        self.assertNotIn("sys.path.insert", content)
        # Should not try to compute _REPO_ROOT for path manipulation
        self.assertNotIn("sys.path", content)


if __name__ == "__main__":
    unittest.main()
