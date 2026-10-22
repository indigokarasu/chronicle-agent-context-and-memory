# How Chronicle compares

Mem0 and Hindsight are native Hermes memory providers. The meaningful difference
is which Hermes extension points a system owns and what must run behind it.

## Hermes integration

| System | Memory provider | Context engine | Auto-capture | Auto-recall |
|---|:---:|:---:|:---:|:---:|
| **Chronicle** | **✓** | **✓** | Every turn | ✓ |
| Hermes files | Built in | — | Agent-directed | Always injected |
| Mem0 | ✓ | — | Every turn | ✓ |
| Hindsight | ✓ | — | Default on | Default on |
| Graphiti | — | — | MCP/custom | MCP/custom |
| Mnemosyne | ✓ | — | Every turn | ✓ |
| Limbic | ✓ | — | Agent-directed | ✓ |

**Auto-capture** means Hermes stores completed turns without the model choosing a
tool. **Auto-recall** means memory is added to turn context automatically, not
merely exposed through a search tool.

## Deployment and controls

| System | Default Hermes setup | No model/service | Hermes-facing controls |
|---|---|:---:|---|
| **Chronicle** | Local SQLite | **✓** | Remember, search, correct, forget |
| Hermes files | Local Markdown | ✓ | Add, replace, remove |
| Mem0 | Mem0 Platform | — | Search, add, update, delete |
| Hindsight | Hindsight Cloud | — | Retain, recall, reflect |
| Graphiti | No provider | — | MCP episode/graph tools |
| Mnemosyne | Local SQLite | — | remember, recall, search |
| Limbic | Local SQLite | — | remember, recall |

Among these systems, Chronicle alone fills both the Hermes memory-provider and
context-engine slots. Its context engine rescues valuable spans into durable
memory before compaction, then rebuilds the working context. Mem0 and Hindsight
also capture every turn, but do not control Hermes compression. Hermes files are
always injected and have built-in editing tools, but are agent-curated rather
than automatically extracted. Graphiti currently requires MCP or custom wiring.

Chronicle also runs without a model, API key, or separate service. If embeddings
are unavailable, it keeps recalling through local full-text, structured, and
raw-turn fallbacks. Mem0 additionally offers self-hosted and in-process OSS
modes, which require its model, embedder, and vector-store stack. Hindsight also
offers embedded-local and external-server modes; embedded-local includes its
database but still requires a configured LLM. Graphiti supports local components
but still needs model, embedding, and graph backends.

This compares documented integration and deployment surfaces, not retrieval
quality: [Hermes provider API](https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin),
[Mem0 for Hermes](https://docs.mem0.ai/integrations/hermes),
[Hindsight provider](https://hermes-agent.nousresearch.com/docs/plugins/hindsight),
and [Graphiti MCP](https://help.getzep.com/graphiti/getting-started/mcp-server).
