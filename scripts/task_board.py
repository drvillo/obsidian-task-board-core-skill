#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

TASK_BOARD_INBOX_ENV = "TASK_BOARD_INBOX"
TASK_BOARD_DETAILS_DIR_ENV = "TASK_BOARD_DETAILS_DIR"
TASK_BOARD_ATTIC_FILE_ENV = "TASK_BOARD_ATTIC_FILE"
TASK_BOARD_TASKS_DIR_ENV = "TASK_BOARD_TASKS_DIR"

TASK_LINE_RE = re.compile(r"^- \[([ xX])\] (.+)$")
TASK_START_SEARCH_RE = re.compile(r"^- \[[ xX]\] .+$", re.MULTILINE)
FIELD_LINE_RE = re.compile(r"^  - ([a-z_]+):\s*(.+)$")
RULE_RE = re.compile(r"^---\s*$", re.MULTILINE)
TASK_ID_RE = re.compile(r"^task-\d{8}-\d{3}$")
REF_RE = re.compile(r"\[\[Tasks/Details/([^#\]]+)(?:#[^\]]+)?\]\]")

STATUS_VALUES = {"inbox", "next", "waiting", "done"}
AGENT_STATUS_VALUES = {"none", "queued", "running", "blocked", "review_needed", "done", "failed"}
ASSIGNEE_TYPE_VALUES = {"human", "agent"}
ACTIVE_STATUSES = {"next", "waiting"}
ACTIVE_AGENT_STATUSES = {"queued", "running", "blocked", "review_needed"}
TRIAGE_FIELDS = ("owner", "next_action", "blocked_on", "decision_by")
METADATA_ORDER = (
    "id",
    "status",
    "owner",
    "assignee_type",
    "assignee",
    "agent_status",
    "created_on",
    "remind_on",
    "run_id",
    "details_ref",
    "results_ref",
    "log_ref",
)


@dataclass
class Task:
    checked: bool
    title: str
    metadata: dict[str, str]
    start_line: int

    @property
    def task_id(self) -> str:
        return self.metadata.get("id", "")

    def render(self) -> str:
        mark = "x" if self.checked else " "
        lines = [f"- [{mark}] {self.title}"]
        for key in METADATA_ORDER:
            lines.append(f"  - {key}: {self.metadata.get(key, 'none')}")
        return "\n".join(lines)

    def is_done(self) -> bool:
        return self.metadata.get("status") == "done"

    def is_agent_task(self) -> bool:
        return self.metadata.get("assignee_type") == "agent"

    def created_on(self) -> date | None:
        return _parse_iso_date(self.metadata.get("created_on", ""))

    def remind_on(self) -> date | None:
        remind = self.metadata.get("remind_on", "none")
        if remind == "none":
            return None
        return _parse_iso_date(remind)


@dataclass
class TaskBoard:
    prefix: str
    tasks: list[Task]
    path: Path

    def render(self) -> str:
        task_body = "\n\n".join(task.render() for task in self.tasks)
        prefix = self.prefix.rstrip() + "\n\n"
        if not task_body:
            return prefix
        return prefix + task_body.rstrip() + "\n"


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _today_iso() -> str:
    return date.today().isoformat()


def _now_label() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _slugify(text: str, max_length: int = 64) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug or "task")[:max_length].rstrip("-")


def _path_from_arg_or_env(raw: str | None, env_name: str) -> Path | None:
    candidate = raw or os.environ.get(env_name)
    if not candidate:
        return None
    return Path(candidate).expanduser()


def resolve_runtime_paths(args: argparse.Namespace) -> argparse.Namespace:
    inbox = _path_from_arg_or_env(args.file, TASK_BOARD_INBOX_ENV)
    if inbox is None:
        raise SystemExit(
            "task inbox path is required; pass --file or set TASK_BOARD_INBOX"
        )

    tasks_dir = _path_from_arg_or_env(args.tasks_dir, TASK_BOARD_TASKS_DIR_ENV) or inbox.parent
    details_dir = _path_from_arg_or_env(args.details_dir, TASK_BOARD_DETAILS_DIR_ENV) or tasks_dir / "Details"
    attic_file = _path_from_arg_or_env(args.attic_file, TASK_BOARD_ATTIC_FILE_ENV) or tasks_dir / "Task Attic.md"

    args.file = str(inbox)
    args.tasks_dir = str(tasks_dir)
    args.details_dir = str(details_dir)
    args.attic_file = str(attic_file)
    return args


