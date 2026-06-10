#!/usr/bin/env python3
"""run_eval.py: evaluation harness for the claude-provenance v0 heuristic.

Runs the v0 heuristic (hooks/provenance_check.py :: analyse) and the offline
axis-2 verifier (provenance.verify.verify_text with fetch=False) against a
hand-labelled seed corpus.  Computes precision, recall and F1 for the
heuristic's "unsupported" detection and counts axis-2 category distribution.

Also evaluates the grader (HeuristicGrader or LLMGrader) against a separate
grader corpus (eval/corpus/grader.jsonl) and reports per-class precision,
recall, F1, macro averages, overall accuracy, and a full confusion matrix.

All computation happens at runtime against real gold labels. No metrics are
hard-coded.

Usage:
    python eval/run_eval.py
    python eval/run_eval.py --corpus path/to/custom.jsonl
    python eval/run_eval.py --grader {heuristic,llm,both,codex}
    python eval/run_eval.py --grader-corpus path/to/grader.jsonl

Exit codes:
    0  -- evaluation completed (even when metrics are low)
    1  -- corpus file missing or malformed

Python 3.8+. Standard library only. No network access (except LLMGrader when
ANTHROPIC_API_KEY is set).
"""

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate the repo root and load the hook by file path so this evaluator
# works whether or not the package is installed. We must NOT import the hook
# as a module that could be edited; we use importlib to load it read-only.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HOOK_PATH = _REPO_ROOT / "warrantos" / "hooks" / "provenance_check.py"


