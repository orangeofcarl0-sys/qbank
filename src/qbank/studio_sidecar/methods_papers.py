"""Studio Protocol paper methods."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

from qbank.models import (
    Paper,
    PaperBuildOptions,
    PaperBuildRequest,
)
from qbank.papers import load_paper
from qbank.studio_operations import StudioProjectAdapter
from qbank.studio_sidecar.errors import (
    INVALID_PARAMS,
    RpcError,
)
from qbank.studio_sidecar.session import (
    OpenRepository,
    StudioSession,
    optional_string,
    required_string,
    string_list,
)


class PaperMethods(StudioSession):
    """Paper Protocol methods."""

    def paper_list(self, _params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        return [
            self._paper_item(opened, path) for path in opened.services.studio_project.list_papers()
        ]

    def paper_get(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._synchronize_snapshot(opened)
        path = self._paper_path(opened, required_string(params, "path"))
        return {
            "path": path.relative_to(opened.context.root).as_posix(),
            "paper": load_paper(path).model_dump(mode="json", exclude_none=True),
            "revision": opened.revision,
        }

    def paper_create(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        path = Path(required_string(params, "path"))
        title = required_string(params, "title")
        question_ids = string_list(params, "questionIds", allow_empty=False)
        dry_run = opened.services.studio_project.create_paper(
            path, title, question_ids, dry_run=True
        )
        paper = opened.services.studio_project.create_paper(
            path, title, question_ids, dry_run=False
        )
        return {
            "ok": True,
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "paper": paper.model_dump(mode="json", exclude_none=True),
            "revision": self._refresh_revision(opened),
        }

    def paper_save(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        path = self._paper_path(opened, required_string(params, "path"))
        raw_paper = params.get("paper")
        if not isinstance(raw_paper, dict):
            raise RpcError(INVALID_PARAMS, "paper must be an object")
        paper = Paper.model_validate(raw_paper)
        service = cast(StudioProjectAdapter, opened.services.studio_project).papers
        dry_run = service.save(
            path, paper, dry_run=True, command="qbank studio protocol paper save"
        )
        saved = service.save(path, paper, dry_run=False, command="qbank studio protocol paper save")
        return {
            "ok": True,
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "paper": saved.model_dump(mode="json", exclude_none=True),
            "revision": self._refresh_revision(opened),
        }

    def paper_add_questions(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        path = self._paper_path(opened, required_string(params, "path"))
        question_ids = string_list(params, "questionIds", allow_empty=False)
        dry_run = opened.services.studio_project.add_to_paper(path, question_ids, dry_run=True)
        paper = opened.services.studio_project.add_to_paper(path, question_ids, dry_run=False)
        return {
            "ok": True,
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "paper": paper.model_dump(mode="json", exclude_none=True),
            "revision": self._refresh_revision(opened),
        }

    def paper_validate(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        path = self._paper_path(opened, required_string(params, "path"))
        report = opened.services.studio_project.validate_paper(path)
        return report.model_dump(mode="json", exclude_none=True)

    def paper_build(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        path = self._paper_path(opened, required_string(params, "path"))
        output = params.get("output")
        if output is not None and not isinstance(output, str):
            raise RpcError(INVALID_PARAMS, "output must be a string or null")
        options = params.get("options", {})
        if not isinstance(options, dict):
            raise RpcError(INVALID_PARAMS, "options must be an object")
        output_format = optional_string(params, "format", default="html")
        if output_format not in {"md", "html", "docx"}:
            raise RpcError(INVALID_PARAMS, "format must be md, html, or docx")
        request = PaperBuildRequest(
            output_format=cast(Literal["md", "html", "docx"], output_format),
            output=Path(output).expanduser() if output else None,
            options=PaperBuildOptions.model_validate(options),
        )
        result = opened.services.studio_project.build_paper(path, request)
        return {
            "ok": result.ok,
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": opened.revision,
        }

    @staticmethod
    def _paper_path(opened: OpenRepository, value: str) -> Path:
        return cast(StudioProjectAdapter, opened.services.studio_project).paper_path(Path(value))

    def _paper_item(self, opened: OpenRepository, path: Path) -> dict[str, Any]:
        paper = load_paper(path)
        return {
            "path": path.relative_to(opened.context.root).as_posix(),
            "title": paper.title,
            "questionIds": [item.id for section in paper.sections for item in section.questions],
            "totalScore": paper.calculated_total,
        }
