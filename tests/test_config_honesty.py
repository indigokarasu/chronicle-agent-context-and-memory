"""
Chronicle — config honesty (§A12).

THE PREMISE: config must never promise what code does not deliver. The CHANGELOG
records a shipped bug of exactly this class for nearly every release, and the
2026-09 audit found ~70 more at once — including `security.encrypt_at_rest: true`
on a store that encrypts nothing.

THE GUARD (`test_no_undeclared_unread_keys`) is the deliverable: every leaf key in
DEFAULTS must be either READ by shipped code or explicitly DECLARED_DORMANT with a
reason. A new knob that nothing reads fails this test on the way in, and a stale
declaration (the key got wired, or deleted) fails it too.

The guard is only worth its runtime if the scanner it depends on is honest in BOTH
directions, so the planted-fixture tests below prove both:
  * a key that IS read — through each accessor shape the codebase uses — is
    reported WIRED;
  * a key that is NOT read is reported UNREAD even when its dotted path appears
    verbatim in the source as a plain string. That second direction is the whole
    reason the loose fix was rejected (A3): treating any quoted dotted path as a
    read flips genuinely-unread keys like `provider` and `store` to WIRED.
"""

import sys
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from audit_config import (  # noqa: E402
    ALLOWED_UNDECLARED_READS,
    audit,
    leaf_keys,
    stale_dormant_declarations,
    undeclared_literal_reads,
)
from engine import trust  # noqa: E402
from engine.config import DECLARED_DORMANT, DEFAULTS, REFUSED_KEYS, Config  # noqa: E402
from engine.core import ChronicleCore  # noqa: E402
from engine.reducer import compute_belief_id, contradiction_policy  # noqa: E402


# ==========================================================================
# (1) THE GUARD
# ==========================================================================

class TestConfigHonestyGuard(unittest.TestCase):
    """Every declared key is read, or declared dormant. No third state."""

    def test_no_undeclared_unread_keys(self):
        rows = audit()
        unread = sorted(k for k, v in rows.items() if v[0] == "UNREAD")
        self.assertEqual(unread, [], (
            "{} config key(s) are declared in DEFAULTS and read by nothing.\n"
            "Resolve each one: WIRE it (make the code read it), DELETE it (it "
            "promises nothing real), or add it to engine.config.DECLARED_DORMANT "
            "with a reason.\nUnread: {}".format(len(unread), unread)))

    def test_no_stale_dormant_declarations(self):
        """A declaration that is no longer true is the same defect, mirrored."""
        stale = stale_dormant_declarations()
        self.assertEqual(stale, [], (
            "DECLARED_DORMANT names keys that are wired or gone: {}. "
            "Remove the declaration.".format(stale)))

    def test_every_dormant_declaration_states_a_reason(self):
        for path, reason in sorted(DECLARED_DORMANT.items()):
            self.assertIsInstance(reason, str, path)
            self.assertGreaterEqual(len(reason.strip()), 20, (
                "{}: a dormant declaration must say what is missing, not just "
                "that something is".format(path)))

    def test_guard_fails_when_an_unread_key_is_added(self):
        """MUTATION: plant an unread key and prove the guard catches it.

        A guard that has never failed is a guard nobody has tested.
        """
        planted = {"a12_probe": {"never_read_by_anything": True}}
        planted.update(DEFAULTS)
        rows = audit(defaults=planted)
        self.assertEqual(rows["a12_probe.never_read_by_anything"][0], "UNREAD")
        unread = [k for k, v in rows.items() if v[0] == "UNREAD"]
        self.assertEqual(unread, ["a12_probe.never_read_by_anything"])


# ==========================================================================
# (1b) THE MIRROR — the direction the guard above cannot see
# ==========================================================================

