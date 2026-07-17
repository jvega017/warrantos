"""Tests for the Merkle-ised ledger core (provenance.merkle)."""

import hashlib
import unittest

from warrantos.provenance.merkle import (
    InclusionProof,
    MerkleTree,
    build_checkpoint,
    leaf_hash,
    ledger_root,
    node_hash,
)


def _entries(n):
    return [("entry-%d" % i).encode() for i in range(n)]


class TestMerkleRoot(unittest.TestCase):
    def test_empty_tree_root_is_sha256_of_empty(self):
        self.assertEqual(MerkleTree([]).root(), hashlib.sha256(b"").digest())

    def test_single_leaf_root_is_its_leaf_hash(self):
        t = MerkleTree([b"only"])
        self.assertEqual(t.root(), leaf_hash(b"only"))

    def test_two_leaves_root_is_node_hash(self):
        t = MerkleTree([b"a", b"b"])
        self.assertEqual(t.root(), node_hash(leaf_hash(b"a"), leaf_hash(b"b")))

    def test_deterministic(self):
        self.assertEqual(MerkleTree(_entries(7)).root(), MerkleTree(_entries(7)).root())

    def test_root_hex_format(self):
        self.assertTrue(MerkleTree(_entries(3)).root_hex().startswith("sha256:"))

    def test_odd_node_promotion_three_leaves(self):
        # With promotion: root = node(node(a,b), c), not node(node(a,b), node(c,c)).
        a, b, c = leaf_hash(b"a"), leaf_hash(b"b"), leaf_hash(b"c")
        expected = node_hash(node_hash(a, b), c)
        self.assertEqual(MerkleTree([b"a", b"b", b"c"]).root(), expected)


class TestTamperDetection(unittest.TestCase):
    def test_changing_any_entry_changes_root(self):
        base = MerkleTree(_entries(9)).root()
        for i in range(9):
            e = _entries(9)
            e[i] = b"TAMPERED"
            self.assertNotEqual(MerkleTree(e).root(), base, "entry %d not covered" % i)

    def test_reordering_changes_root(self):
        e = _entries(6)
        base = MerkleTree(e).root()
        e[0], e[1] = e[1], e[0]
        self.assertNotEqual(MerkleTree(e).root(), base)

    def test_deleting_an_entry_changes_root(self):
        e = _entries(6)
        base = MerkleTree(e).root()
        del e[3]
        self.assertNotEqual(MerkleTree(e).root(), base)

    def test_leaf_and_node_domain_separation(self):
        # A leaf and an internal node over the same bytes must differ, or the
        # tree is open to a second-preimage attack (presenting a node as a leaf).
        self.assertNotEqual(
            hashlib.sha256(b"\x00" + b"x").digest(),
            hashlib.sha256(b"\x01" + b"x").digest(),
        )
        self.assertEqual(leaf_hash(b"x"), hashlib.sha256(b"\x00" + b"x").digest())


class TestInclusionProofs(unittest.TestCase):
    def test_every_index_proves_for_various_sizes(self):
        for n in (1, 2, 3, 4, 5, 8, 9, 16, 17, 31):
            t = MerkleTree(_entries(n))
            root = t.root()
            for i in range(n):
                p = t.proof(i)
                self.assertTrue(MerkleTree.verify(p, root), "n=%d i=%d failed" % (n, i))

    def test_proof_against_wrong_root_fails(self):
        t = MerkleTree(_entries(8))
        p = t.proof(3)
        wrong = MerkleTree(_entries(8) + [b"extra"]).root()
        self.assertFalse(MerkleTree.verify(p, wrong))

    def test_tampered_leaf_in_proof_fails(self):
        t = MerkleTree(_entries(8))
        root = t.root()
        p = t.proof(2)
        forged = InclusionProof(index=p.index, size=p.size, leaf=leaf_hash(b"forged"), steps=p.steps)
        self.assertFalse(MerkleTree.verify(forged, root))

    def test_out_of_range_index_raises(self):
        t = MerkleTree(_entries(4))
        with self.assertRaises(IndexError):
            t.proof(4)

    def test_proof_replayed_at_wrong_index_fails(self):
        # A valid proof for index i must not verify when its index is changed,
        # because the combine order is derived from (index, size), not trusted.
        t = MerkleTree(_entries(8)); root = t.root()
        p = t.proof(2)
        forged = InclusionProof(index=5, size=p.size, leaf=p.leaf, steps=p.steps)
        self.assertFalse(MerkleTree.verify(forged, root))

    def test_proof_with_wrong_size_fails(self):
        t = MerkleTree(_entries(8)); root = t.root()
        p = t.proof(3)
        self.assertFalse(MerkleTree.verify(InclusionProof(p.index, 9, p.leaf, p.steps), root))

    def test_proof_with_extra_forged_step_fails(self):
        t = MerkleTree(_entries(8)); root = t.root()
        p = t.proof(0)
        from warrantos.provenance.merkle import ProofStep
        tampered = InclusionProof(p.index, p.size, p.leaf, list(p.steps) + [ProofStep(b"\x00" * 32, False)])
        self.assertFalse(MerkleTree.verify(tampered, root))

    def test_proof_from_different_tree_fails(self):
        t1 = MerkleTree(_entries(8))
        t2 = MerkleTree([("other-%d" % i).encode() for i in range(8)])
        p = t2.proof(3)  # proof from a different tree of the same size
        self.assertFalse(MerkleTree.verify(p, t1.root()))


class TestCheckpoint(unittest.TestCase):
    def test_ledger_root_matches_tree(self):
        e = _entries(5)
        self.assertEqual(ledger_root(e), MerkleTree(e).root_hex())

    def test_build_checkpoint_fields(self):
        cp = build_checkpoint(_entries(4), run_id="run_x", timestamp="2026-06-09T00:00:00Z")
        self.assertEqual(cp["version"], "warrantos-checkpoint-v2")
        self.assertEqual(cp["entry_count"], 4)
        self.assertEqual(cp["run_id"], "run_x")
        self.assertTrue(cp["root_hash"].startswith("sha256:"))
        self.assertIn("merkle", cp["algorithm"])

    def test_append_returns_index_and_grows(self):
        t = MerkleTree([])
        self.assertEqual(t.append(b"first"), 0)
        self.assertEqual(t.append(b"second"), 1)
        self.assertEqual(len(t), 2)


if __name__ == "__main__":
    unittest.main()
