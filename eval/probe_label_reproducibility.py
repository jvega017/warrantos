"""Probe A: label-reproducibility of the grader gold corpus by a
different-family model.

This is a machine reproducibility signal. It is NOT human inter-rater
reliability. The script reports the kappa as such, and the README and any
downstream write-up MUST do the same.

What it does
------------
For each item in `eval/corpus/grader.jsonl`, the visible labelling fields
(claim, citation, source) are given to a different-vendor model (Gemini
CLI by default) with the same five-class rubric a human annotator would
see. The model's predicted class is compared against the corpus gold and
the agreement and Cohen's kappa are computed.

Why a different family
----------------------
The cross-model grader backend in `provenance/grade.py` uses Codex
(GPT-5.x family). To test label reproducibility without re-using the
grader's own family (same-family agreement is uninformative for this
purpose), the probe runs against a different family. Gemini is the
default; any CLI returning a single-line class name on stdin works.

What this is not
----------------
This is not human inter-rater reliability. It is not a substitute for an
independent second-coder. It does not validate that the corpus is a
good benchmark; it tests whether the gold labels are reproducible from
the same visible information by a different model.

Standard library only. No third-party imports. Australian English.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Redact local user paths (Windows, macOS, Linux, and MSYS forms) so no
# artefact written by this harness can leak a username. Captured stderr
# from the annotator CLI can contain absolute paths to local error logs;
# the username segment is the only personal part and is replaced.
_USER_PATH_RE = re.compile(r"(?i)([A-Za-z]:\\Users\\|/Users/|/home/|/c/Users/)[^\\/\s\"]+")


def sanitise(text):
    """Replace the username segment of any local path with <redacted>."""
    if not text:
        return text
    return _USER_PATH_RE.sub(r"\1<redacted>", text)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CORPUS = _REPO_ROOT / "eval" / "corpus" / "grader.jsonl"
_DEFAULT_OUT_JSON = _REPO_ROOT / "eval" / "probe-a-results.json"
_DEFAULT_OUT_REPORT = _REPO_ROOT / "eval" / "probe-a-report.md"

GOLD_CLASSES = ("verified", "contradicted", "not_addressed", "unverifiable", "skipped")

PROMPT_TEMPLATE = """You are coding citation-claim pairs against a fixed five-class rubric. Read the rubric and the item, then output exactly one of the five class names and nothing else.

Five classes:
- verified: the source explicitly supports the claim's assertion.
- contradicted: the source explicitly contradicts the claim (states the opposite, reverses direction, or gives a materially different figure).
- not_addressed: a source is provided but does not address the claim's specific assertion either way.
- unverifiable: a citation is given but no source text is available to check against.
- skipped: no citation and no source are available; nothing to check.

Item:
claim: {claim}
citation: {citation}
source: {source}