class TestEveryKeyTheCodeReadsIsDeclared(unittest.TestCase):
    """The other half of the guard, added after the v5.7.0 pre-ship review.

    `TestConfigHonestyGuard` walks DEFAULTS and asks "is this key read?". It
    cannot see the mirror-image defect: a key the code READS that DEFAULTS does
    not declare. That is not hypothetical — v5.7.0 shipped a review away from
    it. `DEFAULTS` contained the literal key `"health"` TWICE (A7+A0b's block
    and A3's), Python kept the last, and `health.self_heal.embedder_mismatch_max`
    and `health.census_total_max_age_hours` silently vanished. Nothing failed:
    both readers pass an inline default that happens to match the intended
    value, `audit_config.py` still said "UNREAD 0" (over a smaller denominator),
    and two deliberately-tuned, individually-commented operator knobs simply
    stopped appearing on the config surface the dashboard enumerates.

    Had the two blocks appeared in the OTHER order, A3's
    `health.consistency_sweep.schedule` would have been the casualty and the
    hourly consistency sweep would have silently lost its cadence — a real
    behaviour change, from the same typo.

    Two independent detectors, because either alone has a hole: this one (which
    catches a key that goes missing for ANY reason, including a plain deletion)
    and `TestNoDuplicateDictKeys` below (which catches the duplicate literal
    even when both blocks declare the same keys).
    """

    def test_no_literal_config_read_is_missing_from_defaults(self):
        undeclared = undeclared_literal_reads()
        self.assertEqual(undeclared, {}, (
            "{} config path(s) are read by shipped code but are NOT in "
            "DEFAULTS.\nAn operator cannot discover them, the dashboard cannot "
            "enumerate them, and audit_config.py's 'UNREAD 0' is computed "
            "without them. DECLARE each one in DEFAULTS (with the same value as "
            "the inline default at the read site), or -- if the scanner is "
            "wrong about it -- add it to audit_config.ALLOWED_UNDECLARED_READS "
            "with a reason.\nUndeclared: {}".format(len(undeclared), undeclared)))

    def test_the_two_health_keys_the_duplicate_deleted_are_back(self):
        """The regression itself, named, so a re-merge cannot quietly undo it."""
        cfg = Config({})
        self.assertEqual(cfg.get("health.self_heal.embedder_mismatch_max"), 500)
        self.assertEqual(cfg.get("health.census_total_max_age_hours"), 24)
        # …and A3's key, which the opposite block order would have eaten.
        self.assertEqual(cfg.get("health.consistency_sweep.schedule"), "0 * * * *")
        self.assertIs(cfg.get("health.consistency_sweep.enabled"), True)
        self.assertIs(cfg.get("health.self_heal.tier1_auto"), True)
        self.assertEqual(cfg.get("health.schedule"), "0 4 * * *")

    def test_the_mirror_catches_a_key_that_defaults_stops_declaring(self):
        """MUTATION: delete a key the engine reads and prove the mirror fires.

        Uses health.self_heal.embedder_mismatch_max, i.e. re-creates the exact
        v5.7.0 defect, over a COPY of DEFAULTS (the real one is not touched)."""
        import copy
        mutated = copy.deepcopy(DEFAULTS)
        del mutated["health"]["self_heal"]["embedder_mismatch_max"]
        found = undeclared_literal_reads(defaults=mutated)
        self.assertIn("health.self_heal.embedder_mismatch_max", found)
        self.assertTrue(found["health.self_heal.embedder_mismatch_max"],
                        "the mirror must say WHERE the undeclared read is")

    def test_every_allowed_undeclared_read_states_a_reason(self):
        """Same bar as DECLARED_DORMANT: an exemption without a reason is a
        silenced alarm."""
        self.assertTrue(ALLOWED_UNDECLARED_READS)
        for path, reason in sorted(ALLOWED_UNDECLARED_READS.items()):
            self.assertIsInstance(reason, str, path)
            self.assertGreaterEqual(len(reason.strip()), 20, (
                "{}: say why this read does not need a declared key".format(path)))

    def test_declared_values_match_the_inline_defaults_at_the_read_sites(self):
        """Two keys are declared in DEFAULTS *and* passed as an inline default
        by their reader. config.py cannot import either module (circular), so
        the only thing keeping them equal is this test."""
        import provider
        from engine import reducer
        self.assertEqual(
            list(DEFAULTS["capture"]["tool_reference"]["allowlist"]),
            list(provider._DEFAULT_RETRIEVAL_TOOLS))
        self.assertEqual(DEFAULTS["capture"]["tool_reference"]["ttl_days"],
                         provider._DEFAULT_REFERENCE_TTL_DAYS)
        self.assertEqual(DEFAULTS["curation"]["novelty_top_k"], reducer.NOVELTY_TOP_K)


