#!/usr/bin/env python3
"""tests/test_eval.py: invariant tests for the eval harness and seed corpus.

Does NOT assert specific accuracy numbers -- those are corpus-dependent and
will change as the corpus grows. Instead, asserts:

  1. eval/run_eval.py runs on the seed corpus and exits 0.
  2. Every reported metric is within [0, 1].
  3. The corpus parses as JSONL and every axis-1/axis-2 value is from the
     allowed set.
  4. The v0 false-negative item (c10) is labelled unsupported, confirming
     that the closed bleeding-citation bug remains closed in the corpus.
  5. Grader evaluation: structural assertions added in v0.3.0 (see below).

All tests are offline and deterministic. No sleeps. No network. Standard
library only.

Run from the repo root:
    python -m unittest tests.test_eval -v
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Import conftest helpers to ensure subprocess isolation
from tests.conftest import get_clean_env

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EVAL_SCRIPT = _REPO_ROOT / "eval" / "run_eval.py"
_CORPUS = _REPO_ROOT / "eval" / "corpus" / "seed.jsonl"

# Allowed values for corpus gold labels.
_VALID_AXIS1 = {"supported", "unsupported", "tagged"}
_VALID_AXIS2 = {"verified", "unverifiable", "skipped", "na"}

# The item id for the v0 false-negative regression case.
# In seed.jsonl, c10 has a source three sentences after the claim, which must
# NOT rescue the claim. The gold label for that claim must be "unsupported".
_V0_FN_ITEM_ID = "c10"


# ---------------------------------------------------------------------------
# Helper: load run_eval as a module via importlib so we can call its functions
# directly for fine-grained assertions.
# ---------------------------------------------------------------------------

def _load_run_eval():
    spec = importlib.util.spec_from_file_location("run_eval", str(_EVAL_SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Test 1: the eval script runs on the seed corpus and exits 0.
# ---------------------------------------------------------------------------

class TestRunEvalExitsZero(unittest.TestCase):
    """eval/run_eval.py must exit 0 when run against the seed corpus."""

    def test_exits_zero_on_seed_corpus(self):
        result = subprocess.run(
            [sys.executable, str(_EVAL_SCRIPT)],
            capture_output=True,
            text=True,
            env=get_clean_env(),
        )
        self.assertEqual(
            result.returncode,
            0,
            "run_eval.py exited %d.\nstdout:\n%s\nstderr:\n%s"
            % (result.returncode, result.stdout, result.stderr),
        )

    def test_stdout_contains_metrics_table(self):
        """The script must print a non-empty metrics table to stdout."""
        result = subprocess.run(
            [sys.executable, str(_EVAL_SCRIPT)],
            capture_output=True,
            text=True,
            env=get_clean_env(),
        )
        self.assertIn("evaluation report", result.stdout)
        self.assertIn("precision", result.stdout)
        self.assertIn("recall", result.stdout)
        self.assertIn("F1", result.stdout)

    def test_exits_one_on_missing_corpus(self):
        """When the corpus file does not exist, run_eval must exit 1."""
        result = subprocess.run(
            [sys.executable, str(_EVAL_SCRIPT), "--corpus", "/does/not/exist.jsonl"],
            capture_output=True,
            text=True,
            env=get_clean_env(),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR", result.stderr)


# ---------------------------------------------------------------------------
# Test 2: every reported metric is within [0, 1].
# ---------------------------------------------------------------------------

class TestMetricsInRange(unittest.TestCase):
    """All reported float metrics must be in [0, 1]."""

    def _get_metrics(self):
        """Run the harness and return the computed axis-1 metrics dict."""
        run_eval = _load_run_eval()
        items = run_eval.load_corpus(str(_CORPUS))

        # Re-create the evaluation pipeline from run_eval internals.
        hook_mod = run_eval._load_hook()

        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from warrantos.provenance.verify import verify_text
        from warrantos.provenance.grade import HeuristicGrader

        grader = HeuristicGrader()
        all_axis1 = []
        all_axis2 = []
        for item in items:
            result = run_eval._evaluate_item(item, hook_mod, verify_text, grader)
            all_axis1.extend(result["axis1_results"])
            all_axis2.extend(result["axis2_results"])

        return run_eval._compute_axis1_metrics(all_axis1)

    def test_precision_in_range(self):
        m = self._get_metrics()
        self.assertGreaterEqual(m["precision"], 0.0)
        self.assertLessEqual(m["precision"], 1.0)

    def test_recall_in_range(self):
        m = self._get_metrics()
        self.assertGreaterEqual(m["recall"], 0.0)
        self.assertLessEqual(m["recall"], 1.0)

    def test_f1_in_range(self):
        m = self._get_metrics()
        self.assertGreaterEqual(m["f1"], 0.0)
        self.assertLessEqual(m["f1"], 1.0)


# ---------------------------------------------------------------------------
# Test 3: corpus parses as JSONL and all label values are from the allowed set.
# ---------------------------------------------------------------------------

class TestCorpusValidity(unittest.TestCase):
    """Structural validity of eval/corpus/seed.jsonl."""

    def _load(self):
        items = []
        for lineno, raw in enumerate(
            _CORPUS.read_text(encoding="utf-8").splitlines(), 1
        ):
            raw = raw.strip()
            if not raw:
                continue
            try:
                items.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                self.fail("Line %d is not valid JSON: %s" % (lineno, exc))
        return items

    def test_corpus_is_non_empty(self):
        items = self._load()
        self.assertGreater(len(items), 0, "corpus must contain at least one item")

    def test_required_fields_present(self):
        items = self._load()
        for item in items:
            for field in ("id", "text", "gold"):
                self.assertIn(
                    field,
                    item,
                    "item %r missing required field %r" % (item.get("id", "?"), field),
                )

    def test_axis1_values_are_valid(self):
        items = self._load()
        for item in items:
            for g in item["gold"]:
                self.assertIn(
                    g.get("axis1"),
                    _VALID_AXIS1,
                    "item %r has invalid axis1 value %r" % (item["id"], g.get("axis1")),
                )

    def test_axis2_values_are_valid(self):
        items = self._load()
        for item in items:
            for g in item["gold"]:
                self.assertIn(
                    g.get("axis2"),
                    _VALID_AXIS2,
                    "item %r has invalid axis2 value %r" % (item["id"], g.get("axis2")),
                )

    def test_ids_are_unique(self):
        items = self._load()
        ids = [item["id"] for item in items]
        self.assertEqual(len(ids), len(set(ids)), "corpus contains duplicate ids")

    def test_gold_is_list(self):
        items = self._load()
        for item in items:
            self.assertIsInstance(
                item["gold"],
                list,
                "item %r: 'gold' must be a list" % item["id"],
            )


# ---------------------------------------------------------------------------
# Test 4: the v0 false-negative item is labelled unsupported.
# ---------------------------------------------------------------------------

class TestV0FalseNegativeLabelled(unittest.TestCase):
    """The v0 false-negative regression item must be labelled unsupported.

    Item c10 has a source URL three sentences after the claim. The v0 heuristic
    only looks one sentence ahead (citation-lead). The gold label must remain
    'unsupported' to confirm the bleeding-citation bug stays closed in the
    corpus and that the harness correctly exercises it.
    """

    def test_v0_fn_item_exists(self):
        items = [
            json.loads(l)
            for l in _CORPUS.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        ids = [item["id"] for item in items]
        self.assertIn(
            _V0_FN_ITEM_ID,
            ids,
            "Expected v0 false-negative item %r in corpus" % _V0_FN_ITEM_ID,
        )

    def test_v0_fn_claim_is_unsupported(self):
        items = [
            json.loads(l)
            for l in _CORPUS.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        item = next((i for i in items if i["id"] == _V0_FN_ITEM_ID), None)
        self.assertIsNotNone(item, "Item %r not found" % _V0_FN_ITEM_ID)
        # At least one gold entry must have axis1 == "unsupported".
        unsupported_entries = [g for g in item["gold"] if g["axis1"] == "unsupported"]
        self.assertGreater(
            len(unsupported_entries),
            0,
            "Item %r must have at least one gold entry with axis1='unsupported'; "
            "got: %r" % (_V0_FN_ITEM_ID, [g["axis1"] for g in item["gold"]]),
        )

    def test_v0_fn_heuristic_predicts_unsupported(self):
        """The v0 heuristic itself must predict unsupported for item c10.

        This confirms the test corpus entry is exercising the heuristic
        in the expected direction, not just asserting a vacuous label.
        """
        spec = importlib.util.spec_from_file_location(
            "_hook", str(_REPO_ROOT / "warrantos" / "hooks" / "provenance_check.py")
        )
        hook_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook_mod)

        items = [
            json.loads(l)
            for l in _CORPUS.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        item = next((i for i in items if i["id"] == _V0_FN_ITEM_ID), None)
        self.assertIsNotNone(item)

        rows, _totals = hook_mod.analyse(item["text"])
        # There must be at least one predicted row, and it must be unsupported
        # (the heuristic must not have mistakenly treated the distant source
        # as an adjacent citation-lead).
        statuses = [r[0] for r in rows]
        self.assertIn(
            "unsupported",
            statuses,
            "v0 heuristic should predict 'unsupported' for item %r "
            "(source is two sentences away); got: %r" % (_V0_FN_ITEM_ID, statuses),
        )


# ---------------------------------------------------------------------------
# Constants for grader-evaluation tests (v0.3.0 additions).
# ---------------------------------------------------------------------------

_GRADER_CORPUS = _REPO_ROOT / "eval" / "corpus" / "grader.jsonl"

# Gold class set for the grader corpus (five classes; 'error' is prediction-only).
_VALID_GRADER_GOLD = {
    "verified",
    "contradicted",
    "not_addressed",
    "unverifiable",
    "skipped",
}

# All valid predicted labels (gold set plus 'error' which graders may emit).
_VALID_GRADER_PRED = _VALID_GRADER_GOLD | {"error"}

# Number of items the contract specifies in grader.jsonl.
_GRADER_CORPUS_SIZE = 60

# Unique spec name for importlib loads in these tests. Using a name that
# does not collide with the "run_eval" name used by the existing
# _load_run_eval() helper, which is the source of the prior leak.
_GRADER_SPEC_NAME = "_grader_eval_harness_v030"


def _load_run_eval_isolated(spec_name=_GRADER_SPEC_NAME):
    """Load run_eval.py under a unique spec name and return (mod, inserted_keys).

    inserted_keys is the set of sys.modules keys that were added during the
    load, so the caller can clean them up in tearDown.
    """
    before = set(sys.modules.keys())
    spec = importlib.util.spec_from_file_location(spec_name, str(_EVAL_SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    # Register under the spec name before exec so relative imports resolve.
    sys.modules[spec_name] = mod
    spec.loader.exec_module(mod)
    after = set(sys.modules.keys())
    inserted = after - before
    return mod, inserted


# ---------------------------------------------------------------------------
# Test 5: CLI -- grader evaluation report appears in no-args run.
# ---------------------------------------------------------------------------

class TestGraderEvalCLINoArgs(unittest.TestCase):
    """run_eval.py with no args must include grader report markers in stdout."""

    def setUp(self):
        self._result = subprocess.run(
            [sys.executable, str(_EVAL_SCRIPT)],
            capture_output=True,
            text=True,
            env=get_clean_env(),
        )

    def test_exits_zero(self):
        self.assertEqual(
            self._result.returncode,
            0,
            "run_eval.py exited %d.\nstdout:\n%s\nstderr:\n%s"
            % (
                self._result.returncode,
                self._result.stdout,
                self._result.stderr,
            ),
        )

    # --- Preserved existing markers must still appear. ---

    def test_preserved_report_header(self):
        self.assertIn("claude-provenance v0 evaluation report", self._result.stdout)

    def test_preserved_axis1_marker(self):
        self.assertIn("AXIS 1", self._result.stdout)

    def test_preserved_axis2_marker(self):
        self.assertIn("AXIS 2", self._result.stdout)

    def test_preserved_precision_marker(self):
        self.assertIn("precision", self._result.stdout)

    def test_preserved_recall_marker(self):
        self.assertIn("recall", self._result.stdout)

    def test_preserved_f1_marker(self):
        self.assertIn("F1", self._result.stdout)

    # --- New grader report markers required by contract section 6. ---

    def test_grader_evaluation_marker(self):
        self.assertIn("GRADER EVALUATION", self._result.stdout)

    def test_per_class_precision_recall_f1_marker(self):
        self.assertIn("per-class precision / recall / F1", self._result.stdout)

    def test_macro_avg_marker(self):
        self.assertIn("macro-avg", self._result.stdout)

    def test_overall_accuracy_marker(self):
        self.assertIn("overall accuracy", self._result.stdout)

    def test_confusion_matrix_marker(self):
        self.assertIn(
            "confusion matrix (rows = gold, cols = predicted)", self._result.stdout
        )

    def test_caveat_not_a_benchmark(self):
        self.assertIn("not a benchmark", self._result.stdout)

    def test_caveat_synthetic_self_contained_sources(self):
        self.assertIn("synthetic, self-contained sources", self._result.stdout)

    def test_caveat_corpus_dependent(self):
        self.assertIn("corpus-dependent", self._result.stdout)


# ---------------------------------------------------------------------------
# Test 6: CLI -- --grader both exits 0 and includes LLM unavailable notice.
# ---------------------------------------------------------------------------

class TestGraderEvalCLIBoth(unittest.TestCase):
    """--grader both must exit 0 and print the LLM unavailable notice in CI."""

    def setUp(self):
        # Use clean environment (no ANTHROPIC_API_KEY, CLAUDE_HOME, etc.)
        # so LLMGrader and ClaudeCliGrader fall back to heuristic.
        self._result = subprocess.run(
            [sys.executable, str(_EVAL_SCRIPT), "--grader", "both"],
            capture_output=True,
            text=True,
            env=get_clean_env(),
        )

    def test_exits_zero(self):
        self.assertEqual(
            self._result.returncode,
            0,
            "run_eval.py --grader both exited %d.\nstdout:\n%s\nstderr:\n%s"
            % (
                self._result.returncode,
                self._result.stdout,
                self._result.stderr,
            ),
        )

    def test_llm_grader_unavailable_notice(self):
        """Without ANTHROPIC_API_KEY the LLM unavailable notice must appear."""
        combined = self._result.stdout + self._result.stderr
        self.assertIn(
            "LLM grader unavailable",
            combined,
            "Expected 'LLM grader unavailable' in output when no API key is set.",
        )

    def test_grader_evaluation_marker_still_present(self):
        self.assertIn("GRADER EVALUATION", self._result.stdout)


# ---------------------------------------------------------------------------
# Test 7: CLI -- --grader-corpus /does/not/exist.jsonl exits 1 with ERROR.
# ---------------------------------------------------------------------------

class TestGraderCorpusMissing(unittest.TestCase):
    """--grader-corpus pointing to a non-existent file must exit 1 with ERROR."""

    def test_exits_one_on_missing_grader_corpus(self):
        result = subprocess.run(
            [
                sys.executable,
                str(_EVAL_SCRIPT),
                "--grader-corpus",
                "/does/not/exist.jsonl",
            ],
            capture_output=True,
            text=True,
            env=get_clean_env(),
        )
        self.assertEqual(
            result.returncode,
            1,
            "Expected exit code 1 for missing grader corpus, got %d.\n"
            "stdout:\n%s\nstderr:\n%s"
            % (result.returncode, result.stdout, result.stderr),
        )
        self.assertIn(
            "ERROR",
            result.stderr,
            "Expected 'ERROR' on stderr for missing grader corpus.",
        )


# ---------------------------------------------------------------------------
# Test 8: grader corpus structural validity.
# ---------------------------------------------------------------------------

class TestGraderCorpusValidity(unittest.TestCase):
    """Structural validity of eval/corpus/grader.jsonl."""

    def _load(self):
        items = []
        for lineno, raw in enumerate(
            _GRADER_CORPUS.read_text(encoding="utf-8").splitlines(), 1
        ):
            raw = raw.strip()
            if not raw:
                continue
            try:
                items.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                self.fail("grader.jsonl line %d is not valid JSON: %s" % (lineno, exc))
        return items

    def test_corpus_parses_as_jsonl(self):
        items = self._load()
        self.assertGreater(len(items), 0, "grader.jsonl must not be empty")

    def test_corpus_has_expected_size(self):
        items = self._load()
        self.assertEqual(
            len(items),
            _GRADER_CORPUS_SIZE,
            "grader.jsonl must contain %d items; found %d"
            % (_GRADER_CORPUS_SIZE, len(items)),
        )

    def test_ids_are_unique(self):
        items = self._load()
        ids = [item["id"] for item in items]
        self.assertEqual(
            len(ids),
            len(set(ids)),
            "grader.jsonl contains duplicate ids",
        )

    def test_ids_follow_gxxx_pattern(self):
        items = self._load()
        for item in items:
            self.assertTrue(
                item["id"].startswith("g"),
                "id %r does not start with 'g'" % item["id"],
            )

    def test_required_fields_present(self):
        items = self._load()
        for item in items:
            for field in ("id", "claim", "gold"):
                self.assertIn(
                    field,
                    item,
                    "grader.jsonl item %r missing required field %r"
                    % (item.get("id", "?"), field),
                )

    def test_gold_values_in_five_class_set(self):
        items = self._load()
        for item in items:
            self.assertIn(
                item["gold"],
                _VALID_GRADER_GOLD,
                "item %r has invalid gold value %r" % (item["id"], item["gold"]),
            )

    def test_citation_is_str_or_none(self):
        items = self._load()
        for item in items:
            val = item.get("citation", None)
            self.assertIn(
                type(val),
                (str, type(None)),
                "item %r: 'citation' must be str or None, got %r"
                % (item["id"], type(val).__name__),
            )

    def test_source_is_str_or_none(self):
        items = self._load()
        for item in items:
            val = item.get("source", None)
            self.assertIn(
                type(val),
                (str, type(None)),
                "item %r: 'source' must be str or None, got %r"
                % (item["id"], type(val).__name__),
            )

    def test_at_least_one_contradicted(self):
        """The structural blindness of HeuristicGrader must actually be exercised."""
        items = self._load()
        contradicted = [i for i in items if i["gold"] == "contradicted"]
        self.assertGreater(
            len(contradicted),
            0,
            "grader.jsonl must contain at least one 'contradicted' gold item "
            "so the structural blindness of HeuristicGrader is exercised.",
        )

    def test_all_five_gold_classes_present(self):
        """Every gold class must appear at least once."""
        items = self._load()
        present = {i["gold"] for i in items}
        for cls in _VALID_GRADER_GOLD:
            self.assertIn(
                cls,
                present,
                "grader.jsonl has no item with gold='%s'; all five classes must be present." % cls,
            )


# ---------------------------------------------------------------------------
# Test 9: direct function calls -- load_grader_corpus, grade_grader_corpus,
# compute_grader_metrics.
# ---------------------------------------------------------------------------

class TestGraderFunctionsDirectly(unittest.TestCase):
    """Call new public functions from run_eval.py directly (contract section 5)."""

    def setUp(self):
        # Ensure the provenance package is importable.
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        self._mod, self._inserted = _load_run_eval_isolated()

    def tearDown(self):
        # Remove every sys.modules key that was inserted by the load.
        for key in list(self._inserted):
            sys.modules.pop(key, None)

    # -- load_grader_corpus --

    def test_load_grader_corpus_returns_60_items(self):
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        self.assertEqual(
            len(items),
            _GRADER_CORPUS_SIZE,
            "load_grader_corpus must return %d items; got %d"
            % (_GRADER_CORPUS_SIZE, len(items)),
        )

    def test_load_grader_corpus_items_have_required_fields(self):
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        for item in items:
            for field in ("id", "claim", "gold"):
                self.assertIn(
                    field,
                    item,
                    "item %r missing required field %r" % (item.get("id", "?"), field),
                )

    def test_load_grader_corpus_gold_values_valid(self):
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        for item in items:
            self.assertIn(
                item["gold"],
                _VALID_GRADER_GOLD,
                "item %r has invalid gold value %r" % (item["id"], item["gold"]),
            )

    # -- grade_grader_corpus --

    def test_grade_grader_corpus_returns_one_tuple_per_item(self):
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        self.assertEqual(
            len(results),
            len(items),
            "grade_grader_corpus must return one tuple per item",
        )

    def test_grade_grader_corpus_tuples_have_three_elements(self):
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        for tup in results:
            self.assertEqual(
                len(tup),
                3,
                "Each result tuple must be (id, gold, pred); got length %d" % len(tup),
            )

    def test_grade_grader_corpus_pred_in_valid_set(self):
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        for item_id, gold, pred in results:
            self.assertIn(
                pred,
                _VALID_GRADER_PRED,
                "item %r: pred %r is not in valid label set %s"
                % (item_id, pred, sorted(_VALID_GRADER_PRED)),
            )

    def test_grade_grader_corpus_gold_preserved(self):
        """gold in each result tuple must match the corpus gold label."""
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        by_id = {item["id"]: item["gold"] for item in items}
        for item_id, gold, _pred in results:
            self.assertEqual(
                gold,
                by_id[item_id],
                "item %r: gold in result %r does not match corpus gold %r"
                % (item_id, gold, by_id[item_id]),
            )

    # -- compute_grader_metrics --

    def test_compute_grader_metrics_n_equals_corpus_size(self):
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        metrics = self._mod.compute_grader_metrics(results)
        self.assertEqual(
            metrics["n"],
            _GRADER_CORPUS_SIZE,
            "compute_grader_metrics n must equal the corpus size; got %d" % metrics["n"],
        )

    def test_compute_grader_metrics_accuracy_in_range(self):
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        metrics = self._mod.compute_grader_metrics(results)
        acc = metrics["accuracy"]
        self.assertGreaterEqual(acc, 0.0, "accuracy must be >= 0.0")
        self.assertLessEqual(acc, 1.0, "accuracy must be <= 1.0")

    def test_compute_grader_metrics_per_class_keys_present(self):
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        metrics = self._mod.compute_grader_metrics(results)
        per_class = metrics["per_class"]
        for cls in _VALID_GRADER_GOLD:
            self.assertIn(
                cls,
                per_class,
                "per_class must contain entry for gold class %r" % cls,
            )

    def test_compute_grader_metrics_per_class_metric_keys(self):
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        metrics = self._mod.compute_grader_metrics(results)
        required_keys = {"tp", "fp", "fn", "precision", "recall", "f1", "support"}
        for cls in _VALID_GRADER_GOLD:
            entry = metrics["per_class"][cls]
            for key in required_keys:
                self.assertIn(
                    key,
                    entry,
                    "per_class[%r] missing key %r" % (cls, key),
                )

    def test_compute_grader_metrics_per_class_floats_in_range(self):
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        metrics = self._mod.compute_grader_metrics(results)
        for cls in _VALID_GRADER_GOLD:
            entry = metrics["per_class"][cls]
            for metric_name in ("precision", "recall", "f1"):
                val = entry[metric_name]
                self.assertGreaterEqual(
                    val, 0.0,
                    "per_class[%r][%r] must be >= 0.0; got %r" % (cls, metric_name, val),
                )
                self.assertLessEqual(
                    val, 1.0,
                    "per_class[%r][%r] must be <= 1.0; got %r" % (cls, metric_name, val),
                )

    def test_compute_grader_metrics_macro_keys_present(self):
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        metrics = self._mod.compute_grader_metrics(results)
        macro = metrics["macro"]
        for key in ("precision", "recall", "f1"):
            self.assertIn(key, macro, "macro dict missing key %r" % key)

    def test_compute_grader_metrics_macro_floats_in_range(self):
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        metrics = self._mod.compute_grader_metrics(results)
        for key in ("precision", "recall", "f1"):
            val = metrics["macro"][key]
            self.assertGreaterEqual(val, 0.0, "macro[%r] must be >= 0.0; got %r" % (key, val))
            self.assertLessEqual(val, 1.0, "macro[%r] must be <= 1.0; got %r" % (key, val))

    def test_compute_grader_metrics_confusion_matrix_row_sums(self):
        """Each confusion matrix row (gold class) must sum to that class's support."""
        from warrantos.provenance.grade import HeuristicGrader
        items = self._mod.load_grader_corpus(str(_GRADER_CORPUS))
        results = self._mod.grade_grader_corpus(items, HeuristicGrader())
        metrics = self._mod.compute_grader_metrics(results)
        confusion = metrics["confusion"]
        for cls in _VALID_GRADER_GOLD:
            expected_support = metrics["per_class"][cls]["support"]
            row_sum = sum(
                v for (gold, _pred), v in confusion.items() if gold == cls
            )
            self.assertEqual(
                row_sum,
                expected_support,
                "Confusion matrix row for gold=%r sums to %d but support is %d"
                % (cls, row_sum, expected_support),
            )


