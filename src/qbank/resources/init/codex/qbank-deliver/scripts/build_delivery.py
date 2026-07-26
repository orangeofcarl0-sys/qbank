#!/usr/bin/env python3
"""Validate and build a reproducible qbank Chinese exam delivery workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, cast

from pydantic import ValidationError

from qbank.application.revision import repository_revision
from qbank.context import ProjectContext
from qbank.models import AssetManifest, AssetShowResult, Question
from qbank.yaml_io import load_yaml

TEMPLATE_NAME = "qbank-zh-exam-v1"
VARIANTS = {"student", "answer", "solution"}
QUESTION_HEADER = re.compile(
    r"\\begin\{qbankquestion\}"
    r"\{([^{}]+)\}\{([^{}]*)\}\{([^{}]+)\}\{([^{}]+)\}"
)
ASSET_MACRO = re.compile(r"\\qbankasset(?:\[[^\]]+\])?\{([^{}]+)\}\{([^{}]+)\}")
BANNED_TEX = re.compile(
    r"\\(?:(?:documentclass|usepackage|RequirePackage|LoadClass|input|include|"
    r"includegraphics|InputIfFileExists|openin|openout|read|write|immediate|"
    r"write18|special|directlua|pdfobj|pdfximage|newread|newwrite|scantokens|"
    r"newcommand|renewcommand|providecommand|def|edef|xdef|gdef|csname|catcode|"
    r"ExplSyntaxOn|ExplSyntaxOff)\b|begin\s*\{document\}|end\s*\{document\})"
)
ABSOLUTE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|/(?:Users|home|tmp|private|etc|var)/|"
    r"(?<!\\)/(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+)"
)
UNSAFE_TEX_ENCODING = re.compile(r"\^\^|\\@")
ENVIRONMENT = re.compile(r"\\(?:begin|end)\s*\{([^{}]+)\}")
CONTROL_WORD = re.compile(r"\\([A-Za-z@]+)")
ALLOWED_ENVIRONMENTS = {
    "qbankquestion",
    "qbankchoices2",
    "qbankchoices4",
    "align",
    "align*",
    "aligned",
    "equation",
    "equation*",
    "cases",
    "matrix",
    "pmatrix",
    "bmatrix",
    "vmatrix",
    "Vmatrix",
    "split",
    "gathered",
    "array",
}
ALLOWED_CONTROL_WORDS = {
    "Delta",
    "Gamma",
    "Lambda",
    "Leftarrow",
    "Leftrightarrow",
    "Omega",
    "Phi",
    "Pi",
    "Psi",
    "Rightarrow",
    "Sigma",
    "Theta",
    "Upsilon",
    "Xi",
    "alpha",
    "approx",
    "arccos",
    "arcsin",
    "arctan",
    "arg",
    "array",
    "ast",
    "bar",
    "begin",
    "beta",
    "bigcap",
    "bigcup",
    "bigl",
    "bigoplus",
    "bigotimes",
    "bigr",
    "bigvee",
    "bigwedge",
    "binom",
    "boxed",
    "cdot",
    "cdots",
    "chi",
    "circ",
    "cong",
    "cos",
    "cosh",
    "cot",
    "csc",
    "ddot",
    "ddots",
    "deg",
    "delta",
    "det",
    "dfrac",
    "dim",
    "displaystyle",
    "div",
    "dot",
    "ell",
    "emph",
    "end",
    "epsilon",
    "equiv",
    "eta",
    "exists",
    "exp",
    "forall",
    "frac",
    "gamma",
    "gcd",
    "ge",
    "geq",
    "gets",
    "hat",
    "hspace",
    "iff",
    "implies",
    "in",
    "infty",
    "int",
    "iota",
    "item",
    "kappa",
    "ker",
    "lambda",
    "land",
    "langle",
    "lceil",
    "ldots",
    "le",
    "left",
    "leftarrow",
    "leftrightarrow",
    "leq",
    "lnot",
    "log",
    "lor",
    "lVert",
    "lfloor",
    "lim",
    "liminf",
    "limsup",
    "linewidth",
    "ln",
    "mapsto",
    "mathbf",
    "mathbb",
    "mathcal",
    "mathit",
    "mathrm",
    "mathsf",
    "mathtt",
    "max",
    "min",
    "mp",
    "mu",
    "nabla",
    "ne",
    "neq",
    "notin",
    "nu",
    "oint",
    "omega",
    "operatorname",
    "oplus",
    "otimes",
    "overline",
    "overset",
    "parallel",
    "partial",
    "perp",
    "phi",
    "pi",
    "pm",
    "prod",
    "propto",
    "psi",
    "qbankanswer",
    "qbankasset",
    "qbankmissing",
    "qbankrubric",
    "qbanksolution",
    "qquad",
    "quad",
    "rangle",
    "rceil",
    "rfloor",
    "rho",
    "right",
    "rightarrow",
    "rVert",
    "sec",
    "sigma",
    "sim",
    "sin",
    "sinh",
    "sqrt",
    "subset",
    "subseteq",
    "sum",
    "supset",
    "supseteq",
    "tan",
    "tanh",
    "tau",
    "text",
    "textbf",
    "textit",
    "textnormal",
    "textrm",
    "textsf",
    "texttt",
    "textup",
    "theta",
    "tilde",
    "times",
    "to",
    "triangle",
    "underbrace",
    "underline",
    "underset",
    "upsilon",
    "varepsilon",
    "varphi",
    "varpi",
    "varrho",
    "varsigma",
    "vartheta",
    "vdots",
    "vec",
    "vee",
    "wedge",
    "widehat",
    "widetilde",
    "xi",
    "zeta",
}
Runner = Callable[..., subprocess.CompletedProcess[str]]


class DeliveryError(ValueError):
    """One deterministic delivery-contract failure."""


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DeliveryError(f"{label} must be a mapping")
    return cast(Mapping[str, Any], value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeliveryError(f"{label} must be a non-empty string")
    return value.strip()


def _load_selection(path: Path) -> dict[str, Any]:
    try:
        raw = load_yaml(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DeliveryError(f"unable to read selection.yaml: {exc}") from exc
    selection = dict(_mapping(raw, "selection"))
    if selection.get("version") != "1":
        raise DeliveryError("selection.version must be '1'")
    if selection.get("template") != TEMPLATE_NAME:
        raise DeliveryError(f"selection.template must be {TEMPLATE_NAME}")
    variant = _text(selection.get("variant"), "selection.variant")
    if variant not in VARIANTS:
        raise DeliveryError("selection.variant must be student, answer, or solution")
    _text(selection.get("repository_revision"), "selection.repository_revision")
    document = _mapping(selection.get("document"), "selection.document")
    _text(document.get("title"), "selection.document.title")
    duration = document.get("duration_minutes")
    if duration is not None and (not isinstance(duration, int) or duration <= 0):
        raise DeliveryError("selection.document.duration_minutes must be a positive integer")
    rows = selection.get("questions")
    if not isinstance(rows, list) or not rows:
        raise DeliveryError("selection.questions must be a non-empty list")
    return selection


def _load_questions(path: Path) -> list[Question]:
    questions: list[Question] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DeliveryError(f"unable to read Question snapshot: {exc}") from exc
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            questions.append(Question.model_validate_json(line))
        except ValidationError as exc:
            raise DeliveryError(f"invalid snapshot Question on line {number}: {exc}") from exc
    return questions


def _selection_rows(
    selection: Mapping[str, Any],
    questions: Sequence[Question],
) -> list[tuple[str, int, dict[str, str]]]:
    by_id = {question.id: question for question in questions}
    if len(by_id) != len(questions):
        raise DeliveryError("snapshot contains duplicate question IDs")
    rows: list[tuple[str, int, dict[str, str]]] = []
    seen: set[str] = set()
    raw_rows = cast(list[object], selection["questions"])
    for index, value in enumerate(raw_rows, start=1):
        row = _mapping(value, f"selection.questions[{index}]")
        question_id = _text(row.get("id"), f"selection.questions[{index}].id")
        if question_id in seen:
            raise DeliveryError(f"selection contains duplicate question ID: {question_id}")
        if question_id not in by_id:
            raise DeliveryError(f"selection question is absent from snapshot: {question_id}")
        score = row.get("score")
        if not isinstance(score, int) or score <= 0:
            raise DeliveryError(f"selection score must be a positive integer: {question_id}")
        raw_assets = _mapping(row.get("assets", {}), f"selection asset map for {question_id}")
        assets = {
            _text(asset_id, "asset ID"): _text(representation, "representation ID")
            for asset_id, representation in raw_assets.items()
        }
        rows.append((question_id, score, assets))
        seen.add(question_id)
    if [question.id for question in questions] != [row[0] for row in rows]:
        raise DeliveryError("snapshot order must exactly match selection order")
    return rows


def _warnings(
    selection: Mapping[str, Any],
    questions: Sequence[Question],
) -> list[dict[str, str]]:
    variant = cast(str, selection["variant"])
    warnings: list[dict[str, str]] = []
    for question in questions:
        if question.status.value == "draft":
            warnings.append(
                {
                    "code": "draft_question",
                    "question_id": question.id,
                    "message": "draft question retained with a visible pending-review marker",
                }
            )
        if variant in {"answer", "solution"} and not question.answer_md:
            warnings.append(
                {
                    "code": "missing_answer",
                    "question_id": question.id,
                    "message": "answer is missing and will be rendered as 未提供",
                }
            )
        if variant == "solution" and not question.solution_md:
            warnings.append(
                {
                    "code": "missing_solution",
                    "question_id": question.id,
                    "message": "solution is missing and will be rendered as 未提供",
                }
            )
        if variant == "solution" and not question.rubric_md:
            warnings.append(
                {
                    "code": "missing_rubric",
                    "question_id": question.id,
                    "message": "rubric is missing and will be rendered as 未提供",
                }
            )
    return warnings


def _validate_content(
    content: str,
    rows: Sequence[tuple[str, int, dict[str, str]]],
    questions: Sequence[Question],
) -> None:
    _validate_tex_surface(content)
    headers = QUESTION_HEADER.findall(content)
    ids = [header[0] for header in headers]
    expected = [row[0] for row in rows]
    if ids != expected:
        raise DeliveryError("qbankquestion order and IDs must exactly match selection")
    by_id = {question.id: question for question in questions}
    for header, row in zip(headers, rows, strict=True):
        question_id, _, score, status = header
        if score != str(row[1]):
            raise DeliveryError(f"content score does not match selection: {question_id}")
        if status != by_id[question_id].status.value:
            raise DeliveryError(f"content status does not match snapshot: {question_id}")
        _validate_missing_macros(content, by_id[question_id])
    selected_assets = {
        (question_id, asset_id) for question_id, _, assets in rows for asset_id in assets
    }
    used_assets = set(ASSET_MACRO.findall(content))
    if used_assets != selected_assets:
        raise DeliveryError("content asset macros must exactly match selected assets")


def _validate_tex_surface(content: str) -> None:
    if UNSAFE_TEX_ENCODING.search(content):
        raise DeliveryError("content.tex contains forbidden TeX encoding or internal command")
    if _has_unescaped_percent(content):
        raise DeliveryError("content.tex contains an unescaped TeX comment")
    banned = BANNED_TEX.search(content)
    if banned is not None:
        raise DeliveryError(f"content.tex contains forbidden command: {banned.group(0)}")
    if ABSOLUTE_PATH.search(content):
        raise DeliveryError("content.tex contains an absolute filesystem path")
    unsupported = sorted(set(ENVIRONMENT.findall(content)) - ALLOWED_ENVIRONMENTS)
    if unsupported:
        raise DeliveryError(f"content.tex contains unsupported environments: {unsupported}")
    unsupported_commands = sorted(set(CONTROL_WORD.findall(content)) - ALLOWED_CONTROL_WORDS)
    if unsupported_commands:
        raise DeliveryError(f"content.tex contains unsupported commands: {unsupported_commands}")


def _has_unescaped_percent(content: str) -> bool:
    for index, character in enumerate(content):
        if character != "%":
            continue
        slash_count = 0
        cursor = index - 1
        while cursor >= 0 and content[cursor] == "\\":
            slash_count += 1
            cursor -= 1
        if slash_count % 2 == 0:
            return True
    return False


def _validate_missing_macros(content: str, question: Question) -> None:
    escaped = re.escape(question.id)
    answer = re.search(rf"\\qbankanswer\{{{escaped}\}}\{{", content)
    solution = re.search(rf"\\qbanksolution\{{{escaped}\}}\{{", content)
    rubric = re.search(rf"\\qbankrubric\{{{escaped}\}}\{{", content)
    if answer is None or solution is None or rubric is None:
        raise DeliveryError(
            f"content must contain answer, solution, and rubric macros: {question.id}"
        )
    if not question.answer_md and not re.search(
        rf"\\qbankanswer\{{{escaped}\}}\{{\\qbankmissing\}}",
        content,
    ):
        raise DeliveryError(f"missing answer must use qbankmissing: {question.id}")
    if not question.solution_md and not re.search(
        rf"\\qbanksolution\{{{escaped}\}}\{{\\qbankmissing\}}",
        content,
    ):
        raise DeliveryError(f"missing solution must use qbankmissing: {question.id}")
    if not question.rubric_md and not re.search(
        rf"\\qbankrubric\{{{escaped}\}}\{{\\qbankmissing\}}",
        content,
    ):
        raise DeliveryError(f"missing rubric must use qbankmissing: {question.id}")


def _safe_manifest(path: Path) -> AssetManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "asset" in payload:
            return AssetShowResult.model_validate(payload).asset
        return AssetManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise DeliveryError(f"invalid asset_get snapshot {path}: {exc}") from exc


def _contained_local_asset(
    qbank_root: Path,
    manifest_path: str,
    relative_path: str,
) -> Path:
    manifest = PurePosixPath(manifest_path)
    if manifest.is_absolute() or ".." in manifest.parts:
        raise DeliveryError(f"unsafe asset manifest path: {manifest_path}")
    root = qbank_root.resolve()
    lexical = root / Path(*manifest.parent.parts) / relative_path
    cursor = root
    for part in lexical.relative_to(root).parts:
        cursor /= part
        if cursor.is_symlink():
            raise DeliveryError(f"asset representation crosses a symlink: {cursor}")
    source = lexical.resolve()
    if not source.is_relative_to(root):
        raise DeliveryError("asset representation escapes the qbank root")
    if not source.is_file():
        raise DeliveryError(f"asset representation is missing: {source}")
    return source


def _stage_assets(
    workspace: Path,
    qbank_root: Path,
    stage: Path,
    rows: Sequence[tuple[str, int, dict[str, str]]],
) -> tuple[dict[tuple[str, str], str], list[dict[str, str]]]:
    bindings: dict[tuple[str, str], str] = {}
    records: list[dict[str, str]] = []
    for question_id, _, selected in rows:
        for asset_id, representation_id in sorted(selected.items()):
            snapshot = workspace / "snapshot" / "assets" / question_id / f"{asset_id}.json"
            manifest = _safe_manifest(snapshot)
            if manifest.question_id != question_id or manifest.asset_id != asset_id:
                raise DeliveryError(f"asset snapshot identity mismatch: {question_id}/{asset_id}")
            representation = next(
                (
                    item
                    for item in manifest.representations
                    if item.representation_id == representation_id
                ),
                None,
            )
            if representation is None:
                raise DeliveryError(
                    f"selected representation does not exist: "
                    f"{question_id}/{asset_id}/{representation_id}"
                )
            if representation.url is not None or representation.path is None:
                raise DeliveryError(
                    f"formal builds require a local representation: {question_id}/{asset_id}"
                )
            source = _contained_local_asset(
                qbank_root,
                _text(
                    json.loads(snapshot.read_text(encoding="utf-8")).get(
                        "manifest_path",
                        f"assets/questions/{question_id}/{asset_id}/asset.yaml",
                    ),
                    "manifest_path",
                ),
                representation.path,
            )
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if representation.content_hash != digest:
                raise DeliveryError(f"asset hash changed: {question_id}/{asset_id}")
            relative = Path("assets") / question_id / asset_id / source.name
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            binding = relative.as_posix()
            bindings[(question_id, asset_id)] = binding
            records.append(
                {
                    "question_id": question_id,
                    "asset_id": asset_id,
                    "representation_id": representation_id,
                    "path": binding,
                    "sha256": digest,
                }
            )
    return bindings, records


def _tex_escape(value: object) -> str:
    text = "" if value is None else str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "#": r"\#",
        "$": r"\$",
        "%": r"\%",
        "&": r"\&",
        "_": r"\_",
        "^": r"\textasciicircum{}",
        "~": r"\textasciitilde{}",
    }
    return "".join(replacements.get(character, character) for character in text)


def _selection_tex(
    selection: Mapping[str, Any],
    bindings: Mapping[tuple[str, str], str],
) -> str:
    document = _mapping(selection["document"], "selection.document")
    duration = document.get("duration_minutes")
    lines = [
        rf"\qbanksettitle{{{_tex_escape(document['title'])}}}",
        rf"\qbanksetsubject{{{_tex_escape(document.get('subject', ''))}}}",
        rf"\qbanksetdate{{{_tex_escape(document.get('date', ''))}}}",
        rf"\qbanksetduration{{{_tex_escape(f'{duration} 分钟' if duration else '')}}}",
        rf"\qbanksetvariant{{{selection['variant']}}}",
    ]
    for (question_id, asset_id), relative in sorted(bindings.items()):
        lines.append(
            rf"\expandafter\def\csname qbankasset@{question_id}@{asset_id}"
            rf"\endcsname{{{relative}}}"
        )
    return "\n".join(lines) + "\n"


def _tool_version(executable: str, runner: Runner) -> str:
    try:
        result = runner(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except OSError:
        return "unavailable"
    lines = (result.stdout or result.stderr).splitlines()
    return lines[0].strip() if lines else "unknown"


def _compile(stage: Path, runner: Runner) -> None:
    if shutil.which("latexmk") is None or shutil.which("xelatex") is None:
        raise DeliveryError("latexmk and XeLaTeX are required for PDF construction")
    result = runner(
        [
            "latexmk",
            "-xelatex",
            "-no-shell-escape",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "main.tex",
        ],
        cwd=stage,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if result.returncode != 0 or not (stage / "main.pdf").is_file():
        tail = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-30:])
        raise DeliveryError(f"TeX build failed:\n{tail}")


def _replace_output(stage_output: Path, output: Path) -> None:
    backup = output.with_name(f".{output.name}.previous")
    if backup.exists():
        shutil.rmtree(backup)
    if output.exists():
        output.replace(backup)
    try:
        stage_output.replace(output)
    except OSError as exc:
        if backup.exists() and not output.exists():
            backup.replace(output)
        raise DeliveryError(f"unable to commit delivery output: {exc}") from exc
    if backup.exists():
        shutil.rmtree(backup)


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & 0x400)


def _safe_output_path(workspace: Path, variant: str) -> Path:
    output_root = workspace.resolve() / "output"
    output = output_root / variant
    backup = output.with_name(f".{output.name}.previous")
    for path in (output_root, output, backup):
        if _is_reparse_point(path):
            raise DeliveryError(f"delivery output path crosses a link or reparse point: {path}")
    if output_root.exists() and not output_root.is_dir():
        raise DeliveryError(f"delivery output root is not a directory: {output_root}")
    return output


def _commit_summary(
    stage_output: Path,
    workspace: Path,
    variant: str,
    summary: Mapping[str, Any],
) -> None:
    (stage_output / "build-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    output = _safe_output_path(workspace, variant)
    output.parent.mkdir(parents=True, exist_ok=True)
    _replace_output(stage_output, output)


def build(
    workspace: Path,
    qbank_root: Path,
    *,
    compile_pdf: bool = True,
    commit_output: bool = True,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    selection_path = workspace / "selection.yaml"
    snapshot_path = workspace / "snapshot" / "questions.jsonl"
    content_path = workspace / "content.tex"
    selection = _load_selection(selection_path)
    current_revision = repository_revision(ProjectContext.from_root(qbank_root))
    if selection["repository_revision"] != current_revision:
        raise DeliveryError(
            "repository revision changed after selection; refresh MCP reads and prepare again"
        )
    questions = _load_questions(snapshot_path)
    rows = _selection_rows(selection, questions)
    content = content_path.read_text(encoding="utf-8")
    _validate_content(content, rows, questions)
    warnings = _warnings(selection, questions)
    stage_parent = workspace if commit_output else None
    stage = Path(tempfile.mkdtemp(prefix=".qbank-deliver-", dir=stage_parent))
    stage_output = stage / "committed-output"
    try:
        template_root = Path(__file__).resolve().parents[1] / "assets" / "tex"
        shutil.copy2(template_root / "main.tex", stage / "main.tex")
        shutil.copy2(template_root / "qbankexam.cls", stage / "qbankexam.cls")
        shutil.copy2(content_path, stage / "content.tex")
        bindings, assets = _stage_assets(workspace, qbank_root, stage, rows)
        (stage / "selection.tex").write_text(
            _selection_tex(selection, bindings),
            encoding="utf-8",
            newline="\n",
        )
        if compile_pdf:
            _compile(stage, runner)
        stage_output.mkdir()
        pdf_sha: str | None = None
        if compile_pdf:
            pdf = stage / "main.pdf"
            output_pdf = stage_output / f"{workspace.name}-{selection['variant']}.pdf"
            shutil.copy2(pdf, output_pdf)
            pdf_sha = hashlib.sha256(output_pdf.read_bytes()).hexdigest()
        summary = {
            "ok": True,
            "repository_revision": selection["repository_revision"],
            "selection_sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
            "template": TEMPLATE_NAME,
            "variant": selection["variant"],
            "questions": [row[0] for row in rows],
            "total_score": sum(row[1] for row in rows),
            "assets": assets,
            "warnings": warnings,
            "tools": {
                "latexmk": _tool_version("latexmk", runner),
                "xelatex": _tool_version("xelatex", runner),
            },
            "pdf_sha256": pdf_sha,
        }
        if commit_output:
            _commit_summary(
                stage_output,
                workspace,
                cast(str, selection["variant"]),
                summary,
            )
        return summary
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--qbank-root", required=True, type=Path)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate without invoking TeX or writing to the delivery workspace.",
    )
    args = parser.parse_args()
    try:
        result = build(
            args.workspace,
            args.qbank_root,
            compile_pdf=not args.validate_only,
            commit_output=not args.validate_only,
        )
    except (DeliveryError, OSError) as exc:
        sys.stdout.write(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2) + "\n"
        )
        return 3
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
