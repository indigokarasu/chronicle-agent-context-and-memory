# What goes into a turn unasked

The memory provider's per-turn recall is memory about the user and about the
message just sent: an item must share a content word with it — as written or
inflected (book/booked, city/cities), not merely as a prefix — and a message
with more than three content words needs two of them in an item. A shorter
message's single shared word is often a coincidence ("system health check" and
a prescription's `health_event`), so such a match must also be near the
message in meaning: the item's stored vector against the message's (a short
item with none is embedded on the spot, a few per turn, within a second and a
half of quick requests to the embedder), at or above
`retrieval.prefetch_min_similarity` (measured per model, 0.65 for
nomic-embed-text); a match nothing can vouch for,
with the embedder busy or down, is left out. Two or three shared words get the
same check at their own floor (0.60), and there the words decide when there is
no vector to compare. The gate reads only the person's words, not the host's
framing around them. Only the user's own words in a past exchange are asked;
URLs, short numbers, host framing, tool output and the agent's own memory
writes never count. A scheduled job's turn gets none
(`retrieval.prefetch_automation`). Nor does it repeat the conversation in
progress: the live session's turns are already in the model's window, so only
what a compaction folded out of it can come back. A credential's value (a
password, API key or token the user handed the agent) is never injected, and
never stored in a belief: the fold masks it, and only the transcript keeps it.
Explicit search, `chronicle_answer` and the context engine's recall are not
gated.
