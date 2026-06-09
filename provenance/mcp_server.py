"""provenance.mcp_server: MCP wrapper around the warrantos pipeline.

Path X4-A. Exposes the warrantos CLI surfaces as MCP tools so Claude
Code or Claude Desktop sessions can invoke the WarrantOS pipeline
directly without spawning a subprocess for each call.

Tools exposed:

- `warrant_check`: run the full pipeline over a draft path and return
  the consolidated JSON report.
- `warrant_classify`: run Layer 1 over a single text item with an
  optional source_agent (SPEC-L1-S005 gate).
- `warrant_record_override`: write a structured human_override row
  to the override ledger (SPEC-L8-S002/S003/S004).
- `warrant_get_run`: read back the per-run JSON artefacts written by
  warrant_check.

The MCP SDK (`mcp` package) is an optional dependency. If it is not
installed, `import provenance.mcp_server` still succeeds, but
`run_stdio_server()` raises ImportError with a clear install message.
The core repo stays stdlib-only; the MCP server is a separate
launchable surface.

Run from the repo root:

    python -m provenance.mcp_server

Stdio MCP transport. Configure in Claude Code's MCP settings as:

    {
        "warrantos": {
            "command": "python",
            "args": ["-m", "provenance.mcp_server"],
            "cwd": "/path/to/claude-provenance"
        }
    }

Python 3.8 compatible (the MCP SDK itself may require newer Python).
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Repo root on sys.path so the CLI module imports work when this file
# is launched as a script via `python -m provenance.mcp_server`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Tool definitions (declarative — usable without the MCP SDK installed)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "warrant_check",
        "description": (
            "Run the WarrantOS pipeline over a draft artefact and return "
            "the consolidated verdict (PASS, HOLD, BLOCK, or "
            "NOT_ASSESSABLE) plus the per-run artefact paths."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_path": {
                    "type": "string",
                    "description": "Absolute or repo-relative path to the draft Markdown file.",
                },
                "context_path": {
                    "type": "string",
                    "description": "Optional path to a JSON context file.",
                },
                "actor_identity": {
                    "type": "object",
                    "description": (
                        "Optional map from role name to actor identity. "
                        "Required for final-prose to avoid NOT_ASSESSABLE."
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "profile": {
                    "type": "string",
                    "enum": [
                        "final-prose",
                        "brief-light",
                        "paper-full",
                        "audit",
                        "methodology",
                        "consultation_report",
                        "changelog",
                    ],
                    "default": "final-prose",
                },
                "run_id": {"type": "string", "description": "Optional run id."},
                "verify": {
                    "type": "boolean",
                    "default": False,
                    "description": "Run the Layer 7 G2 verifier (offline by default).",
                },
                "no_fetch": {
                    "type": "boolean",
                    "default": False,
                    "description": "When verify=true, do not fetch cited URLs.",
                },
                "out_dir": {
                    "type": "string",
                    "description": "Output directory for per-run artefacts.",
                },
                "db_path": {
                    "type": "string",
                    "description": "Override ledger database path.",
                },
            },
            "required": ["draft_path"],
        },
    },
    {
        "name": "warrant_classify",
        "description": (
            "Classify a single context input via Layer 1. Returns the "
            "context_type, ledger_bucket, and admissibility flags. With "
            "source_agent set to a review-role agent, classification is "
            "forced to review_finding per SPEC-L1-S005."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "source_agent": {
                    "type": "string",
                    "description": (
                        "Optional agent identifier. Names in "
                        "REVIEW_ROLE_REGISTRY force review_finding."
                    ),
                },
                "context_id": {"type": "string"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "warrant_record_override",
        "description": (
            "Record a structured human override of a Layer 7 gate verdict. "
            "Empty risk_accepted or compensating_control SHALL block the "
            "override per SPEC-L8-S004."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "db_path": {"type": "string"},
                "run_id": {"type": "string"},
                "reviewer": {"type": "string"},
                "gate_id": {
                    "type": "string",
                    "description": "G1, G2, G3, G4, or G5.",
                },
                "failure_class": {"type": "string"},
                "risk_accepted": {"type": "string"},
                "compensating_control": {"type": "string"},
                "escalation_path_taken": {
                    "type": "string",
                    "default": "none recorded",
                },
                "single_actor": {"type": "boolean", "default": False},
            },
            "required": [
                "db_path",
                "run_id",
                "reviewer",
                "gate_id",
                "failure_class",
                "risk_accepted",
                "compensating_control",
            ],
        },
    },
    {
        "name": "warrant_get_run",
        "description": (
            "Read back the per-run JSON artefacts written by a previous "
            "warrant_check invocation. Returns the verdict, CBOM, "
            "classified context, boundary report, claims, verifier "
            "verdicts, and overrides footer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "out_dir": {
                    "type": "string",
                    "description": "Path to the .warrant/runs/<run_id>/ directory.",
                },
            },
            "required": ["out_dir"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations (stdlib only; do not import mcp here)
# ---------------------------------------------------------------------------

def _import_pipeline():
    """Import the warrantos CLI pipeline lazily.

    Lazy import keeps the test surface clean and avoids paying the
    cli/warrantos_cli.py import cost when only the tool definitions are
    being inspected.
    """
    from cli import warrantos_cli  # noqa: F401
    return warrantos_cli


def tool_warrant_check(args: Dict[str, Any]) -> Dict[str, Any]:
    """In-process implementation of warrant_check."""
    pipeline = _import_pipeline()

    draft_path = args["draft_path"]
    context_path = args.get("context_path")
    actor_identity = args.get("actor_identity") or {}
    profile = args.get("profile", "final-prose")
    run_id = args.get("run_id") or "run_" + uuid.uuid4().hex[:12]
    verify = bool(args.get("verify", False))
    no_fetch = bool(args.get("no_fetch", False))
    out_dir = Path(args.get("out_dir") or (Path(".warrant") / "runs" / run_id))
    db_path = args.get("db_path") or str(Path(".warrant") / "provenance.db")

    draft_text = pipeline.load_draft(draft_path)
    context_items_raw = pipeline.load_context(context_path) if context_path else []

    classified_pairs = pipeline.classify_all(context_items_raw)
    classified = [item for item, _ in classified_pairs]

    boundary = pipeline.scan_prose_boundary(draft_text, artefact_role=profile)

    claim_rows = pipeline.detect_claims(draft_text)
    verifier_rows: List[Dict[str, Any]] = []
    if verify:
        try:
            verifier_rows = pipeline.run_verifier(draft_text, fetch=not no_fetch)
        except Exception as exc:
            verifier_rows = []
            sys.stderr.write("mcp_server: verifier internal error captured: %s\n" % exc)

    context_inputs = [
        pipeline.to_context_input(item, raw) for item, raw in classified_pairs
    ]
    admitted_ids = [ci.context_id for ci in context_inputs if ci.admitted]
    claim_records = [
        pipeline.to_claim_record(row, admitted_ids) for row in claim_rows
    ]

    overrides_on_record = []
    try:
        overrides_on_record = pipeline.list_overrides_for_run(db_path, run_id)
    except Exception:
        overrides_on_record = []

    cbom = pipeline.build_cbom(
        context_inputs=context_inputs,
        claims=claim_records,
        artefact_id=Path(draft_path).name,
        actor_identity=dict(actor_identity),
        classification_overrides=[],
        override_ledger_refs=[str(o.id) for o in overrides_on_record],
    )

    # Separation of duties must apply on the MCP path too, not just the CLI.
    single_actor_override = any(
        getattr(o, "single_actor", False) for o in overrides_on_record
    )
    verdict, reasons = pipeline.consolidate_verdict(
        boundary,
        claim_rows,
        verifier_rows,
        dict(actor_identity),
        cbom.classification_overrides,
        profile,
        single_actor_override=single_actor_override,
    )

    footer_markdown = pipeline.render_override_footer(overrides_on_record)

    pipeline.write_run_artefacts(
        out_dir,
        run_id=run_id,
        cbom=cbom,
        classified=classified,
        boundary=boundary,
        claim_rows=claim_rows,
        verifier_rows=verifier_rows,
        consolidated_verdict=verdict,
        reasons=reasons,
        footer_markdown=footer_markdown,
    )

    type_counts: Dict[str, int] = {}
    for item in classified:
        type_counts[item.context_type] = type_counts.get(item.context_type, 0) + 1

    return {
        "run_id": run_id,
        "profile": profile,
        "verdict": verdict,
        "reasons": reasons,
        "context_items": len(classified),
        "by_context_type": type_counts,
        "claims_detected": len(claim_rows),
        "claims_supported": sum(1 for c in claim_rows if c.get("citation")),
        "boundary_verdict": boundary.verdict,
        "boundary_violations": len(boundary.violations),
        "overrides_total": len(overrides_on_record),
        "out_dir": str(out_dir),
        "cbom_schema": cbom.schema,
        "load_bearing_threshold": pipeline.LOAD_BEARING_THRESHOLD,
    }


def tool_warrant_classify(args: Dict[str, Any]) -> Dict[str, Any]:
    """In-process implementation of warrant_classify."""
    from provenance.context_admissibility import classify_context

    text = args.get("text") or ""
    source_agent = args.get("source_agent")
    context_id = args.get("context_id") or ("ctx_" + uuid.uuid4().hex[:8])
    item = classify_context(context_id, text, source_agent=source_agent)
    return {
        "context_id": item.context_id,
        "context_type": item.context_type,
        "ledger_bucket": item.ledger_bucket,
        "can_influence_output": item.can_influence_output,
        "can_appear_in_final_prose": item.can_appear_in_final_prose,
        "allowed_transformation": item.allowed_transformation,
        "audit_status": item.audit_status,
    }


def tool_warrant_record_override(args: Dict[str, Any]) -> Dict[str, Any]:
    """In-process implementation of warrant_record_override."""
    from provenance.overrides import record_override

    override = record_override(
        args["db_path"],
        run_id=args["run_id"],
        reviewer=args["reviewer"],
        gate_id=args["gate_id"],
        failure_class=args["failure_class"],
        risk_accepted=args["risk_accepted"],
        compensating_control=args["compensating_control"],
        escalation_path_taken=args.get("escalation_path_taken", "none recorded"),
        single_actor=bool(args.get("single_actor", False)),
    )
    return override.to_dict()


def tool_warrant_get_run(args: Dict[str, Any]) -> Dict[str, Any]:
    """In-process implementation of warrant_get_run.

    Reads back the per-run JSON artefacts and returns them as a single
    nested object. Missing files become null entries.
    """
    out_dir = Path(args["out_dir"])
    result: Dict[str, Any] = {"out_dir": str(out_dir)}
    for name in ("verdict", "cbom", "context_items", "boundary", "claims", "verifier"):
        p = out_dir / (name + ".json")
        if p.is_file():
            try:
                result[name] = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                result[name] = {"error": "json decode failed: " + str(exc)}
        else:
            result[name] = None
    footer_path = out_dir / "footer.md"
    result["footer_md"] = (
        footer_path.read_text(encoding="utf-8") if footer_path.is_file() else None
    )
    return result


_TOOL_HANDLERS = {
    "warrant_check": tool_warrant_check,
    "warrant_classify": tool_warrant_classify,
    "warrant_record_override": tool_warrant_record_override,
    "warrant_get_run": tool_warrant_get_run,
}


def call_tool_in_process(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a tool call without going through the MCP SDK.

    This is the function the test suite exercises. It also serves as a
    standalone in-process API for callers that want the WarrantOS
    pipeline as a Python function rather than an MCP tool.
    """
    if name not in _TOOL_HANDLERS:
        raise ValueError("unknown tool: %s" % name)
    return _TOOL_HANDLERS[name](args)


# ---------------------------------------------------------------------------
# MCP transport (optional — requires the mcp SDK)
# ---------------------------------------------------------------------------

def run_stdio_server() -> None:
    """Run the warrantos MCP server on stdio.

    Requires the `mcp` package to be installed. Raises ImportError with
    a clear install message if the package is missing.
    """
    try:
        import asyncio
        from mcp.server import Server  # type: ignore
        from mcp.server.stdio import stdio_server  # type: ignore
        from mcp import types as mcp_types  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "warrantos MCP server requires the `mcp` package. Install with:\n"
            "    pip install mcp\n"
            "Original import error: " + str(exc)
        ) from exc

    server = Server("warrantos")

    @server.list_tools()
    async def _list_tools():
        return [
            mcp_types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in TOOL_DEFINITIONS
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        try:
            result = call_tool_in_process(name, arguments or {})
        except Exception as exc:
            return [mcp_types.TextContent(type="text", text=json.dumps({
                "error": str(exc),
                "tool": name,
            }))]
        return [mcp_types.TextContent(
            type="text",
            text=json.dumps(result, indent=2, sort_keys=True),
        )]

    async def _main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(_main())


if __name__ == "__main__":
    run_stdio_server()