Output exactly one word from this set and nothing else:
verified
contradicted
not_addressed
unverifiable
skipped
"""


def _resolve_bin(name: str) -> str:
    """Resolve a CLI binary robustly on Windows and POSIX.

    Mirrors the discipline in `provenance/grade.py::CodexGrader._resolve_codex_bin`.
    """
    for candidate in (name + ".cmd", name + ".exe", name):
        found = shutil.which(candidate)
        if found:
            return found
    return name


def load_corpus(path: Path) -> list:
    items = []
    seen_ids = set()
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    "malformed JSON in {} line {}: {}".format(path, line_no, exc)
                )
            for required in ("id", "claim", "gold"):
                if required not in item:
                    raise SystemExit(
                        "missing field '{}' in {} line {}".format(required, path, line_no)
                    )
            if item["gold"] not in GOLD_CLASSES:
                raise SystemExit(
                    "gold '{}' not in five-class set, {} line {}".format(
                        item["gold"], path, line_no
                    )
                )
            if item["id"] in seen_ids:
                raise SystemExit("duplicate id '{}'".format(item["id"]))
            seen_ids.add(item["id"])
            items.append(item)
    if not items:
        raise SystemExit("corpus is empty: {}".format(path))
    return items


def build_prompt(item: dict) -> str:
    citation = item.get("citation")
    source = item.get("source")
    return PROMPT_TEMPLATE.format(
        claim=item["claim"],
        citation="<none>" if citation in (None, "") else citation,
        source="<none>" if source in (None, "") else source,
    )


_TRANSIENT_MARKERS = ("503", "unavailable", "high demand", "rate", "overloaded")


def _is_transient(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _TRANSIENT_MARKERS) and "terminalquotaerror" not in low


def call_gemini(prompt: str, gemini_bin: str, timeout: int, model: str = "",
                max_attempts: int = 3) -> tuple:
    """Return (predicted_class_or_None, raw_stdout, error_or_None).

    The prompt is delivered on stdin, not via -p: the -p flag truncates a
    multi-line prompt at the first newline when the CLI is launched through
    a Windows .cmd shim, which silently strips the rubric and the item.
    Stdin delivery passes the full prompt intact on every platform.

    Never raises. Maps every failure to (None, raw, error_message) so the
    caller can record an 'error' verdict and continue. Retries up to
    max_attempts on transient errors (503, high demand) but never on a
    terminal quota error. All returned strings are sanitised so no local
    username or path is recorded in the artefact.
    """
    cmd = [gemini_bin]
    if model:
        cmd += ["-m", model]

    last_err = "unknown"
    for attempt in range(1, max_attempts + 1):
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            return None, "", "binary-not-found"
        except subprocess.TimeoutExpired:
            last_err = "timeout after {}s".format(timeout)
            continue
        except Exception as exc:  # broad: this is best-effort harness, not core
            return None, "", sanitise("subprocess-error: {}".format(exc))

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            last_err = sanitise(
                "non-zero exit {}: stderr={}".format(result.returncode, stderr[:200])
            )
            if _is_transient(stderr) and attempt < max_attempts:
                time.sleep(5 * attempt)
                continue
            return None, sanitise(result.stdout or ""), last_err

        out = (result.stdout or "").strip()
        if not out:
            last_err = "empty stdout"
            if attempt < max_attempts:
                time.sleep(3)
                continue
            return None, "", last_err

        pred = _parse_class(out)
        if pred is None:
            return None, out, sanitise(
                "no class found in output (head: {!r})".format(out[:200])
            )
        return pred, out, None

    return None, "", last_err


def _parse_class(raw: str) -> str:
    """Find a class name in the model's output, prefer the first match."""
    lowered = raw.lower()
    # Strict: line containing only a class name.
    for line in lowered.splitlines():
        token = line.strip().rstrip(".,;:!?\"'`)")
        if token in GOLD_CLASSES:
            return token
    # Loose: first class name appearing anywhere.
    earliest_pos = None
    earliest_class = None
    for cls in GOLD_CLASSES:
        idx = lowered.find(cls)
        if idx >= 0 and (earliest_pos is None or idx < earliest_pos):
            earliest_pos = idx
            earliest_class = cls
    return earliest_class


def compute_metrics(results: list) -> dict:
    """Compute agreement, Cohen's kappa, per-class breakdown, confusion matrix.

    `results` is a list of dicts with keys 'id', 'gold', 'pred'. 'pred'
    may be 'error' to indicate a non-classification outcome.
    """
    n = len(results)
    if n == 0:
        return {"n": 0}

    pred_labels = list(GOLD_CLASSES) + ["error"]
    confusion = {(g, p): 0 for g in GOLD_CLASSES for p in pred_labels}
    for r in results:
        confusion[(r["gold"], r["pred"])] += 1

    correct = sum(confusion[(c, c)] for c in GOLD_CLASSES)
    agreement = correct / n

    # Cohen's kappa over the 5 gold classes; 'error' predictions are
    # counted in totals so they reduce agreement honestly.
    row_totals = {c: sum(confusion[(c, p)] for p in pred_labels) for c in GOLD_CLASSES}
    col_totals = {c: sum(confusion[(g, c)] for g in GOLD_CLASSES) for c in GOLD_CLASSES}
    p_e = sum(
        (row_totals[c] / n) * (col_totals[c] / n) for c in GOLD_CLASSES
    )
    p_o = agreement
    if abs(1.0 - p_e) < 1e-12:
        kappa = 0.0
    else:
        kappa = (p_o - p_e) / (1.0 - p_e)

    per_class = {}
    for c in GOLD_CLASSES:
        support = row_totals[c]
        tp = confusion[(c, c)]
        per_class[c] = {
            "support": support,
            "correct": tp,
            "recall": tp / support if support else 0.0,
        }

    error_count = sum(confusion[(g, "error")] for g in GOLD_CLASSES)

    return {
        "n": n,
        "agreement": agreement,
        "correct": correct,
        "cohens_kappa": kappa,
        "per_class": per_class,
        "confusion": {
            "{}__{}".format(g, p): v for (g, p), v in confusion.items()
        },
        "error_count": error_count,
    }


