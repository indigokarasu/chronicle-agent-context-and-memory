"""
Chronicle — who said it.

Memory about the user may only come from the user. Everything else in a
transcript (the assistant's replies, tool output, scheduled-job prompts, the
host's own control frames, and Chronicle's recalled context fed back into the
prompt) belongs to the agent's side of the record: it stays captured and
searchable, and is never promoted into facts, preferences or standing
instructions about the user.

Before this module the rule was "a line is the user's unless it starts with
`Assistant:`", which failed on a production store in every direction at once:

  * 98% of captured turns (40,841 of 41,492) came from cron sessions, whose
    `user` message is the job's own prompt;
  * `tool:` lines were not a role, so tool output inherited whoever spoke last,
    and a continuation chunk with no prefix was the user by default;
  * Hermes writes control frames as `role: user` rows: compaction handoffs,
    "[System note: ...]", background-process notifications, the Telegram origin
    header, and the `<memory-context>` block holding Chronicle's own recall;
  * compression rescue and context eviction stored message text with no role.

The result was 30,018 active always-injected "directive" notes, and facts such
as the user's name being the agent's own name, all extracted from text the user
never wrote.

The attribution is decided once, at capture, from what the host actually knows
(`agent_context`, `platform`, the turn author, each message's role) and stored
on the event as `speakers`: contiguous `[start, end, speaker]` spans over the
excerpt. Extraction reads the spans, so no later reader re-guesses from line
prefixes, which tool output can forge. Events written before this change carry
no spans and fall back to `legacy_lines`, which never defaults to the user.
"""

from __future__ import annotations

import re

HUMAN = "human"            # the user, typing
AUTOMATION = "automation"  # a scheduled job, a bot, a subagent brief: the user side, not the user
ASSISTANT = "assistant"
TOOL = "tool"
SYSTEM = "system"          # host framing, labels, recalled context
UNKNOWN = "unknown"

SPEAKERS = frozenset({HUMAN, AUTOMATION, ASSISTANT, TOOL, SYSTEM, UNKNOWN})

# Hermes passes agent_context "primary" | "subagent" | "cron" | "flush" to
# MemoryProvider.initialize, and its contract says non-primary contexts must not
# write user memory. Cron agents have also been initialised as "primary" with
# platform "cron", and older hosts pass neither, so the platform and the session
# id are checked too.
_AUTOMATION_PLATFORMS = frozenset({"cron", "batch", "curator", "flush", "subagent",
                                   "background_review"})
AUTOMATION_SESSION_PREFIXES = ("cron_",)

_ROLE_SPEAKER = {"assistant": ASSISTANT, "tool": TOOL, "function": TOOL,
                 "system": SYSTEM, "developer": SYSTEM, "automation": AUTOMATION}

# Source types whose events carry no role information but are, by construction,
# typed by the user. Everything else without spans has no human speaker.
_HUMAN_SOURCE_TYPES = frozenset({"user_direct"})


def is_automation_session(session_id) -> bool:
    return str(session_id or "").startswith(AUTOMATION_SESSION_PREFIXES)


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def user_side(*, agent_context="", platform="", session_id="", author=None) -> str:
    """Who is behind a `user` message in this context: HUMAN or AUTOMATION.

    A host that says nothing (tests, benchmarks, older hosts) gets HUMAN; any
    positive sign of automation wins."""
    ctx = str(agent_context or "").strip().lower()
    if ctx and ctx != "primary":
        return AUTOMATION
    if str(platform or "").strip().lower() in _AUTOMATION_PLATFORMS:
        return AUTOMATION
    if is_automation_session(session_id):
        return AUTOMATION
    if isinstance(author, dict) and _truthy(author.get("is_bot")):
        return AUTOMATION
    return HUMAN


def role_speaker(role, side: str) -> str:
    r = str(role or "").strip().lower()
    if r == "user":
        return side
    return _ROLE_SPEAKER.get(r, UNKNOWN)


def role_label(role, side: str) -> str:
    """The label an excerpt line carries. A `user` row the user did not write is
    labelled `automation`, so the raw recall text does not claim otherwise."""
    r = str(role if role is not None else "?")
    if r.strip().lower() == "user" and side != HUMAN:
        return "Automation" if r.strip()[:1].isupper() else "automation"
    return r


# -- host framing inside a `user` message -----------------------------------
#
# The markers are Hermes' own (agent/prompt_builder.CONTROL_FRAME_OPENERS,
# agent/context_compressor._SYNTHETIC_USER_ROW_PREFIXES, agent/title_generator.
# _MACHINE_PREFIXES, agent/memory_manager.build_memory_context_block, the
# gateway's origin header). A message that OPENS with one is machine-written
# end to end. The steer wrapper is the exception: it wraps the user's own words.
# The host also merges queued rows into one message, so a frame can start at any
# line ("Proceed\n\nContinue\n\n[System note: ...]"): a short note runs to the
# `]` that ends a line, a long machine block (a background-process result, a
# compaction handoff) to the end of the message.

