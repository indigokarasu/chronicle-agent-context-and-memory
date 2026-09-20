"""
Chronicle — a pointer that resolves through nothing is not a pointer.

Phase E's acceptance was "every pointer resolves correctly through Hermes".
Masking shipped first and left a label copied out of the text, which nobody
could ask a question about: `«redacted:vault_ab12cd34ef56»` looked like a
reference whether or not it named anything. This is the half that answers.

The rule the whole module turns on: it calls the vault's `get_meta`, which is
metadata by construction, and NEVER `resolve_secret`, whose own docstring says
callers must never put its return into tool results, logs or any string that
reaches the session DB -- which is every surface Chronicle has.

Fixtures use obviously fake values.
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _tmp_support import temp_home

from engine import credentials as C
from engine import secrets as S

VAULT_ID = "vault_ab12cd34ef56"


class _FakeMeta:
    """The shape of VaultItemMeta: metadata only, no secret values."""
    kind, label, origin = "login", "Zorblax share", "https://zorblax.invalid"
    created_at, identifier_type, identifier = "2026-08-01T10:00:00Z", "email", "pat@example.invalid"
    has_otp = False


class _FakeVault:
    def __init__(self, known=(VAULT_ID,)):
        self.known = set(known)
        self.secret_calls = 0

    def get_meta(self, item_id):
        return _FakeMeta() if item_id in self.known else None

    def resolve_secret(self, item_id):          # must never be reached from here
        self.secret_calls += 1
        return {"password": "zz9-Plural-Zalpha7"}


class TestFindingPointers(unittest.TestCase):
    def test_it_reads_them_out_of_what_masking_wrote(self):
        said = C.redact("the Zoom login is %s password: zz9-Plural-Zalpha7" % VAULT_ID)
        self.assertEqual(S.pointers_in(said), [VAULT_ID])

    def test_several_in_one_text_and_no_duplicates(self):
        text = ("A=«redacted:env:FOO_KEY» B=«redacted:vault_ab12cd34ef56» "
                "C=«redacted:env:FOO_KEY»")
        self.assertEqual(S.pointers_in(text), ["env:FOO_KEY", VAULT_ID])

    def test_a_bare_sentinel_carries_none(self):
        self.assertEqual(S.pointers_in("password: " + C.REDACTED), [])

    def test_the_forms(self):
        self.assertEqual(S.form_of(VAULT_ID), S.VAULT)
        self.assertEqual(S.form_of("env:OPENROUTER_API_KEY"), S.ENV)
        self.assertEqual(S.form_of("ghp_…"), S.PREFIX)
        self.assertEqual(S.form_of("something else"), S.UNKNOWN)


class TestResolving(unittest.TestCase):
    def setUp(self):
        self.vault = _FakeVault()
        self._real = S._vault
        S._vault = lambda: self.vault

    def tearDown(self):
        S._vault = self._real

    def test_a_known_item_resolves_to_metadata(self):
        r = S.resolve(VAULT_ID)
        self.assertTrue(r["resolves"])
        self.assertEqual(r["kind"], "login")
        self.assertEqual(r["identifier"], "pat@example.invalid")
        self.assertEqual(r["origin"], "https://zorblax.invalid")

    def test_it_never_asks_the_vault_for_the_value(self):
        """The one rule. resolve_secret's docstring forbids its return
        reaching the session DB, and everything Chronicle emits does."""
        S.resolve(VAULT_ID)
        S.describe(VAULT_ID)
        S.audit(["x «redacted:%s» y" % VAULT_ID])
        self.assertEqual(self.vault.secret_calls, 0)

    def test_no_secret_value_appears_in_any_output(self):
        blob = repr(S.resolve(VAULT_ID)) + S.describe(VAULT_ID) + repr(S.audit(
            ["«redacted:%s»" % VAULT_ID]))
        self.assertNotIn("Plural-Zalpha7", blob)
        self.assertNotIn("password", blob.lower().replace("passwordless", ""))

    def test_an_unknown_id_does_not_resolve(self):
        r = S.resolve("vault_ffffffffffff")
        self.assertFalse(r["resolves"])
        self.assertIn("no vault item", r["reason"])

    def test_a_vendor_prefix_is_not_a_reference(self):
        r = S.resolve("ghp_…")
        self.assertFalse(r["resolves"])
        self.assertIn("KIND", r["reason"])


class TestEnvPointers(unittest.TestCase):
    def test_set_means_resolves_and_the_value_is_not_read(self):
        import os
        os.environ["CHRONICLE_FAKE_KEY_FOR_TEST"] = "sk-or-v1-abcdef0123456789abcdef"
        try:
            r = S.resolve("env:CHRONICLE_FAKE_KEY_FOR_TEST")
            self.assertTrue(r["resolves"])
            self.assertNotIn("abcdef0123456789", repr(r))
            self.assertNotIn("value", r)
        finally:
            del os.environ["CHRONICLE_FAKE_KEY_FOR_TEST"]

    def test_unset_does_not_resolve(self):
        r = S.resolve("env:CHRONICLE_DEFINITELY_UNSET_KEY")
        self.assertFalse(r["resolves"])


class TestOfflineIsNotDangling(unittest.TestCase):
    """A checkout with no Hermes on the path must say "I cannot tell", not
    report every pointer as broken."""

    def setUp(self):
        self._real = S._vault
        S._vault = lambda: None

    def tearDown(self):
        S._vault = self._real

    def test_it_says_it_cannot_tell(self):
        r = S.resolve(VAULT_ID)
        self.assertFalse(r["resolves"])
        self.assertEqual(r["reason"], "vault unavailable")

    def test_audit_files_it_as_undecidable_not_dangling(self):
        a = S.audit(["«redacted:%s»" % VAULT_ID])
        self.assertEqual(a["undecidable"], [VAULT_ID])
        self.assertEqual(a["dangling"], [])


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.vault = _FakeVault()
        self._real = S._vault
        S._vault = lambda: self.vault

    def tearDown(self):
        S._vault = self._real

    def test_it_separates_what_resolves_from_what_does_not(self):
        a = S.audit(["a «redacted:%s»" % VAULT_ID,
                     "b «redacted:vault_ffffffffffff»",
                     "c " + C.REDACTED])
        self.assertEqual(a["pointers"], 2)
        self.assertEqual(a["resolved"], [VAULT_ID])
        self.assertEqual([p for p, _r in a["dangling"]], ["vault_ffffffffffff"])

    def test_it_runs_over_what_masking_actually_produces(self):
        """End to end: mask real text, then audit the masked text."""
        said = C.redact("the Zoom login is %s password: zz9-Plural-Zalpha7" % VAULT_ID)
        self.assertNotIn("Plural-Zalpha7", said)
        self.assertEqual(S.audit([said])["resolved"], [VAULT_ID])


class TestAgainstTheRealVaultIfPresent(unittest.TestCase):
    """No fake: if Hermes is importable, a made-up id must not resolve."""

    def test_a_fabricated_id_never_resolves(self):
        home = temp_home(prefix="vaultres_")
        try:
            r = S.resolve("vault_0123456789ab")
            self.assertFalse(r["resolves"])
        finally:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
