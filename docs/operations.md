# Operations

## Installation

```bash
hermes plugins install indigokarasu/chronicle-agent-context-and-memory
```

Requires Hermes Agent with plugin support. Python 3.9+.

Chronicle needs no extra Python packages: vector search uses an in-memory cache over the stored vectors. On package-managed Hermes installs, never pip-install into Hermes' environments, because Hermes' package manager owns them. If sqlite-vec was installed for an earlier version, it can be uninstalled.

To install into a named profile, and for the config that goes with it, see
[Configuration](configuration.md#example-two-bot-multi-bot-chat).

## Embeddings and graceful degradation

Embeddings default to `auto`: Chronicle checks local OpenAI-compatible servers
(LM Studio on `:1234`, Ollama on `:11434`, and llama.cpp on `:8080`) and uses the
model they serve. If none is reachable, vector work is queued while full-text
retrieval remains active. Set `model: hashing` or
`CHRONICLE_EMBED_MODEL=hashing` to deliberately choose the offline embedder.

Requires Python 3.9 or newer. The optional `blake3` package enables BLAKE3
content addressing; otherwise Chronicle uses BLAKE2b-256.

## Check that it works

None of these checks needs the `sqlite3` command-line tool.

### Where the store is and what is in it

```bash
python3 <profile home>/plugins/chronicle/scripts/recall_check.py --profile <name>
```

For a named profile, `<profile home>` is `~/.hermes/profiles/<name>`. For the default profile, use `~/.hermes` and `--profile default`.

The check reads the profile's `config.yaml`, resolves the store the way Chronicle does, and opens the store read-only. It prints `key: value` lines: the Hermes home and profile, the config file it read, the store path from the config and the path Chronicle resolves, the git mirror, and the number of events, active beliefs and stored vectors, with the time of the last event. The last line is `PASS` when the store holds events, or `FAIL:` with the reason. The exit code is 0 for PASS and 1 for FAIL. It creates no files. `--json` prints the same values as one JSON object.

### Does Chronicle recall a fact by itself

```bash
python3 <profile home>/plugins/chronicle/scripts/recall_check.py --canary
```

`--canary` works in a temporary Hermes home, so your own home is not read or written. It captures a made-up fact in one session, closes the store, starts a new session on the reopened store, and asks for the fact with `chronicle_answer` and `chronicle_search`. It uses the offline embedder (`hashing`) and opens no network connection. `PASS` means the fact came back through Chronicle. `FAIL:` names the step that did not return it.

### A live check with Hermes' own memory off

Hermes keeps its own `MEMORY.md` and `USER.md` unless both `memory.memory_enabled` and `memory.user_profile_enabled` are false. To check the profile without them:

1. In the profile's `config.yaml`, under `memory:`, set `memory_enabled: false` and `user_profile_enabled: false`.
2. Tell Hermes a made-up fact, for example: `The test word for this check is juniper quill.`
3. Start a new session with `/new`.
4. Ask: `What is the test word for this check?`

If Hermes gives the fact back, Chronicle recalled it without its own memory files. Set the two keys back if you want Hermes' memory files again.

## Moving memories to a new machine

Each Hermes profile has its own store, a local SQLite database under that
profile's home. The default profile's store is
`~/.hermes/commons/db/chronicle/chronicle.db`. A profile named `<name>` keeps its
store at `~/.hermes/profiles/<name>/commons/db/chronicle/chronicle.db` unless its
`db_path` says otherwise, so profiles do not share memories unless their
`db_path` names the same file. A fresh install creates a new store on first use.
To move a profile's memories to a new machine or fresh install:

1. Stop the running hermes session.
2. Copy that profile's `chronicle.db` to the same path on the new machine. For
   the default profile, the path is `~/.hermes/commons/db/chronicle/chronicle.db`.
3. Restart hermes and verify with `/chronicle`.

`SOUL.md`, `USER.md`, and `MEMORY.md` are separate files of the session and
memory layer — they are not part of, or migrated by, Chronicle. There is no
reverse migration from Chronicle to the old default hermes memory handler;
conversation history can only be re-read from its original source.

## Database

Stored at `~/.hermes/commons/db/chronicle/chronicle.db`. The database is self-contained: events, beliefs, principals, and FTS indices in a single file. WAL mode means readers don't block writers.

**Back up with SQLite, not with `cp`:**

```bash
sqlite3 ~/.hermes/commons/db/chronicle/chronicle.db ".backup /path/to/copy.db"
```

`.backup` is safe against a running writer and folds in the WAL. `cp` of a live
WAL-mode database gives a torn copy that silently loses committed frames, and
`VACUUM INTO` may renumber rowids, which breaks anything keyed on them. If you
would rather copy files, stop Hermes first and take `.db`, `.db-wal` **and**
`.db-shm` together. `MemoryStore.close()` / `ChronicleCore.close()` checkpoint
the WAL and release the sidecars if you are shutting down from code.

## Dashboard

Chronicle ships a Hermes dashboard tab (`dashboard/`) that shows store counts,
embedding coverage, recent activity, and a button that queues extraction for
turns that have none.

The UI is built from `dashboard/web/src`, and the built files in
`dashboard/dist` are committed, because the dashboard loads them with no build
step on the host:

```bash
cd dashboard/web && npm install && npm run build
```

`dashboard/web/harness/server.py --db <chronicle.db>` serves the UI and the
plugin API against a local store behind a stand-in for the plugin SDK, for
working on the UI without the OAuth-gated dashboard. It never writes.