def _first_task_offset(text: str) -> int:
    rule_match = RULE_RE.search(text)
    search_start = rule_match.end() if rule_match else 0
    task_match = TASK_START_SEARCH_RE.search(text, search_start)
    return task_match.start() if task_match else len(text)


def load_board(path: Path) -> TaskBoard:
    text = path.read_text(encoding="utf-8")
    first_task = _first_task_offset(text)
    prefix = text[:first_task]
    task_region = text[first_task:]
    tasks: list[Task] = []
    if not task_region.strip():
        return TaskBoard(prefix=prefix, tasks=tasks, path=path)

    lines = task_region.splitlines()
    base_line = prefix.count("\n") + 1
    idx = 0
    while idx < len(lines):
        if not TASK_LINE_RE.match(lines[idx]):
            idx += 1
            continue
        start_idx = idx
        idx += 1
        while idx < len(lines) and not TASK_LINE_RE.match(lines[idx]):
            idx += 1
        block = lines[start_idx:idx]
        task = parse_task_block(block, start_line=base_line + start_idx)
        tasks.append(task)
    return TaskBoard(prefix=prefix, tasks=tasks, path=path)


def parse_task_block(lines: list[str], start_line: int) -> Task:
    match = TASK_LINE_RE.match(lines[0])
    if not match:
        raise ValueError(f"invalid task block at line {start_line}")
    checked = match.group(1).lower() == "x"
    title = match.group(2).strip()
    metadata: dict[str, str] = {}
    for raw in lines[1:]:
        field_match = FIELD_LINE_RE.match(raw)
        if field_match:
            metadata[field_match.group(1)] = field_match.group(2).strip()
    for key in METADATA_ORDER:
        metadata.setdefault(key, "none")
    return Task(checked=checked, title=title, metadata=metadata, start_line=start_line)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def read_json_input(raw: str | None, stdin_json: bool) -> dict[str, Any]:
    try:
        if raw:
            return json.loads(raw)
        if stdin_json:
            return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "invalid JSON input: keep JSON strings on one logical line or use a quoted heredoc; "
            f"parser error at line {exc.lineno} column {exc.colno}"
        ) from exc
    return {}


def detail_ref_to_path(ref: str, details_dir: Path) -> Path | None:
    if not ref or ref == "none":
        return None
    match = REF_RE.search(ref)
    if not match:
        return None
    stem = match.group(1)
    if stem.endswith(".md"):
        return details_dir / stem
    return details_dir / f"{stem}.md"


def build_details_template(task: Task, request: str, acceptance_criteria: list[str]) -> str:
    task_status = task.metadata["agent_status"] if task.metadata["agent_status"] != "none" else task.metadata["status"]
    lines = [
        f"# {task.title}",
        "",
        f"- task_id: {task.task_id}",
        f"- created_on: {task.metadata['created_on']}",
        f"- assignee: {task.metadata['assignee']}",
        f"- run_id: {task.metadata['run_id']}",
        f"- status: {task_status}",
        "",
        "## Request",
        request or "Pending.",
        "",
        "## Acceptance criteria",
    ]
    if acceptance_criteria:
        lines.extend(f"- {item}" for item in acceptance_criteria)
    else:
        lines.append("- Pending")
    lines.extend(
        [
            "",
            "## Execution log",
            f"- {_now_label()} task created",
            "",
            "## Results",
            "- Pending",
        ]
    )
    return "\n".join(lines) + "\n"


def upsert_detail_triage(detail_path: Path, triage: dict[str, Any], *, write: bool = True) -> str:
    if not triage:
        return detail_path.read_text(encoding="utf-8")
    text = detail_path.read_text(encoding="utf-8")
    updated = text
    missing_fields: list[str] = []

    for field in TRIAGE_FIELDS:
        value = triage.get(field)
        if value is None:
            continue
        pattern = re.compile(rf"^- {field}:\s*.*$", flags=re.MULTILINE)
        line = f"- {field}: {str(value).strip()}"
        if pattern.search(updated):
            updated = pattern.sub(line, updated, count=1)
        else:
            missing_fields.append(field)

    if missing_fields:
        insert_lines = [f"- {field}: {str(triage[field]).strip()}" for field in TRIAGE_FIELDS if field in missing_fields]
        insert_block = "\n".join(insert_lines) + "\n"
        status_match = re.search(r"^- status:\s*.*$", updated, flags=re.MULTILINE)
        if status_match:
            insert_at = status_match.end()
            updated = updated[:insert_at] + "\n" + insert_block + updated[insert_at:]
        else:
            first_newline = updated.find("\n")
            if first_newline == -1:
                updated = updated + "\n\n" + insert_block
            else:
                updated = updated[: first_newline + 1] + "\n" + insert_block + updated[first_newline + 1 :]

    if updated != text and write:
        atomic_write(detail_path, updated)
    return updated