class TestNoDuplicateDictKeys(unittest.TestCase):
    """`engine/config.py` may not define the same literal key twice.

    This is the detector that names the CAUSE rather than the symptom, and it
    catches the case the mirror cannot: two blocks that declare the same keys,
    where nothing goes missing today but every future edit to the first block is
    a silent no-op.

    It is pure `ast` on purpose. `ruff check .` already reports F601 and the CI
    lint job already runs it — but that job is red for 66 unrelated style
    findings, so a 67th changed nothing that anyone would notice. A gate nobody
    can see go green is not a gate. This one runs in the normal suite, in all
    four modes, with no tooling.
    """

    #: Every shipped source file, not just config.py: the defect is generic.
    def _sources(self):
        for sub in ("engine", "scripts", "dashboard"):
            for p in sorted((ROOT / sub).rglob("*.py")):
                yield p
        for p in sorted(ROOT.glob("*.py")):
            yield p

    def _duplicates(self, path):
        import ast
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover - a syntax error is another test
            return []
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            seen = {}
            for k in node.keys:
                if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
                    continue
                if k.value in seen:
                    out.append((k.value, seen[k.value], k.lineno))
                seen[k.value] = k.lineno
        return out

    def test_config_py_defines_each_key_once(self):
        dupes = self._duplicates(ROOT / "engine" / "config.py")
        self.assertEqual(dupes, [], (
            "engine/config.py repeats {} dict key literal(s): {}. Python keeps "
            "the LAST, so every key the earlier block declares and the later one "
            "does not is silently deleted. Merge the blocks.".format(
                len(dupes), [(k, "first line %d, again line %d" % (a, b))
                             for k, a, b in dupes])))

    def test_no_shipped_module_repeats_a_dict_key(self):
        offenders = {}
        for path in self._sources():
            dupes = self._duplicates(path)
            if dupes:
                offenders[str(path.relative_to(ROOT))] = dupes
        self.assertEqual(offenders, {}, (
            "duplicate dict key literals (ruff F601): {}".format(offenders)))

    def test_the_detector_finds_a_planted_duplicate(self):
        """MUTATION: it has to be able to fail."""
        from _tmp_support import rm_tree, temp_home
        home = temp_home(prefix="dupkey-")
        self.addCleanup(rm_tree, home)
        planted = Path(home) / "planted.py"
        planted.write_text('D = {"a": 1, "b": 2, "a": 3}\n', encoding="utf-8")
        self.assertEqual([d[0] for d in self._duplicates(planted)], ["a"])


# ==========================================================================
# (2) THE SCANNER, BOTH DIRECTIONS
# ==========================================================================

class _Planted:
    """A throwaway module the scanner is pointed at, plus matching defaults."""

    def __init__(self, source, defaults):
        self.source = source
        self.defaults = defaults

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "planted_module.py"
        self.path.write_text(self.source, encoding="utf-8")
        return audit(defaults=self.defaults, extra_files=[self.path])

    def __exit__(self, *exc):
        self.dir.cleanup()
        return False


