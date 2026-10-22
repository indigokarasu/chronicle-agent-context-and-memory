<p align="center">
  <img src="./assets/readme/hero.jpg" width="100%" alt="Chronicle — durable memory moving through an indigo and magenta archive">
</p>

# Chronicle

### Local-first memory for Hermes Agent that survives restarts, long chats, and context compression.

[![CI](https://github.com/indigokarasu/chronicle-agent-context-and-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/indigokarasu/chronicle-agent-context-and-memory/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/indigokarasu/chronicle-agent-context-and-memory)](https://github.com/indigokarasu/chronicle-agent-context-and-memory/releases/latest)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![MIT License](https://img.shields.io/badge/license-MIT-2ea44f.svg)](LICENSE)
[![No required services](https://img.shields.io/badge/required_services-none-6f42c1.svg)](#why-chronicle)

Version: 5.12.0.

Chronicle gives your Hermes agent durable long-term memory and safer working-memory
compression in one install. Names, preferences, decisions, and prior work stay on
your machine in SQLite; relevant memories come back when they are useful.

## Why Chronicle

- **Local by default.** No account, API key, or hosted memory service is required, and
  memory content never leaves the host unless you set `embeddings.allow_remote` or
  `extraction.llm.allow_remote` to true ([where memory is allowed to go](docs/security.md)).
- **Survives context compression.** Chronicle persists a span before the context
  engine evicts it, then rehydrates relevant memory later.
- **Inspectable and correctable.** Memories are event-sourced with provenance,
  history, correction, forgetting, and access-control tools.
- **Honest when evidence is weak.** Retrieval can fall back to captured turns and
  abstains instead of confidently inventing an answer.
- **Works without an embedding model.** Full-text recall remains available; a local
  OpenAI-compatible embedding server can improve semantic recall when present.

## Try it in two minutes

```bash
hermes plugins install indigokarasu/chronicle-agent-context-and-memory
```

Then open `hermes plugins` and select **Chronicle** for the Memory Provider.
Selecting it for the Context Engine is optional, but enables memory-aware
compression.

<details>
<summary>Or configure it by hand</summary>

```yaml
memory:  { provider: chronicle }
context: { engine: chronicle }
plugins: { enabled: [chronicle] }
```

</details>

Start Hermes and try this small persistence test:

1. Say: `Remember that my project launch day is Friday.`
2. Start a new session and ask: `When is my project launch day?`
3. Run `/chronicle` to see the active embedder and local store counts.

> [!NOTE]
> The database is created automatically under the active Hermes profile. For the
> default profile it is `~/.hermes/commons/db/chronicle/chronicle.db`. Chronicle has
> no required Python dependencies and no separate database setup step. Requires
> Python 3.9 or newer.

## What you get

Two Hermes plugin slots share one in-process core. Either slot can run without the
other, and under Hermes the capture and lifecycle hooks run automatically.

| Slot | What it does | Tools the agent gets |
|---|---|---|
| **Memory provider** (`ChronicleMemoryProvider`) | Durably captures conversation history and retrieves relevant facts, episodes, and raw turns across sessions. Memory about the user comes only from the user's own words. | `chronicle_remember`, `chronicle_search`, `chronicle_answer`, `chronicle_ask_about`, `chronicle_explain`, `chronicle_correct`, `chronicle_forget`, and about thirty more for history, provenance, access control, identity review, goals and diagnostics; the full list is in `engine/tools.py` |
| **Context engine** (`ChronicleContextEngine`, optional) | Replaces the default compressor with memory-aware compaction that makes spans durable before eviction. Nothing is lost: every folded message is archived first and can be restored byte for byte. | `chronicle_pin_context`, `chronicle_focus`, `chronicle_context_status`, `chronicle_expand` |

Maintenance runs on those same hooks, not on cron: there is no daemon to run.

## How it compares

Of the systems compared below, only Chronicle fills both the memory-provider and
context-engine slots, and it runs without a model, API key, or separate service.

| System | Memory provider | Context engine | Auto-capture | Auto-recall | No model or service |
|---|:---:|:---:|:---:|:---:|:---:|
| **Chronicle** | **✓** | **✓** | Every turn | ✓ | **✓** |
| Hermes files | Built in | — | Agent-directed | Always injected | ✓ |
| Mem0 | ✓ | — | Every turn | ✓ | — |
| Hindsight | ✓ | — | Default on | Default on | — |
| Mnemosyne | ✓ | — | Every turn | ✓ | — |
| Limbic | ✓ | — | Agent-directed | ✓ | — |
| Graphiti | — | — | MCP/custom | MCP/custom | — |

**Auto-capture** means Hermes stores completed turns without the model choosing a
tool. **Auto-recall** means memory is added to turn context automatically, not
merely exposed through a search tool. This compares documented integration
surfaces, not retrieval quality; the
[deployment comparison and sources](docs/comparison.md) have the detail.

## Extend it

Chronicle learns from conversation. Companion skills feed it structured data it
would never hear about in a chat, and others keep the memory clean and current.
None is required; each is an optional Hermes skill in its own repository, with its
own install steps.

| Skill | What it adds |
|---|---|
| [Weave](https://github.com/indigokarasu/weave) | People and relationships: contacts, how people know each other, preferences and shared experiences, each with its source |
| [Styx](https://github.com/indigokarasu/styx) | Spending: bank transactions, with garbled merchant names resolved to real businesses |
| [Taste](https://github.com/indigokarasu/taste) | Preferences learned from what you actually buy and book: reservations, deliveries, hotel stays, purchases |
| [Sands](https://github.com/indigokarasu/sands) | Calendar: create, find and change events across calendars in plain language; a weekly job writes travel, medical and personal events into Chronicle as facts |
| [Bower](https://github.com/indigokarasu/bower) | Google Drive: organizes files and notes the people and things they mention, as journal entries Chronicle reviews as candidates |
| [Finch](https://github.com/indigokarasu/finch) | Mines past sessions for corrections, breakthroughs and standing rules; findings about the user go to Chronicle, and it keeps `MEMORY.md` short |
| [UserContext](https://github.com/indigokarasu/UserContext) | A short daily block in `USER.md`: where the user is, the theme of the week, and yesterday, today and tomorrow |

[How a skill hands data to Chronicle](docs/skills.md), and how to declare a
federated database.

## Go deeper

| Running Chronicle | How it works inside |
|---|---|
| **[Configuration](docs/configuration.md)**<br>Every key and its default, profiles and multi-bot setups, the config audit | **[Compaction](docs/compaction.md)**<br>What a compaction keeps, what it folds, and what it leaves in their place |
| **[Operations](docs/operations.md)**<br>Check that it works, back up, move memories to a new machine, embeddings, the dashboard | **[Recall](docs/recall.md)**<br>What goes into a turn unasked, and the gate that decides |
| **[Security](docs/security.md)**<br>Where memory is allowed to go; nothing is encrypted at rest | **[Maintenance](docs/maintenance.md)**<br>Six hook-driven jobs, identity adjudication, speaker attribution |
| **[Skills and federation](docs/skills.md)**<br>How a companion skill hands data to Chronicle | **[Architecture](docs/architecture.md)**<br>The core, project structure, programmatic use, development |

Release notes are in [CHANGELOG.md](CHANGELOG.md).

## Contributing

Bug reports, use cases, and focused pull requests are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow and the best
places to start.

If Chronicle earns a place in your agent setup, please
[star the repository](https://github.com/indigokarasu/chronicle-agent-context-and-memory)
so other Hermes users can find it.

## License

MIT. See [LICENSE](LICENSE).
