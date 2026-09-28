"""Descriptive interaction-pattern mining for relationship learning.

This module intentionally stops at evidence-backed description. It does not
produce behavioral policy, persona changes, or agent identity claims. Those
belong to a downstream relationship-learning/dreaming layer.

The miner reads Chronicle's immutable observed events, keeps only human-authored
text using the same speaker attribution rules as retrieval, and emits bounded
pattern summaries with event ids as provenance.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any

from .speaker import attribute_lines, human_text


def _normalize(text: str) -> str:
    """Case-fold text into a space-delimited form for literal phrase matching."""
    cleaned = "".join(
        ch if ch.isalnum() or ch == "'" else " "
        for ch in str(text or "").casefold()
    )
    return " ".join(cleaned.split())


_RAW_RULES: dict[str, tuple[tuple[str, ...], str]] = {
    "correction": (
        (
            "that's wrong",
            "that is wrong",
            "incorrect",
            "you missed",
            "you omitted",
            "not what i asked",
            "i already said",
            "i told you",
            "i said no",
            "i said not",
            "i said don't",
            "i said do not",
        ),
        "User messages contain repeated direct corrections of the assistant.",
    ),
    "brevity": (
        (
            "brief",
            "briefly",
            "concise",
            "shorter",
            "too long",
            "too verbose",
            "answer first",
            "just answer",
        ),
        "User messages repeatedly request less setup, shorter responses, or answer-first sequencing.",
    ),
    "detail": (
        (
            "more detail",
            "more detailed",
            "excruciating detail",
            "full detail",
            "don't omit",
            "do not omit",
            "complete version",
            "everything",
        ),
        "User messages repeatedly request more complete or detailed treatment in applicable tasks.",
    ),
    "initiative": (
        (
            "just do it",
            "proceed",
            "go ahead",
            "stop asking",
            "don't ask",
            "do not ask",
            "obvious next step",
        ),
        "User messages repeatedly reject unnecessary confirmation and request proceeding with obvious next steps.",
    ),
    "fidelity": (
        (
            "exact",
            "exactly",
            "do not alter",
            "don't alter",
            "don't change",
            "do not change",
            "missing",
            "omitted",
            "left out",
        ),
        "User messages repeatedly correct omissions or unwanted changes to requested details.",
    ),
    "verification": (
        (
            "check again",
            "verify",
            "look at the",
            "inspect the",
            "review the actual",
            "actual code",
            "actual repo",
            "source material",
            "check the source",
            "check the repo",
            "check the code",
        ),
        "User messages repeatedly request checking source material or verifying claims before concluding.",
    ),
}

_RULES = {
    category: (tuple(_normalize(p) for p in phrases), summary)
    for category, (phrases, summary) in _RAW_RULES.items()
}


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("payload")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _matches(normalized_text: str, phrases: tuple[str, ...]) -> bool:
    padded = f" {normalized_text} "
    return any(f" {phrase} " in padded for phrase in phrases)


class InteractionPatternMiner:
    """Mine recurrent, descriptive interaction signals from Chronicle events."""

    def __init__(self, store):
        self.store = store

    def _observed_rows(self, since_seq: int, limit: int) -> list[dict[str, Any]]:
        if hasattr(self.store, "iter_events_since"):
            rows = deque(maxlen=limit if limit > 0 else None)
            for row in self.store.iter_events_since(since_seq):
                if row.get("type") == "observed":
                    rows.append(row)
            return list(rows)

        rows = self.store.get_events_by_type("observed", since_seq)
        return rows[-limit:] if limit > 0 and len(rows) > limit else rows

    @staticmethod
    def _human_text(row: dict[str, Any]) -> str:
        if row.get("actor") != "user":
            return ""
        payload = _payload(row)
        lines = attribute_lines(
            payload,
            session_id=str(row.get("session_id") or ""),
            actor=str(row.get("actor") or ""),
        )
        return human_text(lines).strip()

    @staticmethod
    def _turn_key(row: dict[str, Any]) -> tuple[str, str]:
        event_id = str(row.get("event_id") or "")
        return (
            str(row.get("session_id") or ""),
            str(row.get("occurred_at") or event_id),
        )

    @staticmethod
    def _new_bucket(category: str, summary: str) -> dict[str, Any]:
        return {
            "category": category,
            "summary": summary,
            "event_ids": [],
            "session_ids": set(),
            "turn_keys": set(),
            "last_seq": 0,
        }

    @staticmethod
    def _record(bucket: dict[str, Any], row: dict[str, Any]) -> None:
        turn_key = InteractionPatternMiner._turn_key(row)
        if turn_key in bucket["turn_keys"]:
            return
        bucket["turn_keys"].add(turn_key)

        event_id = str(row.get("event_id") or "")
        session_id = str(row.get("session_id") or "")
        if event_id:
            bucket["event_ids"].append(event_id)
        if session_id:
            bucket["session_ids"].add(session_id)
        bucket["last_seq"] = max(int(row.get("seq") or 0), bucket["last_seq"])

    @staticmethod
    def _emit(bucket: dict[str, Any], min_support: int) -> dict[str, Any] | None:
        support = len(bucket["event_ids"])
        if support < min_support:
            return None
        sessions = len(bucket["session_ids"])
        confidence = min(0.95, 0.50 + (0.08 * support) + (0.03 * sessions))
        return {
            "pattern_id": f"ipat_{bucket['category']}",
            "category": bucket["category"],
            "summary": bucket["summary"],
            "support": support,
            "distinct_sessions": sessions,
            "confidence": round(confidence, 3),
            "event_ids": list(bucket["event_ids"]),
            "last_seq": bucket["last_seq"],
            "scope": "descriptive_only",
        }

    def mine(
        self,
        *,
        since_seq: int = 0,
        limit: int = 5000,
        min_support: int = 2,
    ) -> list[dict[str, Any]]:
        """Return recurrent human interaction signals with source event ids."""
        if min_support < 1:
            raise ValueError("min_support must be >= 1")

        buckets: dict[str, dict[str, Any]] = {}
        for row in self._observed_rows(since_seq, limit):
            text = _normalize(self._human_text(row))
            if not text:
                continue
            for category, (phrases, summary) in _RULES.items():
                if not _matches(text, phrases):
                    continue
                bucket = buckets.setdefault(
                    category, self._new_bucket(category, summary)
                )
                self._record(bucket, row)

        emitted = (
            self._emit(buckets[category], min_support)
            for category in sorted(buckets)
        )
        return [pattern for pattern in emitted if pattern is not None]
