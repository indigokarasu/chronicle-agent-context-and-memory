"""
Chronicle — Principal topology / ACL matrix (§15.8, issue #5).

Adversarial coverage of the declarative users/agents access topology layered
under the per-memory read_acl (engine/access.py). Every test passes an
explicit `topology=` to access.can_read so nothing here depends on — or
leaks into — the module-global default (see test_topology_wired_from_config
for that integration path, which resets the global in tearDown).
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import access
from engine.access import Topology
from engine.core import ChronicleCore


def make_core(principals=None):
    home = tempfile.mkdtemp()
    cfg = {"embeddings": {"model": "hashing"}}
    if principals is not None:
        cfg["principals"] = principals
    return ChronicleCore(home, cfg), home


class TestTopology1to1(unittest.TestCase):
    """One user, one agent: trivial self-read; no sibling to leak to."""

    def test_self_read_always_allowed(self):
        topo = Topology({"agents": [{"id": "alice_bot", "user": "alice"}]})
        self.assertTrue(access.can_read(access.DEFAULT_ACL, "alice_bot", "alice_bot", topology=topo))

    def test_undeclared_stranger_denied_by_default(self):
        topo = Topology({"agents": [{"id": "alice_bot", "user": "alice"}]})
        # A wholly undeclared principal in a different namespace: no shared
        # user, no explicit edge -- denied.
        self.assertFalse(access.can_read(access.DEFAULT_ACL, "alice_bot", "bob_bot", topology=topo))


class TestTopology1toN(unittest.TestCase):
    """One user, several agents."""

    def setUp(self):
        self.topo = Topology({
            "default_cross_agent_read": "allow",
            "agents": [
                {"id": "alice_bot1", "user": "alice"},
                {"id": "alice_bot2", "user": "alice"},
                {"id": "alice_bot3", "user": "alice"},
            ],
        })

    def test_default_allow_lets_every_sibling_read(self):
        for reader in ("alice_bot2", "alice_bot3"):
            self.assertTrue(
                access.can_read(access.DEFAULT_ACL, "alice_bot1", reader, topology=self.topo),
                f"{reader} should read alice_bot1 under default_cross_agent_read: allow")

    def test_default_deny_blocks_every_sibling_without_explicit_edge(self):
        topo = Topology({
            "default_cross_agent_read": "deny",
            "agents": [{"id": "alice_bot1", "user": "alice"}, {"id": "alice_bot2", "user": "alice"}],
        })
        self.assertFalse(access.can_read(access.DEFAULT_ACL, "alice_bot1", "alice_bot2", topology=topo))

    def test_per_memory_deny_still_narrows_within_default_allow(self):
        # Ceiling allows it (same user, default allow); the per-memory ACL's
        # own deny-list still wins -- narrowing is always available.
        acl = access.revoke(access.DEFAULT_ACL, "alice_bot2")
        self.assertFalse(access.can_read(acl, "alice_bot1", "alice_bot2", topology=self.topo))


class TestTopologyNtoN(unittest.TestCase):
    """An agent shared by multiple users (N:N)."""

    def setUp(self):
        self.topo = Topology({
            "agents": [
                {"id": "alice_bot", "user": "alice"},
                {"id": "bob_bot", "user": "bob"},
                {"id": "shared_dash", "users": ["alice", "bob"]},
            ],
        })

    def test_both_owning_users_reach_the_shared_agent(self):
        self.assertTrue(access.can_read(access.DEFAULT_ACL, "shared_dash", "alice_bot", topology=self.topo))
        self.assertTrue(access.can_read(access.DEFAULT_ACL, "shared_dash", "bob_bot", topology=self.topo))

    def test_shared_agent_can_reach_each_owning_users_data(self):
        self.assertTrue(access.can_read(access.DEFAULT_ACL, "alice_bot", "shared_dash", topology=self.topo))
        self.assertTrue(access.can_read(access.DEFAULT_ACL, "bob_bot", "shared_dash", topology=self.topo))

    def test_sharing_the_dashboard_does_not_bridge_alice_and_bob_directly(self):
        # alice_bot and bob_bot share no user of their own (only shared_dash
        # bridges them) -- cross-user denial still holds between the two.
        self.assertFalse(access.can_read(access.DEFAULT_ACL, "alice_bot", "bob_bot", topology=self.topo))


class TestTopologyReadsEdge(unittest.TestCase):
    def test_explicit_cross_user_edge_grants_only_that_pair(self):
        topo = Topology({
            "agents": [
                {"id": "alice_bot", "user": "alice"},
                {"id": "auditor", "user": "ops", "reads": ["alice_bot"]},
            ],
        })
        self.assertTrue(access.can_read(access.DEFAULT_ACL, "alice_bot", "auditor", topology=topo))
        # The edge is one-directional and specific: auditor still can't be
        # read the other way, and a third party gets nothing from the edge.
        self.assertFalse(access.can_read(access.DEFAULT_ACL, "auditor", "alice_bot", topology=topo))

    def test_declared_reads_narrows_same_user_default_allow(self):
        # alice_bot1 explicitly limits itself to reading only itself, even
        # though the default posture for its own user is allow.
        topo = Topology({
            "default_cross_agent_read": "allow",
            "agents": [
                {"id": "alice_bot1", "user": "alice", "reads": ["alice_bot1"]},
                {"id": "alice_bot2", "user": "alice"},
            ],
        })
        self.assertFalse(access.can_read(access.DEFAULT_ACL, "alice_bot2", "alice_bot1", topology=topo))
        # The narrowing is per-principal: alice_bot2 declared no reads list,
        # so alice_bot1's own data is still reachable BY alice_bot2 under the
        # default posture that alice_bot2 (the reader here) is bound by.
        self.assertTrue(access.can_read(access.DEFAULT_ACL, "alice_bot1", "alice_bot2", topology=topo))


class TestTopologySandboxDenial(unittest.TestCase):
    def test_sandbox_denies_inbound_reads_even_under_default_allow(self):
        topo = Topology({
            "default_cross_agent_read": "allow",
            "agents": [
                {"id": "secret_agent", "user": "alice", "sandbox": True},
                {"id": "alice_bot", "user": "alice"},
            ],
        })
        self.assertFalse(access.can_read(access.DEFAULT_ACL, "secret_agent", "alice_bot", topology=topo))

    def test_sandbox_owner_still_reads_its_own_data(self):
        topo = Topology({"agents": [{"id": "secret_agent", "user": "alice", "sandbox": True}]})
        self.assertTrue(access.can_read(access.DEFAULT_ACL, "secret_agent", "secret_agent", topology=topo))

    def test_sandbox_beats_an_explicit_reads_edge(self):
        # Even a config-declared explicit edge naming the sandboxed principal
        # as the owner cannot reach it -- sandbox is an absolute veto, checked
        # before the reads-edge / default-posture logic.
        topo = Topology({
            "agents": [
                {"id": "secret_agent", "user": "alice", "sandbox": True},
                {"id": "auditor", "user": "ops", "reads": ["secret_agent"]},
            ],
        })
        self.assertFalse(access.can_read(access.DEFAULT_ACL, "secret_agent", "auditor", topology=topo))

    def test_sandbox_beats_a_per_memory_grant(self):
        topo = Topology({
            "agents": [
                {"id": "secret_agent", "user": "alice", "sandbox": True},
                {"id": "alice_bot", "user": "alice"},
            ],
        })
        acl = access.grant(access.DEFAULT_ACL, "alice_bot")
        self.assertFalse(access.can_read(acl, "secret_agent", "alice_bot", topology=topo))


class TestTopologyWidenAttemptRejected(unittest.TestCase):
    def test_per_memory_grant_cannot_widen_past_a_declared_reads_ceiling(self):
        topo = Topology({
            "agents": [
                {"id": "narrow_bot", "user": "alice", "reads": ["narrow_bot"]},
                {"id": "alice_bot2", "user": "alice"},
            ],
        })
        # alice_bot2 explicitly grants narrow_bot read access on one of its
        # memories -- a runtime widen attempt. narrow_bot's own declared reads
        # list (config) doesn't include alice_bot2, so it stays denied.
        acl = access.grant(access.DEFAULT_ACL, "narrow_bot")
        self.assertFalse(access.can_read(acl, "alice_bot2", "narrow_bot", topology=topo))

    def test_per_memory_grant_cannot_manufacture_an_implicit_cross_user_edge(self):
        topo = Topology({
            "agents": [{"id": "alice_bot", "user": "alice"}, {"id": "bob_bot", "user": "bob"}],
        })
        acl = access.grant(access.DEFAULT_ACL, "bob_bot")
        self.assertFalse(access.can_read(acl, "alice_bot", "bob_bot", topology=topo))


class TestTopologyCrossUserDenial(unittest.TestCase):
    def test_no_shared_user_no_edge_denied(self):
        topo = Topology({
            "agents": [{"id": "alice_bot", "user": "alice"}, {"id": "bob_bot", "user": "bob"}],
        })
        self.assertFalse(access.can_read(access.DEFAULT_ACL, "alice_bot", "bob_bot", topology=topo))
        self.assertFalse(access.can_read(access.DEFAULT_ACL, "bob_bot", "alice_bot", topology=topo))

    def test_legacy_no_topology_behavior_unchanged(self):
        # topology=None (or the pytest-order-independent module default, which
        # starts unconfigured) behaves exactly as before this feature existed.
        self.assertFalse(access.can_read("user_agents", "alice:agent", "bob:agent", topology=None))
        self.assertTrue(access.can_read("user_agents", "alice:agent1", "alice:agent2", topology=None))


class TestTopologyWiredFromConfig(unittest.TestCase):
    """End-to-end: ChronicleCore installs the topology from `principals:`
    config into the access.can_read module default (the choke point every
    existing call site — retrieval, derivation, curation, tools — already
    uses unmodified)."""

    def tearDown(self):
        access.reset_topology()

    def test_core_boot_installs_sandbox_from_config(self):
        core, _ = make_core({
            "default_cross_agent_read": "allow",
            "agents": [{"id": "secret_agent", "user": "alice", "sandbox": True},
                      {"id": "alice_bot", "user": "alice"}],
        })
        topo = access.active_topology()
        self.assertIsNotNone(topo)
        self.assertTrue(topo.is_sandboxed("secret_agent"))
        # No topology= passed -> falls through to the module default core just installed.
        self.assertFalse(access.can_read(access.DEFAULT_ACL, "secret_agent", "alice_bot"))
        self.assertTrue(access.can_read(access.DEFAULT_ACL, "secret_agent", "secret_agent"))

    def test_core_boot_default_config_matches_legacy_behavior(self):
        core, _ = make_core()  # no principals override -> DEFAULTS (agents: [])
        self.assertTrue(access.can_read("user_agents", "assistant", "research"))
        self.assertFalse(access.can_read("user_agents", "alice:agent", "bob:agent"))


class TestSubjectGrounding(unittest.TestCase):
    def test_accepts_proper_subject_grounding(self):
        access.validate_subject_grounding("pat_testley", "works_at")  # no raise
        access.validate_subject_grounding("user", "name")             # no raise

    def test_rejects_empty_attribute(self):
        with self.assertRaises(ValueError):
            access.validate_subject_grounding("pat_testley", "")

    def test_rejects_dotted_composite_attribute(self):
        with self.assertRaises(ValueError):
            access.validate_subject_grounding("user", "user.attr_works_at")

    def test_rejects_attr_escape_hatch(self):
        with self.assertRaises(ValueError):
            access.validate_subject_grounding("user", "attr_works_at")
        with self.assertRaises(ValueError):
            access.validate_subject_grounding("user", "pat_attr_works_at")

    def test_rejects_dotted_entity_id(self):
        with self.assertRaises(ValueError):
            access.validate_subject_grounding("user.pat", "works_at")

    def test_rejects_empty_entity_id(self):
        with self.assertRaises(ValueError):
            access.validate_subject_grounding("", "works_at")


class TestSubjectGroundingIntegration(unittest.TestCase):
    """The validator actually gates the durable-write path (curation._emit_item),
    not just a standalone function — and it does so WITHOUT crashing the
    extraction task over one bad item (I18)."""

    def setUp(self):
        self.core, self.home = make_core()

    def _base_event(self):
        eid = self.core.capture.observe("For the record.", "ok", session_id="s1")
        return self.core.store.get_event(eid)

    def test_bad_subject_grounding_is_dropped_not_stored(self):
        ev = self._base_event()
        before = self.core.store.count_rows("facts")
        bad_item = {"kind": "fact", "source_event": ev["event_id"],
                    "key": {"entity_id": "user", "attribute": "user.attr_works_at",
                            "predicate_canonical": "user.attr_works_at",
                            "qualifiers_hash": "", "qualifiers": {}},
                    "body": "Acme Fake Co", "confidence": 0.85}
        self.core.curation._emit_item(bad_item, ev, "assistant", "user", "user_direct", "extractor-v1")
        self.assertEqual(self.core.store.count_rows("facts"), before)

    def test_properly_grounded_fact_is_stored(self):
        ev = self._base_event()
        before = self.core.store.count_rows("facts")
        good_item = {"kind": "fact", "source_event": ev["event_id"],
                     "key": {"entity_id": "pat_testley", "attribute": "works_at",
                             "predicate_canonical": "works_at",
                             "qualifiers_hash": "", "qualifiers": {}},
                     "body": "Acme Fake Co", "confidence": 0.85}
        self.core.curation._emit_item(good_item, ev, "assistant", "user", "user_direct", "extractor-v1")
        self.core.process_pending()
        self.assertEqual(self.core.store.count_rows("facts"), before + 1)

    def test_remember_tool_rejects_composite_attribute(self):
        res_json = self.core.tools.dispatch(
            "assistant", "chronicle_remember",
            {"kind": "fact", "content": "Acme Fake Co", "entity": "user", "attribute": "user.attr_works_at"})
        import json
        res = json.loads(res_json)
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
