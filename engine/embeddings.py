"""
Chronicle — Embeddings (§24.4, §27 embeddings:).

A pluggable Embedder interface plus a deterministic, dependency-free default
(feature hashing) so the vector retrieval tier is exercisable offline and in CI
without a model or network. A real deployment runs `nomic-embed-text`
locally (Ollama or llama.cpp) behind the same interface; nothing else changes.

Vectors serialize to a compact little-endian float32 blob (no numpy needed).
"""

from __future__ import annotations

import logging
import math
import random
import re
import struct
import time
from typing import Protocol

logger = logging.getLogger("chronicle.embeddings")

_TOKEN = re.compile(r"[a-z0-9]+")
_HASHING_NAMES = {"hashing", "hashing-v1", "offline", "none"}
_AUTO_NAMES = {"", "auto", "auto-detect", "autodetect", "local", "default"}
# Model ids that look like embedding models (used to auto-pick from /v1/models).
_EMBED_RE = re.compile(r"embed|bge|gte|nomic|e5|minilm|mxbai|arctic|stella|gemma|qwen.*embed", re.IGNORECASE)

# -- token-aware input clamp (§27 embeddings.max_input_tokens / .overflow) ----
#
# The production incident this exists for: the deployed llama.cpp/nomic server
# has a REAL context of 2048 tokens. Excerpts up to 4000 chars overflowed it,
# the server answered HTTP 500, and the curation job burned all its retry
# attempts and became permanently poisoned (re-enqueue reuses the same spent
# row) even after the root cause was fixed. Nothing downstream of this module
# may ever hand a model more than `max_input_tokens` worth of input again.
#
# `_CHARS_PER_TOKEN` is deliberately conservative (an undercount of the real
# chars/token ratio for ordinary English, which runs ~4): pathological input
# (URLs, no spaces, unusual scripts) tokenizes far worse than that, so a chars/3
# ceiling estimate is a safe upper bound on true token count for content we
# cannot inspect the tokenizer for.
_CHARS_PER_TOKEN = 3
_DEFAULT_MAX_INPUT_TOKENS = 2048
_MIN_MAX_INPUT_TOKENS = 256
_MAX_MAX_INPUT_TOKENS = 32768
_OVERFLOW_MODES = ("truncate", "chunk_mean")

# Boundary preference for the local truncate/chunk cut, mirroring
# capture._split_excerpt (message start > sentence end > hard cut). Duplicated
# here rather than imported so the embeddings module — the lowest layer, used
# by reducer/curation/retrieval alike — has no dependency on the capture layer.
_EMBED_MSG_START = re.compile(r"\n(?=[^\s:][^:\n]{0,32}: )")
_EMBED_SENTENCE_END = re.compile(r"[.!?]\s|\n")


