## What this changes

<!-- One or two sentences. Link the issue if there is one (e.g. "Fixes #12"). -->

## Kind of change

- [ ] Bug fix
- [ ] New feature or behaviour change
- [ ] Docs, tests or CI only

## How it was checked

<!-- What you ran, and what you saw. For a behaviour change, say how you tried it in Hermes. -->

## Checklist

- [ ] `ruff check .` and `python -m pytest tests/ -q` pass
- [ ] A release bumps the version in all five places (`plugin.yaml`, `pyproject.toml`, README `Version:`,
      `dashboard/manifest.json`, `__init__.py`) and adds a `## x.y.z` heading to `CHANGELOG.md`
- [ ] A dashboard source change is rebuilt (`cd dashboard/web && npm ci && npm run build`) and `dashboard/dist` committed
- [ ] Docs updated if behaviour or a config key changed (`docs/configuration.md`)
- [ ] No real secret, token, address, hostname or personal data anywhere in the diff; test values are made up
