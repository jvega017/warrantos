"""warrantos.provenance.config: centralized configuration management.

Defines all configuration constants with environment variable overrides and
validation. This module consolidates hardcoded values scattered across the
codebase (verify.py, warrantos_cli.py, salience.py) into a single source
of truth.

All constants support environment variable overrides for deployment flexibility.
Environment variables use the WARRANTOS_ prefix and are validated on import.

Provides:
    Constants:
        MAX_DOC_BYTES          -- max document size (ReDoS/memory protection)
        MAX_SENTENCE_CHARS     -- max sentence length
        DEFAULT_LEDGER_PATH    -- default .warrant directory
        DEFAULT_DB_NAME        -- default database filename
        LOAD_BEARING_THRESHOLD -- claim salience threshold (0-1)
        PROFILE_FRACTIONS      -- per-profile verdict thresholds
        FETCH_TIMEOUT          -- HTTP fetch timeout (seconds)
        FETCH_MAX_BYTES        -- max fetch response size
        REDIRECT_HOP_CAP       -- max HTTP redirects to follow
        SALIENCE_WEIGHTS       -- claim scoring weights
        USER_AGENT             -- HTTP User-Agent string

    Functions:
        validate_config()      -- validate all configuration on load

No third-party dependencies. Python 3.8+.
Australian English throughout.
"""

import os
from typing import Dict
from warrantos import __version__

# ---------------------------------------------------------------------------
# Input limits (prevent ReDoS/memory exhaustion)
# ---------------------------------------------------------------------------

#: Maximum document size in bytes. Prevents memory exhaustion from
#: pathologically large inputs.
MAX_DOC_BYTES = int(os.getenv('WARRANTOS_MAX_DOC_BYTES', 2_000_000))

#: Maximum sentence length in characters. Prevents ReDoS attacks in
#: regex patterns that operate on sentence-level text.
MAX_SENTENCE_CHARS = int(os.getenv('WARRANTOS_MAX_SENTENCE_CHARS', 10_000))

# ---------------------------------------------------------------------------
# Storage paths
# ---------------------------------------------------------------------------

#: Default ledger directory (relative to project root). Can be overridden
#: via WARRANTOS_LEDGER_PATH environment variable.
DEFAULT_LEDGER_PATH = os.getenv('WARRANTOS_LEDGER_PATH', '.warrant')

#: Default database filename within the ledger directory. Can be overridden
#: via WARRANTOS_DB_NAME environment variable.
DEFAULT_DB_NAME = os.getenv('WARRANTOS_DB_NAME', 'provenance.db')

# ---------------------------------------------------------------------------
# Salience and claim assessment
# ---------------------------------------------------------------------------

#: Minimum salience score (0.0-1.0) for a claim to be considered load-bearing.
#: Claims scoring >= this threshold are flagged for mandatory citation.
#: Chosen to include statute/section references, large-magnitude numbers,
#: and decision-language sentences while excluding bare year mentions.
LOAD_BEARING_THRESHOLD = float(os.getenv('WARRANTOS_LOAD_BEARING_THRESHOLD', 0.5))

#: Per-profile uncited-claim fraction thresholds (Phase 1 item 3).
#: When the fraction of detected claims that are uncited (no citation present)
#: exceeds the profile threshold, the verdict is raised to HOLD even when no
#: single claim is load-bearing. This closes the bug where an audit run with
#: 2 of 2 claims uncited could return a bare PASS (the audit profile suppresses
#: the boundary gate, and neither claim alone was load-bearing).
#:
#: Phase 1 fix M1: renamed from "unsupported" to "uncited" to distinguish
#: citation presence (uncited) from verification result (supported/contradicted).
#:
#:   audit         0.00  any uncited claim HOLDs
#:   final-prose   0.00  backstop: any uncited claim HOLDs
#:   paper-full    0.20  tolerates a small uncited minority
#:   brief-light   0.25  tolerates routine date references etc.
#:   methodology   0.40  methods prose is allowed more uncited statement
#:   changelog     1.00  never fires on fraction alone
#:
#: Profiles without an explicit entry use the default (lenient: never fires
#: on fraction alone, preserving prior behaviour for prompt-template and the
#: other process profiles).
PROFILE_UNCITED_THRESHOLD: Dict[str, float] = {
    'audit': 0.0,
    'final-prose': 0.0,
    'paper-full': 0.20,
    'brief-light': 0.25,
    'methodology': 0.40,
    'changelog': 1.0,
}

# Default threshold for profiles not explicitly listed (lenient: never fires).
DEFAULT_UNCITED_THRESHOLD = 1.0