def _load_hook():
    """Load hooks/provenance_check.py via importlib without editing it."""
    spec = importlib.util.spec_from_file_location("_provenance_hook", str(_HOOK_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------

_VALID_AXIS1 = {"supported", "unsupported", "tagged"}
_VALID_AXIS2 = {"verified", "unverifiable", "skipped", "na"}


def load_corpus(path):
    """Parse the JSONL corpus file.  Returns a list of item dicts.

    Raises SystemExit(1) on any file or parse error.
    """
    p = Path(path)
    if not p.is_file():
        sys.stderr.write("ERROR: corpus file not found: %s\n" % path)
        sys.exit(1)

    items = []
    try:
        for lineno, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                sys.stderr.write(
                    "ERROR: corpus line %d is not valid JSON: %s\n" % (lineno, exc)
                )
                sys.exit(1)
            for field in ("id", "text", "gold"):
                if field not in obj:
                    sys.stderr.write(
                        "ERROR: corpus line %d missing required field %r\n" % (lineno, field)
                    )
                    sys.exit(1)
            for g in obj["gold"]:
                if g.get("axis1") not in _VALID_AXIS1:
                    sys.stderr.write(
                        "ERROR: item %r gold axis1 value %r not in %s\n"
                        % (obj["id"], g.get("axis1"), sorted(_VALID_AXIS1))
                    )
                    sys.exit(1)
                if g.get("axis2") not in _VALID_AXIS2:
                    sys.stderr.write(
                        "ERROR: item %r gold axis2 value %r not in %s\n"
                        % (obj["id"], g.get("axis2"), sorted(_VALID_AXIS2))
                    )
                    sys.exit(1)
            items.append(obj)
    except Exception as exc:
        sys.stderr.write("ERROR: could not read corpus: %s\n" % exc)
        sys.exit(1)

    if not items:
        sys.stderr.write("ERROR: corpus file is empty\n")
        sys.exit(1)

    return items


# ---------------------------------------------------------------------------
# Claim alignment helpers
# ---------------------------------------------------------------------------

def _normalise(s):
    """Lower-case and collapse whitespace for robust substring matching."""
    import re
    return re.sub(r"\s+", " ", s.strip().lower())


def _claim_matches_row(gold_claim, row_snippet):
    """Return True if the gold claim string is a substring of the row snippet.

    Uses normalised comparison to tolerate minor whitespace differences.
    """
    norm_claim = _normalise(gold_claim)
    norm_snippet = _normalise(row_snippet)
    # Substring check: the gold claim text should appear inside the row snippet,
    # or the row snippet should appear inside the gold claim (handles truncation).
    return norm_claim in norm_snippet or norm_snippet in norm_claim


# ---------------------------------------------------------------------------
# Per-item evaluation
# ---------------------------------------------------------------------------

def _evaluate_item(item, hook_mod, verify_text_fn, grader):
    """Evaluate a single corpus item.

    Returns a dict with keys:
        axis1_results  -- list of (gold_claim, gold_axis1, pred_axis1_or_None)
        axis2_results  -- list of (gold_claim, gold_axis2, pred_axis2_or_None)
    """
    text = item["text"]
    gold_entries = item["gold"]

    # --- Axis 1: v0 heuristic ---
    rows, _totals = hook_mod.analyse(text)
    # rows: list of (status, trigger, snippet)

    # --- Axis 2: offline verify_text ---
    verdicts = verify_text_fn(text, grader=grader, fetch=False)
    # verdicts: list of Verdict with .claim_text, .verdict

    axis1_results = []
    axis2_results = []

    for g in gold_entries:
        gold_claim = g["claim"]
        gold_a1 = g["axis1"]
        gold_a2 = g["axis2"]

        # Axis 1: find the matching predicted row (if any).
        matched_a1 = None
        for status, _trigger, snippet in rows:
            if _claim_matches_row(gold_claim, snippet):
                matched_a1 = status
                break
        # If no row matched and the gold says "unsupported"/"supported"/"tagged",
        # the heuristic produced no prediction for this claim.
        axis1_results.append((gold_claim, gold_a1, matched_a1))

        # Axis 2: find the matching verdict (if any).
        matched_a2 = None
        for v in verdicts:
            if _claim_matches_row(gold_claim, v.claim_text):
                matched_a2 = v.verdict
                break
        axis2_results.append((gold_claim, gold_a2, matched_a2))

    return {"axis1_results": axis1_results, "axis2_results": axis2_results}


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def _compute_axis1_metrics(all_axis1):
    """Compute precision, recall, F1 for the positive class "unsupported".

    A true positive (TP) is: gold==unsupported AND pred==unsupported.
    A false positive (FP) is: gold!=unsupported AND pred==unsupported.
    A false negative (FN) is: gold==unsupported AND pred!=unsupported (incl. None).

    Returns a dict with keys: tp, fp, fn, precision, recall, f1,
    total_gold_unsupported, total_pred_unsupported.
    """
    tp = fp = fn = 0
    for _claim, gold, pred in all_axis1:
        is_gold_pos = (gold == "unsupported")
        is_pred_pos = (pred == "unsupported")
        if is_gold_pos and is_pred_pos:
            tp += 1
        elif (not is_gold_pos) and is_pred_pos:
            fp += 1
        elif is_gold_pos and (not is_pred_pos):
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "total_gold_unsupported": tp + fn,
        "total_pred_unsupported": tp + fp,
    }


def _compute_axis1_confusion(all_axis1):
    """Compute a 4x4-ish summary of gold vs pred axis-1 labels.

    Returns dict: {(gold, pred): count} where pred may be None (no prediction).
    Pred None means the heuristic found no trigger-bearing sentence matching
    this gold claim, which typically means the heuristic missed it (false
    negative if gold==unsupported, or correctly ignored it if gold==supported).
    """
    counts = {}
    for _claim, gold, pred in all_axis1:
        key = (gold, pred if pred is not None else "(none)")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _compute_axis2_counts(all_axis2):
    """Count gold axis-2 category distribution and how many verdicts matched."""
    gold_counts = {}
    matched = 0
    for _claim, gold, pred in all_axis2:
        gold_counts[gold] = gold_counts.get(gold, 0) + 1
        if pred is not None:
            matched += 1
    return gold_counts, matched, len(all_axis2)


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

_SEP = "-" * 60
_WIDE_SEP = "=" * 60


def _fmt_metric(label, value):
    """Format a metric name and float value as a table row."""
    return "  %-28s  %.4f" % (label, value)


def _fmt_count(label, value):
    """Format a count row."""
    return "  %-28s  %d" % (label, value)


def print_report(axis1_metrics, axis1_confusion, axis2_gold_counts,
                 axis2_matched, axis2_total, n_items, n_gold_claims):
    """Print a readable metrics table to stdout."""
    print(_WIDE_SEP)
    print("claude-provenance v0 evaluation report")
    print(_WIDE_SEP)
    print()
    print("Corpus: %d items, %d gold claim entries" % (n_items, n_gold_claims))
    print()

    # -- Axis 1: unsupported detection F1 --
    print(_SEP)
    print("AXIS 1 -- v0 heuristic unsupported detection")
    print("  (positive class: gold label == 'unsupported')")
    print(_SEP)
    m = axis1_metrics
    print(_fmt_count("gold unsupported claims",    m["total_gold_unsupported"]))
    print(_fmt_count("predicted unsupported",       m["total_pred_unsupported"]))
    print(_fmt_count("true positives (TP)",         m["tp"]))
    print(_fmt_count("false positives (FP)",        m["fp"]))
    print(_fmt_count("false negatives (FN)",        m["fn"]))
    print()
    print(_fmt_metric("precision",  m["precision"]))
    print(_fmt_metric("recall",     m["recall"]))
    print(_fmt_metric("F1",         m["f1"]))
    print()

    # -- Axis 1: confusion summary --
    print(_SEP)
    print("AXIS 1 -- gold vs prediction breakdown")
    print(_SEP)
    print("  %-20s  %-20s  %s" % ("gold label", "predicted label", "count"))
    for (gold, pred), cnt in sorted(axis1_confusion.items()):
        print("  %-20s  %-20s  %d" % (gold, pred, cnt))
    print()

    # -- Axis 2: offline verdict distribution --
    print(_SEP)
    print("AXIS 2 -- offline verify_text verdict distribution")
    print("  (fetch=False; all verdicts come from the heuristic grader)")
    print(_SEP)
    print(_fmt_count("gold claim entries checked",  axis2_total))
    print(_fmt_count("matched to a verdict",        axis2_matched))
    print()
    print("  Gold axis-2 category distribution:")
    for cat in sorted(axis2_gold_counts):
        print("  %-28s  %d" % (cat, axis2_gold_counts[cat]))
    print()
    print(_WIDE_SEP)
    print("NOTE: metrics are computed from a small hand-built seed corpus.")
    print("Do not quote these numbers as general accuracy. See eval/README.md.")
    print(_WIDE_SEP)


# ---------------------------------------------------------------------------
# Grader corpus loading
# ---------------------------------------------------------------------------

_VALID_GRADER_GOLD = {"verified", "contradicted", "not_addressed", "unverifiable", "skipped"}


def load_grader_corpus(path) -> list:
    """Parse eval/corpus/grader.jsonl. SystemExit(1) on missing file,
    malformed JSON, empty file, missing required field (id, claim, gold),
    gold not in the 5-class set, duplicate id, or citation/source not
    (str or None).
    """
    p = Path(path)
    if not p.is_file():
        sys.stderr.write("ERROR: grader corpus file not found: %s\n" % path)
        sys.exit(1)

    items = []
    seen_ids = set()
    try:
        raw_text = p.read_text(encoding="utf-8")
    except Exception as exc:
        sys.stderr.write("ERROR: could not read grader corpus: %s\n" % exc)
        sys.exit(1)

    lines = raw_text.splitlines()
    non_empty = [ln.strip() for ln in lines if ln.strip()]
    if not non_empty:
        sys.stderr.write("ERROR: grader corpus file is empty\n")
        sys.exit(1)

    for lineno, raw in enumerate(lines, 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.stderr.write(
                "ERROR: grader corpus line %d is not valid JSON: %s\n" % (lineno, exc)
            )
            sys.exit(1)

        # Required fields.
        for field in ("id", "claim", "gold"):
            if field not in obj:
                sys.stderr.write(
                    "ERROR: grader corpus line %d missing required field %r\n"
                    % (lineno, field)
                )
                sys.exit(1)

        # Gold class validation.
        if obj["gold"] not in _VALID_GRADER_GOLD:
            sys.stderr.write(
                "ERROR: grader corpus line %d: gold value %r not in %s\n"
                % (lineno, obj["gold"], sorted(_VALID_GRADER_GOLD))
            )
            sys.exit(1)

        # Duplicate id check.
        item_id = obj["id"]
        if item_id in seen_ids:
            sys.stderr.write(
                "ERROR: grader corpus line %d: duplicate id %r\n" % (lineno, item_id)
            )
            sys.exit(1)
        seen_ids.add(item_id)

        # citation and source must be str or None (absent also counts as None).
        for field in ("citation", "source"):
            val = obj.get(field, None)
            if val is not None and not isinstance(val, str):
                sys.stderr.write(
                    "ERROR: grader corpus line %d: field %r must be a string or null, "
                    "got %r\n" % (lineno, field, type(val).__name__)
                )
                sys.exit(1)

        items.append(obj)

    return items


# ---------------------------------------------------------------------------
# Grader evaluation
# ---------------------------------------------------------------------------

def grade_grader_corpus(items, grader) -> list:
    """Return list of (id, gold, pred) tuples. pred is the
    Verdict.verdict string from grader.grade(claim, source, citation).
    """
    results = []
    for item in items:
        claim = item["claim"]
        # JSON null maps to Python None.
        src = item.get("source", None)
        cit = item.get("citation", None)
        try:
            verdict = grader.grade(claim, src, cit)
            pred = verdict.verdict
        except Exception:
            pred = "error"
        results.append((item["id"], item["gold"], pred))
    return results


# ---------------------------------------------------------------------------
# Grader metric computation
# ---------------------------------------------------------------------------

def compute_grader_metrics(results) -> dict:
    """results is the list from grade_grader_corpus. Returns a dict:
       {
         "per_class": { cls: {"tp":int,"fp":int,"fn":int,
                              "precision":float,"recall":float,
                              "f1":float,"support":int} for cls in 5 gold classes },
         "macro": {"precision":float,"recall":float,"f1":float},
         "accuracy": float,
         "confusion": { (gold,pred): int },   # pred may be 'error'
         "n": int
       }
    One-vs-rest per class: TP gold==c and pred==c; FP gold!=c and pred==c;
    FN gold==c and pred!=c. precision/recall/f1 = 0.0 when denominator 0.
    macro = unweighted mean over the 5 gold classes. accuracy = exact-match
    correct / n. All values computed at runtime; nothing hard-coded.
    """
    gold_classes = list(_VALID_GRADER_GOLD)  # the 5 canonical gold classes
    n = len(results)

    # Build confusion matrix and per-class counters.
    confusion = {}
    per_class = {c: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for c in gold_classes}

    for _id, gold, pred in results:
        key = (gold, pred)
        confusion[key] = confusion.get(key, 0) + 1
        if gold in per_class:
            per_class[gold]["support"] += 1
        for c in gold_classes:
            is_gold_c = (gold == c)
            is_pred_c = (pred == c)
            if is_gold_c and is_pred_c:
                per_class[c]["tp"] += 1
            elif (not is_gold_c) and is_pred_c:
                per_class[c]["fp"] += 1
            elif is_gold_c and (not is_pred_c):
                per_class[c]["fn"] += 1

    # Compute precision / recall / F1 per class.
    for c in gold_classes:
        d = per_class[c]
        tp, fp, fn = d["tp"], d["fp"], d["fn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        d["precision"] = precision
        d["recall"] = recall
        d["f1"] = f1

    # Macro averages (unweighted over the 5 gold classes).
    macro_precision = sum(per_class[c]["precision"] for c in gold_classes) / len(gold_classes)
    macro_recall = sum(per_class[c]["recall"] for c in gold_classes) / len(gold_classes)
    macro_f1 = sum(per_class[c]["f1"] for c in gold_classes) / len(gold_classes)

    # Overall accuracy.
    correct = sum(1 for _id, gold, pred in results if gold == pred)
    accuracy = correct / n if n > 0 else 0.0

    return {
        "per_class": per_class,
        "macro": {
            "precision": macro_precision,
            "recall": macro_recall,
            "f1": macro_f1,
        },
        "accuracy": accuracy,
        "confusion": confusion,
        "n": n,
    }


# ---------------------------------------------------------------------------
# Grader report printing
# ---------------------------------------------------------------------------

# Ordered list of gold classes for display (matches contract section 3).
_GRADER_CLASS_ORDER = [
    "verified",
    "contradicted",
    "not_addressed",
    "unverifiable",
    "skipped",
]

# Predicted labels include all gold labels plus 'error'.
_GRADER_PRED_ORDER = _GRADER_CLASS_ORDER + ["error"]


def print_grader_report(metrics, grader_label, n_items) -> None:
    """Print the grader report to stdout. Markers in section 6 are mandatory."""
    print(_WIDE_SEP)
    print("GRADER EVALUATION")
    print(_WIDE_SEP)
    print()
    print("Grader: %s" % grader_label)
    print("Corpus: %d items" % n_items)
    print()

    # Per-class precision / recall / F1.
    print(_SEP)
    print("per-class precision / recall / F1")
    print(_SEP)
    hdr = "  %-16s  %9s  %9s  %9s  %9s" % ("class", "precision", "recall", "F1", "support")
    print(hdr)
    for c in _GRADER_CLASS_ORDER:
        d = metrics["per_class"][c]
        print(
            "  %-16s  %9.4f  %9.4f  %9.4f  %9d"
            % (c, d["precision"], d["recall"], d["f1"], d["support"])
        )
    print()

    # Macro averages.
    m = metrics["macro"]
    print(_SEP)
    print("macro-avg")
    print(_SEP)
    print("  %-16s  %9.4f  %9.4f  %9.4f" % ("macro-avg", m["precision"], m["recall"], m["f1"]))
    print()

    # Overall accuracy.
    print(_SEP)
    print("overall accuracy")
    print(_SEP)
    print("  accuracy: %.4f  (%d / %d)" % (metrics["accuracy"], round(metrics["accuracy"] * metrics["n"]), metrics["n"]))
    print()

    # Confusion matrix (rows = gold, cols = predicted).
    print(_SEP)
    print("confusion matrix (rows = gold, cols = predicted)")
    print(_SEP)
    # Header row.
    col_w = 14
    header = "  %-16s" % "gold \\ pred"
    for pred_lbl in _GRADER_PRED_ORDER:
        header += ("  %-" + str(col_w) + "s") % pred_lbl
    print(header)
    for gold_lbl in _GRADER_CLASS_ORDER:
        row = "  %-16s" % gold_lbl
        for pred_lbl in _GRADER_PRED_ORDER:
            cnt = metrics["confusion"].get((gold_lbl, pred_lbl), 0)
            row += ("  %-" + str(col_w) + "d") % cnt
        print(row)
    print()

    # Caveat block: all three substrings required by contract section 6.
    print(_SEP)
    print(
        "NOTE: This evaluation is not a benchmark. Numbers are corpus-dependent\n"
        "and should not be quoted as general accuracy.\n"
        "Sources used are synthetic, self-contained sources that isolate grader\n"
        "reasoning from fetch reliability, which is a separate unmeasured axis.\n"
        "The HeuristicGrader cannot emit 'contradicted'; expect mislabelling on\n"
        "that gold block as a structural finding, not a defect."
    )
    print(_WIDE_SEP)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Evaluate the claude-provenance v0 heuristic against a labelled corpus."
    )
    parser.add_argument(
        "--corpus",
        default=str(_REPO_ROOT / "eval" / "corpus" / "seed.jsonl"),
        help="Path to the JSONL corpus file (default: eval/corpus/seed.jsonl).",
    )
    parser.add_argument(
        "--grader-corpus",
        default=str(_REPO_ROOT / "eval" / "corpus" / "grader.jsonl"),
        help="Path to the grader JSONL corpus file (default: eval/corpus/grader.jsonl).",
    )
    parser.add_argument(
        "--grader",
        choices=["heuristic", "llm", "both", "codex"],
        default="heuristic",
        help="Which grader to evaluate: heuristic (default), llm, both, or "
             "codex. 'codex' drives the cross-model CodexGrader via the local "
             "Codex CLI (evaluation only; requires the Codex CLI installed and "
             "authenticated; never auto-selected; not used in CI).",
    )
    args = parser.parse_args(argv)

    # Load corpus.
    items = load_corpus(args.corpus)

    # Load hook module and verify_text function.
    hook_mod = _load_hook()

    # Import verify_text from the installed provenance package.
    # We add the repo root to sys.path so the package resolves even without
    # pip install.
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

    from warrantos.provenance.verify import verify_text
    from warrantos.provenance.grade import HeuristicGrader, LLMGrader, CodexGrader

    grader = HeuristicGrader()

    # Evaluate each seed item.
    all_axis1 = []
    all_axis2 = []

    for item in items:
        result = _evaluate_item(item, hook_mod, verify_text, grader)
        all_axis1.extend(result["axis1_results"])
        all_axis2.extend(result["axis2_results"])

    # Compute metrics.
    axis1_metrics = _compute_axis1_metrics(all_axis1)
    axis1_confusion = _compute_axis1_confusion(all_axis1)
    axis2_gold_counts, axis2_matched, axis2_total = _compute_axis2_counts(all_axis2)

    n_items = len(items)
    n_gold_claims = len(all_axis1)

    # Print seed report.
    print_report(
        axis1_metrics,
        axis1_confusion,
        axis2_gold_counts,
        axis2_matched,
        axis2_total,
        n_items,
        n_gold_claims,
    )

    # ---------------------------------------------------------------------------
    # Grader evaluation section
    # ---------------------------------------------------------------------------

    grader_items = load_grader_corpus(args.grader_corpus)

    # Determine which graders to run.
    graders_to_run = []  # list of (grader_instance, grader_label)

    if args.grader in ("heuristic", "both"):
        graders_to_run.append((HeuristicGrader(), "HeuristicGrader"))

    if args.grader in ("llm", "both"):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            graders_to_run.append((LLMGrader(), "LLMGrader(model=%s)" % _get_llm_model_label()))
        else:
            print("LLM grader unavailable: ANTHROPIC_API_KEY is not set; "
                  "falling back to HeuristicGrader.")
            if args.grader == "llm":
                # For --grader llm with no key, run heuristic as fallback.
                graders_to_run.append((HeuristicGrader(), "HeuristicGrader"))
            # For --grader both, heuristic is already added above; no second block needed.

    if args.grader == "codex":
        graders_to_run.append((CodexGrader(), "CodexGrader(codex-cli)"))

    for grader_instance, grader_label in graders_to_run:
        results = grade_grader_corpus(grader_items, grader_instance)
        metrics = compute_grader_metrics(results)
        print_grader_report(metrics, grader_label, len(grader_items))

    return 0


def _get_llm_model_label() -> str:
    """Return the model label used by LLMGrader for display purposes."""
    # Mirror the default from provenance.grade without importing it at module level.
    return os.environ.get("PROVENANCE_GRADER_MODEL", "claude-haiku-4-5-20251001")


if __name__ == "__main__":
    sys.exit(main())
