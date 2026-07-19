#!/usr/bin/env python3
"""
Phase 4b: Corpus expansion utility for grader evaluation.

Generates synthetic grader corpus items stratified by claim type, domain,
and gradeability. Output is in grader.jsonl format ready for dual annotation.

Usage:
    python corpus_expansion.py --count 50  # Generate 50 items
    python corpus_expansion.py --output expanded_pilot.jsonl --count 50
"""

import json
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple
import argparse

@dataclass
class CorpusItem:
    """Single grader corpus item."""
    id: str
    claim: str
    citation: str or None
    source: str
    gold: str  # For initial generation, this is empty/TBD; annotators fill it in
    note: str

# Template claim-source pairs stratified by trigger type and domain

NUMERIC_CLAIMS_POLICY = [
    (
        "The Public Sector Act was amended in 2018.",
        "According to the 2018 legislative records, the Public Sector Act underwent amendment that year.",
        "year"
    ),
    (
        "Federal employment numbers increased by 12 per cent between 2020 and 2024.",
        "ABS labour force data shows federal employment grew 12 per cent from 2020 to 2024.",
        "percentage"
    ),
    (
        "The department's budget allocation reached $450 million in the 2023 financial year.",
        "Parliamentary budget papers confirm allocation of $450 million for the 2023 financial year.",
        "magnitude"
    ),
]

STATUTE_CLAIMS = [
    (
        "Section 45 of the Privacy Act requires explicit consent for data collection.",
        "The Privacy Act, section 45, specifies that explicit consent must be obtained before collecting personal data.",
        "statute"
    ),
    (
        "Regulation 23 of the Environmental Code prescribes mandatory impact assessment.",
        "The Environmental Code regulation 23 mandates environmental impact assessment for major projects.",
        "statute"
    ),
    (
        "Under the Corporations Act, listed entities must disclose material risks.",
        "The Corporations Act imposes mandatory disclosure requirements for material risks on listed entities.",
        "statute"
    ),
]

ATTRIBUTION_CLAIMS = [
    (
        "Research by Harvard University shows cognitive benefits of daily exercise.",
        "A Harvard University study demonstrates that daily exercise provides measurable cognitive benefits.",
        "attribution"
    ),
    (
        "The OECD reported that digital skills gaps are widening in developing nations.",
        "OECD data from their 2023 skills assessment indicates growing digital capability gaps in developing economies.",
        "attribution"
    ),
    (
        "Studies from the Institute for Fiscal Studies found that tax reforms reduced compliance costs.",
        "IFS research indicates tax reform measures led to measurable reductions in compliance costs.",
        "attribution"
    ),
]

CAUSAL_CLAIMS = [
    (
        "The pandemic led to a 60 per cent increase in remote work adoption.",
        "Statistics from employment agencies show remote work adoption increased 60 per cent as a direct result of pandemic restrictions.",
        "causal"
    ),
    (
        "Increased funding for early intervention resulted in reduced recidivism by 25 per cent.",
        "Justice department data demonstrate that expanded early intervention programs drove a 25 per cent reduction in recidivism.",
        "causal"
    ),
]

COMPARISON_CLAIMS = [
    (
        "Government digital service uptake is twice as high in Australia compared to the UK.",
        "International comparison of e-government adoption shows Australian services are used at approximately double the rate of UK equivalents.",
        "comparison"
    ),
    (
        "Female participation in STEM increased more than male participation between 2015 and 2024.",
        "Education statistics reveal that female STEM enrolment growth rates exceeded male growth rates over the 2015-2024 period.",
        "comparison"
    ),
]

# Hard/ambiguous claims that require annotation judgment
AMBIGUOUS_CLAIMS = [
    (
        "The government's digital transformation strategy achieved significant success.",
        "The digital transformation programme led to widespread modernisation of public services.",
        "ambiguous",  # Success is subjective; depends on metrics
    ),
    (
        "Public confidence in government has improved in recent years.",
        "Survey results from the past two years indicate rising satisfaction with government performance.",
        "ambiguous",  # "Improved" is vague; depends on baseline and metric
    ),
]

