"""
Chronicle — a credential is not a memory.

On a production store the extractor turned two messages the user sent the
agent -- a site login and a file-sharing account, each "Username: …
Password: …" -- into episodes: beliefs, which per-turn recall puts into later
prompts unasked and the dashboard shows. The transcript keeps the message (the
agent it was given to can still search for it); a belief must not carry the
value, and a turn's unasked recall must not repeat it. The belief itself stays,
masked: an appointment whose meeting link carries `?pwd=` is still an
appointment.

Fixtures use obviously fake values.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine import credentials as C
from engine.core import ChronicleCore
from provider import ChronicleMemoryProvider

CFG = {"embeddings": {"model": "hashing"}}
SID = "20260910_101010_ab12cd"
SAID = "Zorblax share login: Username: robin_fake_123 Password: Qx!Placeholder-00-Test_000"


class TestTheShape(unittest.TestCase):
    def test_a_labelled_value_is_a_credential(self):
        for text in ("Login: patfake password : zz9-Plural-Zalpha7 for tunes.example.invalid",
                     SAID, "my password is hunter2", "passcode=AbCdEf", "PIN: 4821",
                     "the Acme Fake Co API key: 9f8e7d6c5b4a", "use sk-FAKEfake1234567890abcdef"):
            with self.subTest(text=text):
                self.assertTrue(C.contains_secret(text))
                # the sentinel, whatever label it ends up carrying: a
                # vendor-prefixed token gets «redacted:sk-…», a bare password
                # gets «redacted-secret», and both are masked.
                self.assertIn("«redacted", C.redact(text))

    def test_talking_about_passwords_is_not_one(self):
        for text in ("The full password is not in the log", "Your password has been updated",
                     "You have updated your Acme Fake Co password.", "Gumroad password-reset request",
                     "the token is expired", "pin: 12", "reset the Zorblax password tomorrow"):
            with self.subTest(text=text):
                self.assertFalse(C.contains_secret(text))
                self.assertEqual(C.redact(text), text)

    def test_masking_is_final(self):
        for text in (SAID, "https://meet.example.invalid/j/1?pwd=AbC123xyz", "my password is hunter2"):
            with self.subTest(text=text):
                once = C.redact(text)
                self.assertFalse(C.contains_secret(once))
                self.assertEqual(C.redact(once), once)

    def test_only_the_value_goes(self):
        self.assertEqual(C.redact(SAID),
                         "Zorblax share login: Username: robin_fake_123 Password: " + C.REDACTED)


class TestTheStore(unittest.TestCase):
    def setUp(self):
        self.home = temp_home(prefix="cred_")
        self.prov = ChronicleMemoryProvider()
        self.prov.initialize(SID, hermes_home=self.home, principal_id="default", config=CFG)
        self.core = self.prov.core

    def tearDown(self):
        ChronicleCore._instances.pop(self.core.store.db_path, None)
        shutil.rmtree(self.home, ignore_errors=True)

    def beliefs(self):
        c = self.core.store._conn()
        rows = [r[0] for r in c.execute("SELECT summary FROM episodes WHERE status='active'")]
        rows += [r[0] for r in c.execute("SELECT body FROM notes WHERE status='active'")]
        rows += [r[0] for r in c.execute("SELECT value FROM facts WHERE status='active'")]
        return rows

    def test_no_belief_holds_the_value(self):
        self.core.capture.observe(SAID, "Saved, I'll use it for the share.", session_id=SID)
        self.core.capture.finalize_session(SID, "clean_exit")
        self.core.process_pending()
        self.assertFalse([b for b in self.beliefs() if "Qx!Placeholder" in (b or "")])

    def test_an_asserted_one_is_masked_in_the_fold(self):
        for kind, key, body in (
                ("episode", {"title": "share login"}, "Pat Testley said the password is Zorb-42-lax"),
                ("note", {"note_type": "norm", "subject": "login"}, "Always use api key: 9f8e7d6c5b4a"),
                ("fact", {"entity_id": "user", "attribute": "wifi", "predicate_canonical": "wifi",
                          "qualifiers_hash": "", "qualifiers": {}, "owner": "default", "domain": "user"},
                 "Riverton wifi passcode=AbCdEf")):
            self.core.capture.append("asserted", {"kind": kind, "key": key, "body": body, "confidence": 0.9,
                                                  "source_event": "x", "source_type": "user_direct"},
                                     actor="user", owner="default", trust_level=3)
        self.core.capture.append("asserted", {"kind": "note", "key": {"note_type": "norm", "subject": "x"},
                                              "body": "Reset the Zorblax password on Fridays",
                                              "confidence": 0.9, "source_event": "x",
                                              "source_type": "user_direct"},
                                 actor="user", owner="default", trust_level=3)
        self.core.process_pending()
        held = self.beliefs()
        self.assertFalse([b for b in held if "Zorb-42" in b or "9f8e7d" in b or "AbCdEf" in b], held)
        self.assertIn("Pat Testley said the password is " + C.REDACTED, held)
        self.assertIn("Reset the Zorblax password on Fridays", held)

    def test_an_appointment_keeps_its_meeting_but_not_its_passcode(self):
        self.core.capture.append("asserted", {
            "kind": "fact", "key": {"entity_id": "user", "attribute": "had_appointment",
                                    "predicate_canonical": "had_appointment", "qualifiers_hash": "",
                                    "qualifiers": {}, "owner": "default", "domain": "user"},
            "body": "Fake Clinic video visit — 2026-03-05 — https://meet.example.invalid/j/123?pwd=AbC123xyz",
            "confidence": 0.9, "source_event": "x", "source_type": "user_direct"},
            actor="user", owner="default", trust_level=3)
        self.core.process_pending()
        self.assertIn("Fake Clinic video visit — 2026-03-05 — https://meet.example.invalid/j/123?pwd=" + C.REDACTED,
                      self.beliefs())

    def test_a_credential_in_the_key_is_masked_too(self):
        self.core.capture.append("asserted", {"kind": "episode", "key": {"title": "share password is Zorb-42-lax"},
                                              "body": "Pat Testley shared the Zorblax login", "confidence": 0.9,
                                              "source_event": "x", "source_type": "user_direct"},
                                 actor="user", owner="default", trust_level=3)
        self.core.process_pending()
        titles = [r[0] for r in self.core.store._conn().execute("SELECT title FROM episodes WHERE status='active'")]
        self.assertFalse([t for t in titles if "Zorb-42" in (t or "")], titles)
        self.assertIn("Pat Testley shared the Zorblax login", self.beliefs())

    def test_a_correction_or_an_inference_is_masked_too(self):
        self.core.capture.append("asserted", {"kind": "note", "key": {"note_type": "norm", "subject": "share"},
                                              "body": "The Zorblax share needs a login", "confidence": 0.9,
                                              "source_event": "x", "source_type": "user_direct"},
                                 actor="user", owner="default", trust_level=3)
        self.core.process_pending()
        bid = self.core.store._conn().execute(
            "SELECT belief_id FROM notes WHERE body='The Zorblax share needs a login'").fetchone()[0]
        self.core.capture.append("corrected", {"belief_id": bid, "reason": "more detail",
                                               "new_body": "The Zorblax share login password is Zorb-42-lax"},
                                 actor="user", owner="default")
        self.core.capture.append("derived", {"kind": "note", "key": {"note_type": "belief", "subject": "inferred"},
                                             "body": "Robin Placeholder's api key: 9f8e7d6c5b4a", "rule_id": "r1",
                                             "premises": [bid], "status": "active"},
                                 actor="system", owner="default")
        self.core.process_pending()
        c = self.core.store._conn()
        every = [r[0] for r in c.execute("SELECT body FROM notes")]
        self.assertFalse([b for b in every if "Zorb-42" in b or "9f8e7d" in b], every)
        self.assertIn("The Zorblax share login password is " + C.REDACTED, every)

    def test_unasked_recall_masks_it_explicit_search_does_not(self):
        self.core.capture.observe(SAID, "Saved.", session_id=SID)
        self.core.process_pending()
        later = self.prov.prefetch("what is the Zorblax share login?", session_id="20260918_000000_ff99ee")
        self.assertIn("Zorblax share login", later)
        self.assertNotIn("Qx!Placeholder", later)
        self.assertIn(C.REDACTED, later)
        found = self.core.retrieval.get_context("Zorblax share login", token_budget=1200, principal="default")
        self.assertIn("Qx!Placeholder-00-Test_000", found)


class TestAPointerBack(unittest.TestCase):
    """Phase E. A bare marker is a dead end: an agent that meets one asks the
    user to type the secret again, which is how a secret reaches a transcript
    twice. With `credentials.pointers` on, the marker says where the value
    lives -- read off the TEXT, never out of the vault or the environment,
    because guessing which vault item a masked string was would be inventing a
    reference. Fixtures use obviously fake values."""

    def test_on_by_default(self):
        said = "OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789abcdef0123456789"
        self.assertEqual(C.redact(said), "OPENROUTER_API_KEY=«redacted:env:OPENROUTER_API_KEY»")

    def test_turning_it_off_leaves_the_bare_sentinel(self):
        said = "OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789abcdef0123456789"
        self.assertEqual(C.redact(said, False), "OPENROUTER_API_KEY=" + C.REDACTED)

    def test_an_env_var_name_is_the_pointer(self):
        said = "OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789abcdef0123456789"
        self.assertEqual(C.redact(said, True), "OPENROUTER_API_KEY=«redacted:env:OPENROUTER_API_KEY»")

    def test_a_vault_id_beside_the_value_is_the_pointer(self):
        said = "the login is vault_ab12cd34ef56, password: zz9-Plural-Zalpha7"
        out = C.redact(said, True)
        self.assertIn("«redacted:vault_ab12cd34ef56»", out)
        self.assertNotIn("zz9-Plural", out)

    def test_otherwise_the_vendor_prefix_says_what_kind_it_was(self):
        self.assertEqual(C.redact("token ghp_abcdefghij0123456789abcdefghij", True),
                         "token «redacted:ghp_\u2026»")

    def test_a_plain_password_gets_no_invented_pointer(self):
        """PASSWORD carries no underscore and names no variable: there is
        nothing in the text to point at, so the sentinel stays bare."""
        self.assertEqual(C.redact("password: zz9-Plural-Zalpha7", True),
                         "password: " + C.REDACTED)

    def test_the_sentinel_is_the_hosts_and_cannot_be_mistaken_for_a_value(self):
        """Hermes masks to «redacted-secret» / «redacted:ghp_…» and tests
        `startswith("«redacted")` to see its own work. Chronicle used to emit
        `[redacted]`, which matched neither, so a host redaction pass did not
        recognise it as masked. And the shape is load-bearing: Hermes issue
        #35519 was an agent writing a truncated-looking mask back into a
        config file, so the replacement must not read as a usable value --
        which is why the pointer is INSIDE the sentinel, not in place of the
        value it replaced."""
        self.assertTrue(C.REDACTED.startswith("«redacted"))
        for said in ("OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789abcdef0123456789",
                     "the login is vault_ab12cd34ef56, password: zz9-Plural-Zalpha7"):
            with self.subTest(said=said):
                out = C.redact(said, True)
                masked = out.split("«")[1]
                self.assertTrue(masked.startswith("redacted"), out)
                self.assertIn("»", out)

    def test_no_part_of_the_secret_survives(self):
        for said in ("OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789abcdef0123456789",
                     "token ghp_abcdefghij0123456789abcdefghij",
                     "password: zz9-Plural-Zalpha7"):
            with self.subTest(said=said):
                out = C.redact(said, True)
                for secret in ("abcdef0123456789", "abcdefghij0123456789", "Plural-Zalpha7"):
                    self.assertNotIn(secret, out)

    def test_it_is_still_idempotent(self):
        for said in ("OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789abcdef0123456789",
                     "the login is vault_ab12cd34ef56, password: zz9-Plural-Zalpha7",
                     "token ghp_abcdefghij0123456789abcdefghij"):
            with self.subTest(said=said):
                once = C.redact(said, True)
                self.assertEqual(C.redact(once, True), once)
                self.assertEqual(C.redact(once), once)

    def test_a_pointer_is_not_read_out_of_the_vault(self):
        """The only vault id it can render is one the text already held."""
        self.assertEqual(C.pointer_for("password: zz9-Plural-Zalpha7", 10, 27), "")

    def test_the_default_is_on(self):
        from engine.config import DEFAULTS
        self.assertIs(DEFAULTS["credentials"]["pointers"], True)


class TestThePointerThroughTheFold(unittest.TestCase):
    """The wiring, not the regex: a belief folded with the flag on carries the
    pointer, and one folded with it off carries what every release before this
    carried. Fixtures use obviously fake values."""

    BODY = ("set OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789abcdef0123456789 in the profile "
            "env; the Zoom login is vault_ab12cd34ef56 password: zz9-Plural-Zalpha7")

    def folded(self, pointers):
        home = temp_home(prefix="ptrfold_")
        sid = "20260919_170000_p%d" % pointers
        prov = ChronicleMemoryProvider()
        try:
            prov.initialize(sid, hermes_home=home, principal_id="default",
                            config={"embeddings": {"model": "hashing"},
                                    "credentials": {"pointers": pointers}})
            prov.core.capture.append("asserted", {
                "kind": "episode", "key": {"title": "the provider key and the Zoom login",
                                           "session_ref": sid},
                "body": self.BODY, "confidence": 0.9, "source_event": "probe",
                "source_type": "probe"}, actor="agent", owner="default", trust_level=3)
            prov.core.process_pending()
            return [r[0] for r in prov.core.store._conn().execute("SELECT summary FROM episodes")]
        finally:
            ChronicleCore._instances.pop(prov.core.store.db_path, None)
            shutil.rmtree(home, ignore_errors=True)

    def test_off_is_what_every_release_before_this_stored(self):
        rows = self.folded(False)
        self.assertTrue(rows)
        self.assertIn("OPENROUTER_API_KEY=" + C.REDACTED, rows[0])
        self.assertIn("password: " + C.REDACTED, rows[0])

    def test_on_the_belief_says_where_to_fetch_it(self):
        rows = self.folded(True)
        self.assertTrue(rows)
        self.assertIn("«redacted:env:OPENROUTER_API_KEY»", rows[0])
        self.assertIn("«redacted:vault_ab12cd34ef56»", rows[0])

    def test_neither_stores_any_of_the_secret(self):
        for pointers in (False, True):
            with self.subTest(pointers=pointers):
                body = " ".join(self.folded(pointers))
                for secret in ("abcdef0123456789", "Plural-Zalpha7"):
                    self.assertNotIn(secret, body)


class TestTheHandoffChronicleWrites(unittest.TestCase):
    """The compaction handoff is the one surface Chronicle AUTHORS.

    A tool result that was kept keeps whatever it said: that is the
    transcript, and the model has already read it. The handoff is different.
    Chronicle writes it from a span it is folding AWAY, and it survives where
    the span does not -- after a rotation the child session carries the
    handoff and not the turns behind it, so a value left here outlives the
    message it came from and travels into a conversation that never saw it.

    Measured before this was fixed: the capped tool result was masked, the
    belief was masked, and the handoff carried the key in full.

    Fixtures use an obviously fake key.
    """

    SECRET = "sk-or-v1-abcdef0123456789abcdef0123456789"

    def session(self, n=30):
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(n):
            msgs.append({"role": "user",
                         "content": "turn %d: check the Zorblax ledger %s" % (i, "detail " * 30)})
            msgs.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": "c%d" % i, "type": "function",
                 "function": {"name": "terminal", "arguments": '{"command": "env | grep OPENROUTER"}'}}]})
            msgs.append({"role": "tool", "tool_call_id": "c%d" % i,
                         "content": "OPENROUTER_API_KEY=%s %s" % (self.SECRET, "row " * 40)})
            msgs.append({"role": "assistant",
                         "content": "ledger %d reconciled %s" % (i, "note " * 30)})
        return msgs

    def compacted(self, pointers):
        from context import ChronicleContextEngine
        home = temp_home(prefix="handcred_")
        try:
            eng = ChronicleContextEngine()
            eng.on_session_start("20260919_180000_hc%d" % pointers, hermes_home=home,
                                 principal_id="default",
                                 config={"embeddings": {"model": "hashing"},
                                         "curation": {"drain": {"per_turn": 0, "background": False}},
                                         "credentials": {"pointers": pointers},
                                         "context_engine": {"digest_episodes": True}})
            eng.update_model("fake-model", 4000)
            out = eng.compress(self.session())
            eng.core.process_pending()
            eps = [r[0] for r in eng.core.store._conn().execute(
                "SELECT summary FROM episodes WHERE status='active'")]
            return out, eps
        finally:
            ChronicleCore._instances.pop(home, None)
            shutil.rmtree(home, ignore_errors=True)

    def handoff(self, out):
        for m in out:
            if "CONTEXT COMPACTION" in (m.get("content") or ""):
                return m["content"]
        self.fail("this fixture did not compact: there is no handoff to check")

    def test_the_handoff_names_the_call_without_the_value(self):
        for pointers in (False, True):
            with self.subTest(pointers=pointers):
                out, _eps = self.compacted(pointers)
                hand = self.handoff(out)
                self.assertIn("OPENROUTER_API_KEY=", hand)   # the reader still learns what ran
                self.assertNotIn(self.SECRET, hand)

    def test_with_pointers_the_handoff_says_where_it_lives(self):
        out, _eps = self.compacted(True)
        self.assertIn("«redacted:env:OPENROUTER_API_KEY»", self.handoff(out))

    def test_a_distilled_episode_never_carries_it(self):
        for pointers in (False, True):
            with self.subTest(pointers=pointers):
                _out, eps = self.compacted(pointers)
                self.assertTrue(any("OPENROUTER" in e for e in eps), "fixture wrote no digest")
                for e in eps:
                    self.assertNotIn(self.SECRET, e)

    def test_a_kept_tool_result_still_says_what_it_said(self):
        """The transcript is not rewritten. What this class protects is the
        line Chronicle writes, not the turns it left alone."""
        out, _eps = self.compacted(False)
        carriers = [m for m in out if self.SECRET in (m.get("content") or "")]
        self.assertTrue(carriers, "the fixture kept no tool result verbatim")
        self.assertTrue(all(m.get("role") == "tool" for m in carriers),
                        [m.get("role") for m in carriers])


if __name__ == "__main__":
    unittest.main()
