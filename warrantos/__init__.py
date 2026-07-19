"""WarrantOS: a burden-of-proof gate for AI-assisted writing.

A claim ships only with a warrant (a source, an explicit [CITE NEEDED], or a
logged BLOCK), AI scaffold residue is caught before it reaches the artefact, and
each run can be sealed into an offline-verifiable .warrant audit trail.

Subpackages:
    warrantos.provenance  the pipeline, gates, ledger, attestation
    warrantos.cli         the warrantos and provenance command-line entry points
    warrantos.hooks       the Claude Code Stop-hook surfaces
"""

__version__ = "0.12.0"