class TestScannerRecognisesRealReads(unittest.TestCase):
    """Direction 1: a key that is genuinely read is reported WIRED."""

    def test_direct_get(self):
        with _Planted("def f(cfg):\n    return cfg.get('planted.direct', 1)\n",
                      {"planted": {"direct": 1}}) as rows:
            self.assertEqual(rows["planted.direct"][0], "WIRED")

    def test_subscript(self):
        with _Planted("def f(cfg):\n    return cfg['planted.direct']\n",
                      {"planted": {"direct": 1}}) as rows:
            self.assertEqual(rows["planted.direct"][0], "WIRED")

    def test_attribute_accessor(self):
        with _Planted("class C:\n    def f(self):\n"
                      "        return self.core.cfg.get('planted.direct', 1)\n",
                      {"planted": {"direct": 1}}) as rows:
            self.assertEqual(rows["planted.direct"][0], "WIRED")

    def test_helper_with_a_config_path_parameter(self):
        """`_clamp_cfg(self.cfg, "retrieval.rerank_top_k", ...)` — the shape the
        old regex missed, which is why it called wired keys dormant."""
        src = ("def _clamp(cfg, key, default, lo, hi):\n"
               "    return max(lo, min(hi, cfg.get(key, default)))\n"
               "\n"
               "class C:\n"
               "    def f(self):\n"
               "        return _clamp(self.cfg, 'planted.clamped', 5, 1, 9)\n")
        with _Planted(src, {"planted": {"clamped": 5}}) as rows:
            self.assertEqual(rows["planted.clamped"][0], "WIRED")
            self.assertEqual(rows["planted.clamped"][1], "helper")

    def test_sub_dict_fetched_once_and_indexed_later(self):
        src = ("class C:\n"
               "    def f(self):\n"
               "        w = self.cfg.get('planted.weights', {})\n"
               "        return w.get('recency', 0.2) + w['salience']\n")
        with _Planted(src, {"planted": {"weights": {"recency": 0.2, "salience": 0.2}}}) as rows:
            self.assertEqual(rows["planted.weights.recency"][0], "WIRED")
            self.assertEqual(rows["planted.weights.salience"][0], "WIRED")

    def test_sub_dict_handed_to_another_function(self):
        src = ("class C:\n"
               "    def f(self):\n"
               "        gf = self.cfg.get('planted.ghost', {})\n"
               "        return self._use(gf)\n"
               "\n"
               "    def _use(self, gf):\n"
               "        return gf.get('confidence_min', 0.8)\n")
        with _Planted(src, {"planted": {"ghost": {"confidence_min": 0.8, "age_days": 14}}}) as rows:
            self.assertEqual(rows["planted.ghost.confidence_min"][0], "WIRED")
            # ...and the sibling nobody pulls out stays honest.
            self.assertEqual(rows["planted.ghost.age_days"][0], "UNREAD")

    def test_dynamic_key_template(self):
        """A9's `cfg.get(f"sweeps.budgets.{name}")`: every declared child is read."""
        src = ("def budget(cfg, name):\n"
               "    return cfg.get(f'planted.budgets.{name}', 5000)\n"
               "\n"
               "def caller(cfg, whatever):\n"
               "    return budget(cfg, whatever)\n")
        with _Planted(src, {"planted": {"budgets": {"decay": 200, "consistency": 2000}}}) as rows:
            self.assertEqual(rows["planted.budgets.decay"][0], "WIRED")
            self.assertEqual(rows["planted.budgets.consistency"][0], "WIRED")

    def test_template_hole_in_the_middle(self):
        """`"domains.{}.contradiction_policy".format(domain)` — the hole is not
        the last segment, so the caller's value has to be spliced, not appended."""
        src = ("def policy(cfg, domain):\n"
               "    return cfg.get('planted.{}.pol'.format(domain), 'x')\n"
               "\n"
               "def caller(cfg, d):\n"
               "    return policy(cfg, d)\n")
        with _Planted(src, {"planted": {"user": {"pol": "x", "other": 1}}}) as rows:
            self.assertEqual(rows["planted.user.pol"][0], "WIRED")
            self.assertEqual(rows["planted.user.other"][0], "UNREAD")

    def test_table_driven_reads(self):
        """A3's scheduler shape: the key names live in a table, not at the call."""
        src = ("_SCHEDULES = (('health', 'planted.health_iv'),\n"
               "              ('reaper', 'planted.reaper_iv'))\n"
               "\n"
               "def run(cfg):\n"
               "    out = []\n"
               "    for job, key in _SCHEDULES:\n"
               "        out.append(cfg.get(key, None))\n"
               "    return out\n")
        with _Planted(src, {"planted": {"health_iv": 1, "reaper_iv": 2, "unused_iv": 3}}) as rows:
            self.assertEqual(rows["planted.health_iv"][0], "WIRED")
            self.assertEqual(rows["planted.reaper_iv"][0], "WIRED")
            # a sibling that is NOT in the table is still unread
            self.assertEqual(rows["planted.unused_iv"][0], "UNREAD")


