"""
Chronicle — Embeddings (§24.4, §27 embeddings:).

A pluggable Embedder interface plus a deterministic, dependency-free default
(feature hashing) so the vector retrieval tier is exercisable offline and in CI
without a model or network. A real deployment runs `nomic-embed-text`
locally (Ollama or llama.cpp) behind the same interface; nothing else changes.

Vectors serialize to a compact little-endian float32 blob (no numpy needed).
"""

from __future__ import annotations

import ipaddress
import logging
import math
import random
import re
import socket
import struct
import time
import urllib.parse
from typing import NamedTuple, Protocol

logger = logging.getLogger("chronicle.embeddings")

_TOKEN = re.compile(r"[a-z0-9]+")
_HASHING_NAMES = {"hashing", "hashing-v1", "offline", "none"}
_AUTO_NAMES = {"", "auto", "auto-detect", "autodetect", "local", "default"}
# Model ids that look like embedding models (used to auto-pick from /v1/models).
_EMBED_RE = re.compile(r"embed|bge|gte|nomic|e5|minilm|mxbai|arctic|stella|gemma|qwen.*embed", re.IGNORECASE)

# -- THE vector-identity scan set (A0e) --------------------------------------
#
# EVERY table that stores an embedding under a model tag, named ONCE. The heal
# (engine/health.py), the bulk migration (scripts/migrate_vectors.py) and the
# hashing-era requeue (scripts/requeue_hash_vectors.py) all bind this exact
# tuple, so they cannot disagree about what "every vector" means.
#
# WHY IT LIVES HERE AND WHY IT IS ONE OBJECT. A0 shipped this list three times
# — once per consumer, hand-typed — and all three copies covered the same three
# tables. The two they left out were the two the live store hurt most:
# `session_index` held 7,288 rows of which 6,753 (93%) were 8192-byte / 2048-dim
# blobs from an abandoned model under a 768-dim embedder, and it had NO `model`
# column at all, so its staleness was invisible to every tag check and showed
# only as a blob width. Nothing scanned it, so no run of anything would ever
# have repaired it, and both the heal's counters and the migration's
# "converged: 100% of vectors" claim were computed over a store neither had
# fully looked at. This module already owns what a vector's identity IS
# (`embedder_model_tag`, `split_model_tag`, `expected_blob_len`), so it owns
# WHERE those identities are stored too. tests/test_a0e_session_projection_vectors
# .py asserts the three consumers bind this same object.
#
# ORDER IS THE REPAIR ORDER, not alphabetical: primary content vectors first,
# then the derived/side channels, so a bounded run spends its budget on memory
# before proxies and projections.
#
# NOT IN THIS SET, and why (asserted by a test, so a sixth embedding-bearing
# table cannot appear and be scanned by nothing):
#   entity_centroids.sum_vec — an accumulated SUM of mention vectors, not an
#     embedding of any recoverable text, so "re-embed" is not even defined for
#     it. It needs no heal because it already refuses to mix geometries: it
#     carries BOTH `model` (stamped through embedder_model_tag, in
#     reducer._identity_evidence) and an explicit `dims`, every comparison is
#     filtered `model=? AND dims=?` (store.recent_entity_centroids), and
#     identity._observe RESETS the accumulator whenever either changes. It is
#     also projection state that a rebuild regenerates from the event log.
VECTOR_TABLES = ("observed_vectors", "memory_vectors", "session_index",
                 "projection_vectors", "query_proxy_vectors")

# -- canonical model identity (§24.4, A0) ------------------------------------
#
# THE LIVE DEFECT THIS EXISTS FOR. One model reports itself under several
# names depending on who is asked, and Chronicle used to store whatever string
# it got:
#
#   ollama /v1/models          -> "nomic-embed-text:latest"
#   llama.cpp --embedding      -> "/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf"
#   an explicit config pin     -> "nomic-embed-text"
#
# Those are ONE model producing ONE 768-dim geometry, but three different tag
# strings. Every consumer that compared tags by raw string equality — the
# health mismatch heal above all — therefore saw a permanent, unfixable
# mismatch: it requeued rows that were already correct, re-embedded them with
# the same model, wrote back a name that STILL did not match whatever the
# other writer used, and dripped forever (measured on the live store: 60 rows
# re-tagged in 9 days, with nothing ever converging).
#
# `canonical_model_id` collapses all of those to ONE stable identity. It is a
# pure string normalization — no I/O, no config — so the same name canonicalizes
# identically in the engine, in a migration script, and in a test.
#
# DECIDED CANONICAL FORM (documented because it is a policy, not a fact):
#   * a name keeps its VERSION. `e5-large` and `e5-large-v2` are two different
#     models that happen to share a width (1024), and so are `bge-large-en` /
#     `bge-large-en-v1.5`, `all-MiniLM-L6-v1` / `-v2`, and
#     `snowflake-arctic-embed-l` / `-l-v2.0`. An earlier build of this function
#     stripped ANY trailing `-vN[.N]`, which collapsed each of those pairs to one
#     id; because the width clause cannot separate same-width models, a store
#     embedded under X-v1 and read by X-v2 then classified as `retag` and was
#     re-labelled in place — cross-model laundering, exactly the corruption this
#     identity exists to prevent. Version suffixes are therefore PART of the
#     identity, and the only equivalences that exist are the ones listed in
#     _MODEL_ALIASES below.
#   * _MODEL_ALIASES is an explicit, closed table of equivalences this project
#     has actually DECLARED, not a general rule. It has exactly one entry today:
#     the nomic-embed-text family. The project names that model canonically with
#     no version at all — engine/config.py:76 "Canonical recommendation (locked
#     2026-07-31): nomic-embed-text, served locally", and CHANGELOG.md:2
#     "Canonical embedder: nomic-embed-text (local only)" — while the three
#     names the live deployment actually reports for it are `nomic-embed-text`,
#     `nomic-embed-text:latest` and the v1.5 gguf path. Those must be ONE id or
#     the live store never converges, so v1/v1.5/bare are declared equivalent
#     HERE, by name, rather than by a rule that silently sweeps in every other
#     model's versions. (nomic v1 and v1.5 are both 768-dim; the pairing is the
#     project's existing position, restated explicitly.)
#   * Adding a row to _MODEL_ALIASES is a DECLARATION that two names are the same
#     geometry, and it is the only way to make two version-bearing names compare
#     equal. If a future deployment needs one, add it with the same kind of
#     citation — never by re-introducing a generic strip.
#   * Identity is never the only test either way: the mismatch rule is
#     `canonical id differs OR prefix marker differs OR blob length !=
#     dimensions*4`, so a wrongly-declared alias that changed dimensions still
#     trips the width clause.
#
# The offline hashing embedder is handled the same way: its aliases are an
# explicit closed set (_HASHING_NAMES) that all mean the one implementation, so
# they map to that implementation's own id ("hashing-v1"), while any other
# "hashing-*" name is kept verbatim — a hand-rolled "hashing-v2" is a real
# geometry change and must not be normalized into v1.
_MODEL_MARKER = "[prefixed]"
_HASHING_CANONICAL = "hashing-v1"
_AUTO_CANONICAL = "auto"
# Weight-file extensions a served path may carry.
_MODEL_FILE_EXT = re.compile(r"\.(?:gguf|ggml|bin|safetensors|pt|pth|onnx)$")
# Quantization suffixes: Q8_0, Q4_K_M, Q5_K_S, IQ4_XS, f16/f32/fp16/fp32, bf16, int8/int4.
# Anchored to a whole trailing segment so a legitimate name ending in "qwen3"
# or "-3-small" is never mistaken for a quantization tag.
_MODEL_QUANT = re.compile(r"[.\-_](?:q\d+(?:_[0-9a-z]+)*|iq\d+_[0-9a-z]+|fp?(?:16|32)|bf16|int[48])$")
_MODEL_TRAILING_SEP = re.compile(r"[.\-_]+$")

# DECLARED EQUIVALENCES. Keys are already lowercased, path-stripped,
# ":tag"-stripped, extension- and quantization-stripped — i.e. the form
# canonical_model_id has reduced a name to by the time this table is consulted.
# See the block comment above for what adding a row here means.
_MODEL_ALIASES = {
    # nomic-embed-text v1 / v1.5 / unversioned are ONE id (config.py:76,
    # CHANGELOG.md:2 — the project names this model without a version).
    "nomic-embed-text-v1": "nomic-embed-text",
    "nomic-embed-text-v1.5": "nomic-embed-text",
}


