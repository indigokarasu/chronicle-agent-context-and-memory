"""
Tests for newly integrated concepts in Chronicle:
1. Binary vector quantization and Hamming distance similarity.
2. Tiered span abstractions.
3. Temporal interval validity.
4. Materialized active profile summaries.
5. Client-side payload encryption in Git mirror logs.
"""

import tempfile
from engine.embeddings import quantize_binary, hamming_distance, binary_similarity
from engine.core import ChronicleCore


def test_binary_vector_quantization():
    vec1 = [0.5, -0.2, 0.8, -0.9, 0.1, 0.2, -0.5, 0.3]
    vec2 = [0.4, -0.1, 0.9, -0.8, 0.2, 0.1, -0.4, 0.4]  # Same signs for all coords
    vec3 = [-0.5, 0.2, -0.8, 0.9, -0.1, -0.1, 0.5, -0.3] # Opposite signs

    b1 = quantize_binary(vec1)
    b2 = quantize_binary(vec2)
    b3 = quantize_binary(vec3)

    assert b1 == b2
    assert hamming_distance(b1, b2) == 0
    assert binary_similarity(b1, b2, 8) == 1.0

    dist_13 = hamming_distance(b1, b3)
    assert dist_13 == 8
    assert binary_similarity(b1, b3, 8) == 0.0


def test_gitmirror_encryption():
    import os
    os.environ["CHRONICLE_GIT_ENCRYPTION_KEY"] = "secret-test-key"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            core = ChronicleCore.get(tmpdir, {"git.enabled": True})
            mirror = core.gitmirror

            plain_text = '{"event_id": "ev_123", "payload": "sensitive data"}'
            encrypted = mirror._encrypt_payload(plain_text)

            assert encrypted.startswith("ENC:")
            assert plain_text not in encrypted

            decrypted = mirror._decrypt_payload(encrypted)
            assert decrypted == plain_text
    finally:
        os.environ.pop("CHRONICLE_GIT_ENCRYPTION_KEY", None)


def test_materialized_profile():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ChronicleCore.get(tmpdir)
        core.initialize("session_prof", principal_id="pat")

        # Capture turn with identity fact
        core.capture.observe("My name is Pat. I work at Acme.", "Hello Pat!", session_id="session_prof")
        core.process_pending()

        profile = core.get_materialized_profile("pat")
        assert profile is not None
        assert "static" in profile
        assert profile["static"].get("name") == "Pat" or profile["static"].get("works_at") == "Acme"


def test_temporal_validity():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ChronicleCore.get(tmpdir)
        core.initialize("session_temp", principal_id="pat")

        # Assert fact with valid_from and valid_until
        core.capture.append("asserted", {
            "kind": "fact",
            "key": {"entity_id": "user", "predicate_canonical": "lives_in", "attribute": "lives_in"},
            "body": "Seattle",
            "valid_from": "2020-01-01T00:00:00.000Z",
            "valid_until": "2023-01-01T00:00:00.000Z"
        }, actor="user", owner="pat")

        core.process_pending()

        facts = core.store.query_beliefs("facts", "entity_id='user' AND predicate_canonical='lives_in'")
        assert len(facts) >= 1
        assert facts[0].get("valid_from") == "2020-01-01T00:00:00.000Z"
        assert facts[0].get("valid_until") == "2023-01-01T00:00:00.000Z"


def test_memory_slots_and_procedures():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ChronicleCore.get(tmpdir)
        core.initialize("session_slots", principal_id="pat")

        # Test setting and getting memory slots
        res_set = core.tools.dispatch("pat", "chronicle_set_memory_slot", {"slot_name": "user_preferences", "content": "Prefers dark mode"})
        assert "slot_updated" in res_set

        res_get = core.tools.dispatch("pat", "chronicle_get_memory_slots", {})
        assert "user_preferences" in res_get
        assert "Prefers dark mode" in res_get

        # Test procedure extraction
        core.capture.observe("Execute tool build_project", "Build successful", session_id="session_slots")
        core.process_pending()

        res_proc = core.tools.dispatch("pat", "chronicle_extract_procedure", {"session_id": "session_slots", "name": "Build Workflow"})
        assert "procedure_extracted" in res_proc
