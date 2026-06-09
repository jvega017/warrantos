"""Merkle-ised ledger core: a tamper-evident integrity layer over the audit ledger.

Pure standard library (``hashlib`` only). This is the foundation for the
cryptographic-integrity wave: a Merkle root over the ledger entries is both the
P0.2 integrity hash (one value that fixes the entire ledger state) and the
P1.x attestation root (the thing a signed checkpoint commits to and an external
verifier checks inclusion proofs against).

Design notes
------------
- RFC 6962 style domain separation: leaf hashes are prefixed with ``0x00`` and
  internal node hashes with ``0x01``. Without this prefix a Merkle tree is
  vulnerable to a second-preimage attack where an internal node is presented as
  a leaf. The prefixes make leaf and node pre-images disjoint.
- Odd nodes at a level are promoted (carried up unchanged) rather than
  duplicated. Duplicating the last node (the Bitcoin approach) enables
  CVE-2012-2459 style ambiguity; promotion avoids it and keeps proofs honest.
- The tree is deterministic: the same ordered list of entries always yields the
  same root, so a checkpoint can be recomputed and compared on any machine with
  no shared state beyond the published root.
"""

from __future__ import annotations

import hashlib
from typing import List, NamedTuple, Optional, Sequence

_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"
# Hash of the empty tree: SHA-256 of the empty string (RFC 6962 convention).
_EMPTY_ROOT = hashlib.sha256(b"").digest()


def leaf_hash(data: bytes) -> bytes:
    """Hash a single ledger entry as a Merkle leaf."""
    return hashlib.sha256(_LEAF_PREFIX + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    """Hash two child digests into a parent node digest."""
    return hashlib.sha256(_NODE_PREFIX + left + right).digest()


class ProofStep(NamedTuple):
    """One sibling on the path from a leaf to the root.

    ``on_left`` is True when the sibling sits to the LEFT of the running hash
    (so the combine order is ``node_hash(sibling, running)``), False when it
    sits to the right.
    """

    sibling: bytes
    on_left: bool


class InclusionProof(NamedTuple):
    index: int
    size: int
    leaf: bytes
    steps: List[ProofStep]


class MerkleTree:
    """A deterministic Merkle tree over an ordered list of byte entries.

    Append-and-recompute, which is correct and ample for audit-ledger sizes.
    Not an O(log n) incremental MMR; correctness and auditability are the goal,
    not throughput.
    """

    def __init__(self, entries: Optional[Sequence[bytes]] = None) -> None:
        self._leaves: List[bytes] = [leaf_hash(e) for e in (entries or [])]

    def append(self, data: bytes) -> int:
        """Append an entry. Returns its leaf index."""
        self._leaves.append(leaf_hash(data))
        return len(self._leaves) - 1

    def __len__(self) -> int:
        return len(self._leaves)

    @staticmethod
    def _levels(leaves: List[bytes]) -> List[List[bytes]]:
        """Build every level of the tree, bottom (leaves) to top (root)."""
        if not leaves:
            return [[_EMPTY_ROOT]]
        levels = [list(leaves)]
        while len(levels[-1]) > 1:
            cur = levels[-1]
            nxt: List[bytes] = []
            for i in range(0, len(cur), 2):
                if i + 1 < len(cur):
                    nxt.append(node_hash(cur[i], cur[i + 1]))
                else:
                    nxt.append(cur[i])  # promote the odd node unchanged
            levels.append(nxt)
        return levels

    def root(self) -> bytes:
        """The Merkle root digest (32 bytes). Empty tree yields the empty root."""
        if not self._leaves:
            return _EMPTY_ROOT
        return self._levels(self._leaves)[-1][0]

    def root_hex(self) -> str:
        return "sha256:" + self.root().hex()

    def proof(self, index: int) -> InclusionProof:
        """Inclusion proof that the leaf at ``index`` is committed by the root."""
        if not (0 <= index < len(self._leaves)):
            raise IndexError("leaf index out of range")
        levels = self._levels(self._leaves)
        steps: List[ProofStep] = []
        idx = index
        for level in levels[:-1]:  # every level except the root
            if idx % 2 == 0:
                sib = idx + 1
                if sib < len(level):
                    steps.append(ProofStep(level[sib], on_left=False))
                # else: this node was promoted, no sibling at this level
            else:
                steps.append(ProofStep(level[idx - 1], on_left=True))
            idx //= 2
        return InclusionProof(
            index=index, size=len(self._leaves), leaf=self._leaves[index], steps=steps
        )

    @staticmethod
    def verify(proof: InclusionProof, root: bytes) -> bool:
        """Recompute the root from a leaf and its proof; compare to ``root``.

        The combine order at each level is derived from ``(index, size)``, not
        trusted from the proof, so a proof for one position cannot be replayed
        at another. All steps must be consumed exactly, so extra forged steps
        are rejected. ``size`` binds the proof to the tree it was issued for.
        """
        if proof.size <= 0 or not (0 <= proof.index < proof.size):
            return False
        running = proof.leaf
        idx, sz, si = proof.index, proof.size, 0
        steps = proof.steps
        while sz > 1:
            if idx % 2 == 1:  # right child: sibling is on the left
                if si >= len(steps):
                    return False
                running = node_hash(steps[si].sibling, running)
                si += 1
            elif idx + 1 < sz:  # left child with a right sibling
                if si >= len(steps):
                    return False
                running = node_hash(running, steps[si].sibling)
                si += 1
            # else: left child promoted (odd node at this level), no step consumed
            idx //= 2
            sz = (sz + 1) // 2
        return si == len(steps) and running == root


def ledger_root(entries: Sequence[bytes]) -> str:
    """Convenience: the Merkle root (as ``sha256:hex``) over ordered entries.

    This is the P0.2 ledger integrity value: one digest that fixes the entire
    ordered ledger state. Any insert, edit, delete, or reorder changes it.
    """
    return MerkleTree(entries).root_hex()


def build_checkpoint(entries: Sequence[bytes], *, run_id: str, timestamp: str) -> dict:
    """A signable checkpoint committing to the ledger state.

    The signature is added by the attestation layer (P1.2); this function
    produces the canonical unsigned body so signing and verification agree on
    exactly what was committed.
    """
    tree = MerkleTree(entries)
    return {
        "version": "warrantos-checkpoint-v1",
        "root_hash": tree.root_hex(),
        "entry_count": len(entries),
        "run_id": run_id,
        "timestamp": timestamp,
        "algorithm": "sha256-merkle-rfc6962-domainsep",
    }
