# Compatibility and deprecation policy

WarrantOS 0.11.0b2 supports CPython 3.11–3.13 on Windows, macOS and Linux. The core
package is dependency-free; optional extras declare their own dependencies.

Within a schema major version, new fields are additive and existing required fields
retain their meaning. Breaking schema, CLI or verification changes require a new
schema major version or a package major release. Security fixes may make verification
more fail-closed without a major version when accepting the previous behaviour would
misrepresent integrity. Deprecated public CLI options receive a changelog entry and,
except for urgent security removal, at least one minor release of warning.

Beta releases are not covered by a stability guarantee. Production qualification is
not implied by semantic versioning.
