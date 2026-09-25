"""
Chronicle — passages and containers for federated records.

WHY PASSAGES. A federated source row (a document, a conversation-day, an email)
gets ONE projection vector, embedded from its cached projection and cut at
about a thousand characters. Everything a long record says past that cut is
invisible to the vector channel: a document's third page, the end of a long
day of messages, an email body the card never carried. A PASSAGE is an extra
vector over one slice of the record's full text. It lives in
`projection_vectors` beside the record's own vector, same provider, under

    <record external_id>#p<n>          n = 0, 1, 2, ... (decimal, no padding)

so the existing tier, the float16 cache and every width/model guard see it
with no new table. Retrieval scores passages like any projection row and then
counts a RECORD once, at the score of its best vector (its own or a passage's),
showing that passage's text as the snippet.

WHY THE SPLIT IS A PURE FUNCTION. The passage text is not stored anywhere in
Chronicle. The builder (ops tooling) reads the record's text from the source,
splits it with `split_passages`, and embeds each piece; at query time the
renderer reads the same text and splits it again to show piece n. The two
agree because the split is deterministic in (text, size, max_per_record) and
`SPLIT_VERSION` names the algorithm, which the builder records in its per-record
state so a change to any of those rebuilds the record's passages instead of
leaving n pointing at a different slice.

WHY CONTAINERS. Records can belong to something larger that a source names in
a column: a thread, a folder. Five messages from one thread that all match a
query are one answer, not five. A source that declares a container has its
surviving hits collapsed per container key at query time: the best record is
shown and the rest are counted. The key is looked up FROM THE SOURCE when a
query needs it and is never copied into a record's cached fields -- adding a
column there changes every row's content hash, and the federation sweep then
drops and re-embeds the whole source.

Config lives on a `federation.local_dbs` entry (see engine/config.py):

    passages:  {column: <text column of the same row>}
           or  {from: {path, table, key_column, join_column, text_column}}
               plus optional size / max_per_record (defaults:
               federation.passages.size / federation.passages.max_per_record)
    container: {column: <column holding the container key>, label: <noun>}

`from.join_column` is the column of the SOURCE row whose value equals
`from.key_column` in the other database.

Stdlib only, no package-relative imports: ops tooling imports this module with
the engine directory on sys.path, the plugin imports it as `engine.passages`.
"""

from __future__ import annotations

import hashlib
import re
from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple

# Bump when split_passages would cut any text differently. It is part of the
# recipe the builder records per record, so every record is rebuilt rather
# than having its stored passage n re-derived as a different slice.
SPLIT_VERSION = 1

DEFAULT_SIZE = 900
DEFAULT_MAX_PER_RECORD = 48
# Below this a passage is too short to say anything a sentence embedding can
# place, and a config typo (size: 9) would otherwise mint thousands of vectors.
MIN_SIZE = 200
# Work bound for one split, applied identically by builder and renderer: the
# passages kept can never need more than size * max_per_record characters, and
# a pathological source row (a multi-megabyte blob) must not cost a query that.
_SOURCE_CAP_FACTOR = 4

PASSAGE_MARK = "#p"
# Canonical decimal only (no sign, no leading zero), so an external id and its
# (record, n) pair map one-to-one and the builder's ids are the only ones that
# parse as passages.
_PASSAGE_RE = re.compile(r"#p(0|[1-9][0-9]*)$")


# -- passage ids -------------------------------------------------------------

def passage_external_id(record_external_id: str, n: int) -> str:
    return "%s%s%d" % (record_external_id, PASSAGE_MARK, int(n))


def split_passage_id(external_id) -> Tuple[str, Optional[int]]:
    """(record external_id, n) for a passage id; (external_id, None) otherwise."""
    ext = "" if external_id is None else str(external_id)
    if PASSAGE_MARK not in ext:          # the common case, on the scoring hot path
        return ext, None
    m = _PASSAGE_RE.search(ext)
    if m is None or m.start() == 0:
        return ext, None
    return ext[:m.start()], int(m.group(1))


def is_passage_id(external_id) -> bool:
    return split_passage_id(external_id)[1] is not None


def passage_id_bounds(record_external_id: str) -> Tuple[str, str]:
    """[lo, hi) such that every passage id of the record sorts inside it.

    A binary range, not `LIKE '<ext>#p%'`: LIKE is case-insensitive for ASCII
    in SQLite (it would also match another record whose id differs only in
    case) and cannot use the (provider, external_id) primary key, so every
    drop would scan the provider's whole slice of the table. Callers still
    check the tail is digits (`passage_tail_glob`) -- the range alone also
    holds ids like '<ext>#px'."""
    return record_external_id + PASSAGE_MARK, record_external_id + "#q"