# Claims with no/weak sources (unsupported cases)
UNSUPPORTED_CLAIMS = [
    (
        "The new policy will save taxpayers $1 billion annually.",
        "The policy is expected to deliver substantial savings through efficiency improvements.",
        "unsupported",  # Prediction, not verified fact
    ),
    (
        "AI technology has already replaced 50,000 jobs in the government sector.",
        "Automation and AI are expected to influence workforce planning in coming years.",
        "unsupported",  # Specific claim not supported by vague source
    ),
]

ALL_TEMPLATES = (
    NUMERIC_CLAIMS_POLICY +
    STATUTE_CLAIMS +
    ATTRIBUTION_CLAIMS +
    CAUSAL_CLAIMS +
    COMPARISON_CLAIMS +
    AMBIGUOUS_CLAIMS +
    UNSUPPORTED_CLAIMS
)

def generate_corpus_items(count: int) -> List[CorpusItem]:
    """Generate corpus items from templates, cycling through types."""
    items = []
    template_count = len(ALL_TEMPLATES)

    for i in range(count):
        template_idx = i % template_count
        claim, source, trigger_type = ALL_TEMPLATES[template_idx]

        # Generate unique ID with trigger type and count
        item_id = f"pilot_{trigger_type[:3]}_{i:03d}"

        # Create corpus item with empty gold/note for annotation
        item = CorpusItem(
            id=item_id,
            claim=claim,
            citation=None,
            source=source,
            gold="",  # Annotators will fill this in
            note=f"Trigger: {trigger_type}. Requires annotation."
        )
        items.append(item)

    return items

def save_corpus(items: List[CorpusItem], output_path: Path):
    """Save corpus items to JSONL file."""
    with open(output_path, 'w') as f:
        for item in items:
            line = json.dumps({
                "id": item.id,
                "claim": item.claim,
                "citation": item.citation,
                "source": item.source,
                "gold": item.gold,
                "note": item.note,
            })
            f.write(line + "\n")

    print(f"✓ Generated {len(items)} corpus items → {output_path}")

def count_existing_corpus(grader_corpus_path: Path) -> int:
    """Count items already in grader.jsonl."""
    # Try multiple paths if given relative path
    paths_to_try = [
        grader_corpus_path,
        Path("eval/corpus/grader.jsonl"),
        Path(__file__).parent / "corpus" / "grader.jsonl",
    ]
    for path in paths_to_try:
        if path.exists():
            with open(path) as f:
                return sum(1 for _ in f)
    return 0

def main():
    parser = argparse.ArgumentParser(
        description="Generate pilot corpus for Phase 4b expansion"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=50,
        help="Number of items to generate (default: 50)"
    )
    parser.add_argument(
        "--output",
        default="corpus_pilot.jsonl",
        help="Output file path (default: corpus_pilot.jsonl)"
    )
    parser.add_argument(
        "--stratified",
        action="store_true",
        help="Generate stratified by claim type (equal distribution)"
    )

    args = parser.parse_args()

    # Generate corpus
    items = generate_corpus_items(args.count)

    # Save
    output_path = Path(args.output)
    save_corpus(items, output_path)

    # Report
    existing = count_existing_corpus(Path("corpus/grader.jsonl"))
    print(f"\nCurrent grader.jsonl: {existing} items")
    print(f"Pilot corpus: {len(items)} items")
    print(f"After merge: ~{existing + len(items)} items (target: 400-500)")

    print("\n" + "="*70)
    print("NEXT STEPS FOR PHASE 4B:")
    print("="*70)
    print(f"1. Review pilot items in {output_path}")
    print("2. Split for dual annotation (2 independent annotators)")
    print("3. Each annotator labels: gold (verdict), confidence, note")
    print("4. Compute Cohen's κ on both annotators' results")
    print("5. If κ ≥ 0.70: proceed to Phase 4c testing")
    print("6. If κ < 0.70: adjudicate disagreements, retrain annotators")

if __name__ == "__main__":
    main()
