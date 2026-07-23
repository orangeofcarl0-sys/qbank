"""Typed, dependency-light definition of the qbank Codex integration."""

from __future__ import annotations

from dataclasses import dataclass

INTEGRATION_REVISION = 3

CONTEXT_REQUIRED_FIELDS = (
    "objective",
    "target_project_root",
    "source_locations",
    "workflow",
    "authorization",
    "acceptance_criteria",
    "unresolved_questions",
)

CONTEXT_AUTHORIZATION_MODES = (
    "read_only",
    "dry_run_only",
    "write_authorized",
)

COMPLETION_HANDOFF_FIELDS = (
    "integration_revision",
    "target_project_root",
    "source_locations",
    "workflow",
    "authorization",
    "commands_executed",
    "writes",
    "validation",
    "outputs",
    "warnings",
    "next_step",
)

FOREIGN_PROJECT_POLICY = (
    "Treat every non-qbank source project as read-only unless the user explicitly "
    "authorizes writes there."
)


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    """One deterministic command or user-authored artifact in a Codex workflow."""

    command: str
    description: str
    command_path: tuple[str, ...] = ()
    writes: bool = False
    dry_run_required: bool = False
    explicit_authorization: bool = False
    interactive: bool = False
    expected: str = ""


@dataclass(frozen=True, slots=True)
class Workflow:
    """One bounded qbank workflow exposed to Codex clients."""

    name: str
    title: str
    purpose: str
    preconditions: tuple[str, ...]
    steps: tuple[WorkflowStep, ...]


@dataclass(frozen=True, slots=True)
class StepBehavior:
    """Mutation and interaction flags shared by workflow steps."""

    writes: bool = False
    dry_run_required: bool = False
    explicit_authorization: bool = False
    interactive: bool = False


@dataclass(frozen=True, slots=True)
class IntegrationCapability:
    """One authoritative mapping across workflows, CLI, MCP, and resources."""

    name: str
    workflow: str
    cli_command: tuple[str, ...] | None
    mcp_tool: str | None
    resource: str | None
    access: str
    schema_version: str = "1.0"


READ_ONLY = StepBehavior()
WRITES = StepBehavior(writes=True)
DRY_RUN = StepBehavior(dry_run_required=True)
EXPLICIT_WRITE = StepBehavior(writes=True, explicit_authorization=True)
EXPLICIT_DRY_RUN = StepBehavior(dry_run_required=True, explicit_authorization=True)
INTERACTIVE = StepBehavior(explicit_authorization=True, interactive=True)


CODEX_RULES = (
    "Establish the target qbank root, source locations, and authorization before acting.",
    FOREIGN_PROJECT_POLICY,
    "Markdown under questions/ is authoritative question data.",
    "JSON and JSONL are AI exchange formats; SQLite is only a rebuildable index.",
    "Read the question Schema before creating exchange data.",
    "Do not directly edit question Markdown or the SQLite index by default.",
    "Use add or ingest to create questions and patch to revise them.",
    "Dry-run every write, inspect diagnostics, then perform the write.",
    "Run validate with JSON output after every real write.",
    "Never silently overwrite an existing question ID.",
    "Run destructive operations only after an explicit user request.",
    "Do not launch blocking interactive commands unless the user asks for them.",
    "Keep uncertain questions draft and never invent answers or provenance.",
)


def _step(
    command: str,
    description: str,
    *command_path: str,
    behavior: StepBehavior = READ_ONLY,
    expected: str = "",
) -> WorkflowStep:
    return WorkflowStep(
        command=command,
        description=description,
        command_path=command_path,
        writes=behavior.writes,
        dry_run_required=behavior.dry_run_required,
        explicit_authorization=behavior.explicit_authorization,
        interactive=behavior.interactive,
        expected=expected,
    )