def estimate_tokens(text: str | None) -> int:
    """Conservative token-count estimate: chars/3, ceiling (§27 embeddings)."""
    if not text:
        return 0
    return -(-len(text) // _CHARS_PER_TOKEN)  # ceil division, stdlib-only


def _cap_chars(max_input_tokens: int) -> int:
    """Character budget that guarantees estimate_tokens(text[:budget]) <= cap.

    Since estimate_tokens is a chars/3 ceiling, capping at max_input_tokens*3
    chars always estimates at or under max_input_tokens."""
    return max(_CHARS_PER_TOKEN, int(max_input_tokens) * _CHARS_PER_TOKEN)


def clamp_max_input_tokens(value) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = _DEFAULT_MAX_INPUT_TOKENS
    return max(_MIN_MAX_INPUT_TOKENS, min(_MAX_MAX_INPUT_TOKENS, v))


def normalize_overflow(value) -> str:
    v = (value or "truncate").strip().lower()
    return v if v in _OVERFLOW_MODES else "truncate"


def should_use_task_prefixes(model: str, task_prefixes_config: str | bool | None) -> bool:
    """Determine whether to prepend task prefixes based on config and model name.

    Config "auto" (default): enabled iff model name contains "nomic".
    Config True: always enabled.
    Config False: always disabled.
    Hashing mode never uses prefixes.
    """
    if task_prefixes_config is None or task_prefixes_config == "auto":
        # Auto-detect: enabled iff model name contains "nomic"
        return "nomic" in (model or "").lower()
    return bool(task_prefixes_config)


def _split_for_cap(text: str, max_input_tokens: int) -> list[str]:
    """Boundary-aware split of `text` into chunks each within max_input_tokens.

    Same boundary preference as capture._split_excerpt: prefer the start of the
    next "role: " message, then a sentence end, then fall back to a hard cut.
    ``"".join(result) == text`` always holds — lossless, so chunk_mean sees the
    whole input and truncate's first chunk is a real prefix of it, never a
    mid-multibyte-character slice landing on an arbitrary boundary."""
    cap_chars = _cap_chars(max_input_tokens)
    if len(text) <= cap_chars:
        return [text]
    chunks, pos, n = [], 0, len(text)
    while pos < n:
        rest = text[pos:]
        if len(rest) <= cap_chars:
            chunks.append(rest)
            break
        window = rest[:cap_chars]
        cut = 0
        for rx in (_EMBED_MSG_START, _EMBED_SENTENCE_END):
            found = list(rx.finditer(window))
            if found:
                cut = found[-1].end()
                break
        cut = cut or cap_chars
        chunks.append(window[:cut])
        pos += cut
    return chunks


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        return [v / norm for v in vec]
    return list(vec)


def _mean_normalize(vecs: list[list[float]]) -> list[float]:
    """L2-normalize each vector, mean them, then re-normalize to unit length —
    the chunk_mean overflow strategy (§27 embeddings.overflow)."""
    if not vecs:
        return []
    normed = [_l2_normalize(v) for v in vecs]
    dims = len(normed[0])
    mean = [0.0] * dims
    for v in normed:
        for i in range(dims):
            mean[i] += v[i]
    k = float(len(normed))
    mean = [x / k for x in mean]
    return _l2_normalize(mean)


class EmbeddingsUnavailable(RuntimeError):
    """No embedding backend is reachable, so NOTHING is written (§24.4).

    Not the same as a transient embed failure: the caller re-queues the work as an
    `embed` curation job (§17.3) instead of silently substituting a hash vector.
    Hash vectors live in an incomparable geometry — mixing them into the store is
    invisible at write time and permanently poisons vector retrieval.
    """


class Embedder(Protocol):
    model: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...

    def embed_query(self, query: str) -> list[float]:
        """Embed a query (typically prepended with a task prefix if configured)."""
        return self.embed(query)

    def embed_document(self, document: str) -> list[float]:
        """Embed a document (typically prepended with a task prefix if configured)."""
        return self.embed(document)

    def model_with_prefix_marker(self) -> str:
        """Return the model name with a prefix marker if task prefixes are used.

        Used for the 'model' field in stored vectors to detect stale bare vectors."""
        return self.model


class HashingEmbedder:
    """Deterministic bag-of-tokens feature-hashing embedder.

    Not semantically strong, but stable and offline: the same text always maps
    to the same L2-normalized vector, lexically-overlapping texts land near each
    other, and unrelated texts are near-orthogonal. Good enough to drive RRF
    fusion, the dual-tier path, and property tests.
    """

    def __init__(self, dimensions: int = 256, model: str = "hashing-v1",
                 max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS, overflow: str = "truncate",
                 task_prefixes: str | bool | None = None):
        self.dimensions = dimensions
        self.model = model
        self.max_input_tokens = clamp_max_input_tokens(max_input_tokens)
        self.overflow = normalize_overflow(overflow)
        # Hashing mode never uses task prefixes (they don't affect the hash meaningfully)
        self.use_task_prefixes = False

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        toks = _TOKEN.findall((text or "").lower())
        for tok in toks:
            # Two independent hashes: bucket index + sign (mitigates collisions).
            h = _stable_hash(tok)
            idx = h % self.dimensions
            sign = 1.0 if (h >> 32) & 1 else -1.0
            vec[idx] += sign
            # A light bigram signal sharpens near-duplicate detection.
        return _l2_normalize(vec)

    def embed(self, text: str) -> list[float]:
        """Embed `text`, clamped to max_input_tokens (§27) — NEVER raises for
        length and NEVER sends over-cap input downstream (there is no real
        network call here, but the clamp must behave identically to the real
        backend so tests/CI exercise the same contract as production)."""
        text = text or ""
        if estimate_tokens(text) <= self.max_input_tokens:
            return self._embed_one(text)
        chunks = _split_for_cap(text, self.max_input_tokens)
        if self.overflow == "chunk_mean":
            return _mean_normalize([self._embed_one(c) for c in chunks])
        return self._embed_one(chunks[0])   # truncate: boundary-aware first chunk only

    def embed_query(self, query: str) -> list[float]:
        """Embed a query (no task prefix in hashing mode)."""
        return self.embed(query)

    def embed_document(self, document: str) -> list[float]:
        """Embed a document (no task prefix in hashing mode)."""
        return self.embed(document)

    def model_with_prefix_marker(self) -> str:
        """Hashing mode never uses task prefixes."""
        return self.model


# Local embedding servers probed when no explicit base_url is configured.
# OpenAI-compatible /v1/embeddings (LM Studio, Ollama ≥0.1.39, llama.cpp, …).
_DEFAULT_ENDPOINTS = [
    "http://localhost:1234/v1",    # LM Studio
    "http://localhost:11434/v1",   # Ollama (OpenAI-compatible)
    "http://127.0.0.1:8080/v1",    # llama.cpp server
]


class OpenAICompatEmbedder:
    """Calls an OpenAI-compatible ``/v1/embeddings`` endpoint (stdlib only).

    `healthcheck()` is strict (raises) so init can decide real-model vs hashing.

    `embed()` is resilient WITHOUT degrading quality: on a transient failure
    (rate-limit 429, timeout, 5xx, a server blip) it WAITS with exponential
    backoff + jitter and RETRIES the same endpoint, up to `max_attempts`. It does
    NOT fall back to offline hashing — hash vectors live in a different, incomparable
    geometry and silently poison the store. If every attempt in the budget fails it
    RAISES; every caller already catches that and simply skips the vector for this
    item (FTS + structured retrieval continue), and the embed is retried fresh on
    the next operation, so a transient outage never pins the whole session to a
    degraded embedder. Auth failures (401/403) are terminal and raised immediately
    (waiting will not fix a bad key).
    """

    def __init__(self, base_url: str, model: str, dimensions: int, api_key: str = "", timeout: float = 10.0,
                 max_attempts: int = 5, backoff_base: float = 1.0, backoff_cap: float = 8.0,
                 max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS, overflow: str = "truncate",
                 task_prefixes: str | bool | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.api_key = api_key or ""
        self.timeout = timeout
        self.max_attempts = max(1, int(max_attempts))
        self.backoff_base = float(backoff_base)
        self.backoff_cap = float(backoff_cap)
        self.max_input_tokens = clamp_max_input_tokens(max_input_tokens)
        self.overflow = normalize_overflow(overflow)
        # Determine if task prefixes should be used (only for real embedders)
        self.use_task_prefixes = should_use_task_prefixes(model, task_prefixes)

    def _embed_raw(self, text: str, timeout: float) -> list[float]:
        import json as _json
        import urllib.request
        body = _json.dumps({"model": self.model, "input": text or ""}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base_url + "/embeddings", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        vec = (data.get("data") or [{}])[0].get("embedding")
        if not isinstance(vec, list) or not vec:
            raise ValueError("response had no embedding (model may not support embeddings)")
        return [float(x) for x in vec]

    def healthcheck(self) -> bool:
        v = self._embed_raw("ok", timeout=min(self.timeout, 4.0))  # raises if the endpoint/model can't embed
        self.dimensions = len(v)  # trust the server's real dimensionality
        return True

    @staticmethod
    def _is_terminal(exc: Exception) -> bool:
        # Auth/credential errors will not fix themselves by waiting; do not retry.
        return getattr(exc, "code", None) in (401, 403)

    def _embed_with_retry(self, text: str) -> list[float]:
        """The original single-call retry loop, now reusable per-chunk so
        chunk_mean can retry each chunk independently without duplicating the
        backoff/terminal-error contract."""
        attempt = 0
        while True:
            try:
                return self._embed_raw(text, timeout=self.timeout)
            except Exception as e:
                attempt += 1
                if self._is_terminal(e):
                    logger.error("Chronicle embeddings: %s auth error (%s) -- terminal, not retrying",
                                 self.base_url, e)
                    raise
                if attempt >= self.max_attempts:
                    logger.error("Chronicle embeddings: %s failed after %d attempts (%s); raising -- "
                                 "no hash fallback; vector skipped this round, FTS retrieval continues, "
                                 "embed retried on the next operation", self.base_url, attempt, e)
                    raise
                wait = min(self.backoff_cap, self.backoff_base * (2 ** (attempt - 1)))
                wait = wait * (0.5 + random.random() * 0.5)  # 50-100% jitter
                logger.warning("Chronicle embeddings: %s embed failed (attempt %d/%d: %s); "
                               "waiting %.1fs then retrying", self.base_url, attempt, self.max_attempts, e, wait)
                if wait > 0:
                    time.sleep(wait)

    def embed(self, text: str) -> list[float]:
        """Embed `text`, clamped to max_input_tokens before it ever reaches the
        wire (§27 embeddings.max_input_tokens/.overflow). This is the fix for
        the nemotron->nomic overflow incident: the model's real context is
        2048 tokens, so an oversized excerpt must never be sent as-is — that
        used to 500 and burn the job's entire retry budget.

        truncate (default): one HTTP call, boundary-truncated to the cap.
        chunk_mean: the input is split into cap-sized, boundary-aware chunks;
        EACH CHUNK gets its own HTTP call (and its own retry budget), the
        resulting vectors are L2-normalized and averaged, then the mean is
        re-normalized to unit length -- a real (if lossy) representation of
        the whole input, not just its first slice.
        """
        text = text or ""
        if estimate_tokens(text) <= self.max_input_tokens:
            return self._embed_with_retry(text)
        chunks = _split_for_cap(text, self.max_input_tokens)
        if self.overflow == "chunk_mean":
            return _mean_normalize([self._embed_with_retry(c) for c in chunks])
        return self._embed_with_retry(chunks[0])   # truncate: one call, first chunk only

    def _embed_raw_batch(self, texts: list[str], timeout: float) -> list[list[float]]:
        import json as _json
        import urllib.request
        body = _json.dumps({"model": self.model, "input": [t or "" for t in texts]}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base_url + "/embeddings", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        rows = data.get("data") or []
        if len(rows) != len(texts):
            raise ValueError("batch response had %d embeddings for %d inputs" % (len(rows), len(texts)))
        # The API contract orders rows by index; sort defensively anyway.
        rows.sort(key=lambda r: r.get("index", 0))
        out = []
        for r in rows:
            vec = r.get("embedding")
            if not isinstance(vec, list) or not vec:
                raise ValueError("batch response row had no embedding")
            out.append([float(x) for x in vec])
        return out

    def _embed_raw_batch_retrying(self, part: list[str]) -> list[list[float]]:
        attempt = 0
        while True:
            try:
                return self._embed_raw_batch(part, timeout=max(self.timeout, 2.0 + 0.25 * len(part)))
            except Exception as e:
                attempt += 1
                if self._is_terminal(e) or attempt >= self.max_attempts:
                    raise
                wait = min(self.backoff_cap, self.backoff_base * (2 ** (attempt - 1)))
                time.sleep(wait * (0.5 + random.random() * 0.5))

    def embed_batch(self, texts: list[str], chunk: int = 64) -> list[list[float]]:
        """Batch embed with the same retry/no-hash-fallback contract as embed().

        One HTTP round-trip per `chunk` texts instead of one per text — the
        difference between minutes and hours on a backfill (requeue script,
        re-embed after an outage). A longer timeout per call, scaled by chunk
        size, because a batch legitimately takes longer than a single.

        Same clamp as embed() (§27 embeddings.max_input_tokens/.overflow): a
        batch is only ever built from within-cap texts, so an oversized item
        can never inflate one request past the model's real context and 500
        the whole batch. Any oversized text is routed through embed() on its
        own — for `truncate` that is one extra call; for `chunk_mean` it is
        one call per chunk — and is never mixed into a raw batch payload.

        The only caller (Reducer.prefetch_vectors) is always document-side, so
        when task prefixes are enabled each text gets "search_document: "
        prepended up front, before the size-check split -- otherwise these
        vectors would go out bare while model_with_prefix_marker() tags them
        [prefixed], permanently desyncing bulk-ingested vectors from the
        query-side prefix contract.
        """
        if self.use_task_prefixes:
            texts = ["search_document: " + (t or "") for t in texts]
        out: list[list[float] | None] = [None] * len(texts)
        batch_idx: list[int] = []
        batch_texts: list[str] = []
        for i, t in enumerate(texts):
            t = t or ""
            if estimate_tokens(t) <= self.max_input_tokens:
                batch_idx.append(i)
                batch_texts.append(t)
            else:
                out[i] = self.embed(t)   # oversized: its own call(s), clamped
        for i in range(0, len(batch_texts), chunk):
            part = batch_texts[i:i + chunk]
            idx_part = batch_idx[i:i + chunk]
            vecs = self._embed_raw_batch_retrying(part)
            for j, vec in zip(idx_part, vecs):
                out[j] = vec
        return out  # type: ignore[return-value]

    def embed_query(self, query: str) -> list[float]:
        """Embed a query with optional task prefix."""
        if self.use_task_prefixes:
            query = "search_query: " + (query or "")
        return self.embed(query)

    def embed_document(self, document: str) -> list[float]:
        """Embed a document with optional task prefix."""
        if self.use_task_prefixes:
            document = "search_document: " + (document or "")
        return self.embed(document)

    def model_with_prefix_marker(self) -> str:
        """Return model name with [prefixed] marker if task prefixes are used."""
        if self.use_task_prefixes:
            return f"{self.model}[prefixed]"
        return self.model


def _candidate_urls(base_url: str | None) -> list[str]:
    import os
    if base_url:
        return [base_url]
    env = os.environ.get("CHRONICLE_EMBED_BASE_URL")
    if env:
        return [env]
    return list(_DEFAULT_ENDPOINTS)


def _discover_embedding_models(base_url: str, api_key: str) -> list[str]:
    """List candidate embedding model ids from an OpenAI-compatible /v1/models.

    Prefers ids that look like embedding models; if none match the heuristic,
    returns all ids (the test-embed in get_embedder filters out chat models that
    can't actually embed). Returns [] if the server can't be queried."""
    import json as _json
    import urllib.request
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    req = urllib.request.Request(base_url.rstrip("/") + "/models", headers=headers)
    with urllib.request.urlopen(req, timeout=4) as resp:
        data = _json.loads(resp.read().decode("utf-8"))
    ids = [m.get("id", "") for m in (data.get("data") or []) if m.get("id")]
    return [i for i in ids if _EMBED_RE.search(i)] or ids


def _probe_endpoints(model: str | None, dims: int, base_url: str | None,
                     api_key: str | None, max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS,
                     overflow: str = "truncate", task_prefixes: str | bool | None = None) -> Embedder | None:
    """First reachable OpenAI-compatible endpoint that really embeds, else None.

    `model` auto/empty → ask each endpoint's /v1/models what it serves and try
    those; otherwise try exactly that id. Shared by init (get_embedder) and the
    later re-probe (DegradedEmbedder.recheck) so both decide identically."""
    auto = (model or "auto").strip().lower() in _AUTO_NAMES
    for url in _candidate_urls(base_url):
        try:
            candidates = _discover_embedding_models(url, api_key or "") if auto else [model]
        except Exception:
            continue  # /models unreachable on this endpoint → try next
        for mid in candidates:
            try:
                emb = OpenAICompatEmbedder(url, mid, dims, api_key or "",
                                           max_input_tokens=max_input_tokens, overflow=overflow,
                                           task_prefixes=task_prefixes)
                if emb.healthcheck():
                    return emb
            except Exception:
                continue  # not an embedding model / rejected → try next candidate
    return None


class DegradedEmbedder:
    """No embedding backend is reachable: write NOTHING, queue the work (§24.4).

    `embed()` raises EmbeddingsUnavailable; the caller enqueues an `embed` curation
    job that is deferred and retried with backoff (§17.3). This replaces the old
    silent fall-back to hashing, which produced vectors in an incomparable geometry
    that nothing downstream could tell apart from real ones.

    Keeps its resolution inputs so `recheck()` can adopt a server that comes up
    later. It upgrades IN PLACE because reducer/retrieval/curation each hold this
    same object — swapping `core.embedder` would leave stale references behind.
    Only the deferred embed job calls recheck(): read paths must never pay probe
    latency against a dead endpoint.
    """

    def __init__(self, model: str = "auto", dimensions: int = 768, base_url: str | None = None,
                 api_key: str | None = None, recheck_seconds: float = 60.0,
                 max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS, overflow: str = "truncate",
                 task_prefixes: str | bool | None = None):
        self.requested_model = model or "auto"
        self.base_url = base_url
        self.api_key = api_key
        self.recheck_seconds = float(recheck_seconds)
        self._dimensions = int(dimensions or 768)
        self.max_input_tokens = clamp_max_input_tokens(max_input_tokens)
        self.overflow = normalize_overflow(overflow)
        self._task_prefixes_config = task_prefixes
        self._live = None                                  # adopted backend, once one appears
        self._next_probe = time.time() + self.recheck_seconds

    @property
    def live(self):
        return self._live

    @property
    def model(self) -> str:
        # Only ever stamped onto a row when a vector exists, i.e. when _live is set.
        return self._live.model if self._live is not None else "degraded"

    @property
    def dimensions(self) -> int:
        return self._live.dimensions if self._live is not None else self._dimensions

    def recheck(self, force: bool = False) -> bool:
        """Re-probe for a backend, at most once per `recheck_seconds`. True once live."""
        if self._live is not None:
            return True
        now = time.time()
        if not force and now < self._next_probe:
            return False
        self._next_probe = now + self.recheck_seconds
        emb = _probe_endpoints(self.requested_model, self._dimensions, self.base_url, self.api_key,
                              max_input_tokens=self.max_input_tokens, overflow=self.overflow,
                              task_prefixes=self._task_prefixes_config)
        if emb is None:
            return False
        logger.warning("Chronicle embeddings: RECOVERED — %r via %s (dim %d); queued embeds resume",
                       emb.model, emb.base_url, emb.dimensions)
        self._live = emb
        return True

    def embed(self, text: str) -> list[float]:
        if self._live is not None:
            return self._live.embed(text)
        raise EmbeddingsUnavailable("no embedding backend reachable (degraded mode)")

    def embed_batch(self, texts: list[str], chunk: int = 64) -> list[list[float]]:
        # Present so an adopted backend keeps its batch path once recheck() has
        # upgraded us in place; still raises while nothing is reachable, exactly
        # like embed(), so callers need no separate degraded branch.
        if self._live is not None:
            return self._live.embed_batch(texts, chunk=chunk)
        raise EmbeddingsUnavailable("no embedding backend reachable (degraded mode)")

    def embed_query(self, query: str) -> list[float]:
        """Delegate to live backend or raise if unavailable."""
        if self._live is not None:
            return self._live.embed_query(query)
        raise EmbeddingsUnavailable("no embedding backend reachable (degraded mode)")

    def embed_document(self, document: str) -> list[float]:
        """Delegate to live backend or raise if unavailable."""
        if self._live is not None:
            return self._live.embed_document(document)
        raise EmbeddingsUnavailable("no embedding backend reachable (degraded mode)")

    def model_with_prefix_marker(self) -> str:
        """Delegate to live backend if available."""
        if self._live is not None:
            return self._live.model_with_prefix_marker()
        return self.model


def get_embedder(model: str | None = None, dimensions: int | None = None,
                 base_url: str | None = None, api_key: str | None = None,
                 max_input_tokens: int | None = None, overflow: str | None = None,
                 task_prefixes: str | bool | None = None) -> Embedder:
    """Return the active embedder, logging exactly ONE line: which mode, and why.

    Default is ``auto``: find a running local OpenAI-compatible server (configured
    base_url / $CHRONICLE_EMBED_BASE_URL, else common LM Studio / Ollama /
    llama.cpp ports) and use whatever embedding model it actually serves — no
    model id is hardcoded. An explicit model name is used as-is.

    If nothing is reachable (or only chat models are loaded) the result is a
    DegradedEmbedder, NOT a hashing fallback: no vectors are written and each
    embed becomes a deferred curation job (§24.4). Retrieval still works on FTS.
    Set model to 'hashing' (or $CHRONICLE_EMBED_MODEL=hashing) to deliberately
    choose the offline/CI embedder — that path is unchanged.

    Exception: an EXPLICIT model + explicit base_url is trusted even when it is
    unreachable at init — it returns the retrying OpenAICompatEmbedder (which
    waits+retries at runtime) rather than pinning the whole session on a transient
    startup rate-limit/outage.

    `max_input_tokens` / `overflow` (§27 embeddings.max_input_tokens/.overflow):
    the token-aware input clamp every returned embedder enforces before any
    text reaches a real model, so a context-overflowing excerpt 500s never
    again poison a curation job's retry budget. Defaults: 2048 tokens
    (clamped [256, 32768]), overflow "truncate".

    `task_prefixes` (E1): "auto" (default: enabled iff model contains "nomic") |
    true (always) | false (never). Hashing mode never uses prefixes.
    """
    dims = int(dimensions) if dimensions else 768
    name = (model or "auto").strip().lower()
    max_tok = clamp_max_input_tokens(max_input_tokens if max_input_tokens is not None
                                     else _DEFAULT_MAX_INPUT_TOKENS)
    ovf = normalize_overflow(overflow)
    if name in _HASHING_NAMES:
        dim = int(dimensions) if dimensions else 256
        logger.info("Chronicle embeddings: HASHING mode — %r requested explicitly; deterministic "
                    "offline vectors (dim %d), no server contacted", name, dim)
        return HashingEmbedder(dimensions=dim, max_input_tokens=max_tok, overflow=ovf,
                               task_prefixes=task_prefixes)
    auto = name in _AUTO_NAMES
    if not auto and base_url:
        # Trust the configured model + endpoint: defer transient failures to the
        # runtime wait-and-retry in embed() instead of downgrading the session.
        emb = OpenAICompatEmbedder(base_url, model, dims, api_key or "",
                                   max_input_tokens=max_tok, overflow=ovf,
                                   task_prefixes=task_prefixes)
        try:
            emb.healthcheck()  # best-effort: confirm reachable + adopt the real dim
            logger.info("Chronicle embeddings: MODEL mode — %r via %s (dim %d)",
                        model, base_url, emb.dimensions)
        except Exception as e:
            logger.warning("Chronicle embeddings: MODEL mode — %r @ %s unreachable at init (%s); "
                           "keeping it and deferring to the runtime retry (never hashing)",
                           model, base_url, e)
        return emb
    emb = _probe_endpoints(model, dims, base_url, api_key, max_input_tokens=max_tok, overflow=ovf,
                          task_prefixes=task_prefixes)
    if emb is not None:
        logger.info("Chronicle embeddings: MODEL mode — local %r via %s (dim %d)",
                    emb.model, emb.base_url, emb.dimensions)
        return emb
    logger.warning("Chronicle embeddings: DEGRADED mode — %s on %s. NO vectors are written; every "
                   "embed is queued as a curation job and retried with backoff until a server "
                   "appears. Set embeddings.model (or $CHRONICLE_EMBED_MODEL) to 'hashing' for "
                   "deterministic offline vectors instead",
                   "no embedding model reachable" if auto else f"model {model!r} not reachable",
                   ", ".join(_candidate_urls(base_url)))
    return DegradedEmbedder(model=name, dimensions=dims, base_url=base_url, api_key=api_key,
                            max_input_tokens=max_tok, overflow=ovf, task_prefixes=task_prefixes)


def _stable_hash(s: str) -> int:
    # FNV-1a 64-bit — deterministic across processes (unlike hash()).
    h = 0xcbf29ce484222325
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack(blob: bytes | None) -> list[float]:
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    # Vectors are pre-normalized; dot ≈ cosine. Clamp for safety.
    return max(-1.0, min(1.0, dot))

def batch_cosine_f64(query, blobs):
    """`batch_cosine` at full float64 precision, same signature and semantics.

    batch_cosine casts the query to float32 to keep the matmul in the same dtype
    as the stored blobs, which costs ~1e-8 of accuracy. That is invisible in a
    ranking — the only thing batch_cosine feeds — but E5's `novelty` is a STORED
    NUMBER whose contract is exactly `1 − max cosine`, checked to 1e-9 against
    the scalar `cosine`. Widening the blobs to float64 instead keeps the result
    within float64 rounding of that scalar (~1e-15) at the cost of a wider
    temporary, and falls back to the same scalar path when numpy is absent.
    """
    n = len(blobs)
    if n == 0:
        return []
    try:
        import numpy as np
    except Exception:
        return [cosine(query, unpack(b)) for b in blobs]
    q = np.asarray(query, dtype=np.float64)
    d = int(q.shape[0]) if q.ndim else 0
    out = [0.0] * n
    if not d:
        return out
    idx, mats = [], []
    for i, b in enumerate(blobs):
        if b and len(b) == d * 4:
            idx.append(i)
            mats.append(b)
    if idx:
        M = np.frombuffer(b"".join(mats), dtype=np.float32).reshape(len(idx), d).astype(np.float64)
        sims = np.clip(M @ q, -1.0, 1.0)
        for j, i in enumerate(idx):
            out[i] = float(sims[j])
    return out


def batch_cosine(query, blobs):
    """Vectorized cosine of `query` (pre-normalized) against many packed,
    pre-normalized embeddings. Returns list[float] aligned to `blobs`.
    Embeddings whose byte length doesn't match the query dimensionality
    (e.g. incomparable hash vectors) score 0.0. Falls back to scalar
    `cosine` if numpy is unavailable."""
    n = len(blobs)
    if n == 0:
        return []
    try:
        import numpy as np
    except Exception:
        return [cosine(query, unpack(b)) for b in blobs]
    q = np.asarray(query, dtype=np.float32)
    d = int(q.shape[0]) if q.ndim else 0
    out = [0.0] * n
    if not d:
        return out
    idx, mats = [], []
    for i, b in enumerate(blobs):
        if b and len(b) == d * 4:
            idx.append(i)
            mats.append(b)
    if idx:
        M = np.frombuffer(b"".join(mats), dtype=np.float32).reshape(len(idx), d)
        sims = np.clip(M @ q, -1.0, 1.0)
        for j, i in enumerate(idx):
            out[i] = float(sims[j])
    return out
