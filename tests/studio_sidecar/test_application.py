from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.errors import ConflictError, DataValidationError, QBankError
from qbank.infrastructure.locking import RepositoryWriteLock
from qbank.markdown_codec import parse_question_text, render_question
from qbank.studio_sidecar.application import StudioApplication
from qbank.studio_sidecar.errors import (
    APPLICATION_ERROR,
    CONFLICT,
    INVALID_PARAMS,
    LOCKED,
    METHOD_NOT_FOUND,
    REPOSITORY_NOT_OPEN,
    VALIDATION,
    RpcError,
)


def test_initialize_reports_unified_core_and_protocol() -> None:
    result = StudioApplication().dispatch("initialize", {"studioVersion": "0.1.0"})
    assert result["coreVersion"] == "0.3.0b2"
    assert result["protocolVersion"] == "1.0"
    assert result["schemaVersions"] == {
        "question": "1.0",
        "asset": "1.0",
        "paper": "1.0",
    }
    assert "question.save" in result["capabilities"]


def test_repository_required_before_reads() -> None:
    with pytest.raises(RpcError) as captured:
        StudioApplication().dispatch("question.list", {})
    assert captured.value.code == REPOSITORY_NOT_OPEN


def test_unknown_method_and_non_repository_are_rejected(tmp_path: Path) -> None:
    app = StudioApplication()
    with pytest.raises(RpcError) as unknown:
        app.dispatch("missing.method", {})
    assert unknown.value.code == METHOD_NOT_FOUND
    with pytest.raises(RpcError) as invalid:
        app.dispatch("repository.open", {"root": str(tmp_path)})
    assert invalid.value.code == INVALID_PARAMS


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (ConflictError("changed"), CONFLICT),
        (DataValidationError("invalid"), VALIDATION),
        (QBankError("write lock unavailable"), LOCKED),
        (OSError("disk unavailable"), APPLICATION_ERROR),
    ],
)
def test_dispatch_maps_application_errors(error: Exception, expected_code: int) -> None:
    app = StudioApplication()

    def fail(_params: dict[str, object]) -> None:
        raise error

    app._methods["test.fail"] = fail
    with pytest.raises(RpcError) as captured:
        app.dispatch("test.fail", {})
    assert captured.value.code == expected_code


def test_parameter_helpers_reject_wrong_types(synthetic_bank: Path) -> None:
    app = StudioApplication()
    with pytest.raises(RpcError) as version:
        app.dispatch("initialize", {"studioVersion": 1})
    assert version.value.code == INVALID_PARAMS
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    with pytest.raises(RpcError) as limit:
        app.dispatch("question.list", {"limit": True})
    assert limit.value.code == INVALID_PARAMS
    with pytest.raises(RpcError) as identifier:
        app.dispatch("question.get", {"id": 1})
    assert identifier.value.code == INVALID_PARAMS


def test_repository_status_loads_bounded_custom_math_macros(
    synthetic_bank: Path,
) -> None:
    config = synthetic_bank / ".qbank" / "studio-math.json"
    config.write_text(
        json.dumps({"macros": {"qop": "\\operatorname{qbank}", "vect": ["\\mathbf{#1}", 1]}}),
        encoding="utf-8",
    )
    app = StudioApplication()
    status = app.dispatch("repository.open", {"root": str(synthetic_bank)})
    assert status["mathMacros"] == {
        "qop": "\\operatorname{qbank}",
        "vect": ["\\mathbf{#1}", 1],
    }
    assert status["studioWarnings"] == []


def test_invalid_custom_math_configuration_is_a_warning(synthetic_bank: Path) -> None:
    config = synthetic_bank / ".qbank" / "studio-math.json"
    config.write_text('{"macros":{"bad-name":true}}', encoding="utf-8")
    status = StudioApplication().dispatch("repository.open", {"root": str(synthetic_bank)})
    assert status["mathMacros"] == {}
    assert status["studioWarnings"][0].startswith("Studio math configuration ignored:")


