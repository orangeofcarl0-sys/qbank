"""Independent authoritative paper persistence with lock and dedicated history."""

from __future__ import annotations

import builtins
import json
import time
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

from qbank.application.assets import AssetApplicationService
from qbank.application.locking import RepositoryWriteLockPort
from qbank.application.revision import repository_revision
from qbank.context import ProjectContext
from qbank.errors import (
    ConflictError,
    DataValidationError,
    QuestionNotFoundError,
    RepositoryRevisionChangedError,
)
from qbank.models import (
    Paper,
    PaperHistoryEntry,
    PaperQuestion,
    PaperSection,
    PaperValidationReport,
)
from qbank.papers import load_paper, validate_paper_in_context
from qbank.transaction import MutationTransaction
from qbank.utils import reject_reparse_points, sha256_text, utc_now
from qbank.yaml_io import dump_yaml


class PaperApplicationService:
    """Validate and persist paper definitions through one shared write lock."""

    def __init__(
        self,
        context: ProjectContext,
        assets: AssetApplicationService,
        lock: RepositoryWriteLockPort,
    ) -> None:
        self.context = context
        self.assets = assets
        self.lock = lock

    def list(self) -> builtins.list[Path]:
        return sorted(self.context.paths.papers.rglob("*.yaml"), key=lambda item: item.as_posix())

    def resolve(self, value: str | Path) -> Path:
        raw = str(value)
        pure = PurePosixPath(raw.replace("\\", "/"))
        absolute = PureWindowsPath(raw).is_absolute() or pure.is_absolute()
        if ".." in pure.parts:
            raise DataValidationError("paper path must not contain '..'")
        candidate = Path(raw) if absolute else self.context.root.joinpath(*pure.parts)
        if not absolute and not candidate.is_relative_to(self.context.paths.papers):
            candidate = self.context.paths.papers.joinpath(*pure.parts)
        try:
            reject_reparse_points(candidate, boundary=self.context.root)
        except ValueError as exc:
            raise DataValidationError("paper path contains an unsupported reparse point") from exc
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.context.paths.papers.resolve()):
            raise DataValidationError("paper path escapes the configured papers directory")
        if resolved.suffix.casefold() not in {".yaml", ".yml"}:
            raise DataValidationError("paper path must use .yaml or .yml")
        return resolved

    def find(self, paper_id: str) -> Path:
        if any(character in paper_id for character in ("/", "\\")):
            path = self.resolve(paper_id)
            if path.is_file():
                return path
            raise QuestionNotFoundError(f"paper not found: {paper_id}")
        matches = [
            path
            for pattern in ("*.yaml", "*.yml")
            for path in self.context.paths.papers.rglob(pattern)
            if path.stem == paper_id
        ]
        if not matches:
            raise QuestionNotFoundError(f"paper not found: {paper_id}")
        if len(matches) > 1:
            raise DataValidationError(f"ambiguous paper id: {paper_id}")
        return matches[0]

    def get(self, paper_id: str) -> Paper:
        return load_paper(self.find(paper_id))

    def validate(self, paper: Paper) -> PaperValidationReport:
        return validate_paper_in_context(self.context, paper, assets=self.assets)

    def save(
        self,
        path: str | Path,
        paper: Paper,
        *,
        dry_run: bool,
        command: str,
        _verified_revision: str | None = None,
    ) -> Paper:
        target = self.resolve(path)
        report = self.validate(paper)
        if not report.ok:
            raise DataValidationError(f"paper validation failed: {report.issues}")
        expected_revision = (
            None if _verified_revision is not None or dry_run else repository_revision(self.context)
        )
        before_text = target.read_text(encoding="utf-8") if target.is_file() else None
        previous = load_paper(target) if before_text is not None else None
        rendered = dump_yaml(paper.model_dump(mode="json", exclude_none=True)) + "\n"
        if dry_run or before_text == rendered:
            return paper
        with self.lock.hold(command):
            if expected_revision is not None:
                self._require_revision(expected_revision)
            transaction = MutationTransaction.for_context(self.context)
            transaction.write(target, rendered)
            history_path, history_text = self._history(
                target,
                previous,
                paper,
                before_text,
                rendered,
                command,
            )
            transaction.write(history_path, history_text)
            transaction.commit()
        return paper

    def create(
        self,
        path: str | Path,
        title: str,
        question_ids: builtins.list[str],
        *,
        dry_run: bool,
        command: str,
    ) -> Paper:
        target = self.resolve(path)
        if target.exists():
            raise ConflictError(f"paper file already exists: {target}")
        paper = Paper(
            schema_version="1.0",
            title=title,
            sections=[
                PaperSection(
                    title="题目",
                    questions=[PaperQuestion(id=value, score=1) for value in question_ids],
                )
            ],
        )
        return self.save(target, paper, dry_run=dry_run, command=command)

    def add_questions(
        self,
        path: str | Path,
        question_ids: builtins.list[str],
        *,
        dry_run: bool,
        command: str,
    ) -> Paper:
        target = self.resolve(path)
        paper = load_paper(target)
        known = {item.id for section in paper.sections for item in section.questions}
        additions = [
            PaperQuestion(id=value, score=1) for value in question_ids if value not in known
        ]
        first = paper.sections[0]
        sections = [first.model_copy(update={"questions": [*first.questions, *additions]})]
        sections.extend(paper.sections[1:])
        updated = paper.model_copy(update={"sections": sections})
        return self.save(target, updated, dry_run=dry_run, command=command)

    def history(self, paper_id: str) -> builtins.list[PaperHistoryEntry]:
        self.find(paper_id)
        root = self.context.paths.state / "paper-history"
        events: builtins.list[PaperHistoryEntry] = []
        if not root.is_dir():
            return events
        for path in sorted(root.glob("*.json")):
            try:
                event = PaperHistoryEntry.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                continue
            if event.paper_id == Path(paper_id).stem:
                events.append(event)
        return events

    def _require_revision(self, expected: str) -> None:
        current = repository_revision(self.context)
        if current != expected:
            raise RepositoryRevisionChangedError(
                "repository_revision_changed: repository changed before paper commit",
                details={"expected": expected, "current": current},
            )

    def _history(
        self,
        path: Path,
        previous: Paper | None,
        paper: Paper,
        before_text: str | None,
        after_text: str,
        command: str,
    ) -> tuple[Path, str]:
        before = previous.model_dump(mode="json") if previous is not None else {}
        after = paper.model_dump(mode="json")
        event = PaperHistoryEntry(
            timestamp=utc_now(),
            operation="paper_update" if previous is not None else "paper_create",
            paper_id=path.stem,
            path=path.relative_to(self.context.root).as_posix(),
            command=command,
            before_hash=sha256_text(before_text),
            after_hash=sha256_text(after_text) or "",
            changed_fields=sorted(
                field for field, value in after.items() if before.get(field) != value
            ),
        )
        compact = event.timestamp.replace(":", "").replace("-", "")
        destination = (
            self.context.paths.state
            / "paper-history"
            / f"{compact}-{time.time_ns()}-{path.stem}-{uuid.uuid4().hex[:8]}.json"
        )
        return destination, json.dumps(
            event.model_dump(mode="json"), ensure_ascii=False, indent=2
        ) + "\n"