class TestScannerRefusesFalsePositives(unittest.TestCase):
    """Direction 2: a key that is NOT read stays UNREAD.

    Each fixture is a shape A3 measured the loose "any quoted dotted path is a
    read" fix against and rejected.
    """

    def test_bare_quoted_dotted_path_is_not_a_read(self):
        src = ('DOC = "see planted.unread in the manual"\n'
               'TABLE = ["planted.unread"]\n'
               '\n'
               'def f():\n'
               '    return "planted.unread"\n')
        with _Planted(src, {"planted": {"unread": 1}}) as rows:
            self.assertEqual(rows["planted.unread"][0], "UNREAD")

    def test_leaf_name_collision_is_not_a_read(self):
        """`provider`/`store` appear as quoted literals all over the tree; that
        is a column name, not a config read."""
        src = ('def f(row):\n'
               '    return row.get("provider"), row["store"]\n')
        with _Planted(src, {"provider": "chronicle", "store": "sqlite"}) as rows:
            self.assertEqual(rows["provider"][0], "UNREAD")
            self.assertEqual(rows["store"][0], "UNREAD")

    def test_reading_a_parent_dict_does_not_wire_its_children(self):
        """`cfg.get("principals")` is a read of `principals`, not of every key
        under it — `principals.deployment` really is unread."""
        src = ('def f(cfg):\n'
               '    return configure(cfg.get("planted.parent"))\n'
               '\n'
               'def configure(spec):\n'
               '    return spec\n')
        with _Planted(src, {"planted": {"parent": {"used": 1, "deployment": "x"}}}) as rows:
            self.assertEqual(rows["planted.parent.deployment"][0], "UNREAD")

    def test_a_helper_body_does_not_wire_every_key_under_its_prefix(self):
        """`_cfg_percent`'s own `f"context_engine.{name}"` must not wire
        `context_engine.engine`; only the literals its CALLERS pass count."""
        src = ("class C:\n"
               "    def _pct(self, name, default):\n"
               "        return self.cfg.get(f'planted.{name}', default)\n"
               "\n"
               "    def f(self):\n"
               "        return self._pct('low_watermark', 0.55)\n")
        with _Planted(src, {"planted": {"low_watermark": 0.55, "engine": "chronicle"}}) as rows:
            self.assertEqual(rows["planted.low_watermark"][0], "WIRED")
            self.assertEqual(rows["planted.engine"][0], "UNREAD")

    def test_tests_do_not_count_as_reads(self):
        """This very file reads plenty of keys. That must not wire them."""
        rows = audit()
        self.assertEqual(rows["retrieval.query_understanding.hyde"][0], "DORMANT")


# ==========================================================================
# (3) THE KEYS THIS TASK WIRED: the config must actually win
# ==========================================================================

