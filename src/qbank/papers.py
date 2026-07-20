"""paper.yaml validation and Markdown/HTML/DOCX building."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml.error import YAMLError

from qbank.application.assets import AssetApplicationService
from qbank.application.ports import RenderingPort
from qbank.artifact_store import AssetCopyPlan, commit_artifact
from qbank.asset_references import (
    AssetKind,
    classify_resource_uri,
    extract_markdown_image_resources,
)
from qbank.assets import AssetService
from qbank.context import ProjectContext
from qbank.domain import AssetTarget
from qbank.errors import (
    DataValidationError,
    DependencyMissingError,
    ExportError,
    QuestionNotFoundError,
)
from qbank.models import (
    Diagnostic,
    DiagnosticCode,
    Paper,
    PaperBuildOptions,
    PaperBuildRequest,
    PaperBuildResult,
    PaperValidationReport,
    PaperValidationSummary,
    ProjectConfig,
    Question,
    QuestionStatus,
)
from qbank.rendering import RenderService
from qbank.repository import MarkdownQuestionRepository, RepositorySnapshot
from qbank.validation import validate_question
from qbank.yaml_io import load_yaml


def load_paper(path: Path) -> Paper:
    """Load and model-validate a paper YAML file."""
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
        return Paper.model_validate(data)
    except (OSError, UnicodeError, YAMLError, ValidationError) as exc:
        raise DataValidationError(f"invalid paper file: {exc}") from exc


def validate_paper_in_context(
    context: ProjectContext,
    paper: Paper,
    *,
    allow_deprecated: bool = False,
    snapshot: RepositorySnapshot | None = None,
    assets: AssetApplicationService | None = None,
) -> PaperValidationReport:
    """Validate references, duplicate IDs, deprecation, and totals."""
    root, config = context.root, context.config
    if snapshot is None:
        snapshot = MarkdownQuestionRepository(context).scan()
    snapshot.require_consistent()
    issues: list[Diagnostic] = []
    seen: set[str] = set()
    referenced = 0
    for section in paper.sections:
        for item in section.questions:
            referenced += 1
            if item.id in seen:
                issues.append(
                    Diagnostic(
                        severity="error",
                        code=DiagnosticCode.DUPLICATE_QUESTION,
                        id=item.id,
                        message="paper contains the same question more than once",
                    )
                )
            seen.add(item.id)
            try:
                record = snapshot.locate(item.id)
            except QuestionNotFoundError:
                issues.append(
                    Diagnostic(
                        severity="error",
                        code=DiagnosticCode.MISSING_QUESTION,
                        id=item.id,
                        message=f"question does not exist: {item.id}",
                    )
                )
                continue
            source_path = record.path
            question = record.question
            if question.status == QuestionStatus.DEPRECATED and not allow_deprecated:
                issues.append(
                    Diagnostic(
                        severity="error",
                        code=DiagnosticCode.DEPRECATED_QUESTION,
                        id=item.id,
                        message="deprecated questions require --allow-deprecated",
                    )
                )
            issues.extend(validate_question(root, config, source_path, question))
            issues.extend(
                _paper_asset_issues(
                    context,
                    question,
                    assets,
                )
            )
    calculated = paper.calculated_total
    declared = paper.metadata.total_score
    if declared is not None and abs(declared - calculated) > 1e-9:
        issues.append(
            Diagnostic(
                severity="error",
                code=DiagnosticCode.TOTAL_SCORE_MISMATCH,
                field="metadata.total_score",
                message=(f"declared total {declared:g} does not match calculated {calculated:g}"),
            )
        )
    errors = sum(item.severity == "error" for item in issues)
    warnings = sum(item.severity == "warning" for item in issues)
    return PaperValidationReport(
        ok=errors == 0,
        summary=PaperValidationSummary(
            sections=len(paper.sections),
            questions=referenced,
            total_score=calculated,
            errors=errors,
            warnings=warnings,
        ),
        issues=issues,
    )


def validate_paper(
    root: Path,
    config: ProjectConfig,
    paper: Paper,
    *,
    allow_deprecated: bool = False,
    snapshot: RepositorySnapshot | None = None,
) -> PaperValidationReport:
    """Compatibility adapter for context-based paper validation."""
    return validate_paper_in_context(
        ProjectContext.from_config(root, config),
        paper,
        allow_deprecated=allow_deprecated,
        snapshot=snapshot,
    )


def _paper_asset_issues(
    context: ProjectContext,
    question: Question,
    assets: AssetApplicationService | None,
) -> list[Diagnostic]:
    try:
        _, issues = AssetService(context, assets).project_question(
            question,
            target="generic",
            require_final=context.config.assets.require_final_for_paper,
        )
        return issues
    except DataValidationError as exc:
        return [
            Diagnostic(
                code=DiagnosticCode.ASSET_REPRESENTATION_MISSING,
                id=question.id,
                field="assets",
                message=str(exc),
            )
        ]


def _project_paper_questions(
    context: ProjectContext,
    paper: Paper,
    snapshot: RepositorySnapshot,
    *,
    target: AssetTarget,
    assets: AssetApplicationService | None = None,
) -> tuple[dict[str, Question], list[Diagnostic]]:
    service = AssetService(context, assets)
    projected: dict[str, Question] = {}
    warnings: list[Diagnostic] = []
    for section in paper.sections:
        for reference in section.questions:
            if reference.id in projected:
                continue
            question, item_warnings = service.project_question(
                snapshot.locate(reference.id).question,
                target=target,
                require_final=context.config.assets.require_final_for_paper,
            )
            projected[reference.id] = question
            warnings.extend(item_warnings)
    return projected, warnings


def _build_context(
    paper: Paper,
    snapshot: RepositorySnapshot,
    options: PaperBuildOptions,
    projected: dict[str, Question] | None = None,
) -> dict[str, Any]:
    include_solutions = (
        paper.options.include_solutions
        if options.with_solutions is None
        else options.with_solutions
    )
    include_answers = (
        paper.options.include_answers if options.with_answers is None else options.with_answers
    ) or include_solutions
    include_rubric = (
        paper.options.include_rubric if options.with_rubric is None else options.with_rubric
    )
    resolved_sections: list[dict[str, Any]] = []
    for section in paper.sections:
        items: list[dict[str, Any]] = []
        for reference in section.questions:
            question = (
                projected[reference.id]
                if projected is not None
                else snapshot.locate(reference.id).question
            )
            items.append({"question": question, "score": reference.score})
        resolved_sections.append(
            {
                "title": section.title,
                "instructions": section.instructions,
                "questions": items,
            }
        )
    return {
        "paper": paper,
        "sections": resolved_sections,
        "total_score": paper.calculated_total,
        "show_scores": paper.options.show_scores,
        "show_ids": (
            paper.options.show_question_ids if options.show_ids is None else options.show_ids
        ),
        "include_answers": include_answers,
        "include_solutions": include_solutions,
        "include_rubric": include_rubric,
    }


def render_paper_markdown(
    root: Path,
    config: ProjectConfig,
    paper: Paper,
    options: PaperBuildOptions | None = None,
    **legacy_options: object,
) -> str:
    """Render paper content through the project Markdown template."""
    options = _paper_options(options, legacy_options)
    context = ProjectContext.from_config(root, config)
    snapshot = MarkdownQuestionRepository(context).scan()
    snapshot.require_consistent()
    renderer = RenderService(context)
    projected, _ = _project_paper_questions(
        context,
        paper,
        snapshot,
        target="md",
    )
    return (
        renderer.project_template(
            "paper.md.j2",
            _build_context(paper, snapshot, options, projected),
        ).rstrip()
        + "\n"
    )


def _paper_asset_plan(
    context: ProjectContext,
    destination_dir: Path,
    questions: list[Question],
    assets: AssetApplicationService | None,
    target: AssetTarget,
    markdown: str,
) -> AssetCopyPlan:
    plan = AssetService(context, assets).question_copy_plan(
        questions,
        destination_dir,
        target=target,
    )
    used = {
        reference.normalized
        for raw in extract_markdown_image_resources(markdown)
        if (reference := classify_resource_uri(raw)).kind == AssetKind.LOCAL
        and reference.normalized is not None
    }
    return {name: value for name, value in plan.items() if name in used}


def _ordered_paper_questions(
    paper: Paper,
    questions: dict[str, Question],
) -> list[Question]:
    return [
        questions[reference.id] for section in paper.sections for reference in section.questions
    ]


def render_html_document(
    root: Path,
    config: ProjectConfig,
    *,
    title: str,
    language: str,
    markdown: str,
) -> str:
    """Safely render Markdown inside the shared sandboxed HTML template."""
    return RenderService(ProjectContext.from_config(root, config)).html_document(
        title=title,
        language=language,
        markdown=markdown,
    )


def render_html_document_in_context(
    context: ProjectContext,
    *,
    title: str,
    language: str,
    markdown: str,
    renderer: RenderingPort | None = None,
) -> str:
    """Render a paper HTML document within an existing project context."""
    return (renderer or RenderService(context)).html_document(
        title=title,
        language=language,
        markdown=markdown,
    )


def pandoc_command(config: ProjectConfig) -> list[str]:
    """Parse the configured Pandoc command consistently across platforms."""
    arguments = shlex.split(config.export.pandoc_command, posix=os.name != "nt")
    if os.name == "nt":
        arguments = [
            argument[1:-1]
            if len(argument) >= 2 and argument[0] == argument[-1] and argument[0] in {'"', "'"}
            else argument
            for argument in arguments
        ]
    return arguments


def _render_paper_source(
    renderer: RenderingPort,
    paper: Paper,
    snapshot: RepositorySnapshot,
    options: PaperBuildOptions,
    projected: dict[str, Question],
) -> str:
    return (
        renderer.project_template(
            "paper.md.j2",
            _build_context(paper, snapshot, options, projected),
        ).rstrip()
        + "\n"
    )


def _pandoc_docx(
    context: ProjectContext,
    markdown: str,
    command: list[str],
) -> bytes:
    with tempfile.TemporaryDirectory(prefix="qbank-pandoc-") as temporary:
        source = Path(temporary) / "paper.md"
        staged_output = Path(temporary) / "paper.docx"
        source.write_text(markdown, encoding="utf-8")
        arguments = [
            *command,
            str(source),
            "--from",
            "markdown",
            "--to",
            "docx",
            "--resource-path",
            str(context.root),
            "--output",
            str(staged_output),
        ]
        reference = context.paths.reference_docx
        if reference.is_file():
            arguments.extend(["--reference-doc", str(reference)])
        result = subprocess.run(
            arguments,
            cwd=context.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode:
            raise ExportError(
                f"Pandoc failed with exit code {result.returncode}: {result.stderr.strip()}"
            )
        try:
            return staged_output.read_bytes()
        except OSError as exc:
            raise ExportError(f"Pandoc did not create its output: {exc}") from exc


def build_paper_in_context(
    context: ProjectContext,
    paper_path: Path,
    request: PaperBuildRequest | None = None,
    snapshot: RepositorySnapshot | None = None,
    renderer: RenderingPort | None = None,
    assets: AssetApplicationService | None = None,
    **legacy_request: object,
) -> PaperBuildResult:
    """Validate and build a paper in Markdown, HTML, or DOCX."""
    root, config = context.root, context.config
    request = _paper_request(request, legacy_request)
    options = request.options
    paper = load_paper(paper_path)
    snapshot = snapshot or MarkdownQuestionRepository(context).scan()
    renderer = renderer or RenderService(context)
    report = validate_paper_in_context(
        context,
        paper,
        allow_deprecated=options.allow_deprecated,
        snapshot=snapshot,
        assets=assets,
    )
    if not report.ok:
        raise DataValidationError(f"paper validation failed: {report.issues}")
    output_format = request.output_format
    suffix = f".{output_format}"
    output = request.output
    if output is None:
        output = context.paths.build / f"{paper_path.stem}{suffix}"
    elif not output.is_absolute():
        output = (root / output).resolve()
    command = pandoc_command(config) if output_format == "docx" else []
    if output_format == "docx" and (not command or not shutil.which(command[0])):
        raise DependencyMissingError(f"Pandoc command not found: {config.export.pandoc_command}")
    target: AssetTarget = (
        "html" if output_format == "html" else "docx" if output_format == "docx" else "md"
    )
    projected, asset_warnings = _project_paper_questions(
        context,
        paper,
        snapshot,
        target=target,
        assets=assets,
    )
    markdown = _render_paper_source(renderer, paper, snapshot, options, projected)
    asset_plan = _paper_asset_plan(
        context,
        output.parent,
        _ordered_paper_questions(paper, projected),
        assets,
        target,
        markdown,
    )
    if output_format == "md":
        artifact: str | bytes = markdown
    elif output_format == "html":
        artifact = render_html_document_in_context(
            context,
            title=paper.title,
            language=paper.language,
            markdown=markdown,
            renderer=renderer,
        )
    else:
        artifact = _pandoc_docx(context, markdown, command)
    commit_artifact(output, artifact, asset_plan)
    return PaperBuildResult(
        ok=True,
        format=output_format,
        output=(
            output.relative_to(root).as_posix() if output.is_relative_to(root) else str(output)
        ),
        questions=report.summary.questions,
        total_score=report.summary.total_score,
        assets=list(asset_plan),
        warnings=_unique_diagnostics(
            [
                *[issue for issue in report.issues if issue.severity == "warning"],
                *asset_warnings,
            ]
        ),
    )


def _unique_diagnostics(issues: list[Diagnostic]) -> list[Diagnostic]:
    """Keep paper-build warnings stable when validation and projection agree."""
    seen: set[tuple[object, ...]] = set()
    unique: list[Diagnostic] = []
    for issue in issues:
        key = (
            issue.severity,
            issue.code,
            issue.message,
            issue.id,
            issue.file,
            issue.field,
        )
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def build_paper(
    root: Path,
    config: ProjectConfig,
    paper_path: Path,
    request: PaperBuildRequest | None = None,
    **legacy_request: object,
) -> PaperBuildResult:
    """Compatibility adapter for the context-based paper build use case."""
    normalized_request = _paper_request(request, legacy_request)
    return build_paper_in_context(
        ProjectContext.from_config(root, config),
        paper_path,
        normalized_request,
    )


def _paper_options(
    options: PaperBuildOptions | None,
    legacy_options: dict[str, object],
) -> PaperBuildOptions:
    if options is not None and legacy_options:
        raise DataValidationError("pass PaperBuildOptions or keyword options, not both")
    try:
        return options or PaperBuildOptions.model_validate(legacy_options)
    except ValidationError as exc:
        raise DataValidationError(str(exc)) from exc


def _paper_request(
    request: PaperBuildRequest | None,
    legacy_request: dict[str, object],
) -> PaperBuildRequest:
    if request is not None and legacy_request:
        raise DataValidationError("pass PaperBuildRequest or keyword options, not both")
    if request is not None:
        return request
    values = dict(legacy_request)
    output_format = values.pop("output_format", None)
    output = values.pop("output", None)
    if output_format not in {"md", "html", "docx"}:
        raise ExportError(f"unsupported paper format: {output_format}")
    try:
        return PaperBuildRequest.model_validate(
            {
                "output_format": output_format,
                "output": output,
                "options": values,
            }
        )
    except ValidationError as exc:
        raise DataValidationError(str(exc)) from exc