def canonical_model_id(name) -> str:
    """Normalize any reported/configured embedder name to a stable identity.

    Idempotent (``canonical_model_id(canonical_model_id(x)) == canonical_model_id(x)``)
    and total: it never raises and never returns None. An unrecognizable name
    comes back lowercased and stripped rather than blank, so an unknown model is
    still comparable to itself.

    Steps, in order:
      1. drop the E1 ``[prefixed]`` marker (so a stored TAG canonicalizes too),
      2. take the last path segment (``/`` and ``\\``) — llama.cpp reports a FILE PATH,
      3. drop an ollama/OpenRouter ``:tag`` (``:latest``, ``:free``, ``:Q8_0``),
      4. lowercase,
      5. strip weight-file extensions (``.gguf`` …), then quantization suffixes
         (``Q8_0``, ``Q4_K_M``, ``f16`` …), repeatedly, in any order they appear,
      6. strip leftover separators,
      7. map through ``_MODEL_ALIASES`` — the closed, documented table of
         equivalences this project has DECLARED (today: nomic-embed-text
         v1/v1.5/bare). A version suffix that is not in that table is kept:
         ``e5-large`` and ``e5-large-v2`` are different models and must not
         compare equal (see the policy block above).

    ``auto``/``""``/``local``/``default`` are placeholders, not identities: they
    canonicalize to ``"auto"``. They never reach a vector tag — an embedder
    resolves ``auto`` against the server and stamps the server's REAL id through
    this same function — but ``model: auto`` resolving through here is what makes
    a config-vs-store comparison well defined instead of a string coincidence.
    """
    raw = ("" if name is None else str(name)).strip()
    if not raw:
        return _AUTO_CANONICAL
    s = raw.replace(_MODEL_MARKER, "").strip()
    s = s.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if ":" in s:
        s = s.split(":", 1)[0]
    s = s.strip().lower()
    if not s:
        return _AUTO_CANONICAL
    if s in _AUTO_NAMES:
        return _AUTO_CANONICAL
    if s in _HASHING_NAMES:
        return _HASHING_CANONICAL
    if s.startswith("hashing"):
        return s          # a deliberate hand-rolled variant: never version-stripped
    while True:
        nxt = _MODEL_FILE_EXT.sub("", s)
        nxt = _MODEL_QUANT.sub("", nxt)
        if nxt == s:
            break
        s = nxt
    s = _MODEL_TRAILING_SEP.sub("", s)
    if not s:
        return raw.lower()
    # Declared equivalences only. Idempotent because every value in the table is
    # itself a key-free canonical form (an alias never maps to another alias).
    return _MODEL_ALIASES.get(s, s)


def make_model_tag(model, use_task_prefixes: bool) -> str:
    """The exact string every vector row is stamped with: canonical identity +
    the E1 task-prefix marker. THE one place the tag format is defined."""
    cid = canonical_model_id(model)
    return cid + _MODEL_MARKER if use_task_prefixes else cid


def split_model_tag(tag):
    """Inverse of `make_model_tag`: ``(canonical_id, has_prefix_marker)``.

    Tolerant of every legacy tag form in the live store — bare names, ollama
    tags, gguf paths, with or without the marker — because that is exactly what
    it is used to classify."""
    raw = ("" if tag is None else str(tag))
    marked = _MODEL_MARKER in raw
    return canonical_model_id(raw), marked


def embedder_model_tag(embedder) -> str:
    """THE single choke point every vector-stamping site goes through.

    Resolution order, most specific first:
      * ``embedder.model_tag()`` — the canonical contract (all built-in embedders),
      * ``embedder.model_with_prefix_marker()`` — pre-A0 / third-party embedders,
        whose (possibly non-canonical) answer is canonicalized here,
      * ``embedder.model`` — an embedder that predates E1 entirely.

    A duck-typed embedder therefore cannot stamp a non-canonical tag by
    accident: whatever it reports, this function is what the store sees. Returns
    ``""`` for no embedder at all, which no caller ever stamps (a vector is only
    written when an embed succeeded)."""
    if embedder is None:
        return ""
    fn = getattr(embedder, "model_tag", None)
    if callable(fn):
        return fn()
    fn = getattr(embedder, "model_with_prefix_marker", None)
    if callable(fn):
        legacy = fn()
        return make_model_tag(legacy, _MODEL_MARKER in str(legacy or ""))
    return canonical_model_id(getattr(embedder, "model", ""))


# Canonical ids that name NO usable geometry. `degraded` is the placeholder a
# DegradedEmbedder reports while the backend is unreachable; `auto` is what an
# unresolved config pin (or an empty/absent name) canonicalizes to. Neither may
# ever be STAMPED on a row (a row so tagged claims to belong to a geometry that
# does not exist, and the heal then burns a re-embed proving it), and neither
# may ever be the COMPARISON TARGET of a mismatch scan (comparing every row
# against 'degraded' classifies the entire corpus as mismatched the moment the
# endpoint blips). One definition, imported by health.py and
# scripts/migrate_vectors.py, so the two cannot drift apart.
_UNUSABLE_CANONICAL_IDS = ("degraded", _AUTO_CANONICAL)


def is_usable_model_tag(tag) -> bool:
    """True when `tag` names a real, comparable geometry.

    Identity-based, not string-based: 'degraded[prefixed]', 'Degraded' and
    'degraded:latest' are all the same non-answer, and so are '', None, 'auto',
    'local' and 'default'."""
    if not tag:
        return False
    return canonical_model_id(tag) not in _UNUSABLE_CANONICAL_IDS


