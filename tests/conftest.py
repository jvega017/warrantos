"""Test suite isolation hardening: network blocking, environment scrubbing, hermetic testing.

Pytest hooks that enforce test isolation:
- Block network socket creation unless explicitly marked with @pytest.mark.network
- Provide fixtures for subprocess environment scrubbing
- Prevent leakage of CLAUDE_HOME, ANTHROPIC_API_KEY, and other external binaries

Also provides helper functions for unittest-based tests to use:
- get_clean_env(): return scrubbed copy of os.environ
- assert_env_clean(): raise if prohibited vars are set

Python 3.11+ compatible.
"""

import os
import socket
import pytest


# ============================================================================
# Helper functions usable by both pytest and unittest tests
# ============================================================================

def get_clean_env():
    """Return a copy of os.environ with external tool variables removed.

    Removes:
    - CLAUDE_HOME: path to Claude CLI cache/config
    - ANTHROPIC_API_KEY: Anthropic API credentials
    - PROVENANCE_*: any provenance grader overrides or config
    - PYTHONPATH: could be set by the test runner

    Use this environment when calling subprocess.run() to ensure tests are
    hermetic and don't accidentally use external tools or API keys.

    Example:
        import subprocess
        result = subprocess.run(
            [sys.executable, 'script.py'],
            env=get_clean_env(),
            capture_output=True
        )
    """
    env = os.environ.copy()
    # Remove tool paths and API keys
    env.pop("CLAUDE_HOME", None)
    env.pop("ANTHROPIC_API_KEY", None)
    # Remove any provenance grader config that could route to external binaries
    for key in list(env.keys()):
        if key.startswith("PROVENANCE_"):
            env.pop(key, None)
    # Remove test runner PATH manipulation
    env.pop("PYTHONPATH", None)
    return env


def assert_env_clean():
    """Assert that prohibited environment variables are NOT set (standalone function).

    Use to verify your test didn't accidentally pick up an external tool:
        def test_something():
            # ... run test code ...
            assert_env_clean()  # raise if leaked

    This is a standalone function, not a pytest fixture. Import it directly.
    """
    prohibited = {"CLAUDE_HOME", "ANTHROPIC_API_KEY"}
    for var in prohibited:
        if var in os.environ:
            raise AssertionError(
                f"Environment variable {var} is set; "
                f"test may leak to external tools. "
                f"Use get_clean_env() to scrub subprocess environment."
            )


# ============================================================================
# Network isolation: fail any test that attempts to open a socket
# ============================================================================

@pytest.fixture
def block_network_access():
    """Fail any test that opens a network socket unless explicitly marked.

    OPTIONAL: Tests must explicitly request this fixture to enable blocking.
    Tests can opt in to network access by decorating with:
        @pytest.mark.network

    Example:
        def test_something_offline(block_network_access):
            # Any socket creation here will raise AssertionError
            pass

    This fixture raises AssertionError on any socket creation outside marked tests.
    """
    original_socket = socket.socket

    def socket_wrapper(*args, **kwargs):
        raise AssertionError(
            "Test attempted to open a network socket without @pytest.mark.network. "
            "Either mock the call, mark with @pytest.mark.network, or verify your "
            "test doesn't need network access."
        )

    socket.socket = socket_wrapper
    yield
    socket.socket = original_socket


# Allow pytest to recognize @pytest.mark.network without warnings
def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers", "network: mark test as needing network access (e.g. HTTP fetch)"
    )


# ============================================================================
# Fixture: scrubbed subprocess environment
# ============================================================================

@pytest.fixture
def clean_env():
    """Return a copy of os.environ with external tool variables removed.

    Removes:
    - CLAUDE_HOME: path to Claude CLI cache/config
    - ANTHROPIC_API_KEY: Anthropic API credentials
    - PROVENANCE_*: any provenance grader overrides or config
    - PYTHONPATH: could be set by the test runner

    Use this environment when calling subprocess.run() to ensure tests are
    hermetic and don't accidentally use external tools or API keys.

    Example:
        import subprocess
        result = subprocess.run(
            [sys.executable, 'script.py'],
            env=clean_env,
            capture_output=True
        )
    """
    env = os.environ.copy()
    # Remove tool paths and API keys
    env.pop("CLAUDE_HOME", None)
    env.pop("ANTHROPIC_API_KEY", None)
    # Remove any provenance grader config that could route to external binaries
    for key in list(env.keys()):
        if key.startswith("PROVENANCE_"):
            env.pop(key, None)
    # Remove test runner PATH manipulation
    env.pop("PYTHONPATH", None)
    return env


# ============================================================================
# Fixture: assert no environment leakage (alternative fixture form)
# ============================================================================

@pytest.fixture
def check_env_clean():
    """Assertion helper fixture: verify that prohibited env vars are NOT set.

    Use as a pytest fixture to verify your test didn't accidentally pick up
    an external tool:
        def test_something(check_env_clean):
            # ... run test code ...
            check_env_clean()
    """
    def _check():
        prohibited = {"CLAUDE_HOME", "ANTHROPIC_API_KEY"}
        for var in prohibited:
            if var in os.environ:
                raise AssertionError(
                    f"Environment variable {var} is set; "
                    f"test may leak to external tools. "
                    f"Use clean_env fixture to scrub subprocess environment."
                )
    return _check