@pytest.mark.parametrize(
    "macros",
    [
        {"loop": "\\loop"},
        {"left": "\\right", "right": "\\left"},
    ],
)
def test_recursive_custom_math_macros_are_rejected(
    synthetic_bank: Path, macros: dict[str, str]
) -> None:
    config = synthetic_bank / ".qbank" / "studio-math.json"
    config.write_text(json.dumps({"macros": macros}), encoding="utf-8")
    status = StudioApplication().dispatch("repository.open", {"root": str(synthetic_bank)})
    assert status["mathMacros"] == {}
    assert "recursive or excessively deep" in status["studioWarnings"][0]


def test_open_list_search_get_validate_save(synthetic_bank: Path) -> None:
    app = StudioApplication()
    status = app.dispatch("repository.open", {"root": str(synthetic_bank)})
    assert status["healthy"] is True
    assert status["questionCount"] == 2
    assert [item["id"] for item in status["questions"]] == [
        "MATH-SYN-0002",
        "OPT-SYN-0001",
    ]
    assert status["tags"]
    assert status["views"]

    questions = app.dispatch("question.list", {})
    assert [item["id"] for item in questions] == ["MATH-SYN-0002", "OPT-SYN-0001"]
    assert isinstance(questions[0]["topics"], list)
    assert "question_type" not in questions[0]
    search_hit = app.dispatch("question.search", {"text": "干涉"})[0]
    assert search_hit["id"] == "OPT-SYN-0001"
    assert isinstance(search_hit["topics"], list)
    assert search_hit["type"] == "short_answer"

    document = app.dispatch("question.get", {"id": "OPT-SYN-0001"})
    assert "<!-- synthetic fixture" in document["source"]
    changed = document["source"].replace("相位差为", "初始相位差为", 1)
    validation = app.dispatch("question.validate", {"id": "OPT-SYN-0001", "source": changed})
    assert validation["ok"] is True
    saved = app.dispatch(
        "question.save",
        {
            "id": "OPT-SYN-0001",
            "source": changed,
            "expectedRevision": document["revision"],
        },
    )
    assert saved["ok"] is True
    assert "初始相位差" in saved["source"]
    assert "<!-- synthetic fixture" in saved["source"]
    assert (synthetic_bank / ".qbank" / "history").is_dir()


def test_repository_activation_is_atomic_and_index_rebuild_is_explicit(
    synthetic_bank: Path,
    tmp_path: Path,
) -> None:
    unavailable = tmp_path / "missing-index"
    shutil.copytree(synthetic_bank, unavailable)
    (unavailable / ".qbank" / "index.sqlite").unlink()
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})

    with pytest.raises(RpcError) as captured:
        app.dispatch("repository.open", {"root": str(unavailable)})

    assert captured.value.code == VALIDATION
    assert captured.value.data == {
        "diagnosticCode": "index_unavailable",
        "canRebuildIndex": True,
    }
    assert app.repository is not None
    assert app.repository.context.root == synthetic_bank.resolve()
    rebuilt = app.dispatch("repository.rebuildIndex", {"root": str(unavailable)})
    assert rebuilt["indexed"] == 2
    assert [item["id"] for item in rebuilt["questions"]] == [
        "MATH-SYN-0002",
        "OPT-SYN-0001",
    ]
    assert app.repository.context.root == unavailable.resolve()


