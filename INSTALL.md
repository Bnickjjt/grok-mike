# grok-mike install

Pinned releases are the only supported install source for the Mike Grok Bot template.

## Quick install (importers)

```bash
git clone --branch v1.0.0 --depth 1 https://github.com/Bnickjjt/grok-mike.git
cd grok-mike
python scripts/verify_and_install.py --workflows "$HOME/agent-data/workflows" --mike-root ./mike-v1
```

The verify script must print `BOOTSTRAP_OK` and exit 0. On any SHA mismatch, stop and ask the publisher — never invent skill prose.

## Contents

- `skills/mike-v1-*` — eight Mike v1 skills (SKILL.md)
- `runtime/mike_engine.py` — validated NCI/engine runtime
- `QA/test_mike_engine.py` — unit tests
- `examples/make_synthetic_fixture.py` — synthetic dossier helper
- `scripts/verify_and_install.py` — SHA-gated install into workflows + mike-v1

NCI is an uncalibrated rubric index out of 100, not a probability that news is false.
