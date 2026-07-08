from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .identifiers import project_key as build_project_key
from .identifiers import role_key as build_role_key
from .models import ApplicationDraft, CastingNotice, ProjectNotice, ReviewDecision, ScreeningDecision


class DecisionStore:
    def __init__(self, path: Path):
        self.path = path
        self._ensure_schema()

    def record_decision(self, decision: ScreeningDecision) -> int:
        project_key = decision.notice.project_key or build_project_key(
            decision.notice.project or decision.notice.title,
            decision.notice.application_url,
            decision.notice.project_date,
        )
        role_key = decision.notice.role_key or build_role_key(
            project_key,
            decision.notice.application_url,
            decision.notice.role,
            decision.notice.title,
            decision.notice.description,
        )
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO decisions (
                  source_message_id, title, application_url, score, should_apply,
                  reasons_json, concerns_json, llm_used, notice_json, project_date,
                  project_key, role_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps({**asdict(decision.notice), "project_key": project_key, "role_key": role_key}, default=str),
                    decision.notice.project_date.isoformat()
                    if decision.notice.project_date
                    else None,
                    project_key,
                    role_key,
                ),
            )
            return int(cursor.lastrowid)

    def record_project(self, project: ProjectNotice) -> int:
        project_key = project.project_key or build_project_key(
            project.title,
            project.project_url,
            project.project_date,
        )
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO projects (
                  source_message_id, title, project_url, description, raw_text, project_date,
                  project_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project.source_message_id,
                    project.title,
                    project.project_url,
                    project.description,
                    project.raw_text,
                    project.project_date.isoformat() if project.project_date else None,
                    project_key,
                ),
            )
            return int(cursor.lastrowid)

    def record_role(self, project_id: int, notice: CastingNotice) -> int:
        project_key = notice.project_key or build_project_key(
            notice.project or notice.title,
            notice.application_url,
            notice.project_date,
        )
        role_key = notice.role_key or build_role_key(
            project_key,
            notice.application_url,
            notice.role,
            notice.title,
            notice.description,
        )
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO roles (
                  project_id, project_key, role_key, source_message_id, title, project, role, location,
                  compensation, application_url, description, raw_text, project_date,
                  notice_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    project_key,
                    role_key,
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
                    json.dumps({**asdict(notice), "project_key": project_key, "role_key": role_key}, default=str),
                ),
            )
            return int(cursor.lastrowid)

    def project_exists(self, project_key: str) -> bool:
        if not project_key:
            return False
        with self._connect() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM projects WHERE project_key = ? LIMIT 1",
                    (project_key,),
                ).fetchone()
                is not None
            )

    def project_notice_exists(self, project: ProjectNotice) -> bool:
        if self.project_exists(project.project_key):
            return True
        if not project.title or project.project_date is None:
            return False
        with self._connect() as conn:
            return (
                conn.execute(
                    """
                    SELECT 1
                    FROM projects
                    WHERE lower(title) = lower(?)
                      AND date(COALESCE(project_date, created_at)) = date(?)
                    LIMIT 1
                    """,
                    (project.title, project.project_date.isoformat()),
                ).fetchone()
                is not None
            )

    def role_exists(self, role_key: str) -> bool:
        if not role_key:
            return False
        with self._connect() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM roles WHERE role_key = ? LIMIT 1",
                    (role_key,),
                ).fetchone()
                is not None
            )

    def decision_exists(self, role_key: str) -> bool:
        if not role_key:
            return False
        with self._connect() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM decisions WHERE role_key = ? LIMIT 1",
                    (role_key,),
                ).fetchone()
                is not None
            )

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

    def record_review(self, decision_id: int, review: ReviewDecision) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE decisions
                SET reviewer_status = ?,
                    reviewer_score = ?,
                    reviewer_reasons_json = ?,
                    reviewer_concerns_json = ?,
                    reviewer_model = ?
                WHERE id = ?
                """,
                (
                    review.status,
                    review.score,
                    json.dumps(review.reasons),
                    json.dumps(review.concerns),
                    review.model,
                    decision_id,
                ),
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
                    SELECT
                      d.id, d.created_at, d.project_date, d.title, d.application_url,
                      d.score, d.should_apply, d.reasons_json, d.concerns_json,
                      d.llm_used, d.notice_json, d.project_key, d.role_key,
                      d.reviewer_status, d.reviewer_score,
                      d.reviewer_reasons_json, d.reviewer_concerns_json, d.reviewer_model,
                      (
                        SELECT a.status
                        FROM applications a
                        WHERE a.title = d.title
                        ORDER BY a.id DESC
                        LIMIT 1
                      ) AS application_status
                    FROM decisions d
                    {where}
                    ORDER BY d.id DESC
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
                  SUM(CASE WHEN d.should_apply = 1 AND EXISTS (
                    SELECT 1 FROM applications a
                    WHERE a.title = d.title AND a.status = 'submitted_backstage'
                  ) THEN 1 ELSE 0 END) AS applied_count,
                  SUM(CASE WHEN d.should_apply = 1
                    AND d.reviewer_status = 'approved'
                    AND NOT EXISTS (
                    SELECT 1 FROM applications a
                    WHERE a.title = d.title AND a.status = 'submitted_backstage'
                  ) THEN 1 ELSE 0 END) AS passed_count,
                  SUM(CASE WHEN d.should_apply = 1
                    AND COALESCE(d.reviewer_status, '') IN ('rejected', 'hold', 'error', '')
                    AND NOT EXISTS (
                      SELECT 1 FROM applications a
                      WHERE a.title = d.title AND a.status = 'submitted_backstage'
                    )
                  THEN 1 ELSE 0 END) AS needs_check_count,
                  SUM(CASE WHEN d.should_apply = 0 THEN 1 ELSE 0 END) AS reject_count
                FROM decisions d
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
                  SUM(CASE WHEN d.llm_used = 1 THEN 1 ELSE 0 END) AS llm_count,
                  SUM(CASE WHEN d.llm_used = 0 THEN 1 ELSE 0 END) AS local_count
                FROM decisions d
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
                  reviewer_status TEXT,
                  reviewer_score REAL,
                  reviewer_reasons_json TEXT,
                  reviewer_concerns_json TEXT,
                  reviewer_model TEXT,
                  notice_json TEXT NOT NULL,
                  project_key TEXT,
                  role_key TEXT
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
                  project_date TEXT,
                  project_key TEXT
                );
                CREATE TABLE IF NOT EXISTS roles (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  project_id INTEGER,
                  project_key TEXT,
                  role_key TEXT,
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
            for column_name, column_type in {
                "reviewer_status": "TEXT",
                "reviewer_score": "REAL",
                "reviewer_reasons_json": "TEXT",
                "reviewer_concerns_json": "TEXT",
                "reviewer_model": "TEXT",
                "project_key": "TEXT",
                "role_key": "TEXT",
            }.items():
                if column_name not in columns:
                    conn.execute(f"ALTER TABLE decisions ADD COLUMN {column_name} {column_type}")
            project_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()
            }
            if "project_key" not in project_columns:
                conn.execute("ALTER TABLE projects ADD COLUMN project_key TEXT")
            role_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(roles)").fetchall()
            }
            for column_name in ("project_key", "role_key"):
                if column_name not in role_columns:
                    conn.execute(f"ALTER TABLE roles ADD COLUMN {column_name} TEXT")
            _backfill_keys(conn)
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_project_key ON projects(project_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_roles_role_key ON roles(role_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decisions_role_key ON decisions(role_key)")


def _backfill_keys(conn: sqlite3.Connection) -> None:
    for row in conn.execute(
        """
        SELECT id, title, project_url, project_date
        FROM projects
        WHERE project_key IS NULL OR project_key = ''
        """
    ).fetchall():
        conn.execute(
            "UPDATE projects SET project_key = ? WHERE id = ?",
            (build_project_key(row[1], row[2], _date_from_text(row[3])), row[0]),
        )

    for row in conn.execute(
        """
        SELECT id, title, project, role, application_url, description, project_date
        FROM roles
        WHERE project_key IS NULL OR project_key = '' OR role_key IS NULL OR role_key = ''
        """
    ).fetchall():
        project_key = build_project_key(row[2] or row[1], row[4], _date_from_text(row[6]))
        role_key = build_role_key(project_key, row[4], row[3], row[1], row[5])
        conn.execute(
            "UPDATE roles SET project_key = ?, role_key = ? WHERE id = ?",
            (project_key, role_key, row[0]),
        )

    for row in conn.execute(
        """
        SELECT id, title, application_url, project_date, notice_json
        FROM decisions
        WHERE project_key IS NULL OR project_key = '' OR role_key IS NULL OR role_key = ''
        """
    ).fetchall():
        try:
            notice = json.loads(row[4])
        except json.JSONDecodeError:
            notice = {}
        project_name = notice.get("project") or row[1]
        role_name = notice.get("role")
        description = notice.get("description") or notice.get("raw_text") or ""
        project_key = notice.get("project_key") or build_project_key(
            project_name,
            row[2],
            _date_from_text(row[3]),
        )
        role_key = notice.get("role_key") or build_role_key(
            project_key,
            row[2],
            role_name,
            row[1],
            description,
        )
        if notice:
            notice["project_key"] = project_key
            notice["role_key"] = role_key
        conn.execute(
            "UPDATE decisions SET project_key = ?, role_key = ?, notice_json = ? WHERE id = ?",
            (project_key, role_key, json.dumps(notice, default=str) if notice else row[4], row[0]),
        )

    project_key_by_title_and_date: dict[tuple[str, str | None], str] = {}
    for row in conn.execute(
        """
        SELECT project_date, notice_json, project_key
        FROM decisions
        WHERE project_key IS NOT NULL AND project_key != ''
        """
    ).fetchall():
        try:
            notice = json.loads(row[1])
        except json.JSONDecodeError:
            continue
        project_title = notice.get("project")
        if project_title:
            project_key_by_title_and_date[(project_title.lower(), row[0])] = row[2]

    for row in conn.execute(
        """
        SELECT id, title, project_date, project_key
        FROM projects
        WHERE project_key IS NULL OR project_key = '' OR project_key LIKE '____-__-__:%'
        """
    ).fetchall():
        key = project_key_by_title_and_date.get((row[1].lower(), row[2]))
        if key:
            conn.execute("UPDATE projects SET project_key = ? WHERE id = ?", (key, row[0]))


def _date_from_text(value: str | None):
    if not value:
        return None
    from datetime import date

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


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
        clauses.append("(d.title LIKE ? OR d.notice_json LIKE ? OR d.reasons_json LIKE ?)")
        pattern = f"%{query}%"
        params.extend([pattern, pattern, pattern])
    if decision in {"apply", "passed", "approved"}:
        clauses.append(
            """
            d.should_apply = 1 AND d.reviewer_status = 'approved' AND NOT EXISTS (
              SELECT 1 FROM applications a
              WHERE a.title = d.title AND a.status = 'submitted_backstage'
            )
            """
        )
    elif decision == "applied":
        clauses.append(
            """
            d.should_apply = 1 AND EXISTS (
              SELECT 1 FROM applications a
              WHERE a.title = d.title AND a.status = 'submitted_backstage'
            )
            """
        )
    elif decision in {"needs_check", "hold"}:
        clauses.append(
            """
            d.should_apply = 1
            AND COALESCE(d.reviewer_status, '') IN ('rejected', 'hold', 'error', '')
            AND NOT EXISTS (
              SELECT 1 FROM applications a
              WHERE a.title = d.title AND a.status = 'submitted_backstage'
            )
            """
        )
    elif decision == "reject":
        clauses.append("d.should_apply = 0")
    elif decision == "skipped":
        clauses.append("d.should_apply = 0")
    if method == "llm":
        clauses.append("d.llm_used = 1")
    elif method == "local":
        clauses.append("d.llm_used = 0")
    if date_from:
        clauses.append("date(COALESCE(d.project_date, d.created_at)) >= date(?)")
        params.append(date_from)
    if date_to:
        clauses.append("date(COALESCE(d.project_date, d.created_at)) <= date(?)")
        params.append(date_to)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params