def ensure_detail_note(
    task: Task,
    details_dir: Path,
    request: str,
    acceptance_criteria: list[str],
    triage: dict[str, Any] | None = None,
    *,
    write: bool = True,
) -> tuple[str, str]:
    existing_ref = task.metadata.get("details_ref", "none")
    details_path = detail_ref_to_path(existing_ref, details_dir)
    if details_path is None:
        slug = _slugify(task.title)
        details_path = details_dir / f"{task.task_id}-{slug}.md"
        details_ref = f"[[Tasks/Details/{details_path.stem}]]"
        results_ref = f"[[Tasks/Details/{details_path.stem}#Results]]"
        task.metadata["details_ref"] = details_ref
        task.metadata["results_ref"] = results_ref
    else:
        details_ref = task.metadata["details_ref"]
        results_ref = task.metadata["results_ref"]
    if not details_path.exists() and write:
        content = build_details_template(task, request=request, acceptance_criteria=acceptance_criteria)
        atomic_write(details_path, content)
    if triage and details_path.exists():
        upsert_detail_triage(details_path, triage, write=write)
    return details_ref, results_ref


def lint_board(board: TaskBoard, details_dir: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}

    for task in board.tasks:
        task_id = task.metadata.get("id", "")
        if not TASK_ID_RE.fullmatch(task_id):
            errors.append(_issue(task, "invalid_id", f"invalid task id '{task_id}'"))
        if task_id in seen_ids:
            errors.append(_issue(task, "duplicate_id", f"duplicate task id '{task_id}'"))
        else:
            seen_ids[task_id] = task.start_line

        status = task.metadata.get("status", "")
        if status not in STATUS_VALUES:
            errors.append(_issue(task, "invalid_status", f"invalid status '{status}'"))

        assignee_type = task.metadata.get("assignee_type", "")
        if assignee_type not in ASSIGNEE_TYPE_VALUES:
            errors.append(_issue(task, "invalid_assignee_type", f"invalid assignee_type '{assignee_type}'"))

        agent_status = task.metadata.get("agent_status", "")
        if agent_status not in AGENT_STATUS_VALUES:
            errors.append(_issue(task, "invalid_agent_status", f"invalid agent_status '{agent_status}'"))

        created_on = task.created_on()
        if created_on is None:
            errors.append(_issue(task, "invalid_created_on", f"invalid created_on '{task.metadata.get('created_on', '')}'"))

        remind_on_value = task.metadata.get("remind_on", "none")
        if remind_on_value != "none" and task.remind_on() is None:
            errors.append(_issue(task, "invalid_remind_on", f"invalid remind_on '{remind_on_value}'"))

        if task.is_done() and not task.checked:
            warnings.append(_issue(task, "unchecked_done", "status is done but checkbox is unchecked"))
        if not task.is_done() and task.checked:
            warnings.append(_issue(task, "checked_not_done", "checkbox is checked but status is not done"))

        if task.is_agent_task():
            details_ref = task.metadata.get("details_ref", "none")
            results_ref = task.metadata.get("results_ref", "none")
            if details_ref == "none":
                errors.append(_issue(task, "missing_details_ref", "agent task is missing details_ref"))
            if results_ref == "none":
                errors.append(_issue(task, "missing_results_ref", "agent task is missing results_ref"))
            if task.metadata.get("agent_status") in {"blocked", "review_needed"}:
                detail_path = detail_ref_to_path(details_ref, details_dir)
                if detail_path is None or not detail_path.exists():
                    errors.append(_issue(task, "missing_detail_note", "blocked/review task detail note is missing"))
                else:
                    detail_text = detail_path.read_text(encoding="utf-8")
                    for field in TRIAGE_FIELDS:
                        if not re.search(rf"^- {field}:\s*(.+)$", detail_text, flags=re.MULTILINE):
                            errors.append(_issue(task, "missing_triage_field", f"detail note is missing triage field '{field}'"))

        if task.remind_on() and task.remind_on() < date.today() and task.metadata.get("status") != "done":
            warnings.append(_issue(task, "overdue_reminder", f"remind_on {task.metadata['remind_on']} is overdue"))

    return {
        "ok": not errors,
        "file": str(board.path),
        "task_count": len(board.tasks),
        "errors": errors,
        "warnings": warnings,
    }