WORKFLOWS = (
    Workflow(
        name="import",
        title="Import questions",
        purpose="Turn supported source evidence into validated draft or reviewed questions.",
        preconditions=(
            "Work inside the qbank project.",
            "Preserve source locations and uncertainty.",
        ),
        steps=(
            _step(
                "qbank doctor --format json",
                "Check the project before preparing exchange data.",
                "doctor",
                expected="No unresolved FAIL checks.",
            ),
            _step(
                "qbank schema --kind question --format json",
                "Read the authoritative exchange schema.",
                "schema",
                expected="A machine-readable JSON Schema.",
            ),
            _step(
                "qbank ingest build/ai/<job>.jsonl --dry-run --format json",
                "Validate every proposed record without writing.",
                "ingest",
                behavior=DRY_RUN,
                expected="All intended records are valid and every warning is reviewed.",
            ),
            _step(
                "qbank ingest build/ai/<job>.jsonl --format json",
                "Commit the already inspected batch.",
                "ingest",
                behavior=WRITES,
                expected="The reported written count matches the inspected plan.",
            ),
            _step(
                "qbank validate --format json",
                "Validate authoritative Markdown after the write.",
                "validate",
                expected="No validation errors.",
            ),
            _step(
                "qbank preview --format json",
                "Build a non-blocking preview artifact.",
                "preview",
                behavior=WRITES,
                expected="The preview result reports its output directory.",
            ),
        ),
    ),
    Workflow(
        name="revise",
        title="Inspect and revise questions",
        purpose="Narrow candidates, report evidence, and apply confirmed structured changes.",
        preconditions=("Define a bounded query scope.", "Do not replace malformed Markdown."),
        steps=(
            _step(
                "qbank query <filters> --fields id,title,subject,chapter,topics,type,difficulty,status --format json",
                "Retrieve bounded summaries before full bodies.",
                "query",
            ),
            _step(
                "qbank get <candidate-ids> --format json",
                "Fetch only candidate question bodies.",
                "get",
            ),
            _step(
                "qbank patch <id> --file build/ai/<id>.patch.json --dry-run --format json",
                "Inspect field-level changes without writing.",
                "patch",
                behavior=DRY_RUN,
            ),
            _step(
                "qbank patch <id> --file build/ai/<id>.patch.json --format json",
                "Commit the inspected patch.",
                "patch",
                behavior=WRITES,
            ),
            _step(
                "qbank validate --format json",
                "Validate the repository after the patch.",
                "validate",
            ),
        ),
    ),
    Workflow(
        name="select",
        title="Search and select questions",
        purpose="Choose questions without loading the entire repository into context.",
        preconditions=("Start with metadata filtering.",),
        steps=(
            _step(
                "qbank query <filters> --fields id,title,subject,chapter,topics,type,difficulty,status --format json",
                "Retrieve candidate summaries.",
                "query",
            ),
            _step(
                "qbank search <text> --format json",
                "Use full-text search only when metadata is insufficient.",
                "search",
                expected="If the index is unavailable, rebuild it only when authorized.",
            ),
            _step(
                "qbank get <candidate-ids> --format json",
                "Inspect the shortlisted full questions.",
                "get",
            ),
        ),
    ),
    Workflow(
        name="paper",
        title="Assemble and export a paper",
        purpose="Select, validate, and render an explicit scored paper definition.",
        preconditions=("Confirm scope, balance, score, and output variants.",),
        steps=(
            _step(
                "qbank schema --kind paper --format json",
                "Read the paper schema before writing YAML.",
                "schema",
            ),
            _step("qbank query <filters> --format json", "Find candidates.", "query"),
            _step(
                "qbank get <candidate-ids> --format json",
                "Inspect shortlisted bodies.",
                "get",
            ),
            _step(
                "write papers/generated/<paper>.yaml",
                "Create the explicit paper definition from confirmed selections.",
                behavior=WRITES,
            ),
            _step(
                "qbank paper validate papers/generated/<paper>.yaml --format json",
                "Validate IDs, scores, status, and assets.",
                "paper",
                "validate",
            ),
            _step(
                "qbank paper build papers/generated/<paper>.yaml --format md --output exports/<paper>-student.md",
                "Build the student artifact.",
                "paper",
                "build",
                behavior=WRITES,
            ),
            _step(
                "qbank paper build papers/generated/<paper>.yaml --format md --with-solutions --output exports/<paper>-solutions.md",
                "Build the solution artifact.",
                "paper",
                "build",
                behavior=WRITES,
            ),
        ),
    ),
    Workflow(
        name="assets",
        title="Manage logical assets",
        purpose="Create or revise versioned assets through validated asset packages.",
        preconditions=("Keep local files inside the configured assets directory.",),
        steps=(
            _step(
                "qbank schema --kind asset-package --format json",
                "Read the logical-asset package schema.",
                "schema",
            ),
            _step(
                "qbank asset show <question-id> <asset-id> --format json",
                "Inspect the current manifest and representations.",
                "asset",
                "show",
            ),
            _step(
                "qbank asset ingest <question-id> build/ai/<asset>.json --dry-run --format json",
                "Validate the asset package without writing.",
                "asset",
                "ingest",
                behavior=DRY_RUN,
            ),
            _step(
                "qbank asset ingest <question-id> build/ai/<asset>.json --format json",
                "Commit the inspected asset package.",
                "asset",
                "ingest",
                behavior=WRITES,
            ),
            _step(
                "qbank asset validate --format json",
                "Validate manifests and representations.",
                "asset",
                "validate",
            ),
        ),
    ),
    Workflow(
        name="taxonomy",
        title="Manage tags and saved views",
        purpose="Inspect and atomically revise taxonomy or reusable query views.",
        preconditions=("Review affected question counts before taxonomy writes.",),
        steps=(
            _step("qbank tag list --format json", "Inspect registered tags.", "tag", "list"),
            _step("qbank tag stats --format json", "Inspect tag usage.", "tag", "stats"),
            _step("qbank view list --format json", "Inspect saved views.", "view", "list"),
            _step(
                "qbank tag rename <old> <new> --dry-run --format json",
                "Preview the complete taxonomy and question diff.",
                "tag",
                "rename",
                behavior=DRY_RUN,
            ),
            _step(
                "qbank tag rename <old> <new> --format json",
                "Commit the inspected taxonomy change.",
                "tag",
                "rename",
                behavior=WRITES,
            ),
            _step("qbank validate --format json", "Validate affected questions.", "validate"),
        ),
    ),
    Workflow(
        name="maintenance",
        title="Run explicit maintenance",
        purpose="Recover projections or perform destructive actions only when requested.",
        preconditions=("Obtain explicit authorization for destructive or interactive steps.",),
        steps=(
            _step(
                "qbank index rebuild --format json",
                "Rebuild a dirty or unavailable disposable search projection.",
                "index",
                "rebuild",
                behavior=EXPLICIT_WRITE,
            ),
            _step(
                "qbank delete <id> --dry-run --format json",
                "Preview deletion of an authoritative question.",
                "delete",
                behavior=EXPLICIT_DRY_RUN,
            ),
            _step(
                "qbank delete <id> --yes --format json",
                "Delete only after confirmation of the exact ID.",
                "delete",
                behavior=EXPLICIT_WRITE,
            ),
            _step(
                "qbank preview --serve",
                "Start the blocking server only for an interactive user session.",
                "preview",
                behavior=INTERACTIVE,
            ),
            _step(
                "qbank desktop",
                "Launch Studio only when the user asks to open it.",
                "desktop",
                behavior=INTERACTIVE,
            ),
        ),
    ),
)