# ---------------------------------------------------------------------------
# Test 10: load_grader_corpus raises SystemExit(1) on malformed corpus.
# ---------------------------------------------------------------------------

class TestLoadGraderCorpusMalformed(unittest.TestCase):
    """load_grader_corpus must raise SystemExit(1) on a malformed temp corpus."""

    def setUp(self):
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        self._mod, self._inserted = _load_run_eval_isolated()
        self._tmpfile = None

    def tearDown(self):
        for key in list(self._inserted):
            sys.modules.pop(key, None)
        if self._tmpfile is not None:
            try:
                os.unlink(self._tmpfile)
            except OSError:
                pass

    def _write_temp_corpus(self, content):
        fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="test_grader_malformed_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
        except Exception:
            os.unlink(path)
            raise
        self._tmpfile = path
        return path

    def test_raises_systemexit_on_invalid_json_line(self):
        path = self._write_temp_corpus("THIS IS NOT JSON\n")
        with self.assertRaises(SystemExit) as ctx:
            self._mod.load_grader_corpus(path)
        self.assertEqual(
            ctx.exception.code,
            1,
            "load_grader_corpus must exit with code 1 on invalid JSON; got %r"
            % ctx.exception.code,
        )

    def test_raises_systemexit_on_missing_required_field(self):
        """A line missing the 'gold' field must trigger SystemExit(1)."""
        bad_line = json.dumps({"id": "g001", "claim": "Some claim."}) + "\n"
        path = self._write_temp_corpus(bad_line)
        with self.assertRaises(SystemExit) as ctx:
            self._mod.load_grader_corpus(path)
        self.assertEqual(
            ctx.exception.code,
            1,
            "load_grader_corpus must exit with code 1 on missing required field; got %r"
            % ctx.exception.code,
        )

    def test_raises_systemexit_on_invalid_gold_value(self):
        """A line with an unrecognised gold label must trigger SystemExit(1)."""
        bad_line = json.dumps({
            "id": "g001",
            "claim": "Some claim.",
            "gold": "INVALID_LABEL",
            "citation": None,
            "source": None,
        }) + "\n"
        path = self._write_temp_corpus(bad_line)
        with self.assertRaises(SystemExit) as ctx:
            self._mod.load_grader_corpus(path)
        self.assertEqual(
            ctx.exception.code,
            1,
            "load_grader_corpus must exit with code 1 on invalid gold value; got %r"
            % ctx.exception.code,
        )

    def test_raises_systemexit_on_empty_file(self):
        """An empty corpus file must trigger SystemExit(1)."""
        path = self._write_temp_corpus("")
        with self.assertRaises(SystemExit) as ctx:
            self._mod.load_grader_corpus(path)
        self.assertEqual(
            ctx.exception.code,
            1,
            "load_grader_corpus must exit with code 1 on empty file; got %r"
            % ctx.exception.code,
        )

    def test_raises_systemexit_on_missing_file(self):
        """A non-existent path must trigger SystemExit(1)."""
        with self.assertRaises(SystemExit) as ctx:
            self._mod.load_grader_corpus("/does/not/exist_grader_test.jsonl")
        self.assertEqual(
            ctx.exception.code,
            1,
            "load_grader_corpus must exit with code 1 on missing file; got %r"
            % ctx.exception.code,
        )

    def test_raises_systemexit_on_duplicate_id(self):
        """Two items with the same id must trigger SystemExit(1)."""
        good_line = json.dumps({
            "id": "g001",
            "claim": "Some claim.",
            "gold": "verified",
            "citation": None,
            "source": "Source text with some claim tokens.",
        })
        dup_line = json.dumps({
            "id": "g001",
            "claim": "Another claim.",
            "gold": "skipped",
            "citation": None,
            "source": None,
        })
        path = self._write_temp_corpus(good_line + "\n" + dup_line + "\n")
        with self.assertRaises(SystemExit) as ctx:
            self._mod.load_grader_corpus(path)
        self.assertEqual(
            ctx.exception.code,
            1,
            "load_grader_corpus must exit with code 1 on duplicate id; got %r"
            % ctx.exception.code,
        )


