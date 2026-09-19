"""Chronicle — the embedder healthcheck must tell a SLOW server from a DOWN one.

Found in production (2026-09-16): the healthcheck capped its probe at 4 s while
real embeds get the request timeout (10 s). On the loaded VPS llama.cpp answered
in 3.3-6.8 s, so the healthcheck called a working server `unreachable` on most
probes and a config pinned to it stayed DEGRADED, writing no vectors.

The fix gives a TIMEOUT exactly one retry at the request timeout, and nothing
else a retry: a refused connection or an HTTP error must still fail at once, or
startup against a dead server gets slower for nothing. Driven through a patched
`_embed_raw` so no socket is opened — the suite runs in a strict-sockets mode.
"""

import socket
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.embeddings import OpenAICompatEmbedder, _is_timeout  # noqa: E402


def _emb(timeout=10.0):
    return OpenAICompatEmbedder("http://127.0.0.1:8080/v1", "nomic-embed-text-v1.5.Q8_0.gguf",
                                768, timeout=timeout)


class TestASlowServerIsNotADownServer(unittest.TestCase):
    def test_a_timeout_on_the_fast_probe_is_retried_at_the_request_timeout(self):
        emb = _emb()
        calls = []

        def fake(text, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                raise urllib.error.URLError(socket.timeout("timed out"))
            return [0.1] * 768

        with mock.patch.object(emb, "_embed_raw", side_effect=fake):
            self.assertTrue(emb.healthcheck())
        self.assertEqual(calls, [4.0, 10.0],
                         "a slow server must get one retry at the full request timeout")
        self.assertEqual(emb.dimensions, 768)

    def test_a_bare_TimeoutError_is_also_recognised(self):
        emb = _emb()
        seq = [TimeoutError("read timed out"), [0.2] * 768]
        with mock.patch.object(emb, "_embed_raw", side_effect=seq):
            self.assertTrue(emb.healthcheck())

    def test_a_refused_connection_still_fails_at_once_with_no_retry(self):
        emb = _emb()
        err = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        with mock.patch.object(emb, "_embed_raw", side_effect=err) as raw:
            with self.assertRaises(urllib.error.URLError):
                emb.healthcheck()
        self.assertEqual(raw.call_count, 1, "a DOWN server must not be retried")

    def test_an_http_error_still_fails_at_once_with_no_retry(self):
        emb = _emb()
        err = urllib.error.HTTPError("http://x", 500, "boom", {}, None)
        with mock.patch.object(emb, "_embed_raw", side_effect=err) as raw:
            with self.assertRaises(urllib.error.HTTPError):
                emb.healthcheck()
        self.assertEqual(raw.call_count, 1)

    def test_a_short_request_timeout_is_never_exceeded_by_the_retry(self):
        emb = _emb(timeout=3.0)          # request timeout already under the fast cap
        with mock.patch.object(emb, "_embed_raw", side_effect=socket.timeout("t")) as raw:
            with self.assertRaises(socket.timeout):
                emb.healthcheck()
        self.assertEqual(raw.call_count, 1, "nothing longer than the request timeout is ever tried")

    def test_is_timeout_is_narrower_than_unreachable(self):
        self.assertTrue(_is_timeout(socket.timeout("t")))
        self.assertTrue(_is_timeout(urllib.error.URLError(TimeoutError("t"))))
        self.assertFalse(_is_timeout(ConnectionRefusedError(111, "refused")))
        self.assertFalse(_is_timeout(urllib.error.URLError(ConnectionRefusedError(111, "r"))))


if __name__ == "__main__":
    unittest.main(verbosity=2)
