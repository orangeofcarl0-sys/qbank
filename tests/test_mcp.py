"""Protocol and transaction coverage for the optional local MCP adapter."""

from __future__ import annotations

import json
import sys
import tempfile
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pydantic import AnyUrl

import qbank.services.mcp_config as mcp_config
from qbank.application.revision import repository_revision
from qbank.cli import app
from qbank.codex_manifest import MCP_RESOURCE_URIS, MCP_TOOL_NAMES
from qbank.context import ProjectContext
from qbank.diagnostics import project_status_in_context
from qbank.errors import (
    AssetNotFoundError,
    ConflictError,
    DataValidationError,
    QuestionNotFoundError,
)
from qbank.mcp.adapter import QbankMcpAdapter
from qbank.mcp.operations import OperationStore
from qbank.mcp.server import create_mcp_server
from qbank.models import (
    IngestPrepareRequest,
    Paper,
    PaperPrepareRequest,
    PatchPrepareRequest,
    TagChangePrepareRequest,
)
from qbank.services.mcp_config import (
    install_project_mcp,
    mcp_integration_status,
    uninstall_project_mcp,
)


def test_server_discovery_matches_manifest(project: tuple[Path, object]) -> None:
    root, _ = project
    server = create_mcp_server(QbankMcpAdapter(ProjectContext.from_root(root)))
    tools = server._tool_manager.list_tools()
    resources = server._resource_manager.list_resources()
    templates = server._resource_manager.list_templates()

    assert tuple(item.name for item in tools) == MCP_TOOL_NAMES
    advertised = {str(item.uri) for item in resources}
    advertised.update(str(item.uri_template) for item in templates)
    assert set(MCP_RESOURCE_URIS) <= advertised
    annotations = {item.name: item.annotations for item in tools}
    assert annotations["repository_status"].readOnlyHint is True
    assert annotations["operation_commit"].destructiveHint is True
    assert annotations["operation_commit"].idempotentHint is True


def test_stdio_initialize_tools_and_resource(project: tuple[Path, object], question) -> None:
    root, _ = project
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:

        async def exercise() -> None:
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "qbank", "mcp", "--repository", str(root)],
                cwd=str(root),
            )
            async with (
                stdio_client(parameters, errlog=errors) as streams,
                ClientSession(*streams) as session,
            ):
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "qbank"
                tools = await session.list_tools()
                assert [item.name for item in tools.tools] == list(MCP_TOOL_NAMES)
                resource = await session.read_resource(AnyUrl("qbank://repository/info"))
                payload = json.loads(resource.contents[0].text)
                assert payload["root"] == str(root)
                assert payload["repository_revision"].startswith("sha256:")
                status = await session.call_tool("repository_status", {})
                assert status.isError is False
                assert status.structuredContent["questions"] == 0
                prepared = await session.call_tool(
                    "ingest_prepare",
                    {"request": {"questions": [question.model_dump(mode="json")]}},
                )
                assert prepared.isError is False
                preview = prepared.structuredContent
                assert preview["committable"] is True
                assert not list((root / "questions").rglob("*.md"))
                committed = await session.call_tool(
                    "operation_commit",
                    {
                        "operation_id": preview["operation_id"],
                        "repository_revision": preview["repository_revision"],
                    },
                )
                assert committed.isError is False
                fetched = await session.call_tool("question_get", {"question_id": question.id})
                assert fetched.structuredContent["id"] == question.id

        anyio.run(exercise)
        errors.seek(0)
        assert errors.read() == ""


def test_prepare_commit_revision_conflict_and_idempotence(
    project: tuple[Path, object],
    question,
) -> None:
    root, _ = project
    adapter = QbankMcpAdapter(ProjectContext.from_root(root))
    prepared = adapter.ingest_prepare(IngestPrepareRequest(questions=[question]))

    assert prepared.committable
    assert not list((root / "questions").rglob("*.md"))
    committed = adapter.operation_commit(prepared.operation_id, prepared.repository_revision)
    assert committed.status == "committed"
    assert len(list((root / "questions").rglob("*.md"))) == 1
    history_count = len(list((root / ".qbank" / "history").glob("*.json")))

    replay = adapter.operation_commit(prepared.operation_id, prepared.repository_revision)
    assert replay.idempotent_replay
    assert len(list((root / ".qbank" / "history").glob("*.json"))) == history_count

    patch = adapter.patch_prepare(
        PatchPrepareRequest.model_validate(
            {"question_id": question.id, "patch": {"set": {"title": "changed"}}}
        )
    )
    (root / "papers" / "concurrent.txt").write_text("change", encoding="utf-8")
    with pytest.raises(ConflictError, match="changed after prepare"):
        adapter.operation_commit(patch.operation_id, patch.repository_revision)
    late_replay = adapter.operation_commit(prepared.operation_id, prepared.repository_revision)
    assert late_replay.idempotent_replay
    assert late_replay.repository_revision == committed.repository_revision