def expected_blob_len(embedder) -> int:
    """Byte length a correctly-dimensioned packed vector must have for this
    embedder (float32 → 4 bytes/dim). 0 when the dimensionality is unknown,
    which callers treat as "cannot check", never as "everything is wrong"."""
    try:
        dims = int(getattr(embedder, "dimensions", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, dims) * 4


# -- declared vector width, and refusing to rewrite a store against a lie (A0g) -
#
# THE DEFECT THIS EXISTS FOR. `OpenAICompatEmbedder.healthcheck()` ends with
# `self.dimensions = len(v)` -- "trust the server's real dimensionality" -- so the
# ACTIVE width is whatever the endpoint answered with, and `embeddings.dimensions`
# from config was read at construction and then thrown away. Every width decision
# downstream (expected_blob_len, the heal's wrong_dim classification,
# migrate_vectors' `_usable`) is made against that adopted number. Measured on a
# store seeded at 768 with a server answering 384 under the SAME model name:
# migrate_vectors printed "expected width: 384 dims" and rewrote 1,534 of 1,536
# rows into a 384-dim geometry, stamped `nomic-embed-text[prefixed]` -- a store
# silently re-geometried by a misconfigured or misreporting endpoint, with no row
# left that says the old vectors were ever 768.
#
# A probe answering a width is a MEASUREMENT. It is only trustworthy where nothing
# states what the width should be, so where something does, a disagreement is a
# refusal, not an adoption. Two things can state it:
#
#   1. `embeddings.dimensions`, when the operator DECLARED it (Config.explicit,
#      not Config.get -- the DEFAULTS value is a recommendation and must not make
#      an unlisted 1024-dim model look misconfigured). This covers `model: auto`,
#      where the model id is not known until the probe has already run, and it
#      covers models no table lists.
#   2. This table, for canonical ids whose published width is a documented fact.
#
# ...and an operator can supersede both for one run (migrate_vectors --expect-dims)
# when a genuinely new or deliberately truncated geometry is intended. An UNKNOWN
# canonical id with nothing declared has NO expectation and is never refused:
# the guard exists to catch a contradiction, not to gate models it has not heard of.
#
# ADDING A ROW IS A CLAIM ABOUT A MODEL, so it carries its citation, the same rule
# _MODEL_ALIASES follows. Do not add one from memory.
KNOWN_MODEL_DIMENSIONS = {
    # nomic-embed-text (v1 / v1.5 / the bare name -- one canonical id, see
    # _MODEL_ALIASES): 768.
    #   * upstream model card (nomic-ai/nomic-embed-text-v1.5): 768-dimension
    #     output. It is Matryoshka-trained, so a server MAY be configured to
    #     return a truncated 512/256/128/64 -- a different geometry, which is
    #     exactly what `embeddings.dimensions` / --expect-dims are for;
    #   * measured on this host 2026-09-10: ollama `nomic-embed-text:latest`
    #     POST /v1/embeddings returned 768 floats;
    #   * this module's canonical-identity block above already states it ("ONE
    #     model producing ONE 768-dim geometry"), engine/config.py DEFAULTS
    #     carries dimensions: 768, and CHANGELOG.md:2 names it the canonical
    #     embedder. The number was load-bearing in three places and written down
    #     as an expectation in none.
    "nomic-embed-text": 768,
}


def known_model_dimensions(model) -> int:
    """Published width for a model name, via its canonical id. 0 = no entry.

    0 means "this table has no opinion", never "wrong": an unlisted model is a
    model nobody documented here, and refusing it would be a gate rather than a
    guard."""
    return int(KNOWN_MODEL_DIMENSIONS.get(canonical_model_id(model), 0) or 0)


def width_expectation(embedder, cfg=None, override=None) -> tuple:
    """``(dims, source)`` the active embedder OUGHT to answer with; ``(0, "")``
    when nothing states one.

    Precedence, most specific first: an explicit per-run `override`; the
    operator's DECLARED `embeddings.dimensions`; this module's known-dimensions
    table for the resolved canonical id. `source` names which one, so a refusal
    can say where the number it is defending came from.

    A `cfg` without `explicit()` (a plain dict, a stub) contributes nothing rather
    than falling back to `get()`: reading the merged value would turn the 768
    DEFAULT into a declaration and refuse every unlisted model of another width."""
    try:
        if override:
            return max(0, int(override)), "--expect-dims"
    except (TypeError, ValueError):
        pass
    declared = None
    explicit = getattr(cfg, "explicit", None)
    if callable(explicit):
        declared = explicit("embeddings.dimensions")
    if declared:
        try:
            return max(0, int(declared)), "config embeddings.dimensions"
        except (TypeError, ValueError):
            pass
    known = known_model_dimensions(getattr(embedder, "model", ""))
    if known:
        return known, "the known-dimensions table for %r" % canonical_model_id(
            getattr(embedder, "model", ""))
    return 0, ""


def width_contradiction(embedder, cfg=None, override=None) -> str:
    """"" when the embedder's reported width is consistent with the expectation
    (or when there is no expectation, or no reported width); otherwise ONE line
    naming expected vs reported.

    Truthy return means REFUSE: a caller that rewrites stored vectors must write
    nothing and exit non-zero. A wrong-geometry vector that can still be found
    beats a store silently rebuilt in a geometry nobody asked for -- the same rule
    the A0fix refusal contract applies to text."""
    expected, source = width_expectation(embedder, cfg, override)
    if not expected:
        return ""
    try:
        reported = int(getattr(embedder, "dimensions", 0) or 0)
    except (TypeError, ValueError):
        reported = 0
    if not reported or reported == expected:
        return ""
    return ("the endpoint reports %d-dimension vectors for model %r (tag %s), but "
            "%s expects %d" % (reported, getattr(embedder, "model", ""),
                               embedder_model_tag(embedder) or "?", source, expected))


# -- token-aware input clamp (§27 embeddings.max_input_tokens / .overflow) ----
#
# The production incident this exists for: the deployed llama.cpp/nomic server
# has a REAL context of 2048 tokens. Excerpts up to 4000 chars overflowed it,
# the server answered HTTP 500, and the curation job burned all its retry
# attempts and became permanently poisoned (re-enqueue reuses the same spent
# row) even after the root cause was fixed. Nothing downstream of this module
# may ever hand a model more than `max_input_tokens` worth of input again.
#
# -- THE ESTIMATE, AND THE NAMED MARGINS ON TOP OF IT (A10b) -----------------
#
# A10 unified the tree onto ONE chars/token ratio -- `get_context` had been
# budgeting `token_budget * 4` while `estimate_tokens` counted chars/3, so the
# engine's budget arithmetic disagreed with its own accounting by 33% -- and
# set that one ratio to 3. That closed the disagreement but priced a SAFETY
# MARGIN into the ESTIMATE itself, where every call site paid it whether or not
# its failure mode wanted it. A10b separates the two:
#
#     estimate_tokens(text)                -> the best available ESTIMATE
#     estimate_tokens(text, margin=NAME)   -> that estimate, inflated by a
#                                             named, documented safety margin
#     budget_chars(n, margin=NAME)         -> the exact inverse of the above
#
# THE ESTIMATE: `_CHARS_PER_TOKEN = 4`. No BPE tokenizer is installable here
# (tiktoken / transformers / tokenizers / sentencepiece are all absent, and no
# network or paid API is permitted), so the ratio is BRACKETED by measurement
# rather than called: a byte-level BPE's pre-tokenizer splits at exactly the
# [A-Za-z0-9]+ / single-punctuation boundaries and then merges bytes WITHIN a
# piece (absorbing the leading space), so every such "atom" costs at least one
# token and long or rare atoms cost more. Hence tokens >= atoms, and chars/atom
# is an UPPER BOUND on the true chars/token ratio. Measured by
# `scripts/measure_chars_per_token.py` over the corpora this project evaluates
# on -- rerun it when the constant is questioned, rather than re-deriving the
# argument:
#
#     oracle.json       8.1M chars   chars/word 6.24   chars/atom 4.63
#     s_sample100.json 49.1M chars   chars/word 6.25   chars/atom 4.76
#
# 4 is the largest integer strictly below both bounds. It leaves >= 14%
# (4.63 / 4 = 1.16) for the atoms that really do split into several tokens, and
# being an integer it keeps `estimate_tokens` and `budget_chars` exact inverses
# in integer arithmetic -- no float drift to re-open the A10 defect. It is a
# POINT ESTIMATE and deliberately NOT a bound; bounds are what the margins are.
#
# WHY NOT KEEP 3: chars/3 over-estimates the true token count by >= 1.54x on
# both corpora, so a caller asking `get_context` for 12 000 tokens was handed
# ~36 000 chars where ~48 000 fit. Chronicle silently returned about a third
# less evidence than the budget allowed -- measured at -3.5 points of ctx_eval
# recall @12k (89.7 -> 86.2) in A10's own A/B. Over-estimating is only "safe"
# where the failure mode is an overflow; where the failure mode is
# under-delivery it is simply wrong, and one number cannot serve both.
#
# THE MARGINS: a margin is a multiplier (>= 1) applied to the estimate BY A
# CALL SITE, chosen for what happens when that site is wrong. It is never
# folded back into the estimate and never anonymous -- every production call
# names one, and tests/test_token_margins.py fails if a call site stops naming
# one, if a second chars/token constant appears anywhere in the tree, or if a
# site swaps to a margin that does not match its failure mode.
_CHARS_PER_TOKEN = 4


class SafetyMargin(NamedTuple):
    """One named, documented headroom factor on the token estimate.

    `num`/`den` is the multiplier applied to the ESTIMATED token cost, kept as
    an exact rational so the arithmetic stays integer and `budget_chars` stays
    a true inverse of `estimate_tokens`. `num >= den >= 1` always: a "safety
    margin" below 1 would make a cap under-count, which is the one thing no
    call site can ever want.
    """

    name: str
    num: int
    den: int
    why: str


CONTEXT_BUDGET = SafetyMargin(
    "CONTEXT_BUDGET", 1, 1,
    "get_context assembly, packing and the final trim -- the budget the CALLER "
    "asked for. UNDER-delivery is the failure mode here: the budget is a slice "
    "of a window the caller already sized, so quietly shipping three quarters "
    "of it costs evidence and nothing else (-3.5 pts ctx_eval @12k under "
    "chars/3). No headroom is added: the caller's own N is the headroom, and "
    "`estimate_tokens(ctx) <= token_budget` stays exactly true.")

COMPRESSION_BUDGET = SafetyMargin(
    "COMPRESSION_BUDGET", 1, 1,
    "compress() / preflight / checkpoint digest / working-set rehydration -- "
    "the live window trim. The headroom for this site is STATED ELSEWHERE and "
    "must not be double-charged: the target is context_engine."
    "low_watermark_percent (0.55) of the model's REAL context window, so ~45% "
    "of that window is already reserve, and should_compress() re-fires off the "
    "host's real prompt-token count when an estimate runs low. That covers any "
    "content down to 4 * 0.55 = 2.2 true chars/token; denser windows than that "
    "cost an extra compression pass, not an overflow.")

EMBED_INPUT = SafetyMargin(
    "EMBED_INPUT", 4, 3,
    "the embedding input clamp -- the one place an estimate crosses a HARD "
    "model boundary. THE INCIDENT: a deployed llama.cpp/nomic server whose real "
    "context is 2048 tokens was handed 4000-char excerpts, answered HTTP 500, "
    "and the curation job burned its entire retry budget and stayed permanently "
    "poisoned (re-enqueue reuses the same spent row). The content is arbitrary "
    "-- URLs, base64, CJK and minified code drive chars/atom toward 1 -- and "
    "nothing here can inspect the server's tokenizer. 4/3 reproduces EXACTLY "
    "the chars/3 ceiling that has held since that incident (4/3 of chars/4 IS "
    "chars/3, byte for byte), so this is the incident-tested value rather than "
    "a worst-case bound: it covers content down to 3 true chars/token. Below "
    "that the remaining containment is _split_for_cap's boundary-aware chunking "
    "plus the job's bounded retries, which is why a CJK-heavy corpus wants "
    "max_input_tokens configured BELOW the server's real context.")

# Every margin in the tree, in one place: the registry tests/test_token_margins
# checks call sites against. A new margin must be added HERE, with a `why`.
MARGINS = (CONTEXT_BUDGET, COMPRESSION_BUDGET, EMBED_INPUT)
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


def estimate_tokens(text: str | None, margin: SafetyMargin | None = None) -> int:
    """Estimated tokens in `text` (chars/4, ceiling), optionally inflated by a
    NAMED safety margin (§27 embeddings; A10b).

    With no margin this is the best available ESTIMATE and nothing else -- the
    number to report, log or compare budgets in. A call site whose failure mode
    needs headroom passes its own margin (`estimate_tokens(t, margin=
    EMBED_INPUT)`), which is the ONLY way headroom is ever added; production
    call sites must name one explicitly, which tests/test_token_margins.py
    enforces so a forgotten margin cannot be mistaken for a deliberate one.
    """
    if not text:
        return 0
    num, den = (1, 1) if margin is None else (margin.num, margin.den)
    # ceil division, stdlib-only, integer throughout (no float ratio to drift).
    return -(-(len(text) * num) // (_CHARS_PER_TOKEN * den))


def budget_chars(token_budget, margin: SafetyMargin | None = None) -> int:
    """Chars a `token_budget`-token block may occupy — estimate_tokens' inverse.

    The ONE place a token budget becomes a char budget. Exact inverse of
    `estimate_tokens` UNDER THE SAME MARGIN, by construction, so the guarantee
    is total rather than approximate:

        len(text) <= budget_chars(n, margin=M)  <=>  estimate_tokens(text, margin=M) <= n

    (both are the same integer rational; there is no second ratio left to
    disagree with, the way `* 4` and `// 3` did.) Mixing margins across the two
    directions is the one misuse this cannot catch, which is why the margin is
    named at the call site and pinned per site by tests/test_token_margins.py.
    A negative or unparseable budget is 0 chars, not a crash and not
    "unbounded"."""
    try:
        n = int(token_budget)
    except (TypeError, ValueError):
        return 0
    num, den = (1, 1) if margin is None else (margin.num, margin.den)
    return max(0, n) * _CHARS_PER_TOKEN * den // num


def _cap_chars(max_input_tokens: int) -> int:
    """Character budget that guarantees the clamped text is within `cap`
    tokens under the EMBED_INPUT margin.

    Same inverse as `budget_chars` under the EMBED_INPUT margin (this is the
    incident-driven clamp, not a budget), with a floor of one token's worth so
    an absurdly small cap still admits something rather than embedding "".
    """
    return max(budget_chars(1, margin=EMBED_INPUT),
               budget_chars(max_input_tokens, margin=EMBED_INPUT))


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

    def model_tag(self) -> str:
        """THE tag every vector of this embedder's is stamped with (A0):
        `canonical_model_id(self.model)` plus the E1 `[prefixed]` marker when
        task prefixes are on. Call sites go through
        `embeddings.embedder_model_tag(embedder)`, which resolves this."""
        return make_model_tag(self.model, bool(getattr(self, "use_task_prefixes", False)))

    def model_with_prefix_marker(self) -> str:
        """Retained pre-A0 name for `model_tag()`; identical result.

        Kept because duck-typed embedders and older call sites still spell it
        this way; it delegates rather than reimplementing so the two names can
        never drift into two different tag formats."""
        return self.model_tag()


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
        if estimate_tokens(text, margin=EMBED_INPUT) <= self.max_input_tokens:
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

    def model_tag(self) -> str:
        """Hashing mode never uses task prefixes, so the tag is just the
        canonical id — which maps every alias in `_HASHING_NAMES` ('hashing',
        'offline', 'none') onto this implementation's own id, 'hashing-v1', and
        leaves any other deliberate 'hashing-*' variant alone."""
        return make_model_tag(self.model, False)

    def model_with_prefix_marker(self) -> str:
        """Retained pre-A0 name for `model_tag()`; identical result."""
        return self.model_tag()


# -- on-host guard for memory-bearing requests (A2) ---------------------------
#
# THE PROMISE THIS ENFORCES. `config.DEFAULTS` told every operator that
# Chronicle has "no remote-API tier: memory excerpts never leave the host".
# That sentence described a RECOMMENDED DEPLOYMENT; it was never a control.
# `get_embedder` trusted any explicit `base_url`, `$CHRONICLE_EMBED_BASE_URL`
# was honoured unchecked, and `extraction.llm.base_url` POSTs whole excerpts to
# whatever it is pointed at. In production an out-of-tree script pointed exactly
# that knob at a hosted API and shipped ~190k excerpts off-host for a month; the
# engine had no opinion about it while it happened and the store could not tell
# afterwards.
#
# The engine now REFUSES to send memory content anywhere that is not this host
# or its own private network, unless the operator explicitly sets
# `embeddings.allow_remote: true` / `extraction.llm.allow_remote: true`.
# Refusal never becomes an exception at a call site: embeddings fall to
# DegradedEmbedder (no vectors written, every embed queued — §24.4) and
# extraction falls back to the heuristic, because capture must never depend on
# a model being reachable (I18). A misconfigured endpoint costs vectors, not
# memories, and never silently costs privacy.
#
# WHAT COUNTS AS ON-HOST — the entire policy, in one list:
#   loopback     127.0.0.0/8, ::1, `::`/`0.0.0.0`, and the literal names
#                `localhost` / `*.localhost` (reserved to loopback by RFC 6761)
#   private      RFC1918 10/8, 172.16/12, 192.168/16; IPv6 ULA fc00::/7;
#                RFC6598 shared space 100.64/10
#   link-local   169.254.0.0/16, fe80::/10
#   unix         a `unix:` / `http+unix:` socket URL — a socket cannot leave
#                the machine at all. NOTE this is a DESTINATION verdict, not a
#                claim of transport support: `urllib` cannot open a unix socket,
#                so such a base_url passes the guard and then simply fails to
#                connect. The guard decides where bytes may go; it does not
#                promise the client can get there.
# Anything else — a public IP literal, a public hostname, an https:// URL to a
# hosted API — is REMOTE and refused at default config.
#
# DNS POLICY (fail closed, resolved once, never in a hot path):
#   * IP literals and the `localhost` family are classified with NO DNS at all,
#     so the guard works on a box with no resolver.
#   * Any other hostname is resolved ONCE — at embedder/extractor construction —
#     and the verdict is cached process-wide. `embed()` never resolves.
#   * A hostname is on-host only if EVERY address it resolves to is on-host. One
#     public answer makes the whole name remote, so a split-horizon or
#     DNS-rebinding answer cannot buy access.
#   * Resolution FAILURE refuses. An unresolvable name is not evidence of
#     privacy; treating "I could not check" as "it is fine" is the exact shape
#     of the bug this guard exists for.
#   * An IPv4-mapped IPv6 address is judged by the IPv4 address inside it
#     (`::ffff:8.8.8.8` is 8.8.8.8, NOT "private" — which is what Python's own
#     `ipaddress.is_private` would say for ::ffff:0:0/96 on 3.9). 6to4 and
#     Teredo addresses tunnel a public v4 and are refused outright.


class RemoteEndpointRefused(RuntimeError):
    """A memory-bearing endpoint is off-host and allow_remote is false.

    Raised by the constructors (`OpenAICompatEmbedder`, `LLMExtractor`) so the
    refusal happens BEFORE any object capable of making the call exists, and
    caught by `get_embedder` / `make_extractor`, which degrade instead."""


ONHOST_KINDS = ("loopback", "private", "link-local", "unix")

_LOCALHOST_NAMES = frozenset({"localhost", "localhost.localdomain",
                              "ip6-localhost", "ip6-loopback"})
_UNIX_SCHEMES = frozenset({"unix", "unix+http", "unix+https", "http+unix", "https+unix"})

_ONHOST_V4 = (
    ("loopback", ipaddress.ip_network("127.0.0.0/8")),
    ("loopback", ipaddress.ip_network("0.0.0.0/32")),      # "this host"
    ("private", ipaddress.ip_network("10.0.0.0/8")),
    ("private", ipaddress.ip_network("172.16.0.0/12")),
    ("private", ipaddress.ip_network("192.168.0.0/16")),
    ("private", ipaddress.ip_network("100.64.0.0/10")),    # RFC6598 shared/CGNAT
    ("link-local", ipaddress.ip_network("169.254.0.0/16")),
)
_ONHOST_V6 = (
    ("loopback", ipaddress.ip_network("::1/128")),
    ("loopback", ipaddress.ip_network("::/128")),
    ("private", ipaddress.ip_network("fc00::/7")),         # ULA
    ("link-local", ipaddress.ip_network("fe80::/10")),
)

# host -> kind, filled once per hostname. Only NAMES that needed DNS land here;
# IP literals and `localhost` are decided without a lookup and are not cached.
# Tests may `.clear()` it to re-arm resolution.
_HOST_KIND_CACHE: dict = {}

# One WARNING per process per purpose, for each of the two outcomes worth
# saying out loud: a refusal, and an allow_remote that IS sending memory
# off-host. Module-level (not per-embedder) because get_embedder runs on every
# ChronicleCore() and a per-object counter would re-log on every boot — the
# same reason `_DORMANT_WARNED` and `_WRONG_DIM` are module-level.
# Tests may `.clear()` these to re-arm.
_REMOTE_REFUSED_WARNED: set = set()
_REMOTE_ALLOWED_WARNED: set = set()


def _getaddrinfo(host: str):
    """Indirection so a test can substitute a resolver without monkeypatching
    the `socket` module globally (and so nothing else in the process inherits
    a fake resolver)."""
    return socket.getaddrinfo(host, None)


def classify_address(ip) -> str:
    """Classify one already-parsed `ipaddress` object. No I/O."""
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped                       # ::ffff:8.8.8.8 IS 8.8.8.8
    elif ip.version == 6 and (getattr(ip, "sixtofour", None) is not None
                              or getattr(ip, "teredo", None) is not None):
        return "remote"                   # tunnels a public v4 inside
    table = _ONHOST_V4 if ip.version == 4 else _ONHOST_V6
    for kind, net in table:
        if ip in net:
            return kind
    return "remote"


def _classify_resolved(host: str) -> str:
    """Resolve `host` once and reduce every answer to a single verdict."""
    cached = _HOST_KIND_CACHE.get(host)
    if cached is not None:
        return cached
    try:
        infos = _getaddrinfo(host)
    except Exception:
        kind = "unresolvable"
    else:
        kinds = []
        for info in infos or ():
            try:
                addr = info[4][0]
            except Exception:
                continue
            try:
                kinds.append(classify_address(ipaddress.ip_address(str(addr).split("%")[0])))
            except ValueError:
                kinds.append("remote")    # cannot parse it -> cannot vouch for it
        if not kinds:
            kind = "unresolvable"
        elif "remote" in kinds:
            kind = "remote"               # ONE public answer makes the name remote
        elif all(k == "loopback" for k in kinds):
            kind = "loopback"
        else:
            kind = "private"
    _HOST_KIND_CACHE[host] = kind
    return kind


def endpoint_kind(url: str | None) -> str:
    """Classify a base_url: loopback | private | link-local | unix | remote |
    unresolvable | none.

    `none` means "no endpoint configured" (empty/None) — nothing is sent, so
    there is nothing to refuse. Everything else is a place bytes could go."""
    raw = (url or "").strip()
    if not raw:
        return "none"
    scheme = raw.split(":", 1)[0].lower() if ":" in raw else ""
    if scheme in _UNIX_SCHEMES:
        return "unix"
    try:
        parts = urllib.parse.urlsplit(raw if "://" in raw else "http://" + raw)
        host = (parts.hostname or "").strip()
    except Exception:
        return "unresolvable"
    if not host:
        return "unresolvable"             # cannot name the destination -> refuse
    host = host.lower().rstrip(".")
    if host in _LOCALHOST_NAMES or host.endswith(".localhost"):
        return "loopback"                 # RFC 6761: no DNS needed, ever
    try:
        return classify_address(ipaddress.ip_address(host))
    except ValueError:
        pass
    return _classify_resolved(host)


def check_endpoint(url: str | None, allow_remote: bool = False, purpose: str = "embeddings",
                   config_key: str = "embeddings.allow_remote") -> str:
    """Return the endpoint kind if `url` may carry memory content; otherwise
    raise `RemoteEndpointRefused`.

    Call this ONCE, where the client object is built — the verdict is then a
    property of that object and no per-request work is added."""
    kind = endpoint_kind(url)
    if kind == "none" or kind in ONHOST_KINDS:
        return kind
    if allow_remote:
        if purpose not in _REMOTE_ALLOWED_WARNED:
            _REMOTE_ALLOWED_WARNED.add(purpose)
            logger.warning(
                "Chronicle %s: %s is OFF-HOST (%s) and %s is true -- memory content WILL be "
                "sent to a third party. This is an explicit operator choice; the local-first "
                "guarantee in the config comment does not apply to this deployment.",
                purpose, _redact(url), kind, config_key)
        return kind
    if purpose not in _REMOTE_REFUSED_WARNED:
        _REMOTE_REFUSED_WARNED.add(purpose)
        logger.warning(
            "Chronicle %s: REFUSED %s -- it is %s, and Chronicle only sends memory content to "
            "an endpoint on this host or its private network (127.0.0.0/8, ::1, localhost, "
            "RFC1918/ULA/link-local, or a unix socket). %s continues WITHOUT it: %s. Set "
            "%s: true if you really intend memory excerpts to leave this host.",
            purpose, _redact(url), kind, purpose,
            "no vectors are written and every embed is queued for retry"
            if purpose == "embeddings" else "the offline heuristic extractor is used",
            config_key)
    else:
        logger.debug("Chronicle %s: refused %s (%s); already warned once this process",
                     purpose, _redact(url), kind)
    raise RemoteEndpointRefused(
        "%s endpoint %s is %s; set %s: true to permit it" % (purpose, _redact(url), kind, config_key))


def _redact(url: str | None) -> str:
    """scheme://host:port of `url`, with any userinfo dropped — enough to name
    the destination in a log line without echoing a key embedded in the URL."""
    raw = (url or "").strip()
    if not raw:
        return "(unset)"
    try:
        parts = urllib.parse.urlsplit(raw if "://" in raw else "http://" + raw)
        if not parts.hostname:
            return raw.split("?", 1)[0][:80]
        netloc = parts.hostname + (":%d" % parts.port if parts.port else "")
        return "%s://%s" % (parts.scheme or "http", netloc)
    except Exception:
        return raw.split("?", 1)[0][:80]


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

    An exhausted budget raises EmbeddingsUnavailable and opens a circuit for
    `circuit_cooldown` seconds, during which calls fail at once rather than each
    re-spending the whole budget (see _circuit_trip).
    """

    def __init__(self, base_url: str, model: str, dimensions: int, api_key: str = "", timeout: float = 10.0,
                 max_attempts: int = 5, backoff_base: float = 1.0, backoff_cap: float = 8.0,
                 max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS, overflow: str = "truncate",
                 task_prefixes: str | bool | None = None, allow_remote: bool = False,
                 circuit_cooldown: float = 30.0):
        self.base_url = base_url.rstrip("/")
        # A2: the on-host check happens HERE, once, before an object that can
        # POST an excerpt exists -- and it is the only place DNS is consulted,
        # so embed()/embed_batch() stay resolution-free. RemoteEndpointRefused
        # propagates to get_embedder/_probe_endpoints, which degrade.
        self.endpoint_kind = check_endpoint(self.base_url, allow_remote, purpose="embeddings",
                                            config_key="embeddings.allow_remote")
        self.allow_remote = bool(allow_remote)
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
        # Circuit breaker: see _circuit_trip.
        self.circuit_cooldown = max(0.0, float(circuit_cooldown))
        self._open_until = 0.0

    # -- circuit breaker ------------------------------------------------------
    # Every call used to start from a fresh retry budget with no memory that the
    # endpoint had just failed. On a CPU-throttled host whose local embedding
    # server answered `/v1/models` in 0.1 s and then timed out on real work, one
    # context compaction that evicted twenty spans paid twenty full retry cycles
    # — measured at over six minutes, with 26 timeouts, before it had finished its
    # FIRST pass. Once a call exhausts its budget the endpoint is presumed down
    # for `circuit_cooldown` seconds: calls in that window fail at once, the
    # first call after it probes again, and a success closes the circuit.
    #
    # Exhaustion now raises EmbeddingsUnavailable, not the raw socket error.
    # That is the exception every caller treats as "the backend is down, try
    # later": _safe_vec queues a deferred embed job, the curation worker defers
    # the job without spending its failure cap. A raw `socket.timeout` reached
    # the generic handler instead, which logged at DEBUG and dropped the vector
    # for good — while the warning line above it promised "embed retried on the
    # next operation". Auth failures (401/403) are unchanged: waiting does not
    # fix a bad key.
    def _circuit_check(self):
        left = self._open_until - time.monotonic()
        if left > 0:
            raise EmbeddingsUnavailable(
                "%s is presumed down after repeated failures; next attempt in %.0fs"
                % (_redact(self.base_url), left))

    def _circuit_trip(self, attempts: int, exc: Exception) -> "EmbeddingsUnavailable":
        self._open_until = time.monotonic() + self.circuit_cooldown
        logger.error("Chronicle embeddings: %s failed after %d attempts (%s); vector deferred to "
                     "the curation queue, FTS retrieval continues; calls fail fast for %.0fs",
                     _redact(self.base_url), attempts, exc, self.circuit_cooldown)
        return EmbeddingsUnavailable("%s unavailable after %d attempts: %s"
                                     % (_redact(self.base_url), attempts, exc))

    def _circuit_reset(self):
        self._open_until = 0.0

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
        """Can this endpoint embed? Raises if not. Sets `dimensions` from the reply.

        Two attempts, and only a TIMEOUT earns the second. The short first
        attempt bounds startup when a server is DOWN -- a refused connection
        returns at once whatever the timeout, and so does any HTTP error. A
        timeout means something else: the port accepted and the server is
        working, just slower than the short cap. On a loaded host that is the
        normal case -- measured on the production VPS (2 cores, load ~13):
        llama.cpp answered in 3.3 s, 5.4 s and 6.8 s. With a flat 4 s cap the
        healthcheck declared that working server `unreachable` (a timeout is an
        OSError, which `_outcome_for` files with a closed port), so a config
        pinned to it sat DEGRADED writing no vectors, although real embeds get
        `self.timeout` and succeed. The retry uses exactly that request timeout,
        so the healthcheck can never be stricter than the requests it vouches for.
        """
        fast = min(self.timeout, 4.0)
        try:
            v = self._embed_raw("ok", timeout=fast)
        except Exception as e:
            if self.timeout <= fast or not _is_timeout(e):
                raise
            logger.info("Chronicle embeddings: %s healthcheck exceeded %.0fs; retrying once with "
                        "the %.0fs request timeout (slow, not down)", self.base_url, fast, self.timeout)
            v = self._embed_raw("ok", timeout=self.timeout)
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
        self._circuit_check()
        attempt = 0
        while True:
            try:
                vec = self._embed_raw(text, timeout=self.timeout)
                self._circuit_reset()
                return vec
            except Exception as e:
                attempt += 1
                if self._is_terminal(e):
                    logger.error("Chronicle embeddings: %s auth error (%s) -- terminal, not retrying",
                                 self.base_url, e)
                    raise
                if attempt >= self.max_attempts:
                    raise self._circuit_trip(attempt, e) from e
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
        if estimate_tokens(text, margin=EMBED_INPUT) <= self.max_input_tokens:
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
        self._circuit_check()
        attempt = 0
        while True:
            try:
                out = self._embed_raw_batch(part, timeout=max(self.timeout, 2.0 + 0.25 * len(part)))
                self._circuit_reset()
                return out
            except Exception as e:
                attempt += 1
                if self._is_terminal(e):
                    raise
                if attempt >= self.max_attempts:
                    raise self._circuit_trip(attempt, e) from e
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
        vectors would go out bare while model_tag() tags them
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
            if estimate_tokens(t, margin=EMBED_INPUT) <= self.max_input_tokens:
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

    def model_tag(self) -> str:
        """Canonical identity + the E1 `[prefixed]` marker (A0).

        `self.model` stays the RAW id the server was asked for — it goes on the
        wire in every request body and must match what the endpoint answers to.
        Only the STORED tag is canonicalized, which is the whole point: a
        llama.cpp server reporting
        "/opt/llama-embed/nomic-embed-text-v1.5.Q8_0.gguf" and an ollama server
        reporting "nomic-embed-text:latest" keep their own wire names and write
        the SAME row tag, "nomic-embed-text[prefixed]"."""
        return make_model_tag(self.model, self.use_task_prefixes)

    def model_with_prefix_marker(self) -> str:
        """Retained pre-A0 name for `model_tag()`; identical result."""
        return self.model_tag()


def _candidate_urls(base_url: str | None) -> list[str]:
    import os
    if base_url:
        return [base_url]
    env = os.environ.get("CHRONICLE_EMBED_BASE_URL")
    if env:
        return [env]
    return list(_DEFAULT_ENDPOINTS)


def _permitted_urls(base_url: str | None, allow_remote: bool = False) -> list[str]:
    """`_candidate_urls` minus anything the on-host guard refuses (A2).

    Kept separate from `_candidate_urls` so the DEGRADED log line can still
    name every endpoint that WAS considered, including the refused ones."""
    out = []
    for url in _candidate_urls(base_url):
        try:
            check_endpoint(url, allow_remote, purpose="embeddings",
                           config_key="embeddings.allow_remote")
        except RemoteEndpointRefused:
            continue
        out.append(url)
    return out


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


# -- the probe: auto-detection's network half, as an injectable object (A11b) --
#
# THE REPRODUCIBILITY DEFECT THIS ENDS. `get_embedder("auto")` — the DEFAULT,
# i.e. what every `ChronicleCore(...)` without an explicit embeddings config
# got — opened TCP connections to localhost:1234, :11434 and :8080 *during
# construction*. Whether a laptop happened to have Ollama running therefore
# decided which code path the constructor took, which embedder the core held,
# and what geometry every vector written afterwards lived in. Two machines
# running the same commit on the same store did not agree. That is a
# reproducibility bug first and a test-hermeticity bug second.
#
# The fix is not to remove the probe — auto-detection is genuinely what a local
# deployment wants — but to name it. All endpoint I/O now goes through one
# `EndpointProbe` object, so:
#   * a caller can pass `probe=` and get a deterministic answer;
#   * a harness can `set_default_probe(NullProbe())` once and make every
#     construction in the process socket-free without threading a parameter
#     through call sites it does not own;
#   * the default is still `NetworkProbe()`, and it is now written down as such
#     instead of being implicit in three inline urlopen calls.
#
# The A2 on-host guard is NOT delegated to the probe. `_probe_endpoints` calls
# `check_endpoint` on every candidate before the probe sees it AND on whatever
# the probe hands back, so a substituted probe cannot widen where memory may go.


class EndpointProbe(Protocol):
    """Every network operation embedder auto-detection performs, in one place."""

    def list_models(self, url: str, api_key: str) -> list:
        """Model ids this endpoint serves; [] if it serves none. May raise."""

    def make(self, url: str, model: str, dims: int, **kw) -> Embedder:
        """Construct a client for (url, model). No network I/O beyond the A2
        guard's name resolution — reachability is `healthcheck`'s question."""

    def healthcheck(self, embedder) -> bool:
        """True if `embedder` really embeds. Raises with a reason if it does not."""


class NetworkProbe:
    """The real probe: talks to the endpoint. This is the default."""

    def list_models(self, url: str, api_key: str) -> list:
        return _discover_embedding_models(url, api_key or "")

    def make(self, url: str, model: str, dims: int, **kw) -> Embedder:
        return OpenAICompatEmbedder(url, model, dims, **kw)

    def healthcheck(self, embedder) -> bool:
        return bool(embedder.healthcheck())


class NullProbe:
    """A probe that contacts nothing and finds nothing.

    Deterministic by construction: `get_embedder("auto", probe=NullProbe())`
    returns a DegradedEmbedder on every machine, whether or not something is
    listening on 11434. This is the probe a hermetic test harness installs."""

    def __init__(self, reason: str = "endpoint probing disabled (NullProbe)"):
        self.reason = reason

    def list_models(self, url: str, api_key: str) -> list:
        return []

    def make(self, url: str, model: str, dims: int, **kw) -> Embedder:
        return OpenAICompatEmbedder(url, model, dims, **kw)

    def healthcheck(self, embedder) -> bool:
        raise EmbeddingsUnavailable(self.reason)


class StaticProbe:
    """A probe backed by a table instead of a network: ``{url: [model, ...]}``
    (or ``{url: {"models": [...], "dimensions": n}}``).

    Lets a test describe a fake listener — "pretend ollama is up on 11434
    serving nomic-embed-text" — and get the SAME resolution every run, with no
    socket involved and with the A2 guard still deciding the destination."""

    def __init__(self, servers: dict | None = None, dimensions: int = 768):
        self.servers = dict(servers or {})
        self.dimensions = int(dimensions)

    def _entry(self, url: str) -> dict:
        raw = self.servers.get((url or "").rstrip("/"), self.servers.get(url))
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        return {"models": list(raw)}

    def list_models(self, url: str, api_key: str) -> list:
        return list(self._entry(url).get("models") or [])

    def make(self, url: str, model: str, dims: int, **kw) -> Embedder:
        return OpenAICompatEmbedder(url, model, dims, **kw)

    def healthcheck(self, embedder) -> bool:
        entry = self._entry(getattr(embedder, "base_url", ""))
        models = entry.get("models") or []
        if embedder.model not in models:
            raise EmbeddingsUnavailable(
                "%s does not serve %r (StaticProbe)" % (_redact(embedder.base_url), embedder.model))
        embedder.dimensions = int(entry.get("dimensions") or self.dimensions)
        return True


_DEFAULT_PROBE: list = [NetworkProbe()]


def default_probe():
    """The probe used when a caller passes none. `NetworkProbe()` out of the box."""
    return _DEFAULT_PROBE[0]


def set_default_probe(probe) -> None:
    """Install the process-wide default probe (None restores `NetworkProbe()`).

    For a harness that must make EVERY construction in the process
    deterministic, including cores built by code it does not own."""
    _DEFAULT_PROBE[0] = probe if probe is not None else NetworkProbe()


# -- probe outcomes: failures are reported, not swallowed (A11b) ---------------
#
# The loop used to be `except Exception: continue`, twice. A guard refusal, a
# 500, a malformed /v1/models body and "nothing is listening" were all the same
# silent `continue`, so a broken deployment and an empty one produced identical
# output: one DEGRADED line naming the URLs and nothing about WHY. Now every
# candidate gets a recorded outcome with its reason. Noise is controlled by
# OUTCOME, not by dropping the information: "nothing listening" is the normal
# case and logs at DEBUG; anything else logs one WARNING per (url, outcome) per
# process, and the full per-candidate report is attached to the embedder and
# available from `last_probe_report()`.

#: (url, outcome) pairs already warned about this process. Tests may `.clear()`.
_PROBE_WARNED: set = set()

#: Report from the most recent probe sweep; see `last_probe_report()`.
_LAST_PROBE_REPORT: list = []

#: Outcomes that mean "this endpoint simply is not there" — expected, not news.
QUIET_OUTCOMES = ("unreachable", "no_models")


def last_probe_report() -> list:
    """Per-candidate outcome of the most recent endpoint probe sweep.

    A list of ``{"url", "model", "outcome", "reason"}``. `outcome` is one of
    ``refused`` (A2 guard), ``unreachable``, ``no_models``, ``not_embedder``,
    ``error``, ``ok``."""
    return list(_LAST_PROBE_REPORT)


def reset_probe_report() -> None:
    """Clear the last report and re-arm the one-shot warnings (tests/long hosts)."""
    del _LAST_PROBE_REPORT[:]
    _PROBE_WARNED.clear()


def _is_timeout(exc: BaseException) -> bool:
    """True when `exc` is a read/connect TIMEOUT, directly or wrapped by urllib.

    `socket.timeout` is its own OSError subclass on Python 3.9 and an alias of
    TimeoutError from 3.10, so both are named. Deliberately narrower than
    `_outcome_for`'s "unreachable", which lumps timeouts with refused
    connections: the healthcheck must tell "slow" from "down"."""
    kinds = (TimeoutError, socket.timeout)
    return isinstance(exc, kinds) or isinstance(getattr(exc, "reason", None), kinds)


def _outcome_for(exc: BaseException) -> str:
    """Classify a probe failure. Only "nothing is listening here" is quiet.

    An HTTP status means the endpoint ANSWERED — a 500 or a 404 is a real
    signal about a server that exists, not a closed port — so it classifies as
    `error` even though `urllib.error.HTTPError` is an `OSError` subclass."""
    if isinstance(exc, RemoteEndpointRefused):
        return "refused"
    if isinstance(getattr(exc, "code", None), int):
        return "error"
    cause = getattr(exc, "reason", None)
    if not isinstance(cause, BaseException):
        cause = exc
    if isinstance(cause, OSError):
        return "unreachable"
    return "error"


def _record_probe(report: list, url: str, model: str, outcome: str, reason: str) -> None:
    """Append one candidate's outcome and say it out loud exactly once."""
    entry = {"url": _redact(url), "model": model or "", "outcome": outcome,
             "reason": (reason or "")[:200]}
    report.append(entry)
    if outcome == "ok":
        return
    key = (entry["url"], outcome)
    if outcome in QUIET_OUTCOMES or outcome == "refused":
        # "refused" already produced its own one-per-process WARNING inside
        # check_endpoint; repeating it here would double every refusal.
        logger.debug("Chronicle embeddings: probe %s %s%s — %s", entry["url"],
                     ("model %r " % model) if model else "", outcome, entry["reason"])
        return
    if key in _PROBE_WARNED:
        logger.debug("Chronicle embeddings: probe %s %s again (%s); already warned once",
                     entry["url"], outcome, entry["reason"])
        return
    _PROBE_WARNED.add(key)
    logger.warning(
        "Chronicle embeddings: probe of %s FAILED with %s%s — %s. This is NOT the ordinary "
        "'nothing listening' case; the endpoint answered or the guard rejected it. Auto-detection "
        "will treat this endpoint as unusable.",
        entry["url"], outcome, (" for model %r" % model) if model else "", entry["reason"])


def _probe_endpoints(model: str | None, dims: int, base_url: str | None,
                     api_key: str | None, max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS,
                     overflow: str = "truncate", task_prefixes: str | bool | None = None,
                     allow_remote: bool = False, probe=None,
                     report: list | None = None) -> Embedder | None:
    """First reachable OpenAI-compatible endpoint that really embeds, else None.

    `model` auto/empty → ask each endpoint's /v1/models what it serves and try
    those; otherwise try exactly that id. Shared by init (get_embedder) and the
    later re-probe (DegradedEmbedder.recheck) so both decide identically.

    `probe` (A11b) is the object that performs the endpoint I/O; `None` means
    `default_probe()`. `report` collects one record per candidate — pass a list
    to read the outcomes, or read `last_probe_report()` afterwards.

    A2: off-host candidates are dropped BEFORE the probe sees them. That call is
    not memory-bearing, but it carries `api_key` and it is the step that would
    announce this host to a third party, so an unchecked
    `$CHRONICLE_EMBED_BASE_URL` must not reach it either. The guard is applied
    AGAIN to whatever the probe returns: an injected probe supplies the
    reachability answer, never the destination policy."""
    probe = probe if probe is not None else default_probe()
    if report is None:
        report = []
    del _LAST_PROBE_REPORT[:]
    auto = (model or "auto").strip().lower() in _AUTO_NAMES
    kw = dict(api_key=api_key or "", max_input_tokens=max_input_tokens, overflow=overflow,
              task_prefixes=task_prefixes, allow_remote=allow_remote)
    found = None
    for url in _candidate_urls(base_url):
        try:
            check_endpoint(url, allow_remote, purpose="embeddings",
                           config_key="embeddings.allow_remote")
        except RemoteEndpointRefused as e:
            _record_probe(report, url, "", "refused", str(e))
            continue
        if auto:
            try:
                candidates = probe.list_models(url, api_key or "")
            except Exception as e:
                _record_probe(report, url, "", _outcome_for(e), "%s: %s" % (type(e).__name__, e))
                continue
            if not candidates:
                _record_probe(report, url, "", "no_models",
                              "endpoint lists no model that can be tried")
                continue
        else:
            candidates = [model]
        for mid in candidates:
            try:
                emb = probe.make(url, mid, dims, **kw)
            except RemoteEndpointRefused as e:
                _record_probe(report, url, mid, "refused", str(e))
                break                       # the URL is refused, not this model
            except Exception as e:
                _record_probe(report, url, mid, "error", "%s: %s" % (type(e).__name__, e))
                continue
            if emb is None:
                _record_probe(report, url, mid, "not_embedder", "probe returned no client")
                continue
            try:
                # A2 re-assert on the RETURNED client: a probe may decide what is
                # reachable, never what is permissible.
                check_endpoint(getattr(emb, "base_url", url), allow_remote, purpose="embeddings",
                               config_key="embeddings.allow_remote")
            except RemoteEndpointRefused as e:
                _record_probe(report, getattr(emb, "base_url", url), mid, "refused", str(e))
                continue
            try:
                ok = probe.healthcheck(emb)
            except Exception as e:
                _record_probe(report, url, mid, _outcome_for(e), "%s: %s" % (type(e).__name__, e))
                continue
            if not ok:
                _record_probe(report, url, mid, "not_embedder", "healthcheck returned false")
                continue
            _record_probe(report, url, mid, "ok", "healthcheck passed")
            found = emb
            break
        if found is not None:
            break
    _LAST_PROBE_REPORT.extend(report)
    return found


def probe_summary(report: list | None) -> str:
    """One-line 'url=outcome' digest of a probe report, for a log line."""
    if not report:
        return "no candidate endpoints"
    return ", ".join("%s=%s" % (r["url"], r["outcome"]) for r in report)


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
                 task_prefixes: str | bool | None = None, allow_remote: bool = False,
                 probe=None, probe_report: list | None = None):
        self.requested_model = model or "auto"
        self.base_url = base_url
        self.api_key = api_key
        # A2: carried so `recheck()` re-applies the SAME on-host guard. A
        # degraded-because-off-host embedder must never adopt that endpoint on
        # a later probe just because the probe path forgot the flag.
        self.allow_remote = bool(allow_remote)
        # A11b: the probe that failed to find a backend is the probe recheck()
        # must keep using. A DegradedEmbedder produced under an injected probe
        # that later adopted a REAL server on the next recheck would reintroduce
        # exactly the nondeterminism the injection exists to remove.
        self.probe = probe
        self.probe_report = list(probe_report or [])
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
        report: list = []
        emb = _probe_endpoints(self.requested_model, self._dimensions, self.base_url, self.api_key,
                              max_input_tokens=self.max_input_tokens, overflow=self.overflow,
                              task_prefixes=self._task_prefixes_config,
                              allow_remote=self.allow_remote, probe=self.probe, report=report)
        self.probe_report = report
        if emb is None:
            logger.debug("Chronicle embeddings: recheck found nothing — %s", probe_summary(report))
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

    def model_tag(self) -> str:
        """Delegate to the adopted backend; 'degraded' while nothing is live.

        The degraded value is never stamped on a row — no vector exists to stamp
        while embed() is raising — but it is canonical-shaped so a health scan
        comparing tags against it behaves like any other comparison."""
        if self._live is not None:
            return self._live.model_tag()
        return canonical_model_id(self.model)

    def model_with_prefix_marker(self) -> str:
        """Retained pre-A0 name for `model_tag()`; identical result."""
        return self.model_tag()


def get_embedder(model: str | None = None, dimensions: int | None = None,
                 base_url: str | None = None, api_key: str | None = None,
                 max_input_tokens: int | None = None, overflow: str | None = None,
                 task_prefixes: str | bool | None = None,
                 allow_remote: bool | None = None, probe=None) -> Embedder:
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

    `probe` (A11b): the object that performs endpoint I/O during auto-detection
    — `list_models` / `make` / `healthcheck`. `None` uses `default_probe()`,
    which is `NetworkProbe()` unless a host installed another with
    `set_default_probe()`. THIS IS THE NETWORK I/O THAT HAPPENS AT
    CONSTRUCTION: with the default probe, resolving `auto` opens TCP
    connections to the candidate endpoints before this function returns, and
    the answer therefore depends on what is listening on the machine. Pass
    `NullProbe()` for "never contact anything" or `StaticProbe({...})` for a
    fixed answer, and construction becomes socket-free and identical on every
    machine. The A2 destination guard is applied by `_probe_endpoints` itself,
    before and after the probe runs, so an injected probe cannot widen it.

    `allow_remote` (A2, `embeddings.allow_remote`, default false): permission to
    send memory excerpts to an endpoint that is NOT on this host or its private
    network. With it false — the default — an off-host `base_url` (or
    `$CHRONICLE_EMBED_BASE_URL`) is REFUSED with one WARNING and the result is a
    DegradedEmbedder: no vectors are written, embeds queue, retrieval runs on
    FTS. Nothing is sent. The refusal survives `recheck()`, so the endpoint is
    not adopted later either; fixing it means fixing the config.
    """
    dims = int(dimensions) if dimensions else 768
    allow_remote = bool(allow_remote)
    active_probe = probe if probe is not None else default_probe()
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
        # "Trust" is scoped to REACHABILITY, never to destination (A2): an
        # off-host endpoint is refused here, before the object exists.
        try:
            emb = active_probe.make(base_url, model, dims, api_key=api_key or "",
                                    max_input_tokens=max_tok, overflow=ovf,
                                    task_prefixes=task_prefixes, allow_remote=allow_remote)
        except RemoteEndpointRefused:
            # check_endpoint already logged the one WARNING that explains it.
            # base_url is kept so recheck() keeps refusing the SAME endpoint
            # rather than quietly adopting some other local server instead.
            return DegradedEmbedder(model=name, dimensions=dims, base_url=base_url, api_key=api_key,
                                    max_input_tokens=max_tok, overflow=ovf,
                                    task_prefixes=task_prefixes, allow_remote=allow_remote,
                                    probe=probe)
        try:
            active_probe.healthcheck(emb)  # best-effort: confirm reachable + adopt the real dim
            logger.info("Chronicle embeddings: MODEL mode — %r via %s (dim %d)",
                        model, base_url, emb.dimensions)
        except Exception as e:
            logger.warning("Chronicle embeddings: MODEL mode — %r @ %s unreachable at init (%s: %s); "
                           "keeping it and deferring to the runtime retry (never hashing)",
                           model, base_url, type(e).__name__, e)
        return emb
    report: list = []
    emb = _probe_endpoints(model, dims, base_url, api_key, max_input_tokens=max_tok, overflow=ovf,
                          task_prefixes=task_prefixes, allow_remote=allow_remote,
                          probe=probe, report=report)
    if emb is not None:
        logger.info("Chronicle embeddings: MODEL mode — local %r via %s (dim %d)",
                    emb.model, emb.base_url, emb.dimensions)
        return emb
    considered = _candidate_urls(base_url)
    if not _permitted_urls(base_url, allow_remote):
        # Every candidate was refused as off-host (A2). Say THAT, not
        # "unreachable" -- the endpoint may be perfectly reachable; Chronicle
        # declined to send memory to it.
        reason = "every candidate endpoint refused as off-host (embeddings.allow_remote is false)"
    else:
        reason = "no embedding model reachable" if auto else f"model {model!r} not reachable"
    logger.warning("Chronicle embeddings: DEGRADED mode — %s on %s [%s]. NO vectors are written; "
                   "every embed is queued as a curation job and retried with backoff until a "
                   "server appears. Set embeddings.model (or $CHRONICLE_EMBED_MODEL) to 'hashing' "
                   "for deterministic offline vectors instead",
                   reason, ", ".join(considered), probe_summary(report))
    return DegradedEmbedder(model=name, dimensions=dims, base_url=base_url, api_key=api_key,
                            max_input_tokens=max_tok, overflow=ovf, task_prefixes=task_prefixes,
                            allow_remote=allow_remote, probe=probe, probe_report=report)


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


def quantize_binary(vec: list[float]) -> bytes:
    """Quantize a float vector into a compact binary bitpack.

    Each coordinate becomes a single bit: 1 if > 0.0 else 0.
    1024 floats -> 128 bytes (32x compression).
    """
    if not vec:
        return b""
    byte_list = bytearray((len(vec) + 7) // 8)
    for i, val in enumerate(vec):
        if val > 0.0:
            byte_list[i // 8] |= (1 << (7 - (i % 8)))
    return bytes(byte_list)


_BIT_COUNTS = [bin(i).count("1") for i in range(256)]


def hamming_distance(a: bytes, b: bytes) -> int:
    """Compute Hamming distance between two bitpacked byte strings."""
    if not a or not b or len(a) != len(b):
        return max(len(a), len(b)) * 8
    dist = 0
    for byte_a, byte_b in zip(a, b):
        dist += _BIT_COUNTS[byte_a ^ byte_b]
    return dist


def binary_similarity(a: bytes, b: bytes, total_bits: int) -> float:
    """Normalized Hamming similarity in range [0.0, 1.0]."""
    if not a or not b or total_bits <= 0:
        return 0.0
    dist = hamming_distance(a, b)
    return max(0.0, min(1.0, 1.0 - (dist / float(total_bits))))

# -- wrong-dimension refusal (A0c) -------------------------------------------
#
# THE SILENCE THIS ENDS. Every cosine over a stored blob used to return 0.0 for
# a blob whose byte length did not match the query's dimensionality, and 0.0 is
# below every similarity floor in retrieval, so the row simply never appeared.
# On the live store that was 88% of memory: ~170k vectors written by a 2048-dim
# model, read by a 768-dim one, contributing nothing to the vector channel, with
# no error, no log line, no counter and no degraded-mode signal anywhere. The
# store looked healthy and answered as if that memory did not exist.
#
# A wrong-length blob is still SKIPPED — there is no meaningful cosine between
# two different geometries and inventing one would be worse. What changes is
# that it is skipped LOUDLY: counted process-wide, reported per query, and
# logged once at WARNING so the condition is discoverable from a log tail.
_WRONG_DIM = {"count": 0, "warned": False}


def note_wrong_dim(n: int, where: str = "") -> None:
    """Record `n` wrong-length blobs skipped by a similarity scan.

    Monotone and process-wide. The WARNING fires ONCE per process: this is
    called from inside per-page scan loops, so warning per occurrence would
    emit thousands of lines per query on an affected store and be
    indistinguishable from noise."""
    if n <= 0:
        return
    _WRONG_DIM["count"] += n
    if not _WRONG_DIM["warned"]:
        _WRONG_DIM["warned"] = True
        logger.warning(
            "Chronicle embeddings: %d stored vector(s) skipped as WRONG-DIMENSION during "
            "similarity scoring%s. Those rows are INVISIBLE to the vector channel -- they are "
            "not scored, not ranked, not retrieved. This means part of the store was written by "
            "a different embedding model. Run scripts/migrate_vectors.py to re-embed, or check "
            "health's vectors_wrong_dim counter for the store-wide total. (Logged once per "
            "process; the running total is embeddings.wrong_dim_skipped().)",
            n, (" in " + where) if where else "")


def wrong_dim_skipped() -> int:
    """Process-wide running total of wrong-dimension blobs skipped on read."""
    return _WRONG_DIM["count"]


def reset_wrong_dim_skipped() -> None:
    """Zero the counter and re-arm the one-shot warning (tests / long-lived hosts)."""
    _WRONG_DIM["count"] = 0
    _WRONG_DIM["warned"] = False


def wrong_dim_indices(query_dims: int, blobs) -> list:
    """Indices of blobs that are PRESENT but not `query_dims * 4` bytes.

    An absent/empty blob is "no vector", not a wrong-dimension one, and is
    never reported: callers already treat a missing vector as a non-hit, and
    conflating the two would make the counter meaningless."""
    if not query_dims:
        return []
    want = query_dims * 4
    return [i for i, b in enumerate(blobs) if b and len(b) != want]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine of two same-length pre-normalized vectors; 0.0 otherwise.

    A LENGTH MISMATCH between two present vectors is counted (A0c) before
    returning 0.0 — that case is not "these are dissimilar", it is "these are
    not comparable", and it used to be indistinguishable from the former."""
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        note_wrong_dim(1, "cosine")
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
    idx, mats, skipped = [], [], 0
    for i, b in enumerate(blobs):
        if b and len(b) == d * 4:
            idx.append(i)
            mats.append(b)
        elif b:
            skipped += 1     # A0c: present but incomparable -- never silent
    note_wrong_dim(skipped, "batch_cosine_f64")
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
    (e.g. incomparable hash vectors, or vectors written by a different model)
    are SKIPPED and COUNTED (A0c, `note_wrong_dim`) rather than silently scored
    0.0 -- 0.0 is below every similarity floor in retrieval, so the old
    behavior made those rows invisible with no signal anywhere. Falls back to
    scalar `cosine` if numpy is unavailable, which counts them the same way."""
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
    idx, mats, skipped = [], [], 0
    for i, b in enumerate(blobs):
        if b and len(b) == d * 4:
            idx.append(i)
            mats.append(b)
        elif b:
            skipped += 1     # A0c: present but incomparable -- never silent
    note_wrong_dim(skipped, "batch_cosine")
    if idx:
        M = np.frombuffer(b"".join(mats), dtype=np.float32).reshape(len(idx), d)
        sims = np.clip(M @ q, -1.0, 1.0)
        for j, i in enumerate(idx):
            out[i] = float(sims[j])
    return out
