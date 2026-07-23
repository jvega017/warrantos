#!/usr/bin/env python3
"""Measure citation-trigger fire rate on ordinary English prose.

Purpose: WarrantOS's CLAIM_TRIGGERS patterns have only been measured for recall
on a curated policy corpus. This script measures how often they fire on ordinary,
non-policy English prose as a proxy upper bound for the false-positive rate that
determines whether enforce mode is usable.

Method: Gather documentation (README, package docs) from Python site-packages
and /usr/share/doc, then measure trigger fire rates across sentences.

Interpretation: Package documentation is presumed to contain few checkable factual
claims of the kind WarrantOS targets, so the fire rate approximates an upper bound
on false positives. This is a proxy measurement, not a labeled evaluation, and some
fires may be legitimate (e.g. real years in changelogs, version numbers).
"""

import sys
import os
import glob
import site
import sysconfig
from pathlib import Path
from collections import defaultdict


def find_documentation_files(max_files=500):
    """Gather METADATA files, .md, .rst files from site-packages and /usr/share/doc.

    METADATA files: extract text after first blank line (skip if < 200 chars).
    Skips /workspace/warrantos and caps at max_files for runtime.
    Returns list of file paths.
    """
    candidates = []
    warrantos_root = Path("/workspace/warrantos").resolve()

    # Collect potential directories to search.
    search_dirs = []

    # site-packages directories
    if site.getsitepackages():
        search_dirs.extend(site.getsitepackages())

    # User site-packages
    user_site = site.getusersitepackages()
    if user_site:
        search_dirs.append(user_site)

    # sysconfig site-packages paths
    for scheme in ["stdlib", "platstdlib", "purelib", "platlib"]:
        try:
            path = sysconfig.get_path(scheme)
            if path and path not in search_dirs:
                search_dirs.append(path)
        except (KeyError, AttributeError):
            pass

    # /usr/share/doc if present
    if Path("/usr/share/doc").exists():
        search_dirs.append("/usr/share/doc")

    # Deduplicate
    search_dirs = list(set(search_dirs))

    # First, gather METADATA files from dist-info directories
    for search_dir in search_dirs:
        search_dir_path = Path(search_dir)
        if not search_dir_path.exists():
            continue

        try:
            for metadata_path in search_dir_path.glob("**/*.dist-info/METADATA"):
                if not metadata_path.is_file():
                    continue

                # Skip warrantos files, including warrantos's own installed
                # dist-info: its long description is the WarrantOS README,
                # which would contaminate the "ordinary prose" corpus.
                if warrantos_root in metadata_path.resolve().parents:
                    continue
                if metadata_path.parent.name.lower().startswith("warrantos"):
                    continue

                # Extract body (text after first blank line)
                try:
                    with open(metadata_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    # Find the first blank line (email-style headers separator)
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1:
                        body = parts[1].strip()
                        # Skip if body is too short
                        if len(body) >= 200:
                            candidates.append(str(metadata_path))
                            if len(candidates) >= max_files:
                                return candidates[:max_files]
                except (UnicodeDecodeError, PermissionError, OSError):
                    continue
        except (PermissionError, OSError, RuntimeError):
            continue

    # Then gather markdown and rst files
    patterns = ["**/*.md", "**/*.rst", "**/README*"]
    for search_dir in search_dirs:
        search_dir_path = Path(search_dir)
        if not search_dir_path.exists():
            continue

        for pattern in patterns:
            try:
                for fpath in search_dir_path.glob(pattern):
                    if not fpath.is_file():
                        continue

                    # Skip warrantos files
                    if warrantos_root in fpath.resolve().parents:
                        continue

                    # Skip non-UTF8 or problematic files
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            _ = f.read(512)  # Test read
                    except (UnicodeDecodeError, PermissionError, OSError):
                        continue

                    candidates.append(str(fpath))

                    if len(candidates) >= max_files:
                        return candidates[:max_files]
            except (PermissionError, OSError, RuntimeError):
                # Some glob operations may fail on symlinks or permission issues
                continue

    return candidates[:max_files]


def load_triggers():
    """Load CLAIM_TRIGGERS from warrantos.provenance.extract.

    Adds warrantos repo to sys.path so imports work from anywhere.
    """
    # Add warrantos to path relative to this script
    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Import and extract triggers
    from warrantos.provenance.extract import CLAIM_TRIGGERS, sentences

    return CLAIM_TRIGGERS, sentences


def measure_triggers(file_paths, triggers, sentences_fn):
    """Process files and measure trigger fire rates.

    For METADATA files, extracts only the body (text after first blank line).
    Returns dict with statistics:
    - total_files: int
    - total_sentences: int
    - trigger_stats: dict of trigger_name -> {count, fires_per_100, examples}
    - sentences_with_any_trigger: int
    """
    trigger_stats = defaultdict(lambda: {"count": 0, "examples": []})
    total_sentences = 0
    sentences_with_any_trigger = 0

    for fpath in file_paths:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, PermissionError, OSError):
            continue

        # For METADATA files, extract only the body (after email headers)
        if fpath.endswith("/METADATA"):
            parts = text.split("\n\n", 1)
            if len(parts) > 1:
                text = parts[1]
            else:
                # No body found, skip
                continue

        # Split into sentences
        sents = sentences_fn(text)
        total_sentences += len(sents)

        for sent in sents:
            # Truncate for reporting
            sent_display = sent[:100] if len(sent) > 100 else sent

            # Check which triggers match
            fired_any = False
            for trigger_name, pattern in triggers:
                if pattern.search(sent):
                    fired_any = True
                    trigger_stats[trigger_name]["count"] += 1

                    # Keep up to 3 examples per trigger
                    if len(trigger_stats[trigger_name]["examples"]) < 3:
                        trigger_stats[trigger_name]["examples"].append(sent_display)

            if fired_any:
                sentences_with_any_trigger += 1

    return {
        "total_files": len(file_paths),
        "total_sentences": total_sentences,
        "trigger_stats": dict(trigger_stats),
        "sentences_with_any_trigger": sentences_with_any_trigger,
    }


