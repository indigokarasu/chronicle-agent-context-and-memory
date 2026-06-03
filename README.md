# Chronicle Memory Provider

Graph-native memory plugin for Hermes Agent, built on LadybugDB (Kuzu fork).

## Features

- **Fast fact storage** — Direct entity creation with embeddings
- **Multi-stage recall** — Vector similarity + FTS + graph traversal
- **Pattern detection** — Hidden connections, structural gaps, communities
- **Decay lifecycle** — Exponential decay with access strengthening
- **Bipartite metagraph** — Relationships as first-class EdgeNode entities
- **Engram-Cue model** — Content-addressable associative recall

## Installation

```bash
hermes plugins install indigokarasu/chronicle-plugin
```

## Configuration

Set in `~/.hermes/config.yaml`:

```yaml
memory:
  provider: chronicle
```

## Database

Stored at `~/.hermes/commons/db/chronicle/chronicle.lbug`
