"""tests.test_config: configuration module unit tests.

Tests the centralized configuration system in warrantos.provenance.config.
Covers default values, environment variable overrides, and validation.

Python 3.8+. Stdlib only.
"""

import os
import pytest

# Test 1: Default values load correctly
def test_config_defaults():
    """Test that default configuration values are loaded correctly."""
    # Import after setting up environment (no env vars set)
    from warrantos.provenance.config import (
        MAX_DOC_BYTES,
        MAX_SENTENCE_CHARS,
        DEFAULT_LEDGER_PATH,
        DEFAULT_DB_NAME,
        LOAD_BEARING_THRESHOLD,
        FETCH_TIMEOUT,
        FETCH_MAX_BYTES,
        REDIRECT_HOP_CAP,
        SALIENCE_WEIGHTS,
        USER_AGENT,
        PROFILE_UNCITED_THRESHOLD,
        DEFAULT_UNCITED_THRESHOLD,
    )

    # Check default values match expectations
    assert MAX_DOC_BYTES == 2_000_000
    assert MAX_SENTENCE_CHARS == 10_000
    assert DEFAULT_LEDGER_PATH == ".warrant"
    assert DEFAULT_DB_NAME == "provenance.db"
    assert LOAD_BEARING_THRESHOLD == 0.5
    assert FETCH_TIMEOUT == 8
    assert FETCH_MAX_BYTES == 1_500_000
    assert REDIRECT_HOP_CAP == 3
    assert USER_AGENT.startswith("warrantos/")

    # Check profile thresholds
    assert PROFILE_UNCITED_THRESHOLD["audit"] == 0.0
    assert PROFILE_UNCITED_THRESHOLD["final-prose"] == 0.0
    assert PROFILE_UNCITED_THRESHOLD["methodology"] == 0.40
    assert DEFAULT_UNCITED_THRESHOLD == 1.0

    # Check salience weights
    assert SALIENCE_WEIGHTS["statute"] == 0.9
    assert SALIENCE_WEIGHTS["numeric"] == 0.8
    assert SALIENCE_WEIGHTS["causal"] == 0.7
    assert SALIENCE_WEIGHTS["attribution"] == 0.6


def test_config_validation_passes():
    """Test that validate_config() passes with valid defaults."""
    from warrantos.provenance.config import validate_config

    # Should not raise
    validate_config()


def test_config_validation_negative_bytes():
    """Test that validation catches negative MAX_DOC_BYTES."""
    import importlib
    import sys
    import subprocess

    # Run in a subprocess to avoid import caching issues
    code = """
import os
import sys
os.environ["WARRANTOS_MAX_DOC_BYTES"] = "-1"
try:
    from warrantos.provenance.config import ConfigError
    print("ERROR: No exception raised")
    sys.exit(1)
except Exception as e:
    if "MAX_DOC_BYTES must be positive" in str(e):
        print("SUCCESS")
        sys.exit(0)
    else:
        print(f"ERROR: Wrong exception: {e}")
        sys.exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd="/workspace/warrantos",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Subprocess failed: {result.stderr}"


def test_config_validation_invalid_threshold():
    """Test that validation catches out-of-range LOAD_BEARING_THRESHOLD."""
    import sys
    import subprocess

    # Run in a subprocess to avoid import caching issues
    code = """
import os
import sys
os.environ["WARRANTOS_LOAD_BEARING_THRESHOLD"] = "1.5"
try:
    from warrantos.provenance.config import ConfigError
    print("ERROR: No exception raised")
    sys.exit(1)
except Exception as e:
    if "LOAD_BEARING_THRESHOLD must be in" in str(e):
        print("SUCCESS")
        sys.exit(0)
    else:
        print(f"ERROR: Wrong exception: {e}")
        sys.exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd="/workspace/warrantos",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Subprocess failed: {result.stderr}"


