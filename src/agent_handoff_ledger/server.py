from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

from mcp.server import MCPServer

SERVER_NAME = "agent-handoff-ledger"
DEFAULT_MAX_HANDOFFS = 4
MAX_HANDOFFS = 16
DEFAULT_LEASE_MINUTES = 90
MAX_LEASE_MINUTES = 24 * 60

mcp = MCPServer(SERVER_NAME)

SCHEMA = """
CREATE TABLE IF NOT EXISTS handoffs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'active', 'completed')),
    target_agent TEXT NOT NULL DEFAULT 'any',
    owner TEXT,
    summary TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL DEFAULT '',
    changed_files TEXT NOT NULL DEFAULT '',
    handoff_count INTEGER NOT NULL DEFAULT 0,
    max_handoffs INTEGER NOT NULL DEFAULT 4,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_lock (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    task_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES handoffs(id),
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_task ON events(task_id, sequence);
"""


class HandoffError(ValueError):
    """An expected, user-correctable handoff error."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _parse_stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _project_root() -> Path:
    configured = os.environ.get("AGENT_HANDOFF_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise HandoffError("AGENT_HANDOFF_ROOT must point to an existing directory.")
        return root

    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def _connect() -> sqlite3.Connection:
    root = _project_root()
    state_dir = root / ".agent-handoff"
    state_dir.mkdir(parents=True, exist_ok=True)
    ignore_file = state_dir / ".gitignore"
    if not ignore_file.exists():
        ignore_file.write_text("*\n!.gitignore\n", encoding="utf-8")

    connection = sqlite3.connect(state_dir / "ledger.sqlite3", timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    connection.executescript(SCHEMA)
    return connection


@contextmanager
def _database(write: bool = False) -> Iterator[sqlite3.Connection]:
    connection = _connect()
    try:
        if write:
            connection.execute("BEGIN IMMEDIATE")
        yield connection
        if write:
            connection.commit()
    except Exception:
        if write:
            connection.rollback()
        raise
    finally:
        connection.close()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _guard(function: Callable[..., str]) -> Callable[..., str]:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> str:
        try:
            return function(*args, **kwargs)
        except (HandoffError, sqlite3.Error, OSError) as exc:
            return _json({"ok": False, "error": str(exc)})

    return wrapped


def _text(value: str, label: str, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise HandoffError(f"{label} must be text.")
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise HandoffError(f"{label} cannot be empty.")
    if len(cleaned) > limit:
        raise HandoffError(f"{label} must be {limit} characters or fewer.")
    return cleaned


def _agent(value: str, label: str = "agent") -> str:
    cleaned = re.sub(r"\s+", "-", _text(value, label, 64)).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", cleaned):
        raise HandoffError(f"{label} may contain letters, numbers, dots, underscores, and hyphens.")
    return cleaned


def _lease_minutes(value: int) -> int:
    if not isinstance(value, int) or value < 5 or value > MAX_LEASE_MINUTES:
        raise HandoffError("lease_minutes must be between 5 and 1440.")
    return value


def _event(
    db: sqlite3.Connection,
    task_id: str,
    actor: str,
    kind: str,
    details: dict[str, Any],
) -> None:
    db.execute(
        "INSERT INTO events(task_id, actor, kind, details, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, actor, kind, _json(details), _stamp()),
    )


def _task(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _expire_lock(db: sqlite3.Connection, lock: sqlite3.Row) -> None:
    task_id = lock["task_id"]
    now = _stamp()
    warning = "Previous writer lease expired; inspect the workspace before continuing."
    db.execute(
        """UPDATE handoffs
           SET status = 'queued', owner = NULL, target_agent = 'any', lease_expires_at = NULL,
               summary = CASE WHEN summary = '' THEN ? ELSE summary || char(10) || char(10) || ? END,
               updated_at = ?
           WHERE id = ? AND status = 'active'""",
        (warning, warning, now, task_id),
    )
    db.execute("DELETE FROM workspace_lock WHERE singleton = 1")
    _event(db, task_id, "system", "lease_expired", {"previous_agent": lock["agent"]})


def _require_lock(db: sqlite3.Connection, task_id: str, agent: str) -> sqlite3.Row:
    lock = db.execute("SELECT * FROM workspace_lock WHERE singleton = 1").fetchone()
    if not lock or lock["task_id"] != task_id or lock["agent"] != agent:
        raise HandoffError("This agent does not hold the active writer lease for that task.")
    if _parse_stamp(lock["expires_at"]) <= _now():
        raise HandoffError("The writer lease expired. Claim the task again before changing its state.")
    return lock


@mcp.tool()
@_guard
def create_handoff(
    title: str,
    objective: str,
    target_agent: str = "any",
    max_handoffs: int = DEFAULT_MAX_HANDOFFS,
    created_by: str = "human",
) -> str:
    """Create a persistent task brief for another coding agent or a later session."""
    title = _text(title, "title", 200)
    objective = _text(objective, "objective", 12000)
    target = "any" if target_agent.strip().lower() == "any" else _agent(target_agent, "target_agent")
    actor = _agent(created_by, "created_by")
    if not isinstance(max_handoffs, int) or max_handoffs < 0 or max_handoffs > MAX_HANDOFFS:
        raise HandoffError(f"max_handoffs must be between 0 and {MAX_HANDOFFS}.")

    task_id = uuid4().hex[:10]
    now = _stamp()
    with _database(write=True) as db:
        db.execute(
            """INSERT INTO handoffs
               (id, title, objective, status, target_agent, max_handoffs, created_at, updated_at)
               VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)""",
            (task_id, title, objective, target, max_handoffs, now, now),
        )
        _event(db, task_id, actor, "created", {"target_agent": target, "max_handoffs": max_handoffs})
        row = db.execute("SELECT * FROM handoffs WHERE id = ?", (task_id,)).fetchone()
    return _json({"ok": True, "handoff": _task(row)})


@mcp.tool()
@_guard
def claim_handoff(
    task_id: str,
    agent: str,
    lease_minutes: int = DEFAULT_LEASE_MINUTES,
) -> str:
    """Atomically claim a queued task and the workspace's single-writer lease."""
    task_id = _text(task_id, "task_id", 10)
    agent = _agent(agent)
    if not isinstance(lease_minutes, int) or lease_minutes < 5 or lease_minutes > MAX_LEASE_MINUTES:
        raise HandoffError("lease_minutes must be between 5 and 1440.")
    now = _now()
    expires = _stamp(now + timedelta(minutes=lease_minutes))

    with _database(write=True) as db:
        row = db.execute("SELECT * FROM handoffs WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HandoffError(f"No handoff exists with id {task_id}.")
        if row["status"] == "completed":
            raise HandoffError("That handoff is already complete.")

        lock = db.execute("SELECT * FROM workspace_lock WHERE singleton = 1").fetchone()
        if lock and _parse_stamp(lock["expires_at"]) <= now:
            _expire_lock(db, lock)
            lock = None

        if lock:
            if lock["task_id"] == task_id and lock["agent"] == agent:
                db.execute("UPDATE workspace_lock SET expires_at = ? WHERE singleton = 1", (expires,))
                db.execute(
                    "UPDATE handoffs SET lease_expires_at = ?, updated_at = ? WHERE id = ?",
                    (expires, _stamp(now), task_id),
                )
                _event(db, task_id, agent, "lease_renewed", {"expires_at": expires})
                row = db.execute("SELECT * FROM handoffs WHERE id = ?", (task_id,)).fetchone()
                return _json({"ok": True, "handoff": _task(row), "message": "Lease renewed."})
            raise HandoffError(
                f"Workspace is held by {lock['agent']} on handoff {lock['task_id']}; "
                "wait for a handoff or completion."
            )

        if row["target_agent"] not in ("any", agent):
            raise HandoffError(f"This task is queued for {row['target_agent']}, not {agent}.")

        db.execute(
            """INSERT INTO workspace_lock(singleton, task_id, agent, expires_at)
               VALUES (1, ?, ?, ?)
               ON CONFLICT(singleton) DO UPDATE SET task_id=excluded.task_id,
                   agent=excluded.agent, expires_at=excluded.expires_at""",
            (task_id, agent, expires),
        )
        db.execute(
            """UPDATE handoffs
               SET status='active', owner=?, target_agent='any', lease_expires_at=?, updated_at=?
               WHERE id=?""",
            (agent, expires, _stamp(now), task_id),
        )
        _event(db, task_id, agent, "claimed", {"lease_expires_at": expires})
        row = db.execute("SELECT * FROM handoffs WHERE id = ?", (task_id,)).fetchone()
    return _json({"ok": True, "handoff": _task(row)})


@mcp.tool()
@_guard
def renew_handoff(
    task_id: str,
    agent: str,
    lease_minutes: int = DEFAULT_LEASE_MINUTES,
) -> str:
    """Extend the current writer lease before a long-running task continues."""
    task_id = _text(task_id, "task_id", 10)
    agent = _agent(agent)
    if not isinstance(lease_minutes, int) or lease_minutes < 5 or lease_minutes > MAX_LEASE_MINUTES:
        raise HandoffError("lease_minutes must be between 5 and 1440.")
    now = _now()
    expires = _stamp(now + timedelta(minutes=lease_minutes))

    with _database(write=True) as db:
        _require_lock(db, task_id, agent)
        db.execute("UPDATE workspace_lock SET expires_at = ? WHERE singleton = 1", (expires,))
        db.execute(
            "UPDATE handoffs SET lease_expires_at = ?, updated_at = ? WHERE id = ?",
            (expires, _stamp(now), task_id),
        )
        _event(db, task_id, agent, "lease_renewed", {"expires_at": expires})
        row = db.execute("SELECT * FROM handoffs WHERE id = ?", (task_id,)).fetchone()
    return _json({"ok": True, "handoff": _task(row)})


@mcp.tool()
@_guard
def pass_handoff(
    task_id: str,
    agent: str,
    target_agent: str,
    summary: str,
    next_action: str,
    changed_files: str = "",
) -> str:
    """Release the writer lease and pass a bounded, resumable brief to another agent."""
    task_id = _text(task_id, "task_id", 10)
    agent = _agent(agent)
    target = _agent(target_agent, "target_agent")
    summary = _text(summary, "summary", 12000)
    next_action = _text(next_action, "next_action", 4000)
    changed_files = _text(changed_files, "changed_files", 12000, allow_empty=True)
    if target == agent:
        raise HandoffError("Choose a different target agent or complete the task.")

    now = _stamp()
    with _database(write=True) as db:
        _require_lock(db, task_id, agent)
        row = db.execute("SELECT * FROM handoffs WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HandoffError(f"No handoff exists with id {task_id}.")
        if row["handoff_count"] >= row["max_handoffs"]:
            raise HandoffError(
                "The handoff budget is exhausted. Stop the agent loop and ask a person "
                "whether to complete the task or create a new handoff."
            )
        count = row["handoff_count"] + 1
        db.execute(
            """UPDATE handoffs
               SET status='queued', owner=NULL, target_agent=?, summary=?, next_action=?,
                   changed_files=?, handoff_count=?, lease_expires_at=NULL, updated_at=?
               WHERE id=?""",
            (target, summary, next_action, changed_files, count, now, task_id),
        )
        db.execute("DELETE FROM workspace_lock WHERE singleton = 1")
        _event(
            db,
            task_id,
            agent,
            "handed_off",
            {"target_agent": target, "summary": summary, "next_action": next_action, "changed_files": changed_files},
        )
        updated = db.execute("SELECT * FROM handoffs WHERE id = ?", (task_id,)).fetchone()
    return _json({"ok": True, "handoff": _task(updated), "message": "Writer lease released."})


@mcp.tool()
@_guard
def complete_handoff(task_id: str, agent: str, summary: str) -> str:
    """Mark a claimed task complete and release the workspace writer lease."""
    task_id = _text(task_id, "task_id", 10)
    agent = _agent(agent)
    summary = _text(summary, "summary", 12000)
    now = _stamp()

    with _database(write=True) as db:
        _require_lock(db, task_id, agent)
        db.execute(
            """UPDATE handoffs
               SET status='completed', owner=NULL, summary=?, lease_expires_at=NULL, updated_at=?
               WHERE id=?""",
            (summary, now, task_id),
        )
        db.execute("DELETE FROM workspace_lock WHERE singleton = 1")
        _event(db, task_id, agent, "completed", {"summary": summary})
        row = db.execute("SELECT * FROM handoffs WHERE id = ?", (task_id,)).fetchone()
    return _json({"ok": True, "handoff": _task(row), "message": "Writer lease released."})


@mcp.tool()
@_guard
def show_handoff(task_id: str) -> str:
    """Read a task brief and its append-only handoff history."""
    task_id = _text(task_id, "task_id", 10)
    with _database() as db:
        row = db.execute("SELECT * FROM handoffs WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise HandoffError(f"No handoff exists with id {task_id}.")
        events = db.execute(
            "SELECT actor, kind, details, created_at FROM events WHERE task_id = ? ORDER BY sequence",
            (task_id,),
        ).fetchall()
    history = [
        {
            "actor": event["actor"],
            "kind": event["kind"],
            "details": json.loads(event["details"]),
            "created_at": event["created_at"],
        }
        for event in events
    ]
    return _json({"ok": True, "handoff": _task(row), "history": history})


@mcp.tool()
@_guard
def list_handoffs(status: str = "open", limit: int = 20) -> str:
    """List recent handoffs by status: open, queued, active, completed, or all."""
    status = _text(status, "status", 20).lower()
    if status not in {"open", "queued", "active", "completed", "all"}:
        raise HandoffError("status must be open, queued, active, completed, or all.")
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise HandoffError("limit must be between 1 and 100.")

    with _database() as db:
        if status == "open":
            rows = db.execute(
                "SELECT * FROM handoffs WHERE status IN ('queued', 'active') ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        elif status == "all":
            rows = db.execute(
                "SELECT * FROM handoffs ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM handoffs WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
    return _json({"ok": True, "handoffs": [_task(row) for row in rows]})


def main() -> None:
    """Run the local MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()