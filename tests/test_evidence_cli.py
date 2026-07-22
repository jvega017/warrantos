import json
import tempfile
import unittest
from pathlib import Path

from warrantos.cli.evidence_cli import main


class EvidenceCliTests(unittest.TestCase):
    def test_end_to_end_snapshot_assert_verify_reverify_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.txt"
            artefact = root / "artefact.md"
            snapshot = root / "snapshot.json"
            asserted = root / "asserted.json"
            verified = root / "verified.json"
            source.write_text("Official results show a 12 percent reduction in delay.", encoding="utf-8")
            artefact.write_text("The pilot achieved a 12 percent reduction in delay.", encoding="utf-8")
            self.assertEqual(main([
                "snapshot", str(source), "--id", "src_1", "--uri", "file:source.txt",
                "--retrieved-at", "2026-07-20T00:00:00Z", "--out", str(snapshot),
            ]), 0)
            self.assertEqual(main([
                "assert", "--artefact", str(artefact), "--claim-id", "claim_1",
                "--claim-text", "a 12 percent reduction in delay", "--snapshot", str(snapshot),
                "--source", str(source), "--passage", "a 12 percent reduction in delay",
                "--created-by", "agent:binder", "--binding-id", "bind_1", "--out", str(asserted),
            ]), 0)
            self.assertEqual(main([
                "verify", "--artefact", str(artefact), "--binding", str(asserted),
                "--snapshot", str(snapshot), "--source", str(source),
                "--reviewer", "human:reviewer", "--verdict", "supports", "--out", str(verified),
            ]), 0)
            self.assertEqual(json.loads(verified.read_text())["support_state"], "support_verified")
            self.assertEqual(main([
                "reverify", "--artefact", str(artefact), "--binding", str(verified),
                "--snapshot", str(snapshot), "--source", str(source), "--json",
            ]), 0)
            source.write_text("Substituted source.", encoding="utf-8")
            self.assertEqual(main([
                "reverify", "--artefact", str(artefact), "--binding", str(verified),
                "--snapshot", str(snapshot), "--source", str(source), "--json",
            ]), 1)


if __name__ == "__main__":
    unittest.main()