# SQLite GLOB matching a tail that contains a non-digit; `NOT GLOB` it to keep
# canonical passage numbers only.
PASSAGE_TAIL_NON_DIGIT = "*[^0-9]*"

# Deletes one record's passage vectors from projection_vectors. ONE statement
# for the store (a changed source row) and the passage builder (a rebuild), so
# the two can never disagree about which rows are a record's passages.
DELETE_PASSAGES_SQL = (
    "DELETE FROM projection_vectors WHERE provider=? AND external_id>=? "
    "AND external_id<? AND length(external_id)>? AND substr(external_id, ?) NOT GLOB ?")


def delete_passages_params(provider: str, record_external_id: str) -> tuple:
    lo, hi = passage_id_bounds(record_external_id)
    return (provider, lo, hi, len(lo), len(lo) + 1, PASSAGE_TAIL_NON_DIGIT)


# -- the split ---------------------------------------------------------------

# Boundaries in order of preference, each with the separator that rejoins two
# pieces cut at it: paragraphs, then lines (a transcript's natural unit), then
# sentences, then words. A word longer than a passage is cut hard.
_LEVELS = (
    (re.compile(r"\n[ \t]*\n\s*"), "\n\n"),
    (re.compile(r"\n\s*"), "\n"),
    (re.compile(r"(?<=[.!?])\s+"), " "),
    (re.compile(r"\s+"), " "),
)


def normalize_text(text) -> str:
    """The text a split and a text hash are computed over."""
    if text is None:
        return ""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    return str(text).replace("\r\n", "\n").replace("\r", "\n").strip()


def _pieces(text: str, size: int, level: int, sep_before: str, out: list) -> None:
    text = text.strip()
    if not text:
        return
    if len(text) <= size:
        out.append((sep_before, text))
        return
    if level >= len(_LEVELS):
        for i in range(0, len(text), size):
            out.append((sep_before if i == 0 else "", text[i:i + size]))
        return
    pattern, sep = _LEVELS[level]
    parts = [p for p in pattern.split(text) if p.strip()]
    if len(parts) <= 1:
        _pieces(text, size, level + 1, sep_before, out)
        return
    for i, part in enumerate(parts):
        _pieces(part, size, level + 1, sep_before if i == 0 else sep, out)


def split_passages(text, size: int = DEFAULT_SIZE,
                   max_per_record: int = DEFAULT_MAX_PER_RECORD) -> List[str]:
    """The record's text as at most `max_per_record` passages of <= `size` chars.

    Greedy packing of the largest units that fit: whole paragraphs where they
    fit, else lines, else sentences, else words, else a hard cut. Pure and
    deterministic -- see the module docstring for why that is load-bearing.
    Text past the last kept passage is not covered; the cap is a cost bound
    (vectors, embedding time), and 48 x 900 covers the longest documents the
    shipped sources hold."""
    size = max(MIN_SIZE, int(size))
    max_n = max(1, int(max_per_record))
    t = normalize_text(text)[:size * max_n * _SOURCE_CAP_FACTOR]
    if not t:
        return []
    pieces: list = []
    _pieces(t, size, 0, "", pieces)
    out: List[str] = []
    cur = ""
    for sep, piece in pieces:
        if not cur:
            cur = piece
        elif len(cur) + len(sep) + len(piece) <= size:
            cur += sep + piece
        else:
            out.append(cur)
            if len(out) >= max_n:
                return out
            cur = piece
    if cur and len(out) < max_n:
        out.append(cur)
    return out


def text_hash(text) -> str:
    """Digest of the normalized text a record's passages were cut from."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:32]


# -- config ------------------------------------------------------------------

class PassageSpec(NamedTuple):
    """Where one source's record text lives, and how it is cut."""
    provider: str
    table: str
    id_column: str
    column: str             # same-row text column ("" when `from` is used)
    from_path: str
    from_table: str
    key_column: str
    join_column: str
    text_column: str
    size: int
    max_per_record: int

    @property
    def uses_other_db(self) -> bool:
        return not self.column

    def recipe(self, model_tag: str = "") -> str:
        """Everything that decides passage n's text and vector: rebuild on change."""
        return "v%d/%d/%d/%s" % (SPLIT_VERSION, self.size, self.max_per_record, model_tag or "")