WORKFLOW_BY_NAME = {workflow.name: workflow for workflow in WORKFLOWS}

INTEGRATION_CAPABILITIES = (
    IntegrationCapability(
        "repository_status",
        "maintenance",
        ("status",),
        "repository_status",
        "qbank://repository/info",
        "read",
    ),
    IntegrationCapability(
        "schema",
        "import",
        ("schema",),
        "schema_get",
        "qbank://schema/question",
        "read",
    ),
    IntegrationCapability(
        "question_search",
        "select",
        ("search",),
        "question_search",
        None,
        "read",
    ),
    IntegrationCapability(
        "question_get",
        "select",
        ("get",),
        "question_get",
        "qbank://question/{id}",
        "read",
    ),
    IntegrationCapability(
        "question_validate",
        "maintenance",
        ("validate",),
        "question_validate",
        None,
        "read",
    ),
    IntegrationCapability(
        "taxonomy",
        "taxonomy",
        ("tag", "list"),
        "taxonomy_get",
        "qbank://taxonomy",
        "read",
    ),
    IntegrationCapability(
        "asset",
        "assets",
        ("asset", "show"),
        "asset_get",
        None,
        "read",
    ),
    IntegrationCapability(
        "paper_get",
        "paper",
        ("paper", "validate"),
        "paper_get",
        "qbank://paper/{id}",
        "read",
    ),
    IntegrationCapability(
        "operation_get",
        "maintenance",
        None,
        "operation_get",
        None,
        "read",
    ),
    IntegrationCapability(
        "paper_history_get",
        "paper",
        None,
        "paper_history_get",
        None,
        "read",
    ),
    IntegrationCapability(
        "ingest_prepare",
        "import",
        ("ingest",),
        "ingest_prepare",
        None,
        "prepare",
    ),
    IntegrationCapability(
        "patch_prepare",
        "revise",
        ("patch",),
        "patch_prepare",
        None,
        "prepare",
    ),
    IntegrationCapability(
        "tag_change_prepare",
        "taxonomy",
        ("tag",),
        "tag_change_prepare",
        None,
        "prepare",
    ),
    IntegrationCapability(
        "paper_prepare",
        "paper",
        ("paper",),
        "paper_prepare",
        None,
        "prepare",
    ),
    IntegrationCapability(
        "asset_ingest_prepare",
        "assets",
        ("asset", "ingest"),
        "asset_ingest_prepare",
        None,
        "prepare",
    ),
    IntegrationCapability(
        "asset_status_prepare",
        "assets",
        ("asset", "finalize"),
        "asset_status_prepare",
        None,
        "prepare",
    ),
    IntegrationCapability(
        "asset_preferred_prepare",
        "assets",
        ("asset", "set-render"),
        "asset_preferred_prepare",
        None,
        "prepare",
    ),
    IntegrationCapability(
        "operation_commit",
        "maintenance",
        None,
        "operation_commit",
        None,
        "write",
    ),
    IntegrationCapability(
        "operation_cancel",
        "maintenance",
        None,
        "operation_cancel",
        None,
        "write",
    ),
    IntegrationCapability(
        "asset_schema",
        "assets",
        ("schema",),
        None,
        "qbank://schema/asset",
        "read",
    ),
    IntegrationCapability(
        "paper_schema",
        "paper",
        ("schema",),
        None,
        "qbank://schema/paper",
        "read",
    ),
    IntegrationCapability(
        "question_history",
        "revise",
        None,
        None,
        "qbank://history/{id}",
        "read",
    ),
)

