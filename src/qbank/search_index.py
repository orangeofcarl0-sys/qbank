"""Rebuildable SQLite FTS5 search index with explicit read/write modes."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from qbank.context import ProjectContext
from qbank.domain import RepositorySnapshot
from qbank.errors import DataValidationError
from qbank.models import DiagnosticCode, IndexHealth, ProjectConfig, Question, SearchHit
from qbank.repository import MarkdownQuestionRepository
from qbank.utils import atomic_write_text, utc_now


@dataclass(frozen=True, slots=True)
class IndexDocument:
    """The single authoritative projection of a question into SQLite."""

    id: str
    title: str
    stem: str
    answer: str
    solution: str
    topics: str
    chapter: str

    @classmethod
    def from_question(cls, question: Question) -> IndexDocument:
        """Project one domain question into stable index values."""
        return cls(
            id=question.id,
            title=question.title,
            stem=question.stem_md,
            answer=question.answer_md,
            solution=question.solution_md,
            topics=" ".join(question.topics),
            chapter=question.chapter or "",
        )

    @classmethod
    def columns(cls) -> tuple[str, ...]:
        """Return SQLite columns in their canonical order."""
        return tuple(cls.__dataclass_fields__)

    def values(self) -> tuple[str, ...]:
        """Return values in canonical SQLite column order."""
        return tuple(getattr(self, column) for column in self.columns())

    def comparable(self) -> tuple[str, ...]:
        """Return non-ID values used by stale-index diagnostics."""
        return self.values()[1:]


INDEX_COLUMNS = IndexDocument.columns()
SEARCHABLE_COLUMNS = INDEX_COLUMNS[1:]
COLUMN_SQL = ", ".join(INDEX_COLUMNS)
PLACEHOLDERS = ", ".join("?" for _ in INDEX_COLUMNS)
SCHEMA = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS question_fts USING fts5(
  id UNINDEXED,
  {", ".join(SEARCHABLE_COLUMNS)},
  tokenize = 'trigram'
);
CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tag_counts (
  tag TEXT PRIMARY KEY,
  count INTEGER NOT NULL CHECK (count >= 0)
);
CREATE TABLE IF NOT EXISTS tag_cooccurrence (
  left_tag TEXT NOT NULL,
  right_tag TEXT NOT NULL,
  count INTEGER NOT NULL CHECK (count >= 0),
  PRIMARY KEY (left_tag, right_tag),
  CHECK (left_tag < right_tag)
);
"""
INSERT_SQL = f"INSERT INTO question_fts({COLUMN_SQL}) VALUES ({PLACEHOLDERS})"