class TestConfidenceTablesHonourOverrides(unittest.TestCase):
    """`confidence.base.*` / `confidence.trust_ceiling.*` were module constants
    (`trust.py` imported CONFIDENCE_BASE/TRUST_CEILING), so an operator override
    changed nothing — while hostmodel.py told them host facts used "the
    operator's configured confidence.base"."""

    def test_base_confidence_reads_config(self):
        self.assertEqual(trust.base_confidence("user_direct"), 0.85)
        cfg = Config({"confidence": {"base": {"user_direct": 0.95}}})
        self.assertEqual(trust.base_confidence("user_direct", cfg), 0.95)
        # an untouched sibling keeps its default (deep merge)
        self.assertEqual(trust.base_confidence("tool_output", cfg), 0.50)

    def test_trust_ceiling_reads_config(self):
        self.assertEqual(trust.ceiling(2), 0.75)
        cfg = Config({"confidence": {"trust_ceiling": {2: 0.99}}})
        self.assertEqual(trust.ceiling(2, cfg), 0.99)

    def test_trust_ceiling_survives_a_yaml_string_key(self):
        cfg = Config({"confidence": {"trust_ceiling": {"2": 0.99}}})
        self.assertEqual(trust.ceiling(2, cfg), 0.99)

    def test_no_config_keeps_the_module_constants(self):
        """Every `Reducer(store)` path constructs with cfg=None."""
        self.assertEqual(trust.base_confidence("user_direct", None), 0.85)
        self.assertEqual(trust.ceiling(4, None), 1.00)


class TestStoredFactConfidenceFollowsConfig(unittest.TestCase):
    """ACCEPTANCE (A12): a config override of `confidence.base.user_direct`
    changes a stored fact's confidence."""

    def _store_fact(self, overrides):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cfg = {"embeddings": {"model": "hashing"}}
        cfg.update(overrides)
        core = ChronicleCore(hermes_home=tmp, config=cfg)
        key = {"entity_id": "e:pat_testley", "predicate_canonical": "works_at",
               "attribute": "works_at", "qualifiers": {}, "owner": "default",
               "domain": "user"}
        eid = core.capture.append(
            "asserted",
            {"kind": "fact", "key": key, "body": "Acme Fake Co",
             "source_type": "user_direct", "domain": "user", "status": "active"},
            actor="user", trust_level=4)
        core.tick()
        bid = compute_belief_id("fact", key, [eid])
        row = core.store.get_belief("facts", bid)
        self.assertIsNotNone(row, "fixture did not store a fact")
        return row["confidence"]

    def test_default_and_overridden_confidence_differ(self):
        default_conf = self._store_fact({})
        raised = self._store_fact({"confidence": {"base": {"user_direct": 0.95}}})
        lowered = self._store_fact({"confidence": {"base": {"user_direct": 0.30}}})
        self.assertAlmostEqual(default_conf, 0.85, places=6)
        self.assertAlmostEqual(raised, 0.95, places=6)
        self.assertAlmostEqual(lowered, 0.30, places=6)

    def test_trust_ceiling_override_caps_a_stored_fact(self):
        capped = self._store_fact({"confidence": {"base": {"user_direct": 0.95},
                                                  "trust_ceiling": {4: 0.60}}})
        self.assertAlmostEqual(capped, 0.60, places=6)


class TestDomainContradictionPolicyHonoursConfig(unittest.TestCase):
    """`domains.<d>.contradiction_policy` was shadowed by reducer.DOMAIN_POLICY."""

    def test_default_falls_back_to_the_module_table(self):
        self.assertEqual(contradiction_policy(None, "user"), "flag_for_review")
        self.assertEqual(contradiction_policy(Config(), "agent"), "newer_wins")
        self.assertEqual(contradiction_policy(Config(), "general"), "refetch")

    def test_override_wins(self):
        cfg = Config({"domains": {"user": {"contradiction_policy": "newer_wins"}}})
        self.assertEqual(contradiction_policy(cfg, "user"), "newer_wins")

    def test_unknown_domain_uses_the_general_default(self):
        self.assertEqual(contradiction_policy(Config(), "no_such_domain"), "refetch")

    def test_a_typo_falls_back_rather_than_silently_changing_behaviour(self):
        cfg = Config({"domains": {"user": {"contradiction_policy": "newer_winz"}}})
        self.assertEqual(contradiction_policy(cfg, "user"), "flag_for_review")