# ---------------------------------------------------------------------------
# Test 11: end-to-end main() invoked in-process with stdout captured.
# ---------------------------------------------------------------------------

class TestMainInProcess(unittest.TestCase):
    """Call main() directly in-process (no subprocess) and assert all mandatory
    stdout markers from contract section 6 are present."""

    def setUp(self):
        # Ensure the provenance package is importable.
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        self._mod, self._inserted = _load_run_eval_isolated(
            spec_name="_grader_eval_harness_inprocess"
        )
        self._orig_stdout = sys.stdout

    def tearDown(self):
        # Restore stdout in case the test left it redirected.
        sys.stdout = self._orig_stdout
        for key in list(self._inserted):
            sys.modules.pop(key, None)

    def _run_main_capturing_stdout(self, argv=None):
        """Call main(argv), capture stdout, return (captured_text, exit_code).

        Catches SystemExit so the calling test is not aborted.
        exit_code is the .code attribute of SystemExit, or None if main()
        returned normally (which counts as exit 0 per contract section 8).
        """
        buf = io.StringIO()
        exit_code = None
        sys.stdout = buf
        try:
            ret = self._mod.main(argv)
            # main() returns 0 on success; treat a normal return as exit 0.
            exit_code = ret if ret is not None else 0
        except SystemExit as exc:
            exit_code = exc.code
        finally:
            sys.stdout = self._orig_stdout
        return buf.getvalue(), exit_code

    # Pass an explicit empty argv so argparse uses defaults rather than
    # reading sys.argv (which contains unittest discover args in test mode).
    _DEFAULT_ARGV = []

    def test_main_exits_zero_with_default_args(self):
        """main() with default args (heuristic grader) must exit 0."""
        _output, exit_code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn(
            exit_code,
            (0, None),
            "main() must exit 0 on success; got exit_code=%r" % exit_code,
        )

    # --- Preserved markers (contract section 6, existing). ---

    def test_main_stdout_contains_report_header(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("claude-provenance v0 evaluation report", output)

    def test_main_stdout_contains_axis1(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("AXIS 1", output)

    def test_main_stdout_contains_axis2(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("AXIS 2", output)

    def test_main_stdout_contains_precision(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("precision", output)

    def test_main_stdout_contains_recall(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("recall", output)

    def test_main_stdout_contains_f1(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("F1", output)

    # --- New grader markers (contract section 6). ---

    def test_main_stdout_contains_grader_evaluation(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("GRADER EVALUATION", output)

    def test_main_stdout_contains_grader_label(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("Grader: ", output)

    def test_main_stdout_contains_per_class_header(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("per-class precision / recall / F1", output)

    def test_main_stdout_contains_macro_avg(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("macro-avg", output)

    def test_main_stdout_contains_overall_accuracy(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("overall accuracy", output)

    def test_main_stdout_contains_confusion_matrix(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("confusion matrix (rows = gold, cols = predicted)", output)

    def test_main_stdout_caveat_not_a_benchmark(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("not a benchmark", output)

    def test_main_stdout_caveat_synthetic_sources(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("synthetic, self-contained sources", output)

    def test_main_stdout_caveat_corpus_dependent(self):
        output, _code = self._run_main_capturing_stdout(self._DEFAULT_ARGV)
        self.assertIn("corpus-dependent", output)


# ---------------------------------------------------------------------------
# Test 12: --grader llm with ANTHROPIC_API_KEY absent -- in-process unit test.
# ---------------------------------------------------------------------------

class TestLLMGraderKeyAbsentInProcess(unittest.TestCase):
    """When ANTHROPIC_API_KEY is absent, --grader llm must:
    - print a notice containing 'LLM grader unavailable'
    - not raise
    - exit 0 (contract section 8)
    """

    def setUp(self):
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        self._mod, self._inserted = _load_run_eval_isolated(
            spec_name="_grader_eval_harness_llmabsent"
        )
        # Preserve original stdout and any existing ANTHROPIC_API_KEY value.
        self._orig_stdout = sys.stdout
        self._saved_api_key = os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        sys.stdout = self._orig_stdout
        for key in list(self._inserted):
            sys.modules.pop(key, None)
        # Restore ANTHROPIC_API_KEY to its original value if it existed.
        if self._saved_api_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = self._saved_api_key
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    def _run_main_no_key(self, argv=None):
        """Run main() with ANTHROPIC_API_KEY absent. Returns (output, exit_code)."""
        buf = io.StringIO()
        exit_code = None
        sys.stdout = buf
        try:
            ret = self._mod.main(argv)
            exit_code = ret if ret is not None else 0
        except SystemExit as exc:
            exit_code = exc.code
        finally:
            sys.stdout = self._orig_stdout
        return buf.getvalue(), exit_code

    # Pass explicit argv to prevent argparse from reading sys.argv in test mode.
    _LLM_ARGV = ["--grader", "llm"]

    def test_llm_key_absent_does_not_raise(self):
        """With no API key, --grader llm must not raise an unhandled exception."""
        try:
            output, _code = self._run_main_no_key(self._LLM_ARGV)
        except Exception as exc:
            self.fail(
                "--grader llm with no API key raised an unexpected exception: %r" % exc
            )

    def test_llm_key_absent_exits_zero(self):
        """With no API key, --grader llm must exit 0 (contract section 8)."""
        _output, exit_code = self._run_main_no_key(self._LLM_ARGV)
        self.assertIn(
            exit_code,
            (0, None),
            "--grader llm with no API key must exit 0; got exit_code=%r" % exit_code,
        )

    def test_llm_key_absent_prints_unavailable_notice(self):
        """With no API key, --grader llm must print 'LLM grader unavailable'."""
        output, _code = self._run_main_no_key(self._LLM_ARGV)
        self.assertIn(
            "LLM grader unavailable",
            output,
            "Expected 'LLM grader unavailable' in stdout when ANTHROPIC_API_KEY "
            "is absent and --grader llm is requested.\nActual output:\n%s" % output,
        )

    def test_llm_key_absent_still_produces_grader_report(self):
        """Even without API key, --grader llm must still produce a grader report
        (heuristic fallback) and include the mandatory GRADER EVALUATION marker."""
        output, _code = self._run_main_no_key(self._LLM_ARGV)
        self.assertIn(
            "GRADER EVALUATION",
            output,
            "GRADER EVALUATION marker must appear even when LLM is unavailable.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