_WHOLE_MESSAGE_FRAMES = (
    "[System:", "[System note:", "[SYSTEM]", "[CONTEXT", "[PRIOR CONTEXT", "[IMPORTANT:",
    "[Runtime note:", "[Your active task list", "[Planning state preserved",
    "[ASYNC DELEGATION", "Cronjob Response:",
)

_INLINE_FRAMES = re.compile(
    r"^\[(?:System note:|System:|Runtime note:|SYSTEM\]).*?(?:\][ \t]*(?=\n|\Z)|\Z)"
    r"|^(?:\[(?:IMPORTANT:|CONTEXT COMPACTION|CONTEXT SUMMARY\]|PRIOR CONTEXT|Your active task list"
    r"|Planning state preserved|ASYNC DELEGATION)|Cronjob Response:).*\Z"
    r"|<memory-context>.*?(?:</memory-context>|\Z)"
    r"|<(system-reminder|command-message|command-name|command-args|local-command-caveat"
    r"|local-command-stderr|local-command-stdout|task-notification|ide_opened_file"
    r"|ide_selection)>.*?(?:</\1>|\Z)"
    r"|\[/?OUT-OF-BAND USER MESSAGE[^\]\n]*\]"
    r"|Gateway message origin \(JSON data[^\n]*(?:\n\{[^\n]*\})?"
    r"(?:\n+Do not guess a reply destination[^\n]*)?",
    re.DOTALL | re.IGNORECASE | re.MULTILINE)


def split_user_content(content: str, side: str) -> list:
    """`[(start, end, speaker)]` covering `content`: host framing is SYSTEM, the
    rest is `side`. Contiguous, in order, adjacent equal speakers merged."""
    text = content or ""
    if not text:
        return []
    if text.lstrip().startswith(_WHOLE_MESSAGE_FRAMES):
        return [(0, len(text), SYSTEM)]
    spans, pos = [], 0
    for m in _INLINE_FRAMES.finditer(text):
        if m.start() > pos:
            spans.append((pos, m.start(), side))
        spans.append((m.start(), m.end(), SYSTEM))
        pos = m.end()
    if pos < len(text):
        spans.append((pos, len(text), side))
    # Whitespace between frames is nobody's words.
    spans = [(a, b, SYSTEM if who == side and not text[a:b].strip() else who)
             for a, b, who in spans]
    return merge_spans(spans)


def merge_spans(spans) -> list:
    out: list = []
    for a, b, who in spans:
        if b <= a:
            continue
        if out and out[-1][2] == who and out[-1][1] == a:
            out[-1] = (out[-1][0], b, who)
        else:
            out.append((a, b, who))
    return out


_PART_MARKERS = {"image_url": "[image]", "image": "[image]", "input_image": "[image]",
                 "input_audio": "[audio]", "audio": "[audio]", "file": "[file]",
                 "input_file": "[file]"}


