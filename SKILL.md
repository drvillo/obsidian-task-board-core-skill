---
name: obsidian-task-board-core
description: Manage a Markdown-native Obsidian task board through a deterministic CLI with linting, active-only inbox migration, archive/attic moves, agent-task reconciliation, and reminder maintenance. Use when Codex needs to create, update, validate, reconcile, or clean up an Obsidian task board stored in Markdown files.
metadata: {"openclaw":{"skillKey":"obsidian-task-board-core","requires":{"anyBins":["python3","python"],"env":["TASK_BOARD_INBOX"]}}}
---

# Obsidian Task Board Core

## Overview

Use this skill to manage an Obsidian task board as structured Markdown instead of freehand text edits. The core interface is `scripts/task_board.py`, which provides deterministic commands for linting, task creation and updates, archive/attic hygiene, agent-task reconciliation, and reminder resolution.

## Configuration

- Required:
  - Set `TASK_BOARD_INBOX` to the path of `Task Inbox.md`, or pass `--file` explicitly on each command.
- Optional:
  - `TASK_BOARD_DETAILS_DIR`
  - `TASK_BOARD_ATTIC_FILE`
  - `TASK_BOARD_TASKS_DIR`
- If optional paths are omitted, the CLI derives them from the inbox path.

Read `references/configuration.md` for the exact env vars, defaults, and example commands.

## Core workflow

1. Run `python3 {baseDir}/scripts/task_board.py lint` before and after non-trivial board mutations.
2. Use the CLI for all task creation, updates, closure, archive, attic moves, reconciliation, and reminder resolution.
3. Treat the inbox as active-only:
   - keep `next`, `waiting`, and agent tasks in `queued|running|blocked|review_needed`
   - move `done` tasks to monthly archives
   - move stale discarded items to the attic
4. For blocked or `review_needed` agent tasks, keep triage metadata in the detail note:
   - `owner`
   - `next_action`
   - `blocked_on`
   - `decision_by`

## Common commands

- Snapshot:
```bash
python3 {baseDir}/scripts/task_board.py snapshot
```
- Create a task:
```bash
python3 {baseDir}/scripts/task_board.py create --stdin-json
```
- Reconcile an agent task:
```bash
python3 {baseDir}/scripts/task_board.py reconcile-agent-task --stdin-json
```
- Archive completed tasks:
```bash
python3 {baseDir}/scripts/task_board.py archive-done --older-than-days 1
```
- Resolve an overdue reminder:
```bash
python3 {baseDir}/scripts/task_board.py resolve-reminder --id <task-id> --remind-on YYYY-MM-DD
```

## References

- `references/configuration.md` for env vars, path defaults, and invocation patterns
- `references/task-model.md` for the task schema and lifecycle rules

## Notes

- This skill is intentionally CLI-first and does not require Lobster.
- If Lobster is installed, wrap these commands in local workflows outside the public skill.
- Keep machine-specific paths, agent IDs, cron wiring, and user-specific helper scripts in a private local overlay rather than editing this skill.
