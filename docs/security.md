# Security

Two settings decide whether memory content may leave this host, and one thing Chronicle
deliberately does not do is encrypt at rest. To report a vulnerability, see
[SECURITY.md](../SECURITY.md).

## Where memory is allowed to go

Chronicle is local-first, and that is now a **control, not a claim**. Two endpoints in
the engine can carry memory content off the machine: the embeddings server
(`embeddings.base_url`, or `$CHRONICLE_EMBED_BASE_URL`) and the optional LLM extractor
(`extraction.llm.base_url`, which POSTs the raw excerpt in its prompt). Before either
one is used, Chronicle resolves its host and **refuses anything that is not on this
host or its private network**:

| Allowed | Refused |
|---------|---------|
| `127.0.0.0/8`, `::1`, `0.0.0.0`/`::` | any public IP literal |
| the literal name `localhost` (and `*.localhost`) — no DNS needed | a public hostname, e.g. a hosted inference API |
| RFC1918 `10/8`, `172.16/12`, `192.168/16`; ULA `fc00::/7`; CGNAT `100.64/10` | an `https://` URL to a third-party endpoint |
| link-local `169.254.0.0/16`, `fe80::/10` | a hostname that will not resolve (**fail closed**) |
| a `unix:` / `http+unix:` socket URL | a hostname with **any** public answer in its DNS result |

`0.0.0.0` and `::` in the table above are **destinations, not bind
addresses**: they classify where memory content may be *sent*, and connecting
to either targets this host. Chronicle opens **no listening socket** — nothing
in the engine accepts inbound connections — and the dashboard dev harness
(`dashboard/web/harness/server.py`) binds `127.0.0.1` explicitly. This table
governs egress of memory-bearing requests, not network exposure: exposure is a
separate question, answered by your own firewall.

A hostname is resolved **once**, when the client is constructed, and the verdict is
cached — the embed path itself never does DNS.

Refusal is not a crash. Embeddings fall to **degraded mode** (no vectors written, every
embed queued for retry, FTS retrieval unaffected) and the LLM extractor falls back to
the offline heuristic. One `WARNING` per process explains what was refused and why.
Nothing is sent.

To deliberately send memory excerpts to a remote endpoint, set
`embeddings.allow_remote: true` (and/or `extraction.llm.allow_remote: true`). Both
default to `false`. With them true, Chronicle logs one warning stating plainly that
memory content is leaving the host, and the local-first guarantee no longer applies to
that deployment.

## Chronicle does not encrypt anything at rest

Stated plainly because a previous release shipped `security.encrypt_at_rest:
true` as a **default** while nothing anywhere encrypted anything. The SQLite
database, its WAL, the git mirror and every vector blob are written in the
clear. Both `security.encrypt_at_rest` and `principals.encryption.
restricted_partition_keys` have been **removed**, and setting either one now
makes `Config()` raise rather than ignore it: silently ignoring a security key
leaves an operator believing in protection they do not have.

Use full-disk or filesystem-level encryption on the host. Read isolation
between principals is enforced by `access.can_read` — an ACL, not cryptography.