def test_adapter_reads_and_all_prepared_mutation_kinds(
    project: tuple[Path, object],
    question,
) -> None:
    root, _ = project
    adapter = QbankMcpAdapter(ProjectContext.from_root(root))
    status = adapter.repository_status()
    shared_status = project_status_in_context(adapter.context, adapter.services.diagnostics)
    assert {key: value for key, value in status.items() if key != "repository_revision"} == (
        shared_status.model_dump(mode="json")
    )
    assert status["questions"] == 0
    assert adapter.schema_get("patch")["title"] == "QuestionPatch"
    assert adapter.question_search(limit=2).mode == "query"

    ingest = adapter.ingest_prepare(IngestPrepareRequest(questions=[question]))
    adapter.operation_commit(ingest.operation_id, ingest.repository_revision)
    assert adapter.question_get(question.id).id == question.id
    assert adapter.question_validate(question.id).ok
    assert adapter.question_search(text="Michelson", limit=3).items
    assert adapter.taxonomy_get().schema_version == "1.0"
    assert adapter.history_get(question.id)
    assert adapter.paper_get("demo-paper").id == "demo-paper"

    patch = adapter.patch_prepare(
        PatchPrepareRequest.model_validate(
            {"question_id": question.id, "patch": {"set": {"title": "Revised"}}}
        )
    )
    adapter.operation_commit(patch.operation_id, patch.repository_revision)
    assert adapter.question_get(question.id).title == "Revised"

    tag = adapter.tag_change_prepare(
        TagChangePrepareRequest(
            action="rename",
            source="interferometry",
            target="interferometry-renamed",
        )
    )
    adapter.operation_commit(tag.operation_id, tag.repository_revision)
    assert "interferometry-renamed" in adapter.question_get(question.id).topics

    paper = Paper.model_validate(
        {
            "schema_version": "1.0",
            "title": "Prepared paper",
            "sections": [{"title": "S", "questions": [{"id": question.id, "score": 2}]}],
        }
    )
    paper_plan = adapter.paper_prepare(
        PaperPrepareRequest(path="papers/generated/mcp-paper.yaml", paper=paper)
    )
    paper_result = adapter.operation_commit(
        paper_plan.operation_id,
        paper_plan.repository_revision,
    )
    assert paper_result.result["paper"]["title"] == "Prepared paper"
    assert adapter.paper_get("generated/mcp-paper.yaml").paper.title == "Prepared paper"

    with pytest.raises(DataValidationError, match="limit"):
        adapter.question_search(limit=0)
    with pytest.raises(DataValidationError, match="not both"):
        adapter.question_search(text="x", filters={})
    with pytest.raises(QuestionNotFoundError, match="not found"):
        adapter.paper_get("missing")
    with pytest.raises(AssetNotFoundError, match="asset"):
        adapter.asset_get(question.id, "missing")


def test_in_process_server_wrappers_and_resources(
    project: tuple[Path, object],
    question,
) -> None:
    root, _ = project
    server = create_mcp_server(QbankMcpAdapter(ProjectContext.from_root(root)))

    async def exercise() -> None:
        manager = server._tool_manager
        status = await manager.call_tool("repository_status", {})
        assert status["questions"] == 0
        assert (await manager.call_tool("schema_get", {"kind": "question"}))["title"] == "Question"
        assert (await manager.call_tool("question_search", {"limit": 1})).mode == "query"
        assert (await manager.call_tool("taxonomy_get", {})).schema_version == "1.0"
        plan = await manager.call_tool(
            "ingest_prepare", {"request": {"questions": [question.model_dump(mode="json")]}}
        )
        cancelled = await manager.call_tool(
            "operation_cancel",
            {"operation_id": plan.operation_id},
        )
        assert cancelled.status == "cancelled"
        for uri in (
            "qbank://repository/info",
            "qbank://schema/question",
            "qbank://schema/asset",
            "qbank://schema/paper",
            "qbank://taxonomy",
        ):
            resource = await server._resource_manager.get_resource(uri)
            assert resource is not None
            assert await resource.read()

    anyio.run(exercise)


