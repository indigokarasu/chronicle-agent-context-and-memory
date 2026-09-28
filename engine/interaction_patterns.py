"""Descriptive interaction-pattern mining for relationship learning.

This module intentionally stops at evidence-backed description.  It does not
produce behavioral policy, persona changes, or agent identity claims.  Those
belong to a downstream relationship-learning/dreaming layer.

The miner reads Chronicle's immutable observed events, keeps only human-authored
text using the same speaker attribution rules as retrieval, and emits bounded
pattern summaries with event ids as provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from typing import Any

from .speaker import attribute_lines, human_text


_RULES: dict[str, tuple[tuple[re.Pattern[str], ...], str]] = {
    "correction": (
        (
            re.compile(r"\b(?:that's wrong|that is wrong|incorrect|you missed|you omitted|not what i asked)\b", re.I),
            re.compile(r"\b(?:i already said|i told you|i said (?:no|not|don't|do not))\b", re.I),
        ),
        "User messages contain repeated direct corrections of the assistant.",
    ),
    "brevity": (
        (
            re.compile(r"\b(?:brief|briefly|concise|shorter|too long|too verbose|answer first|just answer)\b", re.I),
        ),
        "User messages repeatedly request less setup, shorter responses, or answer-first sequencing.",
    ),
    "detail": (
        (
            re.compile(r"\b(?:more detail|more detailed|excruciating detail|full detail|don't omit|do not omit|complete version|everything)\b", re.I),
        ),
        "User messages repeatedly request more complete or detailed treatment in applicable tasks.",
    ),
    "initiative": (
        (
            re.compile(r"\b(?:just do it|proceed|go ahead|stop asking|don't ask|do not ask|obvious next step)\b", re.I),
        ),
        "User messages repeatedly reject unnecessary confirmation and request proceeding with obvious next steps.",
    ),
    "fidelity": (
        (
            re.compile(r"\b(?:exact|exactly|do not alter|don't alter|don't change|do not change|missing|omitted|left out)\b", re.I),
        ),
        "User messages repeatedly correct omissions or unwanted changes to requested details.",
    ),
    "verification": (
        (
            re.compile(r"\b(?:check again|verify|look at the|inspect the|review the actual|actual (?:code|repo)|source material|check the (?:source|repo|code))\b", re.I),
        ),
        "User messages repeatedly request checking source material or verifying claims before concluding.",
    ),
}


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("payload")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


class InteractionPatternMiner:
    """Mine recurrent, descriptive interaction signals from Chronicle events.

    Output is deliberately policy-free.  A downstream relationship learner may
    interpret these observations, but Chronicle only reports what recurred and
    where the supporting evidence lives.
    """

    def __init__(self, store):
        self.store = store

    def mine(
        self,
        *,
        since_seq: int = 0,
        limit: int = 5000,
        min_support: int = 2,
    ) -> list[dict[str, Any]]:
        if min_support < 1:
            raise ValueError("min_support must be >= 1")

        if hasattr(self.store, "iter_events_since"):
            # Chronicle stores can contain hundreds of thousands of events.
            # Keep memory bounded while retaining the latest observed events.
            rows_q = deque(maxlen=limit if limit > 0 else None)
            for row in self.store.iter_events_since(since_seq):
                if row.get("type") == "observed":
                    rows_q.append(row)
            rows = list(rows_q)
        else:
            # Small test/fallback stores may only implement this older helper.
            rows = self.store.get_events_by_type("observed", since_seq)
            if limit > 0 and len(rows) > limit:
                rows = rows[-limit:]

        buckets: dict[str, dict[str, Any]] = {}
        for row in rows:
            # Chronicle capture records automation/system user-side turns with a
            # non-user actor.  Never train a user model from those events.
            if row.get("actor") != "user":
                continue

            payload = _payload(row)
            lines = attribute_lines(
                payload,
                session_id=str(row.get("session_id") or ""),
                actor=str(row.get("actor") or ""),
            )
            text = human_text(lines).strip()
            if not text:
                continue

            for category, (patterns, summary) in _RULES.items():
                if not any(pattern.search(text) for pattern in patterns):
                    continue
                bucket = buckets.setdefault(
                    category,
                    {
                        "category": category,
                        "summary": summary,
                        "event_ids": [],
                        "session_ids": set(),
                        "turn_keys": set(),
                        "last_seq": 0,
                    },
                )
                event_id = str(row.get("event_id") or "")
                session_id = str(row.get("session_id") or "")
                # A long turn may be stored as several chunk events with one
                # occurred_at timestamp. Count that turn once per category.
                turn_key = (
                    session_id,
                    str(row.get("occurred_at") or event_id),
                )
                if turn_key in bucket["turn_keys"]:
                    continue
                bucket["turn_keys"].add(turn_key)
                if event_id:
                    bucket["event_ids"].append(event_id)
                if session_id:
                    bucket["session_ids"].add(session_id)
                bucket["last_seq"] = max(int(row.get("seq") or 0), bucket["last_seq"])

        out: list[dict[str, Any]] = []
        for category in sorted(buckets):
            bucket = buckets[category]
            support = len(bucket["event_ids"])
            if support < min_support:
                continue
            sessions = len(bucket["session_ids"])
            confidence = min(0.95, 0.50 + (0.08 * support) + (0.03 * sessions))
            stable = hashlib.sha256(category.encode("utf-8")).hexdigest()[:12]
            out.append(
                {
                    "pattern_id": f"ipat_{stable}",
                    "category": category,
                    "summary": bucket["summary"],
                    "support": support,
                    "distinct_sessions": sessions,
                    "confidence": round(confidence, 3),
                    "event_ids": list(bucket["event_ids"]),
                    "last_seq": bucket["last_seq"],
                    "scope": "descriptive_only",
                }
            )
        return out