class ContainerSpec(NamedTuple):
    column: str
    label: str
    # "" (default) = the container key is an opaque group id (a thread id):
    # records sharing it collapse at query time (_collapse_containers), full
    # stop. A non-empty separator marks the key as a HIERARCHICAL PATH (a
    # folder), which additionally supports matching a query's focus tokens
    # against path SEGMENTS and reading an aggregate card by path prefix
    # (engine/localdb.py LocalDBProvider.folder_card) -- see
    # `folder_matches`/`best_folder_matches` below. Optional and backward
    # compatible: an entry that never sets it (every container declared
    # before F10d) parses exactly as before.
    path_separator: str = ""


def _int_setting(raw, key, fallback) -> int:
    v = raw.get(key)
    if v is None:
        return int(fallback)
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError("passages.%s must be an integer, got %r" % (key, v))


def passage_spec(entry, cfg=None) -> Optional[PassageSpec]:
    """The `passages` block of a `federation.local_dbs` entry, or None.

    Raises ValueError for a block that cannot be executed (both or neither of
    column/from, a missing `from` key, a nonsense size): callers on a read path
    log and ignore the source's passages, the builder reports and skips it."""
    if not isinstance(entry, dict):
        return None
    raw = entry.get("passages")
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("passages must be a mapping, got %r" % type(raw).__name__)
    provider = str(entry.get("name") or "").strip()
    table = str(entry.get("table") or "").strip()
    id_column = str(entry.get("id_column") or "id").strip()
    if not provider or not table:
        raise ValueError("passages need the entry's name and table")
    column = str(raw.get("column") or "").strip()
    frm = raw.get("from")
    if bool(column) == bool(frm):
        raise ValueError("passages need exactly one of `column` or `from`")
    fp = ft = fk = fj = fx = ""
    if frm:
        if not isinstance(frm, dict):
            raise ValueError("passages.from must be a mapping")
        fp, ft, fk, fj, fx = (str(frm.get(k) or "").strip() for k in
                              ("path", "table", "key_column", "join_column", "text_column"))
        missing = [k for k, v in (("path", fp), ("table", ft), ("key_column", fk),
                                  ("join_column", fj), ("text_column", fx)) if not v]
        if missing:
            raise ValueError("passages.from is missing %s" % ", ".join(missing))
    size_default = DEFAULT_SIZE
    max_default = DEFAULT_MAX_PER_RECORD
    if cfg is not None:
        size_default = cfg.get("federation.passages.size", DEFAULT_SIZE) or DEFAULT_SIZE
        max_default = (cfg.get("federation.passages.max_per_record", DEFAULT_MAX_PER_RECORD)
                       or DEFAULT_MAX_PER_RECORD)
    size = _int_setting(raw, "size", size_default)
    max_n = _int_setting(raw, "max_per_record", max_default)
    if size < MIN_SIZE:
        raise ValueError("passages.size %d is below the minimum %d" % (size, MIN_SIZE))
    if max_n < 1:
        raise ValueError("passages.max_per_record must be at least 1")
    return PassageSpec(provider, table, id_column, column, fp, ft, fk, fj, fx, size, max_n)


def container_spec(entry) -> Optional[ContainerSpec]:
    """The `container` block of a `federation.local_dbs` entry, or None."""
    if not isinstance(entry, dict):
        return None
    raw = entry.get("container")
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("container must be a mapping, got %r" % type(raw).__name__)
    column = str(raw.get("column") or "").strip()
    if not column:
        raise ValueError("container needs a column")
    label = str(raw.get("label") or "").strip() or column
    path_separator = str(raw.get("path_separator") or "").strip()
    return ContainerSpec(column, label, path_separator)


# -- folder-shaped containers (F10d) ------------------------------------------
#
# WHY. A container normally groups records that already have their own vector
# (a thread's messages): collapsing them is a query-time JOIN over hits that
# exist. A folder is different -- someone can ask about "the Taxes 2026
# Deductions folder" without any one file in it ever having scored on its own
# projection vector, so there is nothing for `_collapse_containers` to collapse.
# The functions below answer a different question: given the query's own focus
# tokens, does any declared folder path match well enough to answer with an
# aggregate card (path, file count, top file names) instead? Pure and stdlib
# only, like the rest of this module -- the DB read that turns a matched path
# into a card is `LocalDBProvider.folder_card` (engine/localdb.py), which reads
# the source at query time, exactly like a container key lookup (never stored,
# never linked, I20).