def test_cancel_expiry_and_paper_escape(project: tuple[Path, object], question) -> None:
    root, _ = project
    adapter = QbankMcpAdapter(ProjectContext.from_root(root))
    prepared = adapter.ingest_prepare(IngestPrepareRequest(questions=[question]))
    cancelled = adapter.operation_cancel(prepared.operation_id)
    replay = adapter.operation_cancel(prepared.operation_id)
    assert cancelled.status == "cancelled"
    assert replay.idempotent_replay
    with pytest.raises(ConflictError, match="cancelled"):
        adapter.operation_commit(prepared.operation_id, prepared.repository_revision)

    paper = Paper.model_validate(
        {
            "schema_version": "1.0",
            "title": "T",
            "sections": [{"title": "S", "questions": [{"id": question.id, "score": 1}]}],
        }
    )
    with pytest.raises(DataValidationError, match="contained relative"):
        adapter.paper_prepare(PaperPrepareRequest(path="../escape.yaml", paper=paper))
    with pytest.raises(DataValidationError, match="contained relative"):
        adapter.paper_prepare(PaperPrepareRequest(path="C:\\escape.yaml", paper=paper))

    now = datetime(2026, 1, 1, tzinfo=UTC)
    store = OperationStore(
        lambda: "revision",
        lambda _operation: {"ok": True},
        ttl=timedelta(seconds=1),
        now=lambda: now + timedelta(seconds=2),
    )
    operation_id, expires = "expired", now + timedelta(seconds=1)
    preview = prepared.model_copy(
        update={
            "operation_id": operation_id,
            "repository_revision": "revision",
            "expires_at": expires,
        }
    )
    store.add(IngestPrepareRequest(questions=[question]), preview)
    with pytest.raises(ConflictError, match="expired"):
        store.commit(operation_id, "revision")


def test_revision_rejects_authoritative_symlink(
    project: tuple[Path, object],
    tmp_path: Path,
) -> None:
    root, _ = project
    target = tmp_path / "outside.md"
    target.write_text("outside", encoding="utf-8")
    link = root / "questions" / "escape.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are unavailable")
    with pytest.raises(DataValidationError, match="escapes the repository"):
        repository_revision(ProjectContext.from_root(root))


def test_project_mcp_config_is_dry_run_scoped_and_reversible(
    project: tuple[Path, object],
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    config = root / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('model = "gpt-5"\n', encoding="utf-8")

    planned = install_project_mcp(context, dry_run=True)
    assert planned.changed
    assert config.read_text(encoding="utf-8") == 'model = "gpt-5"\n'

    installed = install_project_mcp(context, dry_run=False)
    assert installed.changed
    assert "[mcp_servers.qbank]" in config.read_text(encoding="utf-8")
    assert str(root).replace("\\", "\\\\") in config.read_text(encoding="utf-8")
    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    assert parsed["mcp_servers"]["qbank"]["command"] == sys.executable
    assert parsed["mcp_servers"]["qbank"]["args"][-1] == str(root)
    assert mcp_integration_status(context).registered

    removed = uninstall_project_mcp(context, dry_run=False)
    assert removed.changed
    assert config.read_text(encoding="utf-8") == 'model = "gpt-5"\n'


def test_project_mcp_config_refuses_unmanaged_collision(project: tuple[Path, object]) -> None:
    root, _ = project
    config = root / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('[mcp_servers.qbank]\ncommand = "custom"\n', encoding="utf-8")
    with pytest.raises(ConflictError, match="unmanaged"):
        install_project_mcp(ProjectContext.from_root(root), dry_run=True)


def test_integration_status_degrades_when_codex_cannot_execute(
    project: tuple[Path, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    install_project_mcp(context, dry_run=False)
    calls = 0

    def denied(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise PermissionError("denied")

    monkeypatch.setattr(mcp_config.shutil, "which", lambda _name: "codex")
    monkeypatch.setattr(mcp_config.subprocess, "run", denied)
    status = mcp_integration_status(context)

    assert status.ok
    assert status.codex_cli_available is False
    assert status.degraded
    assert calls == 1


def test_codex_mcp_cli_commands_and_server_entry(
    cli_project: Path,
    runner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_config, "_codex_cli_ready", lambda: (True, "ready"))

    status = runner.invoke(app, ["codex", "integration-status", "--format", "json"])
    assert status.exit_code == 0
    assert json.loads(status.stdout)["registered"] is False

    dry_run = runner.invoke(
        app,
        ["codex", "install-mcp", "--project", "--dry-run", "--format", "json"],
    )
    assert dry_run.exit_code == 0
    assert not (cli_project / ".codex" / "config.toml").exists()

    installed = runner.invoke(
        app,
        ["codex", "install-mcp", "--project", "--yes", "--format", "json"],
    )
    assert installed.exit_code == 0
    checked = runner.invoke(app, ["codex", "mcp-check", "--format", "json"])
    assert checked.exit_code == 0
    assert json.loads(checked.stdout)["ok"] is True

    uninstall_plan = runner.invoke(
        app,
        ["codex", "uninstall-mcp", "--project", "--dry-run", "--format", "json"],
    )
    assert uninstall_plan.exit_code == 0
    removed = runner.invoke(
        app,
        ["codex", "uninstall-mcp", "--project", "--yes", "--format", "json"],
    )
    assert removed.exit_code == 0

    called: list[Path] = []
    monkeypatch.setattr("qbank.mcp.server.run_stdio_server", called.append)
    server = runner.invoke(app, ["mcp", "--repository", str(cli_project)])
    assert server.exit_code == 0
    assert called == [cli_project.resolve()]
