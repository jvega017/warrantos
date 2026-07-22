# Release process

1. Reconcile `release-manifest.json`, the package version and every truth surface.
2. Run the complete three-OS CI matrix, hermetic tests, attestation tests, evaluation
   harness, documentation build and package smoke test.
3. Tag the exact PEP 440 version as `v<version>`; `tools/check_tag_version.py` rejects
   any mismatch.
4. Build wheel and source distribution once from the tag and validate metadata.
5. Publish those artifacts to TestPyPI through OIDC Trusted Publishing and install the
   exact version from TestPyPI in a clean environment.
6. Promote the same downloaded workflow artifacts to PyPI through OIDC Trusted
   Publishing. PyPI publication attestations bind the distribution to the workflow.
7. Attach the unchanged distributions and hashes to the GitHub Release.

The workflow contains no long-lived package-index token. Repository environments and
Trusted Publisher records must be configured by the maintainer before the first tag.
Publishing remains a maintainer-authorised external action.
