# Task Model

## Inbox model

The inbox is an active queue, not a historical ledger.

Keep only:

- `next`
- `waiting`
- agent tasks in `queued|running|blocked|review_needed`

Move:

- `done` tasks to monthly archive files
- stale discarded items to the attic

## Required metadata fields

Each task block uses:

- `id`
- `status`
- `owner`
- `assignee_type`
- `assignee`
- `agent_status`
- `created_on`
- `remind_on`
- `run_id`
- `details_ref`
- `results_ref`
- `log_ref`

## Agent-task rules

- Agent tasks must keep `details_ref` and `results_ref` valid.
- `review_needed` is reserved for coding-agent style review states.
- `blocked` and `review_needed` tasks require detail-note triage fields:
  - `owner`
  - `next_action`
  - `blocked_on`
  - `decision_by`

## CLI responsibilities

The CLI is the canonical mutation path for:

- linting
- create/update/close
- archive/attic moves
- agent-task reconciliation
- reminder resolution