MCP_CAPABILITY_BY_TOOL = {
    capability.mcp_tool: capability
    for capability in INTEGRATION_CAPABILITIES
    if capability.mcp_tool is not None
}
MCP_TOOL_NAMES = tuple(MCP_CAPABILITY_BY_TOOL)
MCP_RESOURCE_URIS = tuple(
    dict.fromkeys(
        capability.resource
        for capability in INTEGRATION_CAPABILITIES
        if capability.resource is not None
    )
)

# Preserve the original four machine-facing keys, commands, and list shape.
LEGACY_COMMAND_SEQUENCES = {
    "import": [
        "qbank doctor --format json",
        "qbank schema --format json",
        "qbank ingest build/ai/<job>.jsonl --dry-run --format json",
        "qbank ingest build/ai/<job>.jsonl --format json",
        "qbank validate --format json",
        "qbank preview",
    ],
    "revise": [
        "qbank query <filters> --format json",
        "qbank get <candidate-ids> --format json",
        "qbank patch ID --file PATCH --dry-run --format json",
        "qbank patch ID --file PATCH --format json",
        "qbank validate --format json",
    ],
    "select": [
        "qbank query <filters> --fields id,title,subject,chapter,topics,type,difficulty,status --format json",
        "qbank search <text> --format json",
        "qbank get <candidate-ids> --format json",
    ],
    "paper": [
        "qbank query <filters> --format json",
        "qbank get <candidate-ids> --format json",
        "qbank paper validate papers/generated/<paper>.yaml --format json",
        "qbank paper build papers/generated/<paper>.yaml --format md --output exports/<paper>-student.md",
        "qbank paper build papers/generated/<paper>.yaml --format md --with-solutions --output exports/<paper>-solutions.md",
    ],
}

REQUIRED_COMMANDS = tuple(
    sorted(
        {
            step.command_path
            for workflow in WORKFLOWS
            for step in workflow.steps
            if step.command_path
        }
    )
)

SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/context-handoff.md",
    "references/workflows.md",
    "references/command-reference.md",
    "references/examples.md",
)

DIGITIZE_SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "assets/classification-map.csv",
    "assets/digitization-profile.yaml",
    "references/calibration.md",
    "references/field-policy.md",
    "references/intake.md",
)
