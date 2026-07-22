"""Installed command surface for WarrantOS evidence bindings and trust roots."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from warrantos.provenance.claim_support import (
    assert_binding, claim_binding_from_dict, snapshot_text,
    source_snapshot_from_dict, verify_binding, verify_recorded_binding,
)
from warrantos.provenance.trust import load_trust_root, verify_release_warrant


def _read_json(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object: %s" % path)
    return data


def _write_json(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="warrantos-evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot", help="Hash exact source bytes and text extraction.")
    snapshot.add_argument("source")
    snapshot.add_argument("--id", required=True)
    snapshot.add_argument("--uri", required=True)
    snapshot.add_argument("--retrieved-at")
    snapshot.add_argument("--media-type", default="text/plain")
    snapshot.add_argument("--out", required=True)

    assertion = sub.add_parser("assert", help="Bind an artefact claim to an exact source passage.")
    assertion.add_argument("--artefact", required=True)
    assertion.add_argument("--claim-id", required=True)
    assertion.add_argument("--claim-text", required=True)
    assertion.add_argument("--snapshot", required=True)
    assertion.add_argument("--source", required=True)
    assertion.add_argument("--passage", required=True)
    assertion.add_argument("--created-by", required=True)
    assertion.add_argument("--binding-id")
    assertion.add_argument("--out", required=True)

    verify = sub.add_parser(
        "verify",
        help="Reproduce bytes/ranges; legacy review flags cannot confer semantic support.",
    )
    verify.add_argument("--artefact", required=True)
    verify.add_argument("--binding", required=True)
    verify.add_argument("--snapshot", required=True)
    verify.add_argument("--source", required=True)
    verify.add_argument("--reviewer", required=True, help="Legacy compatibility input; ignored.")
    verify.add_argument(
        "--verdict", choices=("supports", "contested", "contradicts"), required=True,
        help="Legacy compatibility input; ignored. Output is passage_reproduced.",
    )
    verify.add_argument("--out", required=True)

    reverify = sub.add_parser(
        "reverify", help="Fail-closed evidence recheck; semantic labels are downgraded.",
    )
    reverify.add_argument("--artefact", required=True)
    reverify.add_argument("--binding", required=True)
    reverify.add_argument("--snapshot", required=True)
    reverify.add_argument("--source", required=True)
    reverify.add_argument("--json", action="store_true")

    release = sub.add_parser("verify-release", help="Verify exact release bytes against a pinned signer.")
    release.add_argument("--warrant", required=True)
    release.add_argument("--prose", required=True)
    release.add_argument("--cbom", required=True)
    release.add_argument("--trust-root", required=True)
    release.add_argument("--json", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            timestamp = args.retrieved_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            snapshot = snapshot_text(
                source_snapshot_id=args.id, canonical_uri=args.uri,
                retrieved_at=timestamp, content=Path(args.source).read_bytes(),
                media_type=args.media_type,
            )
            _write_json(args.out, snapshot.to_dict())
            return 0
        if args.command == "assert":
            snapshot = source_snapshot_from_dict(_read_json(args.snapshot))
            binding = assert_binding(
                binding_id=args.binding_id or "bind_" + uuid.uuid4().hex[:12],
                claim_id=args.claim_id, claim_text=args.claim_text,
                artefact_text=Path(args.artefact).read_text(encoding="utf-8"),
                snapshot=snapshot, source_text=Path(args.source).read_text(encoding="utf-8"),
                passage=args.passage, created_by=args.created_by,
                created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            )
            _write_json(args.out, binding.to_dict())
            return 0
        if args.command in ("verify", "reverify"):
            snapshot = source_snapshot_from_dict(_read_json(args.snapshot))
            binding = claim_binding_from_dict(_read_json(args.binding))
            common = dict(
                artefact_text=Path(args.artefact).read_text(encoding="utf-8"),
                snapshots=[snapshot], source_bytes={snapshot.source_snapshot_id: Path(args.source).read_bytes()},
            )
            if args.command == "verify":
                result = verify_binding(binding, reviewer=args.reviewer,
                                        semantic_verdict=args.verdict, **common)
                _write_json(args.out, result.binding.to_dict() if result.valid else result.to_dict())
            else:
                result = verify_recorded_binding(binding, **common)
                sys.stdout.write(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n")
            return 0 if result.valid else 1
        if args.command == "verify-release":
            result = verify_release_warrant(
                _read_json(args.warrant),
                prose=Path(args.prose).read_text(encoding="utf-8"),
                cbom=_read_json(args.cbom), trust_root=load_trust_root(args.trust_root),
            )
            if args.json:
                sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
            else:
                sys.stdout.write("trust: %s\nsignature: %s\nOVERALL: %s\n" % (
                    result["trust"], result["signature"], result["overall"]))
            return 0 if result["overall"] == "VALID" else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write("warrantos-evidence: %s\n" % exc)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
