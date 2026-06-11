#!/usr/bin/env python3
"""Tests for the SPEC-F-S002 machine-readable actor-role registry.

The six actor roles were previously documented only in prose and in the
cbom.py docstring; this registry makes them enumerable and validatable at
runtime (Foundation row F-policy). These tests pin:

- the exact six role_id strings required on CBOM.actor_identity,
- agreement between the registry and the cbom.py docstring,
- validate_actor_identity() behaviour (missing, empty, unknown keys),
- registry serialisation schema stability.
"""

import unittest

from warrantos.provenance import roles


# The canonical six. If this set changes, SPEC-F-S002 and cbom.py change too.
EXPECTED_ROLE_IDS = {
    "context_classifier",
    "insight_compiler",
    "source_curator",
    "clean_room_writer",
    "reviewer_qa",
    "auditor",
}


class TestRoleRegistry(unittest.TestCase):
    def test_exactly_six_roles(self):
        self.assertEqual(len(roles.ACTOR_ROLES), 6)
        self.assertEqual(set(roles.role_ids()), EXPECTED_ROLE_IDS)
        self.assertEqual(set(roles.REQUIRED_ACTOR_ROLE_IDS), EXPECTED_ROLE_IDS)

    def test_role_ids_lifecycle_order(self):
        # Order is significant: intake first, audit last.
        self.assertEqual(roles.role_ids()[0], "context_classifier")
        self.assertEqual(roles.role_ids()[-1], "auditor")

    def test_get_role_and_unknown(self):
        r = roles.get_role("clean_room_writer")
        self.assertEqual(r.title, "Clean-Room Writer")
        self.assertIn("SPEC-L6-S001", r.spec_refs)
        with self.assertRaises(KeyError):
            roles.get_role("not_a_role")

    def test_is_actor_role(self):
        self.assertTrue(roles.is_actor_role("auditor"))
        self.assertFalse(roles.is_actor_role("ledger_writer"))  # a viewer, not an actor

    def test_registry_matches_cbom_docstring(self):
        # cbom.py docstring names the six roles required on actor_identity;
        # the registry SHALL agree byte-for-byte on the role_id set.
        from warrantos.provenance import cbom
        doc = cbom.CBOM.__doc__ or ""
        for role_id in EXPECTED_ROLE_IDS:
            self.assertIn(role_id, doc, "role %r missing from cbom docstring" % role_id)


class TestValidateActorIdentity(unittest.TestCase):
    def _full(self):
        return {rid: "actor-%s" % rid for rid in EXPECTED_ROLE_IDS}

    def test_complete_map_passes(self):
        self.assertEqual(roles.validate_actor_identity(self._full()), [])

    def test_missing_role_flagged(self):
        m = self._full()
        del m["auditor"]
        problems = roles.validate_actor_identity(m)
        self.assertTrue(any("missing actor role 'auditor'" in p for p in problems))

    def test_empty_identity_flagged(self):
        m = self._full()
        m["reviewer_qa"] = "   "
        problems = roles.validate_actor_identity(m)
        self.assertTrue(any("empty identity" in p and "reviewer_qa" in p for p in problems))

    def test_unknown_key_flagged(self):
        m = self._full()
        m["ledger_writer"] = "someone"
        problems = roles.validate_actor_identity(m)
        self.assertTrue(any("unknown actor role key 'ledger_writer'" in p for p in problems))

    def test_empty_map_flags_all_six(self):
        problems = roles.validate_actor_identity({})
        missing = [p for p in problems if "missing actor role" in p]
        self.assertEqual(len(missing), 6)


class TestRegistrySerialisation(unittest.TestCase):
    def test_schema_stable(self):
        d = roles.registry_to_dict()
        self.assertEqual(d["schema"], "warrantos-roles/v1")
        self.assertEqual(d["spec_ref"], "SPEC-F-S002")
        self.assertEqual(len(d["actor_roles"]), 6)
        self.assertEqual(set(d["required_actor_role_ids"]), EXPECTED_ROLE_IDS)

    def test_viewer_identities_distinct_from_actors(self):
        # ledger_writer is a viewer, not one of the six actor roles.
        self.assertIn("ledger_writer", roles.VIEWER_IDENTITIES)
        self.assertNotIn("ledger_writer", roles.REQUIRED_ACTOR_ROLE_IDS)


if __name__ == "__main__":
    unittest.main()
