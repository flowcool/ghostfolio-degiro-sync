# Issue tracker: Beads

Issues and specs for this repository live in the shared Beads database. Use the
`bd` CLI for all operations and scope every query and mutation to
`project=ghostfolio-degiro-sync`.

## Conventions

- **Create an issue**: `bd create --title "..." --description "..." --type=task|bug|feature --priority=<0-4> --metadata '{"project":"ghostfolio-degiro-sync"}'`
- **Read an issue**: `bd show <id>`
- **List work**: `bd ready --metadata-field project=ghostfolio-degiro-sync` or `bd list --status=<status> --metadata-field project=ghostfolio-degiro-sync`
- **Claim work**: `bd update <id> --claim`
- **Comment on an issue**: use `/home/flow/.agents/bin/bd-finding` for material findings and milestones.
- **Create a dependency**: `bd dep add <issue> <depends-on>`
- **Close**: `bd close <id> --reason="..."`

Read `AGENTS.md` for the repository's Beads quality, evidence, and close-out
requirements. Do not use `bd edit`, which opens an interactive editor.

## When a skill says "publish to the issue tracker"

Create a Beads issue with `project=ghostfolio-degiro-sync`.

## When a skill says "fetch the relevant ticket"

Read it with `bd show <id>`.
