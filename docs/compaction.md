# Compaction

When the context engine is selected, Hermes hands it compaction: it calls the engine's `compress()` and `prune_tool_results_only()` itself (the memory provider's `on_pre_compress` then returns nothing, so nothing is summarised twice). The memory provider hooks into `on_session_end`, `on_turn_start`, `on_delegation`, and `on_memory_write`.

## How a compaction works

- **It follows your `compression:` settings.** Hermes does not pass its policy
  to a plugin engine, so Chronicle reads it: it compacts at `threshold` of the
  window, down to twice `threshold × target_ratio`, keeps `protect_first_n`
  and `protect_last_n` messages, and also folds down to half of
  `hygiene_hard_message_limit` when the gateway compacts on message count.
  Explicit `context_engine.high_watermark_percent` / `low_watermark_percent`
  still win.
- **What it keeps.** The protected head and tail, the user's newest request
  (even behind a long tool loop), pinned spans and the user's own
  "never/always/must" instructions, then the best-scoring older turns that fit.
  A tool call and its results are kept or folded together, never split. When
  even the protected spans do not fit, the newest turn wins, then the user's
  newest request, then the rest of the tail newest first; a turn's stale
  recall block (Hermes' `api_content` sidecar) goes before the user's words,
  and a span shortened to fit says how to restore it.
- **What it leaves in their place.** One message where the folded turns were,
  in a conversation role (a mid-conversation `system` message would become
  the system prompt on Anthropic's API):
  `[CONTEXT COMPACTION — REFERENCE ONLY] Chronicle folded …`, listing the
  user's folded requests verbatim, one line per folded tool step (the command
  and its output or error), facts stated in them, memory recalled for a focus
  (or passed by Hermes as `memory_context`), and the ids of anything there was
  no room to show.
- **Nothing is lost.** Every folded message is archived first;
  `chronicle_expand(span_id)` restores it byte for byte.
- **Cache-friendly.** A pass extends the settled prefix byte for byte while it
  is small; once it is most of the budget, the next pass rebases into one
  consolidated handoff (one cache break, as Hermes' own compressor pays).
- **Inspectable.** `chronicle_context_status` reports the policy in force, the
  passes so far and what the handoff carries; each pass logs one
  `chronicle compaction:` line.

## Tools

The context engine adds these tools to the agent:

- **chronicle_pin_context**: Pin a context span so compression never evicts it
- **chronicle_focus**: Set the focus topic for memory-aware compression

- **chronicle_expand**: Restore a folded span byte for byte
- **chronicle_context_status**: Report the policy in force, the passes so far and what the handoff carries
