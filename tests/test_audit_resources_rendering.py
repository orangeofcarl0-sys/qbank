"""Regression tests for Markdown resources, HTML safety, and preview switching."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from jinja2.exceptions import SecurityError

from qbank.exporters import export_questions
from qbank.models import Question
from qbank.operations import add_question, delete_question
from qbank.papers import load_paper, render_paper_markdown
from qbank.preview import build_preview
from qbank.storage import render_question
from qbank.validation import validate_repository


def _codes(report: Any) -> set[str]:
    return {issue.code for issue in report.issues}


def _write_source(root: Path, question: Question) -> None:
    path = root / "questions" / question.subject / f"{question.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_question(question), encoding="utf-8")


def test_local_markdown_asset_must_be_declared_and_exists(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    asset = root / "assets/images/figure.svg"
    asset.write_text("<svg/>", encoding="utf-8")
    question = make_question(
        assets=["assets/images/figure.svg"],
        stem_md="![figure](assets/images/figure.svg)",
    )
    _write_source(root, question)
    assert validate_repository(root, config).ok


def test_undeclared_markdown_asset_is_an_error(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    (root / "assets/images/figure.svg").write_text("<svg/>", encoding="utf-8")
    _write_source(
        root,
        make_question(stem_md="![figure](assets/images/figure.svg)"),
    )
    assert "undeclared_asset_reference" in _codes(validate_repository(root, config))


def test_unused_yaml_asset_is_a_warning(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    (root / "assets/images/unused.svg").write_text("<svg/>", encoding="utf-8")
    _write_source(
        root,
        make_question(assets=["assets/images/unused.svg"]),
    )
    report = validate_repository(root, config)
    assert report.ok
    assert "unused_asset" in _codes(report)


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/figure.png",
        "http://example.com/figure.png",
        "//cdn.example.com/figure.png",
    ],
)
def test_external_markdown_assets_are_allowed_with_warning(
    project: tuple[Path, Any], make_question: Any, uri: str
) -> None:
    root, config = project
    _write_source(root, make_question(stem_md=f"![figure]({uri})"))
    report = validate_repository(root, config)
    assert report.ok
    assert "external_asset" in _codes(report)


@pytest.mark.parametrize(
    "uri",
    [
        "/absolute/figure.png",
        "file:///tmp/figure.png",
        "data:image/png;base64,AAAA",
        "../outside.png",
        "other/figure.png",
    ],
)
def test_invalid_or_outside_markdown_resources_are_errors(
    project: tuple[Path, Any], make_question: Any, uri: str
) -> None:
    root, config = project
    _write_source(root, make_question(stem_md=f"![figure]({uri})"))
    report = validate_repository(root, config)
    assert not report.ok
    assert "invalid_resource_uri" in _codes(report)


def test_mutation_surfaces_external_asset_warning(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    result = add_question(
        root,
        config,
        make_question(stem_md="![external](https://example.com/a.png)"),
    )
    assert result["ok"]
    assert result["validation_warnings"][0]["code"] == "external_asset"


def test_html_export_contains_body_and_escapes_title_and_raw_html(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    question = make_question(
        title='<img src=x onerror="alert(1)">',
        stem_md='Visible body\n\n<script>alert("x")</script>',
    )
    add_question(root, config, question)
    output = root / "exports/safe.html"
    export_questions(
        root,
        config,
        [question],
        output_format="html",
        output=output,
    )
    html = output.read_text(encoding="utf-8")
    assert "Visible body" in html
    assert "&lt;script&gt;" in html
    assert "<script>alert" not in html
    assert "&lt;img src=x onerror=" in html
    assert "<img src=x onerror=" not in html
    assert "{{ body_html" not in html


def test_jinja_environment_blocks_unsafe_attribute_access(
    imported_project: tuple[Path, Any],
) -> None:
    root, config = imported_project
    template = root / "templates/paper.md.j2"
    template.write_text("{{ ().__class__.__mro__ }}", encoding="utf-8")
    paper = load_paper(root / "papers/demo-paper.yaml")
    with pytest.raises(SecurityError):
        render_paper_markdown(root, config, paper)


def test_single_question_preview_uses_parent_asset_path(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    (root / "assets/images/figure.svg").write_text("<svg/>", encoding="utf-8")
    question = make_question(
        assets=["assets/images/figure.svg"],
        stem_md="![figure](assets/images/figure.svg)",
    )
    add_question(root, config, question)
    build_preview(root, config)
    single = (root / "build/preview/questions/OPT-INT-0001.html").read_text(encoding="utf-8")
    index = (root / "build/preview/index.html").read_text(encoding="utf-8")
    assert 'src="../assets/images/figure.svg"' in single
    assert 'src="assets/images/figure.svg"' in index


def test_preview_replacement_removes_deleted_question_pages(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    question = make_question()
    add_question(root, config, question)
    build_preview(root, config)
    stale = root / "build/preview/questions/OPT-INT-0001.html"
    assert stale.exists()
    delete_question(root, config, question.id)
    build_preview(root, config)
    assert not stale.exists()


def test_failed_preview_build_preserves_previous_tree(
    project: tuple[Path, Any],
    make_question: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    add_question(root, config, make_question())
    build_preview(root, config)
    index = root / "build/preview/index.html"
    before = index.read_bytes()

    def fail_write(path: Path, text: str) -> None:
        raise OSError("injected preview failure")

    monkeypatch.setattr("qbank.preview.atomic_write_text", fail_write)
    with pytest.raises(OSError, match="injected"):
        build_preview(root, config)
    assert index.read_bytes() == before
    assert not list((root / "build").glob(".preview-*"))
