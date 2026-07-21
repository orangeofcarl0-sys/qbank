"""Canonical packaged resources and generated files used by qbank init."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import PurePosixPath

from qbank.schemas import all_schemas


@dataclass(frozen=True, slots=True)
class ManagedResource:
    """One initialized path backed by a packaged source or generated text."""

    destination: PurePosixPath
    packaged_source: PurePosixPath | None = None
    generated_text: str | None = None

    def text(self) -> str:
        """Materialize this resource as normalized UTF-8 text."""
        if self.generated_text is not None:
            return self.generated_text
        if self.packaged_source is None:
            raise RuntimeError(f"resource has no source: {self.destination}")
        resource = files("qbank.resources").joinpath(*self.packaged_source.parts)
        return resource.read_text(encoding="utf-8")


STATIC_INIT_RESOURCES = (
    ManagedResource(
        PurePosixPath("AGENTS.md"),
        PurePosixPath("init/AGENTS.md"),
    ),
    ManagedResource(
        PurePosixPath(".agents/skills/qbank/SKILL.md"),
        PurePosixPath("init/codex/skill/SKILL.md"),
    ),
    ManagedResource(
        PurePosixPath(".agents/skills/qbank/agents/openai.yaml"),
        PurePosixPath("init/codex/skill/agents/openai.yaml"),
    ),
    ManagedResource(
        PurePosixPath(".agents/skills/qbank/references/workflows.md"),
        PurePosixPath("init/codex/skill/references/workflows.md"),
    ),
    ManagedResource(
        PurePosixPath(".agents/skills/qbank/references/command-reference.md"),
        PurePosixPath("init/codex/skill/references/command-reference.md"),
    ),
    ManagedResource(
        PurePosixPath(".agents/skills/qbank/references/examples.md"),
        PurePosixPath("init/codex/skill/references/examples.md"),
    ),
    ManagedResource(
        PurePosixPath("qbank.yaml"),
        PurePosixPath("init/qbank.yaml"),
    ),
    ManagedResource(
        PurePosixPath("taxonomy.yaml"),
        PurePosixPath("init/taxonomy.yaml"),
    ),
    ManagedResource(
        PurePosixPath("views.yaml"),
        PurePosixPath("init/views.yaml"),
    ),
    ManagedResource(
        PurePosixPath("templates/paper.md.j2"),
        PurePosixPath("init/templates/paper.md.j2"),
    ),
    ManagedResource(
        PurePosixPath("templates/paper.html.j2"),
        PurePosixPath("init/templates/paper.html.j2"),
    ),
    ManagedResource(
        PurePosixPath("papers/demo-paper.yaml"),
        PurePosixPath("init/papers/demo-paper.yaml"),
    ),
    ManagedResource(
        PurePosixPath("assets/images/interference.svg"),
        PurePosixPath("init/assets/images/interference.svg"),
    ),
)


def initialization_resources() -> tuple[ManagedResource, ...]:
    """Return every managed text file, including generated JSON Schemas."""
    schemas = tuple(
        ManagedResource(
            PurePosixPath("schemas") / name,
            generated_text=json.dumps(
                schema,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        for name, schema in all_schemas().items()
    )
    return (*STATIC_INIT_RESOURCES, *schemas)


def packaged_init_text(relative: str) -> str:
    """Read one packaged initialization source for mirrors and compatibility."""
    resource = files("qbank.resources").joinpath("init", *PurePosixPath(relative).parts)
    return resource.read_text(encoding="utf-8")