# ---------------------------------------------------------------------------
# Network I/O configuration
# ---------------------------------------------------------------------------

#: HTTP request timeout in seconds. Controls how long to wait for a single
#: fetch_text() operation before giving up. Can be overridden via
#: WARRANTOS_FETCH_TIMEOUT environment variable.
FETCH_TIMEOUT = int(os.getenv('WARRANTOS_FETCH_TIMEOUT', 8))

#: Maximum response size in bytes for fetch_text(). Protects against
#: excessive memory use when fetching remote content. Can be overridden via
#: WARRANTOS_FETCH_MAX_BYTES environment variable.
FETCH_MAX_BYTES = int(os.getenv('WARRANTOS_FETCH_MAX_BYTES', 1_500_000))

#: Maximum number of HTTP redirects to follow in fetch_text(). Caps redirect
#: chains to prevent redirect loop attacks. Can be overridden via
#: WARRANTOS_REDIRECT_HOP_CAP environment variable.
REDIRECT_HOP_CAP = int(os.getenv('WARRANTOS_REDIRECT_HOP_CAP', 3))

# ---------------------------------------------------------------------------
# Salience scoring weights (from context_admissibility patterns)
# ---------------------------------------------------------------------------

#: Relative weights for different salience pattern types. Used by score_claim()
#: to compute overall claim salience. Higher weights = more likely to be
#: load-bearing.
#:
#:   numeric     -- magnitude, percentage, year references (0.8)
#:   statute     -- statute/section references (0.9, highest)
#:   causal      -- causal language ("caused", "led to", etc.) (0.7)
#:   attribution -- named-body attribution or comparison (0.6)
SALIENCE_WEIGHTS: Dict[str, float] = {
    'numeric': 0.8,
    'statute': 0.9,
    'causal': 0.7,
    'attribution': 0.6,
}

# ---------------------------------------------------------------------------
# User-Agent string for HTTP requests
# ---------------------------------------------------------------------------

#: User-Agent string sent with HTTP requests. Identifies the WarrantOS
#: version and project URL for server logging.
USER_AGENT = f"warrantos/{__version__} (+https://github.com/jvega017/claude-provenance)"

# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Raised when configuration is invalid."""
    pass


def validate_config() -> None:
    """Validate configuration values on module load.

    Raises ConfigError if any value is outside acceptable bounds.
    Called automatically at module import time.

    Checks:
        - MAX_DOC_BYTES > 0
        - MAX_SENTENCE_CHARS > 0
        - LOAD_BEARING_THRESHOLD in [0.0, 1.0]
        - FETCH_TIMEOUT > 0
        - FETCH_MAX_BYTES > 0
        - REDIRECT_HOP_CAP >= 0

    Raises
    ------
    ConfigError
        If any validation fails.
    """
    if MAX_DOC_BYTES <= 0:
        raise ConfigError(f"MAX_DOC_BYTES must be positive, got {MAX_DOC_BYTES}")

    if MAX_SENTENCE_CHARS <= 0:
        raise ConfigError(f"MAX_SENTENCE_CHARS must be positive, got {MAX_SENTENCE_CHARS}")

    if not (0.0 <= LOAD_BEARING_THRESHOLD <= 1.0):
        raise ConfigError(
            f"LOAD_BEARING_THRESHOLD must be in [0.0, 1.0], got {LOAD_BEARING_THRESHOLD}"
        )

    if FETCH_TIMEOUT <= 0:
        raise ConfigError(f"FETCH_TIMEOUT must be positive, got {FETCH_TIMEOUT}")

    if FETCH_MAX_BYTES <= 0:
        raise ConfigError(f"FETCH_MAX_BYTES must be positive, got {FETCH_MAX_BYTES}")

    if REDIRECT_HOP_CAP < 0:
        raise ConfigError(f"REDIRECT_HOP_CAP must be non-negative, got {REDIRECT_HOP_CAP}")

    # Validate profile uncited thresholds are in [0.0, 1.0].
    for profile, fraction in PROFILE_UNCITED_THRESHOLD.items():
        if not (0.0 <= fraction <= 1.0):
            raise ConfigError(
                f"PROFILE_UNCITED_THRESHOLD['{profile}'] must be in [0.0, 1.0], got {fraction}"
            )

    # Validate salience weights are reasonable.
    for weight_type, weight in SALIENCE_WEIGHTS.items():
        if weight < 0.0:
            raise ConfigError(
                f"SALIENCE_WEIGHTS['{weight_type}'] must be non-negative, got {weight}"
            )


# Validate configuration on module load.
validate_config()
