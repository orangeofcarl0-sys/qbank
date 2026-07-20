"""Query-result export formats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from qbank.application.assets import AssetApplicationService
from qbank.application.ports import RenderingPort
from qbank.artifact_store import commit_artifact
from qbank.assets import AssetService
from qbank.context import ProjectContext
from qbank.domain import AssetTarget
from qbank.errors import DataValidationError, ExportError
from qbank.models import Diagnostic, ExportResult, ProjectConfig, Question
from qbank.rendering import RenderService
from qbank.validation import validate_question


class CollectionExporter(Protocol):
    """One registered serialization strategy for selected questions."""

    copies_assets: bool

    def render(
        self,
        context: ProjectContext,
        questions: list[Question],
        renderer: RenderingPort,
    ) -> str: ...


class JsonExporter:
    """Indented exchange JSON exporter."""

    copies_assets = False

    def render(
        self,
        context: ProjectContext,
        questions: list[Question],
        renderer: RenderingPort,
    ) -> str:
        del context, renderer
        data = [question.model_dump(mode="json", exclude_none=True) for question in questions]
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


class JsonLinesExporter:
    """One exchange JSON object per line."""

    copies_assets = False

    def render(
        self,
        context: ProjectContext,
        questions: list[Question],
        renderer: RenderingPort,
    ) -> str:
        del context, renderer
        return "".join(
            json.dumps(
                question.model_dump(mode="json", exclude_none=True),
                ensure_ascii=False,
            )
            + "\n"
            for question in questions
        )


class MarkdownExporter:
    """Readable Markdown collection exporter."""

    copies_assets = True

    def render(
        self,
        context: ProjectContext,
        questions: list[Question],
        renderer: RenderingPort,
    ) -> str:
        del context, renderer
        return render_question_collection_markdown(questions)


class HtmlExporter:
    """Sandboxed HTML document exporter."""

    copies_assets = True

    def render(
        self,
        context: ProjectContext,
        questions: list[Question],
        renderer: RenderingPort,
    ) -> str:
        del context
        return renderer.html_document(
            title="qbank export",
            language="zh-CN",
            markdown=render_question_collection_markdown(questions),
        )


class PlainTextExporter:
    """Human-readable plain text with no document-level Markdown syntax."""

    copies_assets = False

    def render(
        self,
        context: ProjectContext,
        questions: list[Question],
        renderer: RenderingPort,
    ) -> str:
        del context, renderer
        chunks: list[str] = []
        for question in questions:
            chunks.extend(
                [
                    question.title,
                    f"{question.id} | {question.type.value} | difficulty {question.difficulty}",
                    question.stem_md,
                ]
            )
            for label, content in (
                ("Options", question.options_md),
                ("Answer", question.answer_md),
                ("Solution", question.solution_md),
            ):
                if content:
                    chunks.extend((label, content))
            chunks.append("")
        return "\n\n".join(chunks).rstrip() + "\n"


EXPORTER_REGISTRY: dict[str, CollectionExporter] = {
    "json": JsonExporter(),
    "jsonl": JsonLinesExporter(),
    "md": MarkdownExporter(),
    "html": HtmlExporter(),
    "txt": PlainTextExporter(),
}


def render_question_collection_markdown(questions: list[Question]) -> str:
    """Render questions as a readable Markdown collection."""
    chunks = ["# qbank 导出\n"]
    for question in questions:
        chunks.extend(
            [
                f"\n## {question.title}\n",
                f"\n`{question.id}` · {question.type.value} · 难度 {question.difficulty}\n",
                f"\n{question.stem_md}\n",
            ]
        )
        if question.options_md:
            chunks.append(f"\n### 选项\n\n{question.options_md}\n")
        if question.answer_md:
            chunks.append(f"\n### 答案\n\n{question.answer_md}\n")
        if question.solution_md:
            chunks.append(f"\n### 解析\n\n{question.solution_md}\n")
    return "".join(chunks).rstrip() + "\n"


def _asset_plan(
    context: ProjectContext,
    questions: list[Question],
    output: Path,
    assets: AssetApplicationService | None = None,
    *,
    target: AssetTarget = "generic",
) -> dict[str, tuple[Path, Path]]:
    return AssetService(context, assets).question_copy_plan(
        questions,
        output.parent,
        target=target,
    )


def export_questions_in_context(
    context: ProjectContext,
    questions: list[Question],
    *,
    output_format: str,
    output: Path,
    renderer: RenderingPort | None = None,
    assets: AssetApplicationService | None = None,
) -> ExportResult:
    """Write query results in JSON, JSONL, Markdown, or HTML."""
    root, config = context.root, context.config
    if not output.is_absolute():
        output = (root / output).resolve()
    issues = [
        issue
        for question in questions
        for issue in validate_question(
            root,
            config,
            context.paths.questions / question.subject / f"{question.id}.md",
            question,
        )
    ]
    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    if errors:
        raise DataValidationError(
            "export validation failed: "
            + json.dumps(
                [issue.model_dump(mode="json", exclude_none=True) for issue in errors],
                ensure_ascii=False,
            )
        )
    try:
        exporter = EXPORTER_REGISTRY[output_format]
    except KeyError as exc:
        raise ExportError(f"unsupported export format: {output_format}") from exc
    renderer = renderer or RenderService(context)
    projected = questions
    asset_warnings: list[Diagnostic] = []
    if exporter.copies_assets:
        projected, asset_warnings = AssetService(context, assets).project_questions(
            questions,
            target="html" if output_format == "html" else "md",
        )
    text = exporter.render(context, projected, renderer)
    asset_plan = (
        _asset_plan(
            context,
            projected,
            output,
            assets,
            target="html" if output_format == "html" else "md",
        )
        if exporter.copies_assets
        else {}
    )
    commit_artifact(output, text, asset_plan)
    return ExportResult(
        ok=True,
        format=output_format,
        output=(
            output.relative_to(root).as_posix() if output.is_relative_to(root) else str(output)
        ),
        questions=len(questions),
        warnings=[*warnings, *asset_warnings],
    )


def export_questions(
    root: Path,
    config: ProjectConfig,
    questions: list[Question],
    *,
    output_format: str,
    output: Path,
) -> ExportResult:
    """Compatibility adapter for context-based question export."""
    return export_questions_in_context(
        ProjectContext.from_config(root, config),
        questions,
        output_format=output_format,
        output=output,
    )