class SQLiteSearchIndex:
    """Filesystem-backed SQLite implementation of the search-index port."""

    def __init__(self, context: ProjectContext):
        self.context = context

    @property
    def path(self) -> Path:
        return self.context.paths.state / "index.sqlite"

    @property
    def dirty_marker(self) -> Path:
        return self.context.paths.state / "index.dirty"

    def mark_dirty(self, reason: str) -> None:
        """Record that authoritative files and the index diverged."""
        marker = {
            "code": "index_dirty",
            "timestamp": utc_now(),
            "reason": reason,
        }
        atomic_write_text(
            self.dirty_marker,
            json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
        )

    def clear_dirty(self) -> None:
        """Clear the durable marker after a successful full rebuild."""
        self.dirty_marker.unlink(missing_ok=True)

    def is_dirty(self) -> bool:
        """Return whether a durable dirty marker exists."""
        return self.dirty_marker.is_file()

    def open_readonly(self) -> sqlite3.Connection:
        """Open and verify an existing index without changing the filesystem."""
        if not self.path.is_file():
            raise DataValidationError(
                "index_unavailable: search index is missing; run 'qbank index rebuild'"
            )
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(uri, uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute(f"SELECT {COLUMN_SQL} FROM question_fts LIMIT 0")
            connection.execute("SELECT key, value FROM metadata LIMIT 0")
            connection.execute("SELECT tag, count FROM tag_counts LIMIT 0")
            connection.execute("SELECT left_tag, right_tag, count FROM tag_cooccurrence LIMIT 0")
            return connection
        except sqlite3.DatabaseError as exc:
            if connection is not None:
                connection.close()
            raise DataValidationError(
                "index_unavailable: search index is corrupt or incompatible; "
                "run 'qbank index rebuild'"
            ) from exc

    def open_existing_writable(self) -> sqlite3.Connection:
        """Open a verified existing index for a mutation-side update."""
        if not self.path.is_file():
            raise DataValidationError("search index is missing")
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            connection.execute(f"SELECT {COLUMN_SQL} FROM question_fts LIMIT 0")
            connection.execute("SELECT key, value FROM metadata LIMIT 0")
            connection.execute("SELECT tag, count FROM tag_counts LIMIT 0")
            connection.execute("SELECT left_tag, right_tag, count FROM tag_cooccurrence LIMIT 0")
            return connection
        except sqlite3.DatabaseError:
            if connection is not None:
                connection.close()
            raise

    def apply(
        self,
        *,
        questions: tuple[Question, ...] = (),
        deleted_ids: tuple[str, ...] = (),
        topics_by_question: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        """Apply all incremental changes in one SQLite transaction."""
        if not self.context.config.index.enabled:
            return
        with closing(self.open_existing_writable()) as connection, connection:
            changed_ids = [question.id for question in questions]
            for question_id in (*changed_ids, *deleted_ids):
                connection.execute("DELETE FROM question_fts WHERE id = ?", (question_id,))
            connection.executemany(
                INSERT_SQL,
                [IndexDocument.from_question(question).values() for question in questions],
            )
            projection_source = (
                self._authoritative_topics() if topics_by_question is None else topics_by_question
            )
            self._replace_tag_projection(connection, projection_source)
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES ('updated_at', ?)",
                (utc_now(),),
            )

    def rebuild(self, snapshot: RepositorySnapshot) -> int:
        """Build a replacement index from a clean repository snapshot."""
        snapshot.require_consistent()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        os.close(handle)
        temporary = Path(temporary_name)
        try:
            with closing(sqlite3.connect(temporary)) as connection, connection:
                connection.executescript(SCHEMA)
                connection.executemany(
                    INSERT_SQL,
                    [
                        IndexDocument.from_question(record.question).values()
                        for record in snapshot.records
                    ],
                )
                self._replace_tag_projection(
                    connection,
                    {
                        record.question.id: tuple(record.question.topics)
                        for record in snapshot.records
                    },
                )
                connection.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES ('updated_at', ?)",
                    (utc_now(),),
                )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.clear_dirty()
        return len(snapshot.records)

    def search(self, text: str, *, limit: int = 20) -> list[SearchHit]:
        """Search indexed question text and return ranked summaries."""
        if not self.context.config.index.enabled:
            raise DataValidationError("index_disabled: search index is disabled")
        if self.is_dirty():
            raise DataValidationError(
                "index_dirty: search index requires rebuild; run 'qbank index rebuild'"
            )
        terms = [term for term in text.split() if term]
        if not terms:
            raise DataValidationError("invalid_filter: search text must not be empty")
        with closing(self.open_readonly()) as connection:
            rows = (
                self._search_like(connection, terms, limit)
                if any(len(term) < 3 for term in terms)
                else self._search_fts(connection, text, limit)
            )
        return [SearchHit.model_validate(dict(row)) for row in rows]

    def ensure_searchable(self, snapshot: RepositorySnapshot) -> None:
        """Reject any projection that is not current with authoritative Markdown."""
        health = self.health(snapshot)
        if health.state == "clean":
            return
        if health.state == "disabled":
            code = DiagnosticCode.INDEX_DISABLED
        elif health.state == "dirty":
            code = DiagnosticCode.INDEX_DIRTY
        elif health.state == "stale":
            code = DiagnosticCode.INDEX_STALE
        else:
            code = DiagnosticCode.INDEX_UNAVAILABLE
        raise DataValidationError(f"{code}: {health.message}; run 'qbank index rebuild'")

    def documents(self) -> dict[str, tuple[str, ...]]:
        """Read all indexed projections without mutating the index."""
        with closing(self.open_readonly()) as connection:
            rows = connection.execute(f"SELECT {COLUMN_SQL} FROM question_fts").fetchall()
        return {
            str(row["id"]): tuple(str(row[column]) for column in INDEX_COLUMNS[1:]) for row in rows
        }

    def tag_projection(
        self,
    ) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
        """Read the rebuildable tag-count and co-occurrence projections."""
        with closing(self.open_readonly()) as connection:
            count_rows = connection.execute(
                "SELECT tag, count FROM tag_counts ORDER BY tag"
            ).fetchall()
            pair_rows = connection.execute(
                """
                SELECT left_tag, right_tag, count
                FROM tag_cooccurrence
                ORDER BY left_tag, right_tag
                """
            ).fetchall()
        return (
            {str(row["tag"]): int(row["count"]) for row in count_rows},
            {(str(row["left_tag"]), str(row["right_tag"])): int(row["count"]) for row in pair_rows},
        )

    def last_updated(self) -> str | None:
        """Return the index timestamp without creating or repairing it."""
        try:
            with closing(self.open_readonly()) as connection:
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'updated_at'"
                ).fetchone()
        except DataValidationError:
            return None
        return str(row["value"]) if row else None

    def health(self, snapshot: RepositorySnapshot | None = None) -> IndexHealth:
        """Inspect marker, readability, and optional source projection equality."""
        if not self.context.config.index.enabled:
            return IndexHealth(
                state="disabled",
                updated_at=None,
                documents={},
                message="index disabled",
            )
        if not self.path.is_file():
            return IndexHealth(
                state="missing",
                updated_at=None,
                documents={},
                message="index file is missing",
            )
        try:
            documents = self.documents()
            updated_at = self.last_updated()
        except DataValidationError as exc:
            return IndexHealth(
                state="corrupt",
                updated_at=None,
                documents={},
                message=str(exc),
            )
        if self.is_dirty():
            return IndexHealth(
                state="dirty",
                updated_at=updated_at,
                documents=documents,
                message="index rebuild required",
            )
        if snapshot is not None and not snapshot.invalid_sources:
            source_documents = {
                record.question.id: IndexDocument.from_question(record.question).comparable()
                for record in snapshot.records
            }
            expected_tags = _tag_projection(
                {record.question.id: tuple(record.question.topics) for record in snapshot.records}
            )
            indexed_tags: tuple[dict[str, int], dict[tuple[str, str], int]]
            try:
                indexed_tags = self.tag_projection()
            except DataValidationError:
                indexed_tags = ({}, {})
            if (
                snapshot.duplicate_ids
                or documents != source_documents
                or indexed_tags != expected_tags
            ):
                return IndexHealth(
                    state="stale",
                    updated_at=updated_at,
                    documents=documents,
                    message=f"source={len(source_documents)}, index={len(documents)}",
                )
        return IndexHealth(
            state="clean",
            updated_at=updated_at,
            documents=documents,
            message="index is current",
        )

    def _authoritative_topics(self) -> dict[str, tuple[str, ...]]:
        """Compatibility fallback for direct index-adapter callers."""
        snapshot = MarkdownQuestionRepository(self.context).scan()
        snapshot.require_consistent()
        return {record.question.id: tuple(record.question.topics) for record in snapshot.records}

    @staticmethod
    def _replace_tag_projection(
        connection: sqlite3.Connection,
        topics_by_question: Mapping[str, tuple[str, ...]],
    ) -> None:
        counts, pairs = _tag_projection(topics_by_question)
        connection.execute("DELETE FROM tag_counts")
        connection.execute("DELETE FROM tag_cooccurrence")
        connection.executemany(
            "INSERT INTO tag_counts(tag, count) VALUES (?, ?)",
            sorted(counts.items()),
        )
        connection.executemany(
            """
            INSERT INTO tag_cooccurrence(left_tag, right_tag, count)
            VALUES (?, ?, ?)
            """,
            [(*pair, count) for pair, count in sorted(pairs.items())],
        )

    @staticmethod
    def _search_like(
        connection: sqlite3.Connection,
        terms: list[str],
        limit: int,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        parameters: list[object] = []
        for term in terms:
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{escaped}%"
            clauses.append(
                "("
                + " OR ".join(f"{column} LIKE ? ESCAPE '\\'" for column in SEARCHABLE_COLUMNS)
                + ")"
            )
            parameters.extend([like] * len(SEARCHABLE_COLUMNS))
        return connection.execute(
            f"""
            SELECT id, title, chapter, topics, stem AS snippet, 0.0 AS rank
            FROM question_fts
            WHERE {" AND ".join(clauses)}
            ORDER BY id
            LIMIT ?
            """,
            (*parameters, limit),
        ).fetchall()

    @staticmethod
    def _search_fts(
        connection: sqlite3.Connection,
        text: str,
        limit: int,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT id, title, chapter, topics,
                   snippet(question_fts, 2, '<mark>', '</mark>', ' … ', 18) AS snippet,
                   bm25(question_fts) AS rank
            FROM question_fts
            WHERE question_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (_fts_query(text), limit),
        ).fetchall()


def _context(root: Path, config: ProjectConfig) -> ProjectContext:
    return ProjectContext.from_config(root, config)


def index_path(root: Path, config: ProjectConfig) -> Path:
    """Compatibility adapter returning the configured SQLite path."""
    return SQLiteSearchIndex(_context(root, config)).path


def dirty_path(root: Path, config: ProjectConfig) -> Path:
    """Compatibility adapter returning the dirty marker path."""
    return SQLiteSearchIndex(_context(root, config)).dirty_marker


def mark_dirty(root: Path, config: ProjectConfig, reason: str) -> None:
    """Compatibility adapter for dirty marker writes."""
    SQLiteSearchIndex(_context(root, config)).mark_dirty(reason)


def clear_dirty(root: Path, config: ProjectConfig) -> None:
    """Compatibility adapter for clearing the dirty marker."""
    SQLiteSearchIndex(_context(root, config)).clear_dirty()


def is_dirty(root: Path, config: ProjectConfig) -> bool:
    """Compatibility adapter for marker inspection."""
    return SQLiteSearchIndex(_context(root, config)).is_dirty()


def connect_index(root: Path, config: ProjectConfig) -> sqlite3.Connection:
    """Open an existing writable index; retained for Python API compatibility."""
    return SQLiteSearchIndex(_context(root, config)).open_existing_writable()


def update_question(
    root: Path,
    config: ProjectConfig,
    question: Question,
) -> None:
    """Compatibility adapter replacing one indexed question."""
    context = _context(root, config)
    topics = _topics_from_repository(context)
    topics[question.id] = tuple(question.topics)
    SQLiteSearchIndex(context).apply(
        questions=(question,),
        topics_by_question=topics,
    )


def remove_question(root: Path, config: ProjectConfig, question_id: str) -> None:
    """Compatibility adapter removing one indexed question."""
    context = _context(root, config)
    topics = _topics_from_repository(context)
    topics.pop(question_id, None)
    SQLiteSearchIndex(context).apply(
        deleted_ids=(question_id,),
        topics_by_question=topics,
    )


def apply_index_changes(
    root: Path,
    config: ProjectConfig,
    *,
    questions: tuple[Question, ...] = (),
    deleted_ids: tuple[str, ...] = (),
) -> None:
    """Apply a batch of changes in one SQLite transaction."""
    context = _context(root, config)
    topics = _topics_from_repository(context)
    for question_id in deleted_ids:
        topics.pop(question_id, None)
    topics.update({question.id: tuple(question.topics) for question in questions})
    SQLiteSearchIndex(context).apply(
        questions=questions,
        deleted_ids=deleted_ids,
        topics_by_question=topics,
    )


def rebuild_index(root: Path, config: ProjectConfig) -> int:
    """Compatibility adapter rebuilding from authoritative Markdown."""
    context = _context(root, config)
    snapshot = MarkdownQuestionRepository(context).scan()
    return SQLiteSearchIndex(context).rebuild(snapshot)


def search(
    root: Path,
    config: ProjectConfig,
    text: str,
    *,
    limit: int = 20,
) -> list[SearchHit]:
    """Compatibility adapter for full-text search."""
    context = _context(root, config)
    index = SQLiteSearchIndex(context)
    snapshot = MarkdownQuestionRepository(context).scan()
    snapshot.require_consistent()
    index.ensure_searchable(snapshot)
    return index.search(text, limit=limit)


def last_updated(root: Path, config: ProjectConfig) -> str | None:
    """Compatibility adapter for read-only timestamp inspection."""
    return SQLiteSearchIndex(_context(root, config)).last_updated()


def read_index_documents(
    root: Path,
    config: ProjectConfig,
) -> dict[str, tuple[str, ...]]:
    """Return canonical indexed projections for diagnostics."""
    return SQLiteSearchIndex(_context(root, config)).documents()


def index_health(
    root: Path,
    config: ProjectConfig,
    snapshot: RepositorySnapshot | None = None,
) -> IndexHealth:
    """Return non-mutating index health for status and doctor."""
    return SQLiteSearchIndex(_context(root, config)).health(snapshot)


def _fts_query(text: str) -> str:
    terms = [term for term in text.split() if term]
    if not terms:
        return '""'
    return " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


def _topics_from_repository(context: ProjectContext) -> dict[str, tuple[str, ...]]:
    snapshot = MarkdownQuestionRepository(context).scan()
    snapshot.require_consistent()
    return {record.question.id: tuple(record.question.topics) for record in snapshot.records}


def _tag_projection(
    topics_by_question: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    """Build deterministic tag projections without storing question relations."""
    counts: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    for topics in topics_by_question.values():
        unique = sorted(set(topics))
        counts.update(unique)
        for index, left in enumerate(unique):
            for right in unique[index + 1 :]:
                pairs[(left, right)] += 1
    return dict(counts), dict(pairs)