class TestReaperSwitchIsReal(unittest.TestCase):
    def test_enabled_by_default(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        core = ChronicleCore(hermes_home=tmp, config={"embeddings": {"model": "hashing"}})
        self.assertTrue(core.reaper_enabled)

    def test_disabling_the_reaper_skips_startup_recovery(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        core = ChronicleCore(hermes_home=tmp,
                             config={"embeddings": {"model": "hashing"},
                                     "reaper": {"enabled": False}})
        self.assertFalse(core.reaper_enabled)
        calls = []
        core.reaper.startup_recovery = lambda *a, **k: calls.append(1)
        core.initialize("s-a12-reaper")
        self.assertEqual(calls, [], "reaper.enabled: false must stop startup recovery")


# ==========================================================================
# (4) security.encrypt_at_rest — a promise that did nothing
# ==========================================================================

class TestSecurityPromisesAreRefused(unittest.TestCase):
    """`security.encrypt_at_rest: true` shipped as a DEFAULT on a store that
    writes SQLite, git objects and vector blobs in the clear. A security promise
    that silently does nothing is worse than an absent one, so the key is gone
    from DEFAULTS and setting it is a hard refusal, not a silent ignore: ignoring
    leaves the operator's false belief intact."""

    def test_key_is_gone_from_defaults(self):
        self.assertNotIn("security", DEFAULTS)
        self.assertNotIn("encryption", DEFAULTS["principals"])
        paths = {p for p, _ in leaf_keys(DEFAULTS)}
        self.assertNotIn("security.encrypt_at_rest", paths)
        self.assertNotIn("principals.encryption.restricted_partition_keys", paths)

    def test_setting_encrypt_at_rest_refuses_to_boot(self):
        for value in (True, False, "yes"):
            with self.assertRaises(ValueError) as ctx:
                Config({"security": {"encrypt_at_rest": value}})
            msg = str(ctx.exception)
            self.assertIn("security.encrypt_at_rest", msg)
            self.assertIn("does not encrypt", msg)

    def test_setting_restricted_partition_keys_refuses_to_boot(self):
        with self.assertRaises(ValueError) as ctx:
            Config({"principals": {"encryption": {"restricted_partition_keys": True}}})
        self.assertIn("no per-partition encryption keys", str(ctx.exception))

    def test_unrelated_security_shaped_config_still_boots(self):
        """The refusal is per-key, not "anything under security:"."""
        cfg = Config({"security": {"some_future_key": 1}})
        self.assertEqual(cfg.get("security.some_future_key"), 1)

    def test_every_refused_key_explains_itself(self):
        for path, why in REFUSED_KEYS.items():
            self.assertGreaterEqual(len(why), 60, path)


# ==========================================================================
# (5) deleted keys stay deleted
# ==========================================================================

class TestDeletedKeys(unittest.TestCase):
    DELETED = [
        "provider", "store", "principals.deployment",
        "context.weights.relevance", "context.weights.recency",
        "context.weights.salience", "context.weights.pinned",
        "context_engine.keep_weights.redundancy_vs_store",
        # `retrieval.predictive_prefetch` is NOT here any more. A12 deleted it
        # and A13, which removed its dead consumer, kept it and declared it
        # dormant instead. The v5.7.0 integration keeps A13's form: A12's
        # contract is "wired, deleted OR declared", declared satisfies it, and a
        # declared key tells an operator who set it while a deleted one does not
        # (REFUSED_KEYS covers only the two security keys). See engine/config.py.
        "vector_index.bruteforce_ceiling",
        "calibration.refit_every", "tier_triggers.write_lock_contention",
        "tier_triggers.vector_count", "tier_triggers.sqlite_max_gb",
        "security.encrypt_at_rest",
        "principals.encryption.restricted_partition_keys",
    ]

    def test_deleted_keys_are_absent(self):
        paths = {p for p, _ in leaf_keys(DEFAULTS)}
        for path in self.DELETED:
            self.assertNotIn(path, paths)

    def test_deleted_keys_are_not_declared_dormant(self):
        """A deleted key must not linger as a declaration — that is the same
        drift wearing the other hat."""
        for path in self.DELETED:
            self.assertNotIn(path, DECLARED_DORMANT)


if __name__ == "__main__":
    unittest.main()
