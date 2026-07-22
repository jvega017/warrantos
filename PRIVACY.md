# Privacy and network behaviour

The default WarrantOS CLI is local and has no analytics, crash telemetry or automatic
external emission. Documents, ledgers and `.warrant` bundles remain on the host unless
the operator deliberately copies them elsewhere.

Network-capable features are opt-in:

- installing packages contacts the configured Python package index;
- the `llm` extra can send selected claim and source context to the configured model
  provider when LLM verification is explicitly enabled;
- the MCP server exposes local tools to the MCP host selected by the operator.

WarrantOS never requires a project account. Operators remain responsible for source
classification, provider terms, retention, redaction and access to generated audit
records. Do not use model-backed verification for material that the chosen provider
is not authorised to receive.