def _issue(task: Task, code: str, message: str) -> dict[str, Any]:
    return {
        "id": task.task_id or "missing",
        "line": task.start_line,
        "code": code,
        "message": message,
    }


def next_task_id(tasks: list[Task], today: date | None = None) -> str:
    today = today or date.today()
    date_part = today.strftime("%Y%m%d")
    sequences: list[int] = []
    for task in tasks:
        match = re.match(rf"task-{date_part}-(\d{{3}})$", task.task_id)
        if match:
            sequences.append(int(match.group(1)))
    next_seq = max(sequences, default=0) + 1
    return f"task-{date_part}-{next_seq:03d}"


def find_task(tasks: list[Task], task_id: str) -> Task:
    for task in tasks:
        if task.task_id == task_id:
            return task
    raise SystemExit(f"task not found: {task_id}")


def append_blocks(path: Path, header: str, tasks: list[Task]) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else header
    existing_ids = {match.group(1) for match in re.finditer(r"^\s*- id:\s*(task-\d{8}-\d{3})\s*$", existing, flags=re.MULTILINE)}
    new_blocks = [task.render() for task in tasks if task.task_id not in existing_ids]
    if not new_blocks:
        if not path.exists():
            atomic_write(path, header.rstrip() + "\n")
        return
    text = existing.rstrip()
    if not text:
        text = header.rstrip()
    if not text.endswith("\n"):
        text += "\n"
    text += "\n\n" + "\n\n".join(new_blocks).rstrip() + "\n"
    atomic_write(path, text)


def archive_header(month: str) -> str:
    return f"# Task Archive ({month})\n\nArchived completed tasks moved out of `Task Inbox.md`.\n"


def attic_header() -> str:
    return (
        "# Task Attic\n\n"
        "Inactive archival tasks moved out of `Task Inbox.md`.\n\n"
        "Rules:\n"
        "- Items here are intentionally out of the active queue.\n"
        "- Do not use or reference them unless Francesco explicitly asks.\n"
        "- Moving a task here means “deleted from active use,” not erased from history.\n"
    )


def task_to_public(task: Task) -> dict[str, Any]:
    data = {
        "title": task.title,
        "checked": task.checked,
        "line": task.start_line,
    }
    data.update(task.metadata)
    return data


def write_board(board: TaskBoard) -> None:
    atomic_write(board.path, board.render())