def message_text(content) -> str:
    """The TEXT of a message's content, whatever shape the host sent.

    A string comes back unchanged. A list of parts — how a vision-capable host
    sends a photo with its caption — becomes its text parts, with a marker such
    as `[image]` for each non-text part, and never the part itself. The capture
    path used to render such a message as the Python repr of the list, which
    wrote the full base64 of every photo into the event log (megabytes per
    picture, full-text indexed and queued for embedding), and the context
    engine called `.strip()`/`.lower()` on it and crashed compaction outright."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        content = [content]
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    out.append(part["text"])
                else:
                    out.append(_PART_MARKERS.get(str(part.get("type") or ""), "[attachment]"))
        return "\n".join(x for x in out if x)
    return str(content)


def render_messages(messages, side: str) -> tuple:
    """`(excerpt, spans)` for a message list.

    The excerpt is byte-identical to the pre-attribution format
    (`"role: content"` lines joined by newlines) except that a `user` row the
    user did not write is labelled `automation`. A label belongs to its
    message's first span and a separator to the message before it, so spans
    stay one per message in the common case."""
    parts, spans, pos = [], [], 0
    for i, m in enumerate(messages):
        if i:
            parts.append("\n")
            spans.append((pos, pos + 1, spans[-1][2] if spans else SYSTEM))
            pos += 1
        role = m.get("role", "?")
        raw = m.get('content', '')
        # Byte-identical for a string or None (existing event ids depend on
        # it); a parts list is rendered as text, never as its repr.
        content = message_text(raw) if isinstance(raw, (list, dict)) else f"{raw}"
        label = f"{role_label(role, side)}: "
        who = role_speaker(role, side)
        if who in (HUMAN, AUTOMATION):
            inner = split_user_content(content, who)
        else:
            inner = [(0, len(content), who)] if content else []
        first = inner[0][2] if inner else who
        spans.append((pos, pos + len(label), first))
        body_at = pos + len(label)
        spans.extend((body_at + a, body_at + b, w) for a, b, w in inner)
        parts.append(label + content)
        pos = body_at + len(content)
    return "".join(parts), merge_spans(spans)


def chunk_spans(spans, chunks) -> list:
    """Per-chunk span lists, offsets relative to each chunk (chunks are a
    lossless split of the excerpt the spans cover)."""
    out, base = [], 0
    for chunk in chunks:
        end = base + len(chunk)
        mine = [(max(a, base) - base, min(b, end) - base, who)
                for a, b, who in spans if a < end and b > base]
        out.append([list(s) for s in merge_spans(mine)])
        base = end
    return out


def _valid_spans(spans, n) -> bool:
    if not isinstance(spans, list) or not spans:
        return False
    pos = 0
    for s in spans:
        if not (isinstance(s, (list, tuple)) and len(s) == 3):
            return False
        a, b, who = s
        if not (isinstance(a, int) and isinstance(b, int)) or a != pos or b <= a or who not in SPEAKERS:
            return False
        pos = b
    return pos == n


_LABEL = re.compile(r"^(user|assistant|tool|function|system|developer|automation):[ \t]?",
                    re.IGNORECASE)


def lines_from_spans(excerpt, spans) -> list:
    out = []
    for a, b, who in spans:
        for piece in excerpt[a:b].split("\n"):
            piece = _LABEL.sub("", piece, count=1)
            if piece.strip():
                out.append((piece, who))
    return out


def parse_labeled(excerpt: str, side: str, lead: str) -> list:
    """`[(line, speaker)]` for an excerpt with no stored spans.

    A `role:` label starts a message; unlabelled lines belong to the message
    above them, and lines before any label to `lead`. User messages are split
    into host framing and `side`."""
    out: list = []
    msg_role, buf = None, []

    def flush():
        if not buf:
            return
        body = "\n".join(buf)
        if msg_role is None:
            who = lead
        else:
            who = role_speaker(msg_role, side)
        if who in (HUMAN, AUTOMATION):
            for a, b, w in split_user_content(body, who):
                out.extend((p, w) for p in body[a:b].split("\n") if p.strip())
        else:
            out.extend((p, who) for p in buf if p.strip())

    for line in (excerpt or "").split("\n"):
        m = _LABEL.match(line)
        if m:
            flush()
            msg_role, buf = m.group(1), [line[m.end():]]
        else:
            buf.append(line)
    flush()
    return out


def attribute_lines(payload: dict, *, session_id="", actor="") -> list:
    """`[(line, speaker)]` for an observed event: its stored spans, or the
    legacy reading for events written before spans existed."""
    payload = payload or {}
    excerpt = payload.get("excerpt") or ""
    spans = payload.get("speakers")
    if _valid_spans(spans, len(excerpt)):
        return lines_from_spans(excerpt, spans)
    return legacy_lines(excerpt, source_type=payload.get("source_type") or "",
                        session_id=session_id, actor=actor,
                        chunk_index=payload.get("chunk_index") or 0)


def legacy_lines(excerpt, *, source_type="", session_id="", actor="", chunk_index=0) -> list:
    """Attribution for an event with no stored spans. Never guesses the user.

    * session transcripts: labels are read; a cron session's `user` rows are
      automation; lines before the first label (a continuation chunk) unknown;
    * context evictions stored one message and its role as the actor;
    * rescue text and every other source carry no role: unknown, unless the
      source type is itself user-typed;
    * an event with no source type at all is an API caller's, and its actor is
      the only claim it makes. (Chronicle's own writers always set a source
      type; the production transcripts whose actor was `user` for a cron
      prompt are read by their labels and session above, not by this rule.)"""
    side = AUTOMATION if is_automation_session(session_id) else HUMAN
    if not source_type:
        who = side if actor == "user" else UNKNOWN
        return [(ln, who) for ln in (excerpt or "").split("\n") if ln.strip()]
    if source_type == "session_transcript":
        return parse_labeled(excerpt, side, UNKNOWN)
    if source_type in _HUMAN_SOURCE_TYPES:
        return [(ln, HUMAN) for ln in (excerpt or "").split("\n") if ln.strip()]
    if source_type == "context_eviction":
        who = role_speaker("user" if actor == "user" else
                           ("assistant" if actor == "agent" else "system"), side)
        if who in (HUMAN, AUTOMATION):
            text = excerpt or ""
            return [(p, w) for a, b, w in split_user_content(text, who)
                    for p in text[a:b].split("\n") if p.strip()]
        return [(ln, who) for ln in (excerpt or "").split("\n") if ln.strip()]
    return [(ln, UNKNOWN) for ln in (excerpt or "").split("\n") if ln.strip()]


def has_human(lines) -> bool:
    return any(who == HUMAN for _, who in lines)


def human_text(lines) -> str:
    return "\n".join(text for text, who in lines if who == HUMAN)
