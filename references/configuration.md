# Configuration

## Required input

Set one of:

- `TASK_BOARD_INBOX`
- `--file /path/to/Task Inbox.md`

The CLI exits with a clear error if neither is provided.

## Optional environment variables

- `TASK_BOARD_DETAILS_DIR`
- `TASK_BOARD_ATTIC_FILE`
- `TASK_BOARD_TASKS_DIR`

If optional values are omitted, the CLI derives them from the inbox path:

- tasks dir: parent directory of the inbox
- details dir: `<tasks-dir>/Details`
- attic file: `<tasks-dir>/Task Attic.md`

## Example

```bash
export TASK_BOARD_INBOX="$HOME/Documents/Obsidian/MyVault/Tasks/Task Inbox.md"
python3 <skill-dir>/scripts/task_board.py lint
```

## Local overlays

Private deployments should keep machine-specific wrappers outside this public skill.

Typical private overlay responsibilities:

- export local path env vars
- call this skill with a preferred Python runner
- keep local Lobster workflows and cron jobs
