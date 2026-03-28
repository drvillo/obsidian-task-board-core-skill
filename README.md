# Obsidian Task Board Core Skill

Portable OpenClaw skill for managing a Markdown-native Obsidian task board through a deterministic CLI.

This repo is the public skill bundle for `obsidian-task-board-core`. It focuses on:

- linting and validating task-board structure
- active-only inbox management
- archive and attic moves
- agent-task reconciliation
- reminder maintenance

It is intentionally CLI-first and does not require Lobster.

## Contents

- `SKILL.md`: skill definition and usage guidance
- `scripts/task_board.py`: canonical task-board CLI
- `references/configuration.md`: env vars and path configuration
- `references/task-model.md`: task schema and lifecycle rules
- `agents/openai.yaml`: UI metadata

## Configuration

Required:

- `TASK_BOARD_INBOX`, or pass `--file` to the CLI

Optional:

- `TASK_BOARD_DETAILS_DIR`
- `TASK_BOARD_ATTIC_FILE`
- `TASK_BOARD_TASKS_DIR`

If optional paths are omitted, the CLI derives them from the inbox path.

## Example

```bash
export TASK_BOARD_INBOX="$HOME/Documents/Obsidian/MyVault/Tasks/Task Inbox.md"
python3 scripts/task_board.py lint
python3 scripts/task_board.py snapshot
```

## Notes

- Keep machine-specific paths, cron wiring, agent IDs, and Lobster workflows in a private local overlay.
- The local/private overlay used in the original deployment is not part of this repo.