def write_report(metrics: dict, meta: dict, out_path: Path) -> None:
    n = metrics.get("n", 0)
    err = metrics.get("error_count", 0)
    classes_with_no_returns = [
        c for c in GOLD_CLASSES
        if metrics.get("per_class", {}).get(c, {}).get("support", 0) > 0
        and metrics.get("per_class", {}).get(c, {}).get("correct", 0) == 0
        and all(
            metrics.get("confusion", {}).get("{}__{}".format(c, p), 0) == 0
            for p in GOLD_CLASSES if p != c
        )
    ]
    # A class is "unreached" if every confusion cell except its error column
    # is zero. Compute that strictly.
    unreached = []
    for c in GOLD_CLASSES:
        non_error = sum(
            metrics.get("confusion", {}).get("{}__{}".format(c, p), 0)
            for p in GOLD_CLASSES
        )
        if non_error == 0 and metrics.get("per_class", {}).get(c, {}).get("support", 0) > 0:
            unreached.append(c)

    lines = ["# Probe A: label-reproducibility report", ""]

    if err > 0:
        lines += [
            "## STATUS: partial run, infrastructure errors present",
            "",
            "{} of {} items returned an `error` predicted label (annotator".format(err, n),
            "infrastructure failure, not a classification result). The headline",
            "agreement and kappa below count errors in the totals so they reduce",
            "the numbers honestly. Read the per-class block: a class with zero",
            "returns reflects a quota or transport cut-off on that segment of",
            "the corpus, not a finding about reproducibility for that class.",
            "",
        ]
        if unreached:
            lines += [
                "**Classes not reached by the annotator on this run:** "
                + ", ".join(sorted(unreached)) + ".",
                "A follow-up run targeting only the unreached items would close",
                "the gap with a fraction of the original quota cost.",
                "",
            ]

    lines += [
        "**This is a machine reproducibility signal. It is NOT human inter-rater",
        "reliability.** A different-family model (Gemini) was given the same",
        "visible labelling fields (claim, citation, source) as a human annotator,",
        "blind to the original gold, and asked to emit a class from the five-",
        "class set. Agreement and Cohen's kappa are reported against the",
        "original gold labels.",
        "",
        "## Run metadata",
        "",
        "- date: {}".format(meta.get("date", "")),
        "- corpus: {} ({} items)".format(meta.get("corpus", ""), metrics.get("n", 0)),
        "- annotator (Probe A): {}".format(meta.get("annotator", "")),
        "- annotator model: {}".format(meta.get("model", "")),
        "- grader model being de-conflated from labels: Codex (GPT-5.x family) — different family from annotator (different-family agreement is informative; same-family is not).",
        "- per-call timeout: {}s".format(meta.get("timeout", "")),
        "",
        "## Headline",
        "",
        "- agreement: {:.4f} ({}/{})".format(
            metrics["agreement"], metrics["correct"], metrics["n"]
        ),
        "- Cohen's kappa: {:.4f}".format(metrics["cohens_kappa"]),
        "- error count (annotator infrastructure failure, predicted-only label): {}".format(metrics["error_count"]),
        "",
        "## Per-class agreement",
        "",
        "| class | support | annotator agreed | recall |",
        "|---|---|---|---|",
    ]
    for c in GOLD_CLASSES:
        pc = metrics["per_class"][c]
        lines.append(
            "| {} | {} | {} | {:.4f} |".format(
                c, pc["support"], pc["correct"], pc["recall"]
            )
        )

    lines += [
        "",
        "## Confusion matrix (rows = gold, cols = annotator)",
        "",
        "| gold \\ pred | verified | contradicted | not_addressed | unverifiable | skipped | error |",
        "|---|---|---|---|---|---|---|",
    ]
    pred_labels = list(GOLD_CLASSES) + ["error"]
    for g in GOLD_CLASSES:
        row = ["| " + g]
        for p in pred_labels:
            row.append(str(metrics["confusion"]["{}__{}".format(g, p)]))
        lines.append(" | ".join(row) + " |")

    lines += [
        "",
        "## Honesty caveats (applied)",
        "",
        "- The annotator model (Gemini) is from a different family than the",
        "  grader being evaluated (Codex). Same-family agreement is not run",
        "  here because it would be uninformative.",
        "- A high kappa indicates that the gold labels are reproducible by a",
        "  different model from the same visible information, which",
        "  corroborates the corpus's self-evident-labelling design criterion.",
        "  It does NOT indicate human inter-rater reliability. Independent",
        "  human second-coding remains the named revision item.",
        "- A low kappa is also a finding: it would mean the gold labels are",
        "  not reproducible from the visible fields alone, which would",
        "  weaken the single-annotator defence of the corpus.",
        "- Gemini output is model-dependent and not bit-reproducible across",
        "  runs or model updates. The date and model name above pin this run.",
        "- Errors (predicted-only label, infrastructure failures) are counted",
        "  in the totals; they reduce agreement honestly rather than being",
        "  silently dropped.",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=_DEFAULT_CORPUS)
    parser.add_argument("--out-json", type=Path, default=_DEFAULT_OUT_JSON)
    parser.add_argument("--out-report", type=Path, default=_DEFAULT_OUT_REPORT)
    parser.add_argument("--limit", type=int, default=0, help="if >0, only run on the first N items (smoke test)")
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("PROBE_A_TIMEOUT", "120")))
    parser.add_argument("--annotator", default="gemini-cli", help="label for the report")
    parser.add_argument("--bin", default=os.environ.get("PROBE_A_BIN", "gemini"))
    parser.add_argument("--model", default=os.environ.get("PROBE_A_MODEL", ""), help="model passed to the CLI via -m (e.g. gemini-2.5-flash)")
    args = parser.parse_args(argv)

    items = load_corpus(args.corpus)
    if args.limit and args.limit > 0:
        items = items[: args.limit]

    gemini_bin = _resolve_bin(args.bin)
    print("probe-a: corpus={} items={} annotator={} model={} bin=<resolved>".format(
        args.corpus, len(items), args.annotator, args.model or "<cli-default>"
    ), flush=True)

    results = []
    started = time.time()
    for idx, item in enumerate(items, 1):
        prompt = build_prompt(item)
        pred, raw, err = call_gemini(prompt, gemini_bin, args.timeout, args.model)
        pred_label = pred if pred is not None else "error"
        results.append({
            "id": item["id"],
            "gold": item["gold"],
            "pred": pred_label,
            "error": err,
        })
        print(
            "  [{}/{}] {} gold={} pred={} {}".format(
                idx, len(items), item["id"], item["gold"], pred_label,
                "" if err is None else "(err: {})".format(err)
            ),
            flush=True,
        )

    elapsed = time.time() - started
    metrics = compute_metrics(results)

    try:
        corpus_label = str(args.corpus.relative_to(_REPO_ROOT))
    except ValueError:
        corpus_label = args.corpus.name  # never record an absolute path
    meta = {
        "date": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "corpus": corpus_label,
        "annotator": args.annotator,
        "model": args.model or "<cli-default>",
        "timeout": args.timeout,
        "elapsed_seconds": round(elapsed, 1),
    }

    payload = {"meta": meta, "metrics": metrics, "results": results}
    args.out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_report(metrics, meta, args.out_report)

    print("")
    print("probe-a complete: agreement {}/{}  kappa {:.4f}  errors {}  elapsed {:.0f}s".format(
        metrics["correct"], metrics["n"], metrics["cohens_kappa"], metrics["error_count"], elapsed
    ), flush=True)
    print("  json:   {}".format(args.out_json), flush=True)
    print("  report: {}".format(args.out_report), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
