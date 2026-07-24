from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .candidate_models import (
    CalibrationProposal,
    CandidateFeatures,
    CandidateInput,
    CandidateScore,
    HumanFeedback,
    RequirementMatch,
)
from .identifiers import project_key as build_project_key
from .identifiers import role_key as build_role_key
from .models import CastingNotice, ProjectNotice


class DecisionStore:
    def __init__(self, path: Path):
        self.path = path
        self._ensure_schema()

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
                  project_key, shooting_locations, shooting_dates
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project.source_message_id,
                    project.title,
                    project.project_url,
                    project.description,
                    project.raw_text,
                    project.project_date.isoformat() if project.project_date else None,
                    project_key,
                    project.shooting_locations,
                    project.shooting_dates,
                ),
            )
            return int(cursor.lastrowid)

    def upsert_project(self, project: ProjectNotice, seen_date: date) -> int:
        project_key = project.project_key or build_project_key(
            project.title,
            project.project_url,
            project.project_date,
        )
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM projects WHERE project_key = ? ORDER BY id DESC LIMIT 1",
                (project_key,),
            ).fetchone()
            values = (
                project.source_message_id,
                project.title,
                project.project_url,
                project.description,
                project.raw_text,
                project.project_date.isoformat() if project.project_date else None,
                project_key,
                project.shooting_locations,
                project.shooting_dates,
                seen_date.isoformat(),
            )
            if row is None:
                cursor = conn.execute(
                    """
                    INSERT INTO projects (
                      source_message_id, title, project_url, description, raw_text,
                      project_date, project_key, shooting_locations, shooting_dates,
                      last_seen_date
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                return int(cursor.lastrowid)
            project_id = int(row[0])
            conn.execute(
                """
                UPDATE projects
                SET source_message_id = ?, title = ?, project_url = ?, description = ?,
                    raw_text = ?, project_date = ?, project_key = ?,
                    shooting_locations = COALESCE(?, shooting_locations),
                    shooting_dates = COALESCE(?, shooting_dates), last_seen_date = ?
                WHERE id = ?
                """,
                (*values, project_id),
            )
            return project_id

    def update_project_info(
        self,
        project_id: int,
        shooting_locations: str | None = None,
        shooting_dates: str | None = None,
    ) -> None:
        if not shooting_locations and not shooting_dates:
            return
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE projects
                SET shooting_locations = COALESCE(?, shooting_locations),
                    shooting_dates = COALESCE(?, shooting_dates)
                WHERE id = ?
                """,
                (shooting_locations, shooting_dates, project_id),
            )

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
                  notice_json, shooting_locations, shooting_dates
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    notice.shooting_locations,
                    notice.shooting_dates,
                ),
            )
            return int(cursor.lastrowid)

    def upsert_role(self, project_id: int, notice: CastingNotice) -> int:
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
            row = conn.execute(
                "SELECT id FROM roles WHERE role_key = ? ORDER BY id DESC LIMIT 1",
                (role_key,),
            ).fetchone()
            if row is None:
                return self.record_role(project_id, notice)
            role_id = int(row[0])
            conn.execute(
                """
                UPDATE roles
                SET project_id = ?, project_key = ?, source_message_id = ?, title = ?,
                    project = ?, role = ?, location = ?, compensation = ?,
                    application_url = ?, description = ?, raw_text = ?, project_date = ?,
                    notice_json = ?, shooting_locations = ?, shooting_dates = ?
                WHERE id = ?
                """,
                (
                    project_id,
                    project_key,
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
                    notice.shooting_locations,
                    notice.shooting_dates,
                    role_id,
                ),
            )
            return role_id

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

    def record_candidate(
        self,
        candidate: CandidateInput,
        features: CandidateFeatures,
        requirement_matches: list[RequirementMatch],
        score: CandidateScore,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO candidates (
                  candidate_type, title, source_project_id, source_role_id,
                  project_key, role_key, notice_json, features_json,
                  requirement_match_json, score_json, overall_score, score_band,
                  rank_score, rank_position, draft_suggestion, scoring_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_type.value,
                    candidate.title,
                    candidate.source_project_id,
                    candidate.source_role_id,
                    candidate.project_key,
                    candidate.role_key,
                    json.dumps(asdict(candidate.notice), default=str),
                    json.dumps(asdict(features), default=str),
                    json.dumps(
                        [
                            asdict(match) | {"status": match.status.value}
                            for match in requirement_matches
                        ],
                        default=str,
                    ),
                    json.dumps(asdict(score) | {"score_band": score.score_band.value}, default=str),
                    score.overall_score,
                    score.score_band.value,
                    score.rank_score,
                    score.rank_position,
                    int(score.draft_suggestion),
                    score.scoring_version,
                ),
            )
            return int(cursor.lastrowid)

    def search_candidates(
        self,
        query: str = "",
        band: str = "all",
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        clauses = []
        params: list[object] = []
        if query:
            clauses.append("(lower(title) LIKE lower(?) OR lower(notice_json) LIKE lower(?))")
            params.extend([f"%{query}%", f"%{query}%"])
        if band != "all":
            clauses.append("score_band = ?")
            params.append(band)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return list(
                conn.execute(
                    f"""
                    SELECT *
                    FROM candidates
                    {where}
                    ORDER BY COALESCE(rank_position, 999999), overall_score DESC, id DESC
                    LIMIT ?
                    """,
                    params,
                )
            )

    def candidate_rescore_sources_for_date(
        self,
        target_date: str,
    ) -> list[tuple[ProjectNotice, list[tuple[int, CastingNotice]], int]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            project_rows = list(
                conn.execute(
                    """
                    SELECT *
                    FROM projects
                    WHERE date(COALESCE(last_seen_date, project_date, created_at)) = date(?)
                    ORDER BY id
                    """,
                    (target_date,),
                )
            )
            sources = []
            for project_row in project_rows:
                role_rows = list(
                    conn.execute(
                        """
                        SELECT *
                        FROM roles
                        WHERE project_id = ?
                        ORDER BY id
                        """,
                        (project_row["id"],),
                    )
                )
                sources.append(
                    (
                        _project_from_row(project_row),
                        [(int(row["id"]), _role_from_row(row)) for row in role_rows],
                        int(project_row["id"]),
                    )
                )
            return sources

    def candidate_rows_for_date(self, target_date: str) -> list[sqlite3.Row]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return list(
                conn.execute(
                    """
                    SELECT c.*
                    FROM candidates c
                    JOIN projects p ON p.id = c.source_project_id
                    WHERE date(COALESCE(p.last_seen_date, p.project_date, p.created_at)) = date(?)
                    ORDER BY c.id
                    """,
                    (target_date,),
                )
            )

    def update_candidate_rank(self, candidate_id: int, rank_score: int, rank_position: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE candidates
                SET rank_score = ?, rank_position = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (rank_score, rank_position, candidate_id),
            )

    def clear_candidates_for_date(self, target_date: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM candidates
                WHERE source_project_id IN (
                  SELECT id
                  FROM projects
                  WHERE date(COALESCE(last_seen_date, project_date, created_at)) = date(?)
                )
                """,
                (target_date,),
            )
            return int(cursor.rowcount)

    def record_candidate_feedback(self, feedback: HumanFeedback) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO candidate_feedback (
                  candidate_id, agent_score, human_score, score_delta,
                  affected_components_json, failure_modes_json,
                  free_text_reason, calibration_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback.candidate_id,
                    feedback.agent_score,
                    feedback.human_score,
                    feedback.score_delta,
                    json.dumps(feedback.affected_components),
                    json.dumps(feedback.failure_modes),
                    feedback.free_text_reason,
                    feedback.calibration_status,
                ),
            )
            return int(cursor.lastrowid)

    def feedback_patterns(self, min_examples: int = 2) -> list[sqlite3.Row]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return list(
                conn.execute(
                    """
                    SELECT
                      affected_component.value AS affected_component,
                      failure_mode.value AS failure_mode,
                      COUNT(*) AS example_count,
                      AVG(candidate_feedback.score_delta) AS average_delta
                    FROM candidate_feedback
                    JOIN json_each(candidate_feedback.affected_components_json) AS affected_component
                    JOIN json_each(candidate_feedback.failure_modes_json) AS failure_mode
                    WHERE affected_component.value IS NOT NULL
                      AND affected_component.value != ''
                      AND failure_mode.value IS NOT NULL
                      AND failure_mode.value != ''
                    GROUP BY affected_component, failure_mode
                    HAVING COUNT(*) >= ?
                    ORDER BY ABS(AVG(candidate_feedback.score_delta)) DESC, COUNT(*) DESC
                    """,
                    (min_examples,),
                )
            )

    def record_calibration_proposal(self, proposal: CalibrationProposal) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO calibration_proposals (
                  pattern_key, example_count, average_delta, affected_component,
                  failure_mode, proposal_text, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.pattern_key,
                    proposal.example_count,
                    proposal.average_delta,
                    proposal.affected_component,
                    proposal.failure_mode,
                    proposal.proposal_text,
                    proposal.status,
                ),
            )
            return int(cursor.lastrowid)

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
                  role_key TEXT,
                  shooting_locations TEXT,
                  shooting_dates TEXT,
                  final_bucket TEXT,
                  classifier_json TEXT,
                  reviewer_json TEXT,
                  reviewer_impact TEXT,
                  schema_error TEXT
                );
                CREATE TABLE IF NOT EXISTS applications (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  title TEXT NOT NULL,
                  application_url TEXT,
                  cover_note TEXT NOT NULL,
                  dry_run INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  blocker_reason TEXT
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
                  project_key TEXT,
                  shooting_locations TEXT,
                  shooting_dates TEXT,
                  last_seen_date TEXT
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
                  shooting_locations TEXT,
                  shooting_dates TEXT,
                  FOREIGN KEY(project_id) REFERENCES projects(id)
                );
                CREATE TABLE IF NOT EXISTS candidates (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  candidate_type TEXT NOT NULL,
                  title TEXT NOT NULL,
                  source_project_id INTEGER NOT NULL,
                  source_role_id INTEGER,
                  project_key TEXT,
                  role_key TEXT,
                  notice_json TEXT NOT NULL,
                  features_json TEXT NOT NULL,
                  requirement_match_json TEXT NOT NULL,
                  score_json TEXT NOT NULL,
                  overall_score INTEGER NOT NULL,
                  score_band TEXT NOT NULL,
                  rank_score INTEGER,
                  rank_position INTEGER,
                  draft_suggestion INTEGER NOT NULL,
                  scoring_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidate_feedback (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  candidate_id INTEGER NOT NULL,
                  agent_score INTEGER NOT NULL,
                  human_score INTEGER NOT NULL,
                  score_delta INTEGER NOT NULL,
                  affected_components_json TEXT NOT NULL,
                  failure_modes_json TEXT NOT NULL,
                  free_text_reason TEXT NOT NULL,
                  calibration_status TEXT NOT NULL,
                  FOREIGN KEY(candidate_id) REFERENCES candidates(id)
                );
                CREATE TABLE IF NOT EXISTS calibration_proposals (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  pattern_key TEXT NOT NULL,
                  example_count INTEGER NOT NULL,
                  average_delta REAL NOT NULL,
                  affected_component TEXT NOT NULL,
                  failure_mode TEXT NOT NULL,
                  proposal_text TEXT NOT NULL,
                  status TEXT NOT NULL
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
                "shooting_locations": "TEXT",
                "shooting_dates": "TEXT",
                "final_bucket": "TEXT",
                "classifier_json": "TEXT",
                "reviewer_json": "TEXT",
                "reviewer_impact": "TEXT",
                "schema_error": "TEXT",
            }.items():
                if column_name not in columns:
                    conn.execute(f"ALTER TABLE decisions ADD COLUMN {column_name} {column_type}")
            project_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()
            }
            if "project_key" not in project_columns:
                conn.execute("ALTER TABLE projects ADD COLUMN project_key TEXT")
            for column_name in ("shooting_locations", "shooting_dates"):
                if column_name not in project_columns:
                    conn.execute(f"ALTER TABLE projects ADD COLUMN {column_name} TEXT")
            if "last_seen_date" not in project_columns:
                conn.execute("ALTER TABLE projects ADD COLUMN last_seen_date TEXT")
            role_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(roles)").fetchall()
            }
            for column_name in ("project_key", "role_key"):
                if column_name not in role_columns:
                    conn.execute(f"ALTER TABLE roles ADD COLUMN {column_name} TEXT")
            for column_name in ("shooting_locations", "shooting_dates"):
                if column_name not in role_columns:
                    conn.execute(f"ALTER TABLE roles ADD COLUMN {column_name} TEXT")
            application_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(applications)").fetchall()
            }
            if "blocker_reason" not in application_columns:
                conn.execute("ALTER TABLE applications ADD COLUMN blocker_reason TEXT")
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_score ON candidates(overall_score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_band ON candidates(score_band)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_feedback_candidate ON candidate_feedback(candidate_id)")


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

def _project_from_row(row: sqlite3.Row) -> ProjectNotice:
    return ProjectNotice(
        source_message_id=row["source_message_id"],
        title=row["title"],
        project_url=row["project_url"],
        description=row["description"],
        raw_text=row["raw_text"],
        project_date=_date_from_text(row["project_date"]),
        project_key=row["project_key"] or "",
        shooting_locations=row["shooting_locations"],
        shooting_dates=row["shooting_dates"],
    )


def _role_from_row(row: sqlite3.Row) -> CastingNotice:
    try:
        notice = json.loads(row["notice_json"])
    except (TypeError, json.JSONDecodeError):
        notice = {}
    data = {
        "source_message_id": row["source_message_id"],
        "title": row["title"],
        "project": row["project"],
        "role": row["role"],
        "location": row["location"],
        "compensation": row["compensation"],
        "application_url": row["application_url"],
        "description": row["description"],
        "raw_text": row["raw_text"],
        "project_date": _date_from_text(row["project_date"]),
        "project_key": row["project_key"] or "",
        "role_key": row["role_key"] or "",
        "shooting_locations": row["shooting_locations"],
        "shooting_dates": row["shooting_dates"],
    }
    if isinstance(notice.get("project_labels"), list):
        data["project_labels"] = notice["project_labels"]
    return CastingNotice(**data)


def _date_from_text(value: str | None):
    if not value:
        return None
    from datetime import date

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