def test_failed_index_rebuild_preserves_the_active_repository(
    synthetic_bank: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unavailable = tmp_path / "failed-rebuild"
    shutil.copytree(synthetic_bank, unavailable)
    (unavailable / ".qbank" / "index.sqlite").unlink()
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    assert app.repository is not None
    service_type = type(app.repository.services.questions)

    def fail_rebuild(_service: object) -> int:
        raise OSError("synthetic rebuild failure")

    monkeypatch.setattr(service_type, "rebuild_index", fail_rebuild)

    with pytest.raises(RpcError, match="synthetic rebuild failure"):
        app.dispatch("repository.rebuildIndex", {"root": str(unavailable)})

    assert app.repository is not None
    assert app.repository.context.root == synthetic_bank.resolve()


def test_asset_inventory_exposes_safe_local_external_and_invalid_items(
    synthetic_bank: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = synthetic_bank / "assets" / "images" / "local.svg"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
        '<rect width="20" height="10" fill="#4d7898"/></svg>',
        encoding="utf-8",
    )
    question_path = (
        synthetic_bank / "questions" / "mathematics" / "MATH-SYN-0002.md"
    )
    question, _, _ = parse_question_text(question_path.read_text(encoding="utf-8"))
    question = question.model_copy(
        update={
            "assets": [
                "assets/images/local.svg",
                "HTTPS://example.invalid/figure.svg",
                "../outside.svg",
            ],
            "stem_md": (
                f"{question.stem_md}\n\n![local](assets/images/local.svg)"
                "\n\n![remote](HTTPS://example.invalid/figure.svg)"
                "\n\n![invalid](../outside.svg)"
            ),
        }
    )
    question_path.write_text(render_question(question), encoding="utf-8")
    context = ProjectContext.from_root(synthetic_bank)
    create_project_services(context).questions.rebuild_index()

    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    items = app.dispatch("asset.list", {"questionId": "MATH-SYN-0002"})
    by_kind = {item["kind"]: item for item in items}
    assert by_kind["local"]["reference"] == "assets/images/local.svg"
    assert by_kind["local"]["previewDataUrl"].startswith("data:image/svg+xml;base64,")
    assert by_kind["local"]["capabilities"]["canOpen"] is True
    assert by_kind["external"]["previewDataUrl"] is None
    assert by_kind["external"]["diagnostic"]["code"] == "external_asset"
    assert by_kind["invalid"]["previewDataUrl"] is None
    assert by_kind["invalid"]["capabilities"]["canOpen"] is False

    assert app.repository is not None
    launcher = app.repository.services.assets.launcher
    opened: list[Path] = []
    monkeypatch.setattr(
        launcher,
        "open_file",
        lambda path, *, execute: opened.append(path) or ("open", str(path)),
    )
    result = app.dispatch(
        "asset.open",
        {
            "questionId": "MATH-SYN-0002",
            "reference": "assets/images/local.svg",
            "action": "open_reference",
        },
    )
    assert result["result"]["command"][0] == "open"
    assert opened[-1] == local.resolve()
    with pytest.raises(RpcError) as invalid:
        app.dispatch(
            "asset.open",
            {
                "questionId": "MATH-SYN-0002",
                "reference": "../outside.svg",
                "action": "open_reference",
            },
        )
    assert invalid.value.code == INVALID_PARAMS

def test_session_reads_reuse_one_snapshot(
    synthetic_bank: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    assert app.repository is not None
    repository = app.repository.services.repository
    original_scan = repository.scan
    scan_count = 0

    def counted_scan(*args: object, **kwargs: object) -> object:
        nonlocal scan_count
        scan_count += 1
        return original_scan(*args, **kwargs)

    monkeypatch.setattr(repository, "scan", counted_scan)
    app.dispatch("question.list", {"limit": 100})
    app.dispatch("question.search", {"text": "干涉"})
    app.dispatch("question.get", {"id": "OPT-SYN-0001"})
    app.dispatch("repository.status", {})
    assert scan_count == 0


def test_repository_status_refreshes_snapshot_after_external_change(
    synthetic_bank: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    assert app.repository is not None
    repository = app.repository.services.repository
    original_scan = repository.scan
    scan_count = 0

    def counted_scan(*args: object, **kwargs: object) -> object:
        nonlocal scan_count
        scan_count += 1
        return original_scan(*args, **kwargs)

    monkeypatch.setattr(repository, "scan", counted_scan)
    path = synthetic_bank / "questions" / "optics" / "OPT-SYN-0001.md"
    source = path.read_text(encoding="utf-8")
    title_line = next(line for line in source.splitlines() if line.startswith("title:"))
    path.write_text(source.replace(title_line, "title: Externally updated", 1), encoding="utf-8")

    app.dispatch("repository.status", {})
    document = app.dispatch("question.get", {"id": "OPT-SYN-0001"})
    assert document["question"]["title"] == "Externally updated"
    assert scan_count == 1


def test_save_rejects_stale_revision(synthetic_bank: Path) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    document = app.dispatch("question.get", {"id": "OPT-SYN-0001"})
    with pytest.raises(RpcError) as captured:
        app.dispatch(
            "question.save",
            {
                "id": "OPT-SYN-0001",
                "source": document["source"],
                "expectedRevision": "stale",
            },
        )
    assert captured.value.code == CONFLICT
    assert isinstance(captured.value.data, dict)
    assert captured.value.data["actualRevision"] == document["revision"]


def test_assets_return_contained_preview_and_history(synthetic_bank: Path) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    assets = app.dispatch("asset.list", {"questionId": "OPT-SYN-0001"})
    assert [item["assetId"] for item in assets] == ["diagram-1", "ipe-figure"]
    assert assets[0]["assetId"] == "diagram-1"
    assert assets[0]["previewDataUrl"].startswith("data:image/svg+xml;base64,")
    assert assets[0]["capabilities"]["canEditIpe"] is False
    assert assets[1]["capabilities"]["canEditIpe"] is True
    assert assets[1]["capabilities"]["canRender"] is True
    assert app.dispatch("history.list", {"questionId": "OPT-SYN-0001"}) == []


def test_taxonomy_and_all_asset_open_actions_use_registered_launcher(
    synthetic_bank: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    assert app.repository is not None
    assert isinstance(app.dispatch("taxonomy.list", {}), list)
    launcher = app.repository.services.assets.launcher
    monkeypatch.setattr(launcher, "open_file", lambda path, *, execute: ("open", str(path)))
    monkeypatch.setattr(launcher, "open_directory", lambda path, *, execute: ("reveal", str(path)))
    monkeypatch.setattr(
        launcher,
        "edit_file",
        lambda path, format_, *, execute: ("edit", format_.value, str(path)),
    )
    for action in ("open", "original", "reveal"):
        result = app.dispatch(
            "asset.open",
            {"questionId": "OPT-SYN-0001", "assetId": "diagram-1", "action": action},
        )
        assert result["result"]["dry_run"] is False
    revision = app.dispatch("question.get", {"id": "OPT-SYN-0001"})["revision"]
    edited = app.dispatch(
        "asset.open",
        {
            "questionId": "OPT-SYN-0001",
            "assetId": "ipe-figure",
            "action": "edit_ipe",
            "expectedRevision": revision,
        },
    )
    assert edited["result"]["action"] == "edit"
    with pytest.raises(RpcError) as unsupported:
        app.dispatch(
            "asset.open",
            {"questionId": "OPT-SYN-0001", "assetId": "diagram-1", "action": "shell"},
        )
    assert unsupported.value.code == INVALID_PARAMS
    assert app.dispatch("history.list", {"questionId": "OPT-SYN-0001"})


def test_asset_create_uses_bytes_and_declares_reference(synthetic_bank: Path) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    document = app.dispatch("question.get", {"id": "MATH-SYN-0002"})
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"synthetic-not-decoded-by-qbank").decode("ascii")
    source = document["source"].replace(
        "求线性方程组的形式解。",
        "求线性方程组的形式解。\n\n![合成图](qbank-asset:figure-1)",
    )
    result = app.dispatch(
        "asset.create",
        {
            "questionId": "MATH-SYN-0002",
            "assetId": "figure-1",
            "source": source,
            "mediaType": "image/png",
            "dataBase64": png,
            "expectedRevision": document["revision"],
        },
    )
    assert result["ok"] is True
    loaded = app.dispatch("question.get", {"id": "MATH-SYN-0002"})
    assert "qbank-asset:figure-1" in loaded["source"]
    assert (synthetic_bank / "assets" / "MATH-SYN-0002" / "figure-1" / "asset.yaml").is_file()


def test_asset_create_accepts_editable_ipe_without_a_render_preference(
    synthetic_bank: Path,
) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    document = app.dispatch("question.get", {"id": "MATH-SYN-0002"})
    ipe = (synthetic_bank / "assets" / "OPT-SYN-0001" / "ipe-figure" / "source.ipe").read_bytes()
    source = document["source"].replace(
        "求线性方程组的形式解。",
        "求线性方程组的形式解。\n\n![Ipe](qbank-asset:ipe-new)",
    )
    result = app.dispatch(
        "asset.create",
        {
            "questionId": "MATH-SYN-0002",
            "assetId": "ipe-new",
            "source": source,
            "mediaType": "application/x-ipe",
            "dataBase64": base64.b64encode(ipe).decode("ascii"),
            "expectedRevision": document["revision"],
        },
    )
    assert result["ok"] is True
    item = app.dispatch("asset.list", {"questionId": "MATH-SYN-0002"})[0]
    assert item["preferredRepresentation"] is None
    assert item["capabilities"]["canRender"] is True


def test_asset_mutation_rejects_stale_revision(synthetic_bank: Path) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    with pytest.raises(RpcError) as captured:
        app.dispatch(
            "asset.render",
            {
                "questionId": "OPT-SYN-0001",
                "assetId": "ipe-figure",
                "formats": ["svg"],
                "expectedRevision": "stale",
            },
        )
    assert captured.value.code == CONFLICT
    assert isinstance(captured.value.data, dict)
    assert "actualRevision" in captured.value.data


@pytest.mark.parametrize(
    "params",
    [
        {"mediaType": "application/x-unknown", "dataBase64": "AA=="},
        {"mediaType": "image/png", "dataBase64": "not-base64"},
    ],
)
def test_asset_input_rejects_unknown_or_invalid_payloads(
    synthetic_bank: Path,
    params: dict[str, str],
) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    document = app.dispatch("question.get", {"id": "MATH-SYN-0002"})
    with pytest.raises(RpcError) as captured:
        app.dispatch(
            "asset.create",
            {
                "questionId": "MATH-SYN-0002",
                "assetId": "invalid",
                "source": document["source"],
                "expectedRevision": document["revision"],
                **params,
            },
        )
    assert captured.value.code == INVALID_PARAMS


def test_render_rejects_non_array_formats(synthetic_bank: Path) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    revision = app.dispatch("question.get", {"id": "OPT-SYN-0001"})["revision"]
    with pytest.raises(RpcError) as captured:
        app.dispatch(
            "asset.render",
            {
                "questionId": "OPT-SYN-0001",
                "assetId": "ipe-figure",
                "formats": "svg",
                "expectedRevision": revision,
            },
        )
    assert captured.value.code == INVALID_PARAMS


def test_asset_replace_uses_qbank_versioned_storage(synthetic_bank: Path) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    document = app.dispatch("question.get", {"id": "OPT-SYN-0001"})
    replacement = b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>'
    result = app.dispatch(
        "asset.replace",
        {
            "questionId": "OPT-SYN-0001",
            "assetId": "diagram-1",
            "mediaType": "image/svg+xml",
            "dataBase64": base64.b64encode(replacement).decode("ascii"),
            "expectedRevision": document["revision"],
        },
    )
    assert result["result"]["action"] == "replace"
    assert result["revision"] != document["revision"]
    assets = app.dispatch("asset.list", {"questionId": "OPT-SYN-0001"})
    assert len(assets[0]["representations"]) == 2


def test_question_save_reports_real_cross_process_lock(synthetic_bank: Path) -> None:
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "from qbank.context import ProjectContext\n"
        "from qbank.infrastructure.locking import RepositoryWriteLock\n"
        "context=ProjectContext.from_root(Path(sys.argv[1]))\n"
        "with RepositoryWriteLock(context).hold('sidecar-test-holder'):\n"
        " print('ready', flush=True)\n"
        " sys.stdin.readline()\n"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", script, str(synthetic_bank)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "ready"
        app = StudioApplication()
        app.dispatch("repository.open", {"root": str(synthetic_bank)})
        assert app.repository is not None
        lock = app.repository.services.mutations.lock
        assert isinstance(lock, RepositoryWriteLock)
        lock.default_timeout = 0.15
        document = app.dispatch("question.get", {"id": "OPT-SYN-0001"})
        changed = document["source"].replace("difficulty: 2", "difficulty: 3", 1)
        with pytest.raises(RpcError) as captured:
            app.dispatch(
                "question.save",
                {
                    "id": "OPT-SYN-0001",
                    "source": changed,
                    "expectedRevision": document["revision"],
                },
            )
        assert captured.value.code == LOCKED
    finally:
        if holder.stdin is not None:
            holder.stdin.write("\n")
            holder.stdin.flush()
        holder.wait(timeout=5)


def test_real_ipe_render_and_reconcile(synthetic_bank: Path) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    document = app.dispatch("question.get", {"id": "OPT-SYN-0001"})
    rendered = app.dispatch(
        "asset.render",
        {
            "questionId": "OPT-SYN-0001",
            "assetId": "ipe-figure",
            "formats": ["svg", "png", "pdf"],
            "expectedRevision": document["revision"],
        },
    )
    assert rendered["assets"][1]["previewDataUrl"].startswith("data:image/svg+xml;base64,")

    source = synthetic_bank / "assets" / "OPT-SYN-0001" / "ipe-figure" / "source.ipe"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</ipe>", "<!-- synthetic external Ipe edit -->\n</ipe>"
        ),
        encoding="utf-8",
    )
    reconciled = app.dispatch(
        "asset.reconcile",
        {
            "questionId": "OPT-SYN-0001",
            "assetId": "ipe-figure",
            "expectedRevision": rendered["revision"],
        },
    )
    assert reconciled["changed"] is True
    assert reconciled["render"] is not None
    refreshed = app.dispatch("asset.list", {"questionId": "OPT-SYN-0001"})[1]
    assert refreshed["status"] != "final"
    assert all(not item["stale"] for item in refreshed["representations"])


def test_reconcile_rejects_unrelated_repository_change(synthetic_bank: Path) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    document = app.dispatch("question.get", {"id": "OPT-SYN-0001"})
    rendered = app.dispatch(
        "asset.render",
        {
            "questionId": "OPT-SYN-0001",
            "assetId": "ipe-figure",
            "formats": ["svg"],
            "expectedRevision": document["revision"],
        },
    )
    source = synthetic_bank / "assets" / "OPT-SYN-0001" / "ipe-figure" / "source.ipe"
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    config = synthetic_bank / "qbank.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(RpcError) as captured:
        app.dispatch(
            "asset.reconcile",
            {
                "questionId": "OPT-SYN-0001",
                "assetId": "ipe-figure",
                "expectedRevision": rendered["revision"],
            },
        )
    assert captured.value.code == CONFLICT


def test_bad_source_is_local_validation_not_write(synthetic_bank: Path) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    result = app.dispatch("question.validate", {"id": "OPT-SYN-0001", "source": "not markdown"})
    assert result["ok"] is False
    assert result["diagnostics"][0]["code"] == "invalid_source_file"


def test_validation_reports_identity_and_duplicate_sections(
    synthetic_bank: Path,
) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    source = app.dispatch("question.get", {"id": "OPT-SYN-0001"})["source"]
    mismatched = source.replace("id: OPT-SYN-0001", "id: OPT-SYN-OTHER", 1)
    identity = app.dispatch(
        "question.validate",
        {"id": "OPT-SYN-0001", "source": mismatched},
    )
    assert any(item["code"] == "question_identity_mismatch" for item in identity["diagnostics"])
    duplicated = source + "\n## 题目\n\n重复章节。\n"
    duplicate = app.dispatch(
        "question.validate",
        {"id": "OPT-SYN-0001", "source": duplicated},
    )
    assert any(item["code"] == "duplicate_section" for item in duplicate["diagnostics"])


def test_structured_update_and_filters_use_qbank_services(synthetic_bank: Path) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    document = app.dispatch("question.get", {"id": "OPT-SYN-0001"})
    updated = app.dispatch(
        "question.update",
        {
            "id": "OPT-SYN-0001",
            "set": {
                "chapter": "wave-optics",
                "source": {"type": "book", "reference": "Synthetic source, p. 12"},
            },
            "topics": ["interference", "calibration"],
            "expectedRevision": document["revision"],
        },
    )
    assert updated["ok"] is True
    assert updated["question"]["source"]["reference"] == "Synthetic source, p. 12"
    assert updated["question"]["topics"] == ["interference", "calibration"]
    assert [
        item["id"]
        for item in app.dispatch(
            "question.list",
            {"subject": "optics", "topics": ["calibration"], "topicMode": "and"},
        )
    ] == ["OPT-SYN-0001"]


def test_create_copy_import_and_delete_are_dry_run_first(
    synthetic_bank: Path,
) -> None:
    app = StudioApplication()
    opened = app.dispatch("repository.open", {"root": str(synthetic_bank)})
    created = app.dispatch(
        "question.create",
        {
            "id": "PHY-NEW-0001",
            "title": "Synthetic created question",
            "expectedRevision": app.dispatch("question.get", {"id": "OPT-SYN-0001"})["revision"],
        },
    )
    assert created["dryRun"]["dry_run"] is True
    assert created["result"]["dry_run"] is False
    copied = app.dispatch(
        "question.copy",
        {
            "sourceId": "MATH-SYN-0002",
            "newId": "MATH-COPY-0001",
            "expectedRevision": created["document"]["revision"],
        },
    )
    assert copied["document"]["question"]["status"] == "draft"

    source = app.dispatch("question.get", {"id": "MATH-SYN-0002"})["question"]
    source.update({"id": "MATH-IMPORT-0003", "title": "Imported synthetic question"})
    exchange = synthetic_bank / "incoming.json"
    exchange.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    imported = app.dispatch(
        "question.import",
        {
            "path": str(exchange),
            "expectedRevision": copied["document"]["revision"],
        },
    )
    assert imported["ok"] is True
    assert imported["dryRun"]["dry_run"] is True

    revision = app.dispatch("question.get", {"id": "MATH-IMPORT-0003"})["revision"]
    deleted = app.dispatch(
        "question.delete",
        {"id": "PHY-NEW-0001", "expectedRevision": revision},
    )
    assert deleted["dryRun"]["dry_run"] is True
    assert deleted["result"]["dry_run"] is False
    assert opened["questionCount"] == 2


def test_paper_create_edit_validate_and_build(synthetic_bank: Path) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    revision = app.dispatch("question.get", {"id": "OPT-SYN-0001"})["revision"]
    created = app.dispatch(
        "paper.create",
        {
            "path": "generated/studio-uat.yaml",
            "title": "Studio synthetic UAT",
            "questionIds": ["OPT-SYN-0001"],
            "expectedRevision": revision,
        },
    )
    assert created["ok"] is True
    listed = app.dispatch("paper.list", {})
    paper_path = next(item["path"] for item in listed if item["title"] == "Studio synthetic UAT")
    document = app.dispatch("paper.get", {"path": paper_path})
    paper = document["paper"]
    paper["sections"][0]["questions"][0]["score"] = 5
    paper["metadata"] = {"total_score": 5}
    saved = app.dispatch(
        "paper.save",
        {
            "path": paper_path,
            "paper": paper,
            "expectedRevision": document["revision"],
        },
    )
    report = app.dispatch("paper.validate", {"path": paper_path})
    assert report["ok"] is True
    output = synthetic_bank / "exports" / "studio-uat-student.md"
    built = app.dispatch(
        "paper.build",
        {
            "path": paper_path,
            "format": "md",
            "output": str(output),
            "options": {
                "with_answers": False,
                "with_solutions": False,
                "with_rubric": False,
                "show_ids": False,
            },
            "expectedRevision": saved["revision"],
        },
    )
    assert built["ok"] is True
    assert output.is_file()
    assert "## 答案" not in output.read_text(encoding="utf-8")


def test_advanced_taxonomy_overview_and_selected_bulk_edit(
    synthetic_bank: Path,
) -> None:
    app = StudioApplication()
    app.dispatch("repository.open", {"root": str(synthetic_bank)})
    tags = app.dispatch("taxonomy.list", {})
    interference = next(item for item in tags if item["slug"] == "interference")
    assert interference["count"] == 1
    assert interference["metadata"]["name_zh"] == "干涉"

    revision = app.dispatch("repository.status", {})["revision"]
    created = app.dispatch(
        "taxonomy.update",
        {
            "tag": {
                "slug": "zero-count",
                "name_zh": "零计数标签",
                "aliases": ["unused-alias"],
                "description": "用于验证注册表零计数可见性",
                "status": "active",
            },
            "expectedRevision": revision,
        },
    )
    assert created["dryRun"]["dry_run"] is True
    zero = next(item for item in app.dispatch("taxonomy.list", {}) if item["slug"] == "zero-count")
    assert zero["count"] == 0
    assert zero["metadata"]["aliases"] == ["unused-alias"]
    assert app.dispatch("taxonomy.suggest", {"text": "零计数"})[0]["slug"] == "zero-count"

    edited = app.dispatch(
        "taxonomy.bulkEdit",
        {
            "questionIds": ["MATH-SYN-0002"],
            "add": ["zero-count"],
            "remove": [],
            "expectedRevision": created["revision"],
        },
    )
    assert edited["ok"] is True
    assert edited["dryRun"]["changes"][0]["id"] == "MATH-SYN-0002"
    assert (
        "zero-count" in app.dispatch("question.get", {"id": "MATH-SYN-0002"})["question"]["topics"]
    )
    assert (
        "zero-count"
        not in app.dispatch("question.get", {"id": "OPT-SYN-0001"})["question"]["topics"]
    )
    overview = app.dispatch("taxonomy.overview", {"topN": 20})
    assert any(item["slug"] == "zero-count" for item in overview["frequencies"])
    assert overview["chapter_coverage"]


def test_saved_views_and_atomic_bulk_fields_preserve_full_filters(
    synthetic_bank: Path,
) -> None:
    app = StudioApplication()
    opened = app.dispatch("repository.open", {"root": str(synthetic_bank)})
    filters = {
        "text": "no-current-match",
        "subject": "optics",
        "chapter": "missing-chapter",
        "topics": ["interference"],
        "excludedTopics": ["linear-algebra"],
        "topicMode": "or",
        "type": "short_answer",
        "status": "reviewed",
        "difficultyMin": 2,
        "difficultyMax": 4,
        "language": "zh-CN",
        "year": 2025,
    }
    saved = app.dispatch(
        "view.save",
        {
            "name": "完整筛选",
            "filters": filters,
            "expectedRevision": opened["revision"],
        },
    )
    assert saved["dryRun"]["dry_run"] is True
    view = next(item for item in app.dispatch("view.list", {}) if item["name"] == "完整筛选")
    assert view["filters"]["chapter"] == "missing-chapter"
    assert view["filters"]["excluded_topics"] == ["linear-algebra"]
    assert view["filters"]["year"] == 2025

    updated = app.dispatch(
        "question.bulkUpdate",
        {
            "questionIds": ["MATH-SYN-0002", "OPT-SYN-0001"],
            "set": {"status": "verified", "chapter": "batch-reviewed"},
            "expectedRevision": saved["revision"],
        },
    )
    assert updated["ok"] is True
    assert updated["dryRun"]["would_write"] == 2
    for question_id in ("MATH-SYN-0002", "OPT-SYN-0001"):
        question = app.dispatch("question.get", {"id": question_id})["question"]
        assert question["status"] == "verified"
        assert question["chapter"] == "batch-reviewed"
