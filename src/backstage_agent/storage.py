from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .models import ApplicationDraft, CastingNotice, ProjectNotice, ScreeningDecision


class DecisionStore:
    def __init__(self, path: Path):
        self.path = path
        self._ensure_schema()

    def record_decision(self, decision: ScreeningDecision) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO decisions (
                  source_message_id, title, application_url, score, should_apply,
                  reasons_json, concerns_json, llm_used, notice_json, project_date
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.notice.source_message_id,
                    decision.notice.title,
                    decision.notice.application_url,
                    decision.score,
                    int(decision.should_apply),
                    json.dumps(decision.reasons),
                    json.dumps(decision.concerns),
                    int(decision.llm_used),
                    json.dumps(asdict(decision.notice), default=str),
                    decision.notice.project_date.isoformat()
                    if decision.notice.project_date
                    else None,
                ),
            )

    def record_project(self, project: ProjectNotice) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO projects (
                  source_message_id, title, project_url, description, raw_text, project_date
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project.source_message_id,
                    project.title,
                    project.project_url,
                    project.description,
                    project.raw_text,
                    project.project_date.isoformat() if project.project_date else None,
                ),
            )
            return int(cursor.lastrowid)

    def record_role(self, project_id: int, notice: CastingNotice) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO roles (
                  project_id, source_message_id, title, project, role, location,
                  compensation, application_url, description, raw_text, project_date,
                  notice_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    notice.source_message_id,
                    notice.title,
                    notice.project,
                    notice.role,
                    notice.location,
                    notice.compensation,
                    notice.application_url,
                    notice.description,
                    notice.raw_text,
                    notice.project_date.isoformat() if notice.project_date else None,
                    json.dumps(asdict(notice), default=str),
                ),
            )
            return int(cursor.lastrowid)

    def record_application(self, draft: ApplicationDraft) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO applications (title, application_url, cover_note, dry_run, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    draft.notice.title,
                    draft.notice.application_url,
                    draft.cover_note,
                    int(draft.dry_run),
                    draft.status,
                ),
            )

    def recent_decisions(self, limit: int = 20) -> list[sqlite3.Row]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return list(
                conn.execute(
                    """
                    SELECT created_at, title, score, should_apply, llm_used, reasons_json
                    FROM decisions
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

    def search_decisions(
        self,
        query: str = "",
        decision: str = "all",
        method: str = "all",
        date_from: str = "",
        date_to: str = "",
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        where, params = _decision_filter_sql(query, decision, method, date_from, date_to)
        params.append(limit)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return list(
                conn.execute(
                    f"""
                    SELECT id, created_at, project_date, title, application_url, score, should_apply,
                           reasons_json, concerns_json, llm_used, notice_json
                    FROM decisions
                    {where}
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    params,
                )
            )

    def decision_counts(
        self,
        query: str = "",
        method: str = "all",
        decision: str = "all",
        date_from: str = "",
        date_to: str = "",
    ) -> sqlite3.Row:
        where, params = _decision_filter_sql(query, decision, method, date_from, date_to)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                f"""
                SELECT
                  COUNT(*) AS total,
                  SUM(CASE WHEN should_apply = 1 THEN 1 ELSE 0 END) AS apply_count,
                  SUM(CASE WHEN should_apply = 0 AND reasons_json NOT LIKE '%Skipped LLM screening%' THEN 1 ELSE 0 END) AS reject_count,
                  SUM(CASE WHEN should_apply = 0 AND reasons_json LIKE '%Skipped LLM screening%' THEN 1 ELSE 0 END) AS skipped_count
                FROM decisions
                {where}
                """,
                params,
            ).fetchone()

    def screening_counts(
        self,
        query: str = "",
        decision: str = "all",
        date_from: str = "",
        date_to: str = "",
    ) -> sqlite3.Row:
        where, params = _decision_filter_sql(query, decision, "all", date_from, date_to)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return conn.execute(
                f"""
                SELECT
                  COUNT(*) AS total,
                  SUM(CASE WHEN llm_used = 1 THEN 1 ELSE 0 END) AS llm_count,
                  SUM(CASE WHEN llm_used = 0 THEN 1 ELSE 0 END) AS local_count
                FROM decisions
                {where}
                """,
                params,
            ).fetchone()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  source_message_id TEXT NOT NULL,
                  project_date TEXT,
                  title TEXT NOT NULL,
                  application_url TEXT,
                  score REAL NOT NULL,
                  should_apply INTEGER NOT NULL,
                  reasons_json TEXT NOT NULL,
                  concerns_json TEXT NOT NULL,
                  llm_used INTEGER NOT NULL,
                  notice_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS applications (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  title TEXT NOT NULL,
                  application_url TEXT,
                  cover_note TEXT NOT NULL,
                  dry_run INTEGER NOT NULL,
                  status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  source_message_id TEXT NOT NULL,
                  title TEXT NOT NULL,
                  project_url TEXT,
                  description TEXT NOT NULL,
                  raw_text TEXT NOT NULL,
                  project_date TEXT
                );
                CREATE TABLE IF NOT EXISTS roles (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  project_id INTEGER,
                  source_message_id TEXT NOT NULL,
                  title TEXT NOT NULL,
                  project TEXT,
                  role TEXT,
                  location TEXT,
                  compensation TEXT,
                  application_url TEXT,
                  description TEXT NOT NULL,
                  raw_text TEXT NOT NULL,
                  project_date TEXT,
                  notice_json TEXT NOT NULL,
                  FOREIGN KEY(project_id) REFERENCES projects(id)
                );
                """
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(decisions)").fetchall()
            }
            if "project_date" not in columns:
                conn.execute("ALTER TABLE decisions ADD COLUMN project_date TEXT")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_decisions_project_date
                  ON decisions(project_date)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_roles_project_date
                  ON roles(project_date)
                """
            )


def _decision_filter_sql(
    query: str = "",
    decision: str = "all",
    method: str = "all",
    date_from: str = "",
    date_to: str = "",
) -> tuple[str, list[object]]:
    clauses = []
    params: list[object] = []
    if query:
        clauses.append("(title LIKE ? OR notice_json LIKE ? OR reasons_json LIKE ?)")
        pattern = f"%{query}%"
        params.extend([pattern, pattern, pattern])
    if decision == "apply":
        clauses.append("should_apply = 1")
    elif decision == "reject":
        clauses.append("should_apply = 0 AND reasons_json NOT LIKE ?")
        params.append("%Skipped LLM screening%")
    elif decision == "skipped":
        clauses.append("should_apply = 0 AND reasons_json LIKE ?")
        params.append("%Skipped LLM screening%")
    if method == "llm":
        clauses.append("llm_used = 1")
    elif method == "local":
        clauses.append("llm_used = 0")
    if date_from:
        clauses.append("date(COALESCE(project_date, created_at)) >= date(?)")
        params.append(date_from)
    if date_to:
        clauses.append("date(COALESCE(project_date, created_at)) <= date(?)")
        params.append(date_to)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params