_YEAR_TOKEN_RE = re.compile(r"^\d{4}$")


def is_year_token(token) -> bool:
    """True for a bare 4-digit query token ("2026"). Used to tell a year APART
    from an ordinary word: a year token must match a path segment that IS a
    year, not merely contain one (a segment "Form2026" is not the year 2026)."""
    return bool(_YEAR_TOKEN_RE.match(str(token or "")))


def path_segments(path, separator: str) -> List[str]:
    """`path` split on `separator`, empty pieces dropped (a leading/trailing/
    doubled separator never produces a phantom segment)."""
    if not path or not separator:
        return []
    return [s for s in str(path).split(separator) if s]


def segment_matches(token, segment: str) -> bool:
    """Whether one focus token matches one path segment, case-insensitively.

    A year token must equal the segment exactly -- see `is_year_token`. Any
    other token matches as a substring, the same generosity `LocalDBProvider`
    search already gives a text column, so "tax" reaches a "Taxes" segment."""
    tok, seg = str(token).lower(), str(segment).lower()
    if is_year_token(token):
        return seg == tok
    return tok in seg


def folder_matches(path, tokens, separator: str) -> bool:
    """True iff EVERY token in `tokens` matches some segment of `path`.

    All-or-nothing by design: a folder card is a strong, specific claim ("this
    is the folder you meant"), so a query that names something the path does
    not have (an extra word, a different year) must not match it partially."""
    segs = path_segments(path, separator)
    toks = [t for t in (tokens or []) if t]
    if not segs or not toks:
        return False
    return all(any(segment_matches(t, s) for s in segs) for t in toks)


def best_folder_matches(paths: Iterable[str], tokens, separator: str) -> List[str]:
    """The declared folder paths worth a card for this query: every path that
    `folder_matches`, with a path dropped when another surviving (necessarily
    shorter-or-equal) path is its ancestor.

    A folder card is read BY PREFIX (`LocalDBProvider.folder_card`), so a
    matched ancestor's card already counts every file under a matched
    descendant -- keeping both would show the same files twice, once under
    each path. Deterministic: shallowest path first, then lexicographic, so
    the same input always picks the same survivors."""
    toks = [t for t in (tokens or []) if t]
    if not toks or not separator:
        return []
    matched = sorted({p for p in (paths or []) if p and folder_matches(p, toks, separator)},
                     key=lambda p: (p.count(separator), p))
    kept: List[str] = []
    for p in matched:
        if not any(p == a or p.startswith(a + separator) for a in kept):
            kept.append(p)
    return kept


# -- reading record text -----------------------------------------------------

# lookup(where, table, key_column, keys, columns) -> {str(key): {column: value}}
# `where` is "source" (the entry's own database) or "from" (passages.from.path).
Lookup = Callable[[str, str, str, List, List[str]], Dict[str, Dict]]


def fetch_passage_texts(spec: PassageSpec, source_ids: Iterable, lookup: Lookup) -> Dict[str, str]:
    """{str(source row id): text} for the records whose passage text exists.

    ONE definition of "the text a record's passages are cut from", used by the
    builder and by the renderer, so both read the same bytes. Keys are compared
    as strings because a row id reaches here from JSON (an int) and from the
    source (whatever the column's affinity returns)."""
    ids = []
    seen = set()
    for sid in source_ids:
        if sid is None or str(sid) in seen:
            continue
        seen.add(str(sid))
        ids.append(sid)
    if not ids:
        return {}
    if spec.column:
        rows = lookup("source", spec.table, spec.id_column, ids, [spec.column]) or {}
        return {k: r[spec.column] for k, r in rows.items()
                if r.get(spec.column) not in (None, "")}
    joins = lookup("source", spec.table, spec.id_column, ids, [spec.join_column]) or {}
    join_of = {k: r[spec.join_column] for k, r in joins.items()
               if r.get(spec.join_column) not in (None, "")}
    if not join_of:
        return {}
    keys = []
    kseen = set()
    for v in join_of.values():
        if str(v) not in kseen:
            kseen.add(str(v))
            keys.append(v)
    texts = lookup("from", spec.from_table, spec.key_column, keys, [spec.text_column]) or {}
    out = {}
    for k, v in join_of.items():
        row = texts.get(str(v))
        if row and row.get(spec.text_column) not in (None, ""):
            out[k] = row[spec.text_column]
    return out