def format_report(stats):
    """Format measurement results into readable report."""
    total_files = stats["total_files"]
    total_sentences = stats["total_sentences"]
    trigger_stats = stats["trigger_stats"]
    sentences_with_trigger = stats["sentences_with_any_trigger"]

    # Calculate percentage of sentences with at least one trigger
    if total_sentences > 0:
        pct_with_trigger = (sentences_with_trigger / total_sentences) * 100
    else:
        pct_with_trigger = 0

    # Sort triggers by fire count
    sorted_triggers = sorted(
        trigger_stats.items(),
        key=lambda x: x[1]["count"],
        reverse=True
    )

    # Build report
    report = []
    report.append("=" * 70)
    report.append("WarrantOS Precision Measurement: Citation-Trigger Fire Rate")
    report.append("=" * 70)
    report.append("")

    report.append("CORPUS SUMMARY")
    report.append("-" * 70)
    report.append(f"Total files scanned:        {total_files}")
    report.append(f"Total sentences:           {total_sentences}")
    report.append(f"Sentences with any trigger: {sentences_with_trigger}")
    report.append(f"Percentage with trigger:   {pct_with_trigger:.1f}%")
    report.append("")

    report.append("PER-TRIGGER STATISTICS")
    report.append("-" * 70)
    report.append(f"{'Trigger':<20} {'Count':<10} {'Fires/100 Sentences':<20}")
    report.append("-" * 70)

    for trigger_name, stats_dict in sorted_triggers:
        count = stats_dict["count"]
        if total_sentences > 0:
            fires_per_100 = (count / total_sentences) * 100
        else:
            fires_per_100 = 0
        report.append(f"{trigger_name:<20} {count:<10} {fires_per_100:>18.2f}")

    report.append("")
    report.append("TOP EXAMPLES (5 highest-firing triggers)")
    report.append("-" * 70)

    for trigger_name, stats_dict in sorted_triggers[:5]:
        count = stats_dict["count"]
        examples = stats_dict["examples"]
        report.append(f"\n{trigger_name.upper()} (fired {count} times)")
        for i, example in enumerate(examples, 1):
            # Escape newlines in examples
            example_clean = example.replace("\n", " ").replace("\r", " ")
            report.append(f"  [{i}] {example_clean}")

    report.append("")
    report.append("=" * 70)
    report.append("INTERPRETATION")
    report.append("=" * 70)
    report.append("")
    report.append(f"Corpus size: {total_sentences} sentences from {total_files} files")
    report.append("")

    if total_sentences < 5000:
        report.append("This measurement is UNDERPOWERED (corpus < 5,000 sentences).")
        report.append("The reported fire rates should not be used to draw conclusions about")
        report.append("trigger precision. Interpretation is limited to raw statistics only.")
    else:
        report.append("Corpus is adequately large (>= 5,000 sentences) for a preliminary")
        report.append("assessment of trigger patterns.")

    report.append("")
    report.append("Package documentation is presumed to contain few checkable factual")
    report.append("claims of the kind WarrantOS targets (policy, legislation, data). Thus,")
    report.append("the measured fire rate approximates an UPPER BOUND on false-positive")
    report.append("rate in real policy text. This is a proxy, not a labeled measurement.")
    report.append("")
    report.append("Legitimate fires: Some matches are valid (e.g. real years in")
    report.append("changelogs, version numbers, superlatives in feature descriptions).")
    report.append("The fire rate does not distinguish between false and true positives.")
    report.append("")

    return "\n".join(report)


def main():
    """Run precision measurement."""
    print("Gathering documentation files...", file=sys.stderr)
    file_paths = find_documentation_files(max_files=500)
    print(f"Found {len(file_paths)} files.", file=sys.stderr)

    if not file_paths:
        print("ERROR: No documentation files found.", file=sys.stderr)
        sys.exit(1)

    print("Loading triggers and sentence splitter...", file=sys.stderr)
    triggers, sentences_fn = load_triggers()
    print(f"Loaded {len(triggers)} triggers.", file=sys.stderr)

    print("Measuring trigger fire rates...", file=sys.stderr)
    stats = measure_triggers(file_paths, triggers, sentences_fn)

    # Print report
    report = format_report(stats)
    print(report)


if __name__ == "__main__":
    main()
