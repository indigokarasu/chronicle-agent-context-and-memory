# Skills that extend Chronicle

None of these are required. Each is an optional Hermes skill in its own repository, with its own install steps.

A skill hands data to Chronicle in one of three ways:

- It keeps its own SQLite database, which Chronicle searches read-only. The records stay in that file; Chronicle keeps pointers and vectors so recall can find them. List each database under `federation.local_dbs` and set `retrieval.federated_channel: true`, which is off by default.
- It writes journal files to `~/.hermes/commons/journals/`, which Chronicle reads when `sources.ocas_journals` is enabled (the default is `auto`).
- It records facts through Chronicle's own tools or scripts.

## Structured data

| Skill | What it adds | How it reaches Chronicle |
|---|---|---|
| [Weave](https://github.com/indigokarasu/weave) | People and relationships: contacts, how people know each other, preferences and shared experiences, each with its source | Federated database |
| [Styx](https://github.com/indigokarasu/styx) | Spending: bank transactions, with garbled merchant names resolved to real businesses | Federated database |
| [Taste](https://github.com/indigokarasu/taste) | Preferences learned from what you actually buy and book: reservations, deliveries, hotel stays, purchases | Federated database |
| [Sands](https://github.com/indigokarasu/sands) | Calendar: create, find and change events across calendars in plain language | A weekly job writes travel, medical and personal events into Chronicle as facts |
| [Bower](https://github.com/indigokarasu/bower) | Google Drive: organizes files and notes the people and things they mention | Journal entries that Chronicle reviews as candidates, each with its source; Bower never writes to the store itself |

## Upkeep and recall

| Skill | What it does |
|---|---|
| [Finch](https://github.com/indigokarasu/finch) | Mines past sessions for corrections, breakthroughs and standing rules. Findings about the user go to Chronicle instead of becoming global behaviour, and it keeps `MEMORY.md` short. |
| [UserContext](https://github.com/indigokarasu/UserContext) | Writes a short daily block into `USER.md`: where the user is, the theme of the week, and yesterday, today and tomorrow. It draws on the calendar, recent sessions, email and Chronicle, so a new session starts with what is current instead of having to search for it. |

## Declaring a federated database

```yaml
memory:
  retrieval:
    federated_channel: true
  federation:
    local_dbs:
      - name: weave
        path: /absolute/path/to/weave.sqlite
        read_only: true
```

Give an absolute path. Chronicle opens the file read-only and reads its schema itself, so no database needs special support in Chronicle. Each query searches the first three declared databases unless you raise `federation.channel_max_dbs`.