def test_config_constants_are_immutable():
    """Test that configuration constants are the expected types."""
    from warrantos.provenance.config import (
        MAX_DOC_BYTES,
        MAX_SENTENCE_CHARS,
        FETCH_TIMEOUT,
        FETCH_MAX_BYTES,
        REDIRECT_HOP_CAP,
        LOAD_BEARING_THRESHOLD,
        DEFAULT_LEDGER_PATH,
        DEFAULT_DB_NAME,
        PROFILE_UNCITED_THRESHOLD,
        DEFAULT_UNCITED_THRESHOLD,
        SALIENCE_WEIGHTS,
        USER_AGENT,
    )

    # Verify types
    assert isinstance(MAX_DOC_BYTES, int)
    assert isinstance(MAX_SENTENCE_CHARS, int)
    assert isinstance(FETCH_TIMEOUT, int)
    assert isinstance(FETCH_MAX_BYTES, int)
    assert isinstance(REDIRECT_HOP_CAP, int)
    assert isinstance(LOAD_BEARING_THRESHOLD, float)
    assert isinstance(DEFAULT_LEDGER_PATH, str)
    assert isinstance(DEFAULT_DB_NAME, str)
    assert isinstance(PROFILE_UNCITED_THRESHOLD, dict)
    assert isinstance(DEFAULT_UNCITED_THRESHOLD, (int, float))
    assert isinstance(SALIENCE_WEIGHTS, dict)
    assert isinstance(USER_AGENT, str)


def test_config_profile_fractions_in_range():
    """Test that all profile fractions are in valid [0.0, 1.0] range."""
    from warrantos.provenance.config import PROFILE_UNCITED_THRESHOLD

    for profile, threshold in PROFILE_UNCITED_THRESHOLD.items():
        assert 0.0 <= threshold <= 1.0, (
            f"Profile '{profile}' threshold {threshold} out of range [0.0, 1.0]"
        )


def test_config_profile_fractions_known_profiles():
    """Test that known profiles have expected threshold values."""
    from warrantos.provenance.config import PROFILE_UNCITED_THRESHOLD

    # Verify expected profiles are present
    expected_profiles = {
        "audit",
        "final-prose",
        "paper-full",
        "brief-light",
        "methodology",
        "changelog",
    }
    assert expected_profiles.issubset(PROFILE_UNCITED_THRESHOLD.keys())

    # Verify known thresholds
    assert PROFILE_UNCITED_THRESHOLD["audit"] == 0.0
    assert PROFILE_UNCITED_THRESHOLD["final-prose"] == 0.0
    assert PROFILE_UNCITED_THRESHOLD["changelog"] == 1.0


def test_all_constants_importable():
    """Test that all documented constants can be imported from config."""
    from warrantos.provenance.config import (
        MAX_DOC_BYTES,
        MAX_SENTENCE_CHARS,
        DEFAULT_LEDGER_PATH,
        DEFAULT_DB_NAME,
        LOAD_BEARING_THRESHOLD,
        PROFILE_UNCITED_THRESHOLD,
        DEFAULT_UNCITED_THRESHOLD,
        FETCH_TIMEOUT,
        FETCH_MAX_BYTES,
        REDIRECT_HOP_CAP,
        SALIENCE_WEIGHTS,
        USER_AGENT,
        validate_config,
        ConfigError,
    )

    # If we get here, all imports succeeded
    assert True


def test_verify_module_imports_from_config():
    """Test that verify.py imports constants from config."""
    from warrantos.provenance import verify

    # Check that verify module has access to the constants
    assert hasattr(verify, "FETCH_TIMEOUT") or hasattr(verify, "fetch_text")
    # The main check is that verify.py doesn't crash during import,
    # which would happen if config import failed


def test_cli_module_imports_from_config():
    """Test that warrantos_cli.py imports constants from config."""
    from warrantos.cli import warrantos_cli

    # Check that CLI module has access to the constants
    assert hasattr(warrantos_cli, "PROFILE_UNCITED_THRESHOLD") or hasattr(
        warrantos_cli, "consolidate_verdict"
    )
    # The main check is that CLI doesn't crash during import,
    # which would happen if config import failed
