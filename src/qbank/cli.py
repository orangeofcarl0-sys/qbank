"""Typer composition root for the qbank command-line interface."""

from __future__ import annotations

import typer

from qbank.cli_usage import JsonUsageGroup
from qbank.commands.artifacts import (
    export_command,
    paper_build_command,
    paper_validate_command,
    preview_command,
)
from qbank.commands.assets import (
    asset_add_command,
    asset_edit_command,
    asset_finalize_command,
    asset_ingest_command,
    asset_list_command,
    asset_normalize_command,
    asset_open_command,
    asset_render_command,
    asset_replace_command,
    asset_set_editor_command,
    asset_set_render_command,
    asset_show_command,
    asset_validate_command,
)
from qbank.commands.codex import (
    codex_check_command,
    codex_install_skill_command,
    codex_instructions_command,
)
from qbank.commands.desktop import desktop_command
from qbank.commands.project import (
    doctor_command,
    init_command,
    schema_command,
    status_command,
)
from qbank.commands.questions import (
    add_command,
    delete_command,
    get_command,
    index_rebuild_command,
    ingest_command,
    list_command,
    patch_command,
    query_command,
    search_command,
    validate_command,
)
from qbank.commands.taxonomy import (
    tag_cooccur_command,
    tag_delete_command,
    tag_list_command,
    tag_merge_command,
    tag_normalize_command,
    tag_rename_command,
    tag_show_command,
    tag_stats_command,
    view_apply_command,
    view_delete_command,
    view_list_command,
    view_rename_command,
    view_save_command,
)

app = typer.Typer(
    name="qbank",
    cls=JsonUsageGroup,
    help="Transparent local-first Markdown question bank.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
index_app = typer.Typer(help="Manage the rebuildable SQLite search index.")
paper_app = typer.Typer(help="Validate and build paper.yaml files.")
codex_app = typer.Typer(help="Check and expose repository-scoped Codex integration.")
asset_app = typer.Typer(help="Manage logical multi-representation question assets.")
tag_app = typer.Typer(help="Manage the project tag taxonomy and topic relations.")
view_app = typer.Typer(help="Manage persistent question query views.")
app.add_typer(index_app, name="index")
app.add_typer(paper_app, name="paper")
app.add_typer(codex_app, name="codex")
app.add_typer(asset_app, name="asset")
app.add_typer(tag_app, name="tag")
app.add_typer(view_app, name="view")

app.command("init")(init_command)
app.command("status")(status_command)
app.command("doctor")(doctor_command)
app.command("schema")(schema_command)
app.command("add")(add_command)
app.command("ingest")(ingest_command)
app.command("validate")(validate_command)
app.command("list")(list_command)
app.command("get")(get_command)
app.command("query")(query_command)
app.command("search")(search_command)
app.command("patch")(patch_command)
app.command("delete")(delete_command)
app.command("desktop")(desktop_command)
index_app.command("rebuild")(index_rebuild_command)
app.command("preview")(preview_command)
app.command("export")(export_command)
paper_app.command("validate")(paper_validate_command)
paper_app.command("build")(paper_build_command)
codex_app.command("check")(codex_check_command)
codex_app.command("instructions")(codex_instructions_command)
codex_app.command("install-skill")(codex_install_skill_command)
asset_app.command("list")(asset_list_command)
asset_app.command("show")(asset_show_command)
asset_app.command("ingest")(asset_ingest_command)
asset_app.command("add")(asset_add_command)
asset_app.command("open")(asset_open_command)
asset_app.command("edit")(asset_edit_command)
asset_app.command("render")(asset_render_command)
asset_app.command("replace")(asset_replace_command)
asset_app.command("set-render")(asset_set_render_command)
asset_app.command("set-editor")(asset_set_editor_command)
asset_app.command("finalize")(asset_finalize_command)
asset_app.command("normalize")(asset_normalize_command)
asset_app.command("validate")(asset_validate_command)
tag_app.command("list")(tag_list_command)
tag_app.command("show")(tag_show_command)
tag_app.command("rename")(tag_rename_command)
tag_app.command("merge")(tag_merge_command)
tag_app.command("delete")(tag_delete_command)
tag_app.command("normalize")(tag_normalize_command)
tag_app.command("stats")(tag_stats_command)
tag_app.command("cooccur")(tag_cooccur_command)
view_app.command("list")(view_list_command)
view_app.command("save")(view_save_command)
view_app.command("apply")(view_apply_command)
view_app.command("rename")(view_rename_command)
view_app.command("delete")(view_delete_command)

__all__ = ["app"]
