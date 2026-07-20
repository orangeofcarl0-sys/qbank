"""Static, serverless question-bank preview."""

from __future__ import annotations

import html
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from qbank.application.assets import AssetApplicationService
from qbank.application.ports import RenderingPort
from qbank.assets import AssetService
from qbank.context import ProjectContext
from qbank.domain import RepositorySnapshot
from qbank.errors import DataValidationError
from qbank.models import PreviewResult, ProjectConfig, Question
from qbank.rendering import RenderService
from qbank.repository import MarkdownQuestionRepository
from qbank.utils import atomic_write_text, is_relative_to
from qbank.validation import validate_repository_in_context


def _question_card(
    root: Path,
    path: Path,
    question: Question,
    *,
    renderer: RenderingPort,
    asset_prefix: str = "",
) -> str:
    def render(text: str) -> str:
        return renderer.markdown_html(text, asset_prefix=asset_prefix)

    answer = render(question.answer_md) if question.answer_md else "<p>（未提供）</p>"
    solution = render(question.solution_md) if question.solution_md else "<p>（未提供）</p>"
    search = (question.title + " " + question.stem_md + " " + " ".join(question.topics)).lower()
    options = (
        f'<section class="options">{render(question.options_md)}</section>'
        if question.options_md
        else ""
    )
    return f"""\
<article class="question" data-search="{html.escape(search, quote=True)}"
 data-subject="{html.escape(question.subject, quote=True)}"
 data-type="{html.escape(question.type.value, quote=True)}"
 data-status="{html.escape(question.status.value, quote=True)}"
 data-difficulty="{question.difficulty}">
  <header>
    <h2>{html.escape(question.title)}</h2>
    <div class="meta"><code>{html.escape(question.id)}</code> · {html.escape(question.subject)}
      · {html.escape(question.type.value)} · 难度 {question.difficulty}
      · {html.escape(question.status.value)}</div>
  </header>
  <section class="stem">{render(question.stem_md)}</section>
  {options}
  <details><summary>答案</summary>{answer}</details>
  <details><summary>解析</summary>{solution}</details>
  <p class="source">源文件：{html.escape(path.relative_to(root).as_posix())}</p>
</article>
"""


def _options(values: set[str]) -> str:
    return "".join(
        f'<option value="{html.escape(value, quote=True)}">{html.escape(value)}</option>'
        for value in sorted(values)
    )


def _page(
    renderer: RenderingPort,
    cards: str,
    questions: list[Question],
) -> str:
    return renderer.internal_template(
        "preview/page.html.j2",
        {
            "cards": cards,
            "questions": questions,
            "subject_options": _options({question.subject for question in questions}),
            "type_options": _options({question.type.value for question in questions}),
            "status_options": _options({question.status.value for question in questions}),
            "difficulty_options": _options({str(question.difficulty) for question in questions}),
        },
    )


def build_preview_in_context(
    context: ProjectContext,
    snapshot: RepositorySnapshot | None = None,
    renderer: RenderingPort | None = None,
    assets: AssetApplicationService | None = None,
) -> PreviewResult:
    """Generate a static searchable preview directory."""
    root = context.root
    snapshot = snapshot or MarkdownQuestionRepository(context).scan()
    report = validate_repository_in_context(context, snapshot=snapshot)
    if not report.ok:
        errors = [
            issue.model_dump(mode="json", exclude_none=True)
            for issue in report.issues
            if issue.severity == "error"
        ]
        raise DataValidationError(
            "preview validation failed: " + json.dumps(errors, ensure_ascii=False)
        )
    context.paths.build.mkdir(parents=True, exist_ok=True)
    destination = context.paths.build / "preview"
    temporary = Path(tempfile.mkdtemp(prefix=".preview-", dir=context.paths.build))
    backup = context.paths.build / ".preview-backup"
    asset_service = AssetService(context, assets)
    projected_questions, asset_warnings = asset_service.project_questions(
        [record.question for record in snapshot.records],
        target="preview",
    )
    items = [
        (record.path, question)
        for record, question in zip(snapshot.records, projected_questions, strict=True)
    ]
    renderer = renderer or RenderService(context)
    try:
        (temporary / "questions").mkdir()
        cards: list[str] = []
        search_data: list[dict[str, Any]] = []
        for path, question in items:
            card = _question_card(
                root,
                path,
                question,
                renderer=renderer,
            )
            cards.append(card)
            atomic_write_text(
                temporary / "questions" / f"{question.id}.html",
                _page(
                    renderer,
                    _question_card(
                        root,
                        path,
                        question,
                        renderer=renderer,
                        asset_prefix="../",
                    ),
                    [question],
                ),
            )
            search_data.append(
                {
                    "id": question.id,
                    "title": question.title,
                    "subject": question.subject,
                    "type": question.type.value,
                    "status": question.status.value,
                    "difficulty": question.difficulty,
                }
            )
        asset_service.copy_questions(
            [question for _, question in items],
            temporary,
            output_assets=Path("assets"),
            target="preview",
        )
        atomic_write_text(
            temporary / "index.html",
            _page(
                renderer,
                "".join(cards),
                [question for _, question in items],
            ),
        )
        atomic_write_text(
            temporary / "questions/index.json",
            json.dumps(search_data, ensure_ascii=False, indent=2) + "\n",
        )
        _replace_preview_tree(
            context.paths.build,
            temporary,
            destination,
            backup,
        )
    except Exception:
        if not destination.exists() and backup.exists():
            backup.replace(destination)
        if temporary.exists() and is_relative_to(
            temporary.resolve(), context.paths.build.resolve()
        ):
            shutil.rmtree(temporary)
        raise
    return PreviewResult(
        ok=True,
        output=destination.relative_to(root).as_posix(),
        questions=len(items),
        warnings=[
            *[issue for issue in report.issues if issue.severity == "warning"],
            *asset_warnings,
        ],
    )


def build_preview(root: Path, config: ProjectConfig) -> PreviewResult:
    """Compatibility adapter for context-based preview generation."""
    return build_preview_in_context(ProjectContext.from_config(root, config))


def _replace_preview_tree(
    build_root: Path,
    temporary: Path,
    destination: Path,
    backup: Path,
) -> None:
    if backup.exists():
        if not is_relative_to(backup.resolve(), build_root.resolve()):
            raise DataValidationError("unsafe preview backup path")
        shutil.rmtree(backup)
    if destination.exists():
        destination.replace(backup)
    temporary.replace(destination)
    if backup.exists():
        shutil.rmtree(backup)