def cmd_lint(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    result = lint_board(board, details_dir=Path(args.details_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def cmd_list_active(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    tasks = [
        task_to_public(task)
        for task in board.tasks
        if task.metadata["status"] in ACTIVE_STATUSES or task.metadata["agent_status"] in ACTIVE_AGENT_STATUSES
    ]
    print(json.dumps({"tasks": tasks, "count": len(tasks)}, ensure_ascii=False, indent=2))
    return 0


def cmd_list_overdue(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    tasks = []
    for task in board.tasks:
        remind_on = task.remind_on()
        if remind_on and remind_on < date.today() and task.metadata["status"] != "done":
            tasks.append(task_to_public(task))
    print(json.dumps({"tasks": tasks, "count": len(tasks)}, ensure_ascii=False, indent=2))
    return 0


def cmd_list_agent_active(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    tasks = [
        task_to_public(task)
        for task in board.tasks
        if task.is_agent_task() and task.metadata["agent_status"] in ACTIVE_AGENT_STATUSES
    ]
    print(json.dumps({"tasks": tasks, "count": len(tasks)}, ensure_ascii=False, indent=2))
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    active = [
        task_to_public(task)
        for task in board.tasks
        if task.metadata["status"] in ACTIVE_STATUSES or task.metadata["agent_status"] in ACTIVE_AGENT_STATUSES
    ]
    overdue = []
    for task in board.tasks:
        remind_on = task.remind_on()
        if remind_on and remind_on < date.today() and task.metadata["status"] != "done":
            overdue.append(task_to_public(task))
    agent_active = [
        task_to_public(task)
        for task in board.tasks
        if task.is_agent_task() and task.metadata["agent_status"] in ACTIVE_AGENT_STATUSES
    ]
    lint = lint_board(board, details_dir=Path(args.details_dir))
    print(
        json.dumps(
            {
                "active": {"tasks": active, "count": len(active)},
                "overdue": {"tasks": overdue, "count": len(overdue)},
                "agent_active": {"tasks": agent_active, "count": len(agent_active)},
                "lint": lint,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    payload = read_json_input(args.json_input, args.stdin_json)
    title = (payload.get("title") or "").strip()
    if not title:
        raise SystemExit("create requires a title")

    created_on = payload.get("created_on") or _today_iso()
    task = Task(
        checked=bool(payload.get("checked", False)),
        title=title,
        start_line=0,
        metadata={
            "id": next_task_id(board.tasks, today=_parse_iso_date(created_on) or date.today()),
            "status": payload.get("status", "next"),
            "owner": payload.get("owner", "francesco"),
            "assignee_type": payload.get("assignee_type", "human"),
            "assignee": payload.get("assignee", "none"),
            "agent_status": payload.get("agent_status", "none"),
            "created_on": created_on,
            "remind_on": payload.get("remind_on", "none"),
            "run_id": payload.get("run_id", "none"),
            "details_ref": payload.get("details_ref", "none"),
            "results_ref": payload.get("results_ref", "none"),
            "log_ref": payload.get("log_ref", "[[Logs/Agent Activity Log]]"),
        },
    )
    if task.metadata["status"] == "done":
        task.checked = True
    if task.is_agent_task():
        ensure_detail_note(
            task,
            details_dir=Path(args.details_dir),
            request=payload.get("request", ""),
            acceptance_criteria=payload.get("acceptance_criteria", []),
            triage=payload.get("triage"),
            write=not args.dry_run,
        )
    board.tasks.insert(0, task)
    if not args.dry_run:
        write_board(board)
    result = {"created": task_to_public(task), "file": str(board.path), "dry_run": args.dry_run}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    payload = read_json_input(args.json_input, args.stdin_json)
    task = find_task(board.tasks, payload.get("id") or args.id)
    if "title" in payload:
        task.title = str(payload["title"]).strip()
    for key in METADATA_ORDER:
        if key in payload:
            task.metadata[key] = str(payload[key])
    if task.metadata["status"] == "done":
        task.checked = True
        if task.is_agent_task() and task.metadata["agent_status"] == "none":
            task.metadata["agent_status"] = "done"
    elif "checked" in payload:
        task.checked = bool(payload["checked"])
    elif task.checked and task.metadata["status"] != "done":
        task.checked = False
    if task.is_agent_task() and (payload.get("ensure_detail_note") or task.metadata.get("details_ref") == "none"):
        ensure_detail_note(
            task,
            details_dir=Path(args.details_dir),
            request=payload.get("request", ""),
            acceptance_criteria=payload.get("acceptance_criteria", []),
            triage=payload.get("triage"),
            write=not args.dry_run,
        )
    elif task.is_agent_task() and payload.get("triage"):
        detail_path = detail_ref_to_path(task.metadata.get("details_ref", "none"), Path(args.details_dir))
        if detail_path is None or not detail_path.exists():
            raise SystemExit(f"detail note missing for triage update: {task.task_id}")
        upsert_detail_triage(detail_path, payload["triage"], write=not args.dry_run)
    if not args.dry_run:
        write_board(board)
    print(json.dumps({"updated": task_to_public(task), "file": str(board.path), "dry_run": args.dry_run}, ensure_ascii=False, indent=2))
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    task = find_task(board.tasks, args.id)
    task.metadata["status"] = "done"
    task.checked = True
    if task.is_agent_task():
        task.metadata["agent_status"] = "done"
    if not args.dry_run:
        write_board(board)
    print(json.dumps({"closed": task_to_public(task), "file": str(board.path), "dry_run": args.dry_run}, ensure_ascii=False, indent=2))
    return 0


def cmd_resolve_reminder(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    task = find_task(board.tasks, args.id)

    if args.mark_done:
        task.metadata["status"] = "done"
        task.metadata["remind_on"] = "none"
        task.checked = True
        if task.is_agent_task():
            task.metadata["agent_status"] = "done"
    else:
        if args.remind_on is not None:
            if _parse_iso_date(args.remind_on) is None:
                raise SystemExit(f"invalid remind_on '{args.remind_on}'")
            task.metadata["remind_on"] = args.remind_on
        elif args.clear_reminder:
            task.metadata["remind_on"] = "none"

        if args.status is not None:
            if args.status not in STATUS_VALUES:
                raise SystemExit(f"invalid status '{args.status}'")
            task.metadata["status"] = args.status
            task.checked = args.status == "done"
            if task.is_agent_task() and args.status == "done" and task.metadata["agent_status"] == "none":
                task.metadata["agent_status"] = "done"

    if not args.dry_run:
        write_board(board)
    print(json.dumps({"resolved": task_to_public(task), "file": str(board.path), "dry_run": args.dry_run}, ensure_ascii=False, indent=2))
    return 0


def _archive_tasks(tasks_dir: Path, tasks: list[Task]) -> list[str]:
    archived_files: list[str] = []
    by_month: dict[str, list[Task]] = {}
    for task in tasks:
        created = task.created_on() or date.today()
        month = created.strftime("%Y-%m")
        by_month.setdefault(month, []).append(task)
    for month, month_tasks in by_month.items():
        archive_path = tasks_dir / f"Task Archive-{month}.md"
        append_blocks(archive_path, archive_header(month), month_tasks)
        archived_files.append(str(archive_path))
    return archived_files


def cmd_archive_done(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    cutoff = date.today() - timedelta(days=args.older_than_days)
    archived = [task for task in board.tasks if task.is_done() and (task.created_on() is not None and task.created_on() <= cutoff)]
    kept = [task for task in board.tasks if task not in archived]
    archived_files: list[str] = []
    if not args.dry_run and archived:
        archived_files = _archive_tasks(Path(args.tasks_dir), archived)
        board.tasks = kept
        write_board(board)
    result = {
        "file": str(board.path),
        "dry_run": args.dry_run,
        "older_than_days": args.older_than_days,
        "tasks_archived": len(archived),
        "archived_ids": [task.task_id for task in archived],
        "archive_files": archived_files,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_move_to_attic(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    ids = args.ids
    moved = [task for task in board.tasks if task.task_id in ids]
    if not args.dry_run and moved:
        append_blocks(Path(args.attic_file), attic_header(), moved)
        board.tasks = [task for task in board.tasks if task.task_id not in ids]
        write_board(board)
    print(
        json.dumps(
            {
                "file": str(board.path),
                "dry_run": args.dry_run,
                "tasks_moved": len(moved),
                "moved_ids": [task.task_id for task in moved],
                "attic_file": args.attic_file,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_reconcile_agent_task(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    payload = read_json_input(args.json_input, args.stdin_json)
    task = find_task(board.tasks, payload.get("id"))
    for key in ("status", "agent_status", "run_id", "details_ref", "results_ref", "log_ref", "remind_on"):
        if key in payload:
            task.metadata[key] = str(payload[key])
    if payload.get("title"):
        task.title = str(payload["title"]).strip()
    if payload.get("request") is not None or payload.get("acceptance_criteria") is not None:
        ensure_detail_note(
            task,
            details_dir=Path(args.details_dir),
            request=payload.get("request", ""),
            acceptance_criteria=payload.get("acceptance_criteria", []),
            triage=payload.get("triage"),
            write=not args.dry_run,
        )
    elif task.is_agent_task() and payload.get("triage"):
        detail_path = detail_ref_to_path(task.metadata.get("details_ref", "none"), Path(args.details_dir))
        if detail_path is None or not detail_path.exists():
            raise SystemExit(f"detail note missing for triage update: {task.task_id}")
        upsert_detail_triage(detail_path, payload["triage"], write=not args.dry_run)
    if task.metadata["status"] == "done":
        task.checked = True
    if not args.dry_run:
        write_board(board)
    print(json.dumps({"reconciled": task_to_public(task), "file": str(board.path), "dry_run": args.dry_run}, ensure_ascii=False, indent=2))
    return 0


def cmd_migrate_active_only(args: argparse.Namespace) -> int:
    board = load_board(Path(args.file))
    today = date.today()
    done_tasks = [task for task in board.tasks if task.is_done()]
    stale_unclear: list[Task] = []
    overdue: list[Task] = []
    cutoff = today - timedelta(days=args.unclear_older_than_days)
    for task in board.tasks:
        remind = task.remind_on()
        if remind and remind < today and not task.is_done():
            overdue.append(task)
        created = task.created_on()
        assignee = task.metadata.get("assignee", "")
        if created and created <= cutoff and not task.is_done():
            if assignee.lower() == "unclear" or task.title.lower().startswith("[unclear]"):
                stale_unclear.append(task)

    kept_ids = {task.task_id for task in done_tasks + stale_unclear}
    if not args.dry_run:
        if done_tasks:
            _archive_tasks(Path(args.tasks_dir), done_tasks)
        if stale_unclear:
            append_blocks(Path(args.attic_file), attic_header(), stale_unclear)
        board.tasks = [task for task in board.tasks if task.task_id not in kept_ids]
        write_board(board)

    result = {
        "file": str(board.path),
        "dry_run": args.dry_run,
        "done_tasks_to_archive": [task.task_id for task in done_tasks],
        "stale_unclear_to_attic": [task.task_id for task in stale_unclear],
        "overdue_open_tasks": [task.task_id for task in overdue],
        "remaining_active_tasks": len([task for task in board.tasks if task.task_id not in kept_ids]),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Canonical CLI for Obsidian task board operations.")
    parser.add_argument("--file", default=None, help=f"Task inbox markdown file (or ${TASK_BOARD_INBOX_ENV})")
    parser.add_argument(
        "--details-dir",
        default=None,
        help=f"Task details directory (or ${TASK_BOARD_DETAILS_DIR_ENV}; defaults to sibling Details/)",
    )
    parser.add_argument(
        "--attic-file",
        default=None,
        help=f"Task attic markdown file (or ${TASK_BOARD_ATTIC_FILE_ENV}; defaults to sibling Task Attic.md)",
    )
    parser.add_argument(
        "--tasks-dir",
        default=None,
        help=f"Tasks directory for monthly archives (or ${TASK_BOARD_TASKS_DIR_ENV}; defaults to inbox parent)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("lint")
    sub.add_parser("list-active")
    sub.add_parser("list-overdue")
    sub.add_parser("list-agent-active")
    sub.add_parser("snapshot")

    create = sub.add_parser("create")
    create.add_argument("--json-input", help="Inline JSON object")
    create.add_argument("--stdin-json", action="store_true", help="Read JSON payload from stdin")
    create.add_argument("--dry-run", action="store_true")

    update = sub.add_parser("update")
    update.add_argument("--id", help="Task id when not passed in JSON")
    update.add_argument("--json-input", help="Inline JSON object")
    update.add_argument("--stdin-json", action="store_true", help="Read JSON payload from stdin")
    update.add_argument("--dry-run", action="store_true")

    close = sub.add_parser("close")
    close.add_argument("--id", required=True)
    close.add_argument("--dry-run", action="store_true")

    resolve = sub.add_parser("resolve-reminder")
    resolve.add_argument("--id", required=True)
    action = resolve.add_mutually_exclusive_group(required=True)
    action.add_argument("--mark-done", action="store_true")
    action.add_argument("--remind-on", help="New ISO date for the reminder")
    action.add_argument("--clear-reminder", action="store_true")
    resolve.add_argument("--status", help="Optional new status when re-dating or clearing")
    resolve.add_argument("--dry-run", action="store_true")

    archive = sub.add_parser("archive-done")
    archive.add_argument("--older-than-days", type=int, default=1)
    archive.add_argument("--dry-run", action="store_true")

    attic = sub.add_parser("move-to-attic")
    attic.add_argument("--ids", nargs="+", required=True)
    attic.add_argument("--dry-run", action="store_true")

    reconcile = sub.add_parser("reconcile-agent-task")
    reconcile.add_argument("--json-input", help="Inline JSON object")
    reconcile.add_argument("--stdin-json", action="store_true", help="Read JSON payload from stdin")
    reconcile.add_argument("--dry-run", action="store_true")

    migrate = sub.add_parser("migrate-active-only")
    migrate.add_argument("--unclear-older-than-days", type=int, default=3)
    migrate.add_argument("--dry-run", action="store_true")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args = resolve_runtime_paths(args)
    command = args.command.replace("-", "_")
    handler = globals()[f"cmd_{command}"]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
