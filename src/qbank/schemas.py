"""Single source of truth for qbank JSON Schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from qbank.models import AssetManifest, AssetPackage, Paper, Question, QuestionPatch

SchemaKind = Literal["question", "paper", "patch", "asset", "asset-package"]

SCHEMA_FILENAMES: dict[SchemaKind, str] = {
    "question": "question.schema.json",
    "paper": "paper.schema.json",
    "patch": "patch.schema.json",
    "asset": "asset.schema.json",
    "asset-package": "asset-package.schema.json",
}


def schema_for(kind: SchemaKind) -> dict[str, Any]:
    """Generate the requested public JSON Schema from its Pydantic model."""
    models: dict[SchemaKind, type[BaseModel]] = {
        "question": Question,
        "paper": Paper,
        "patch": QuestionPatch,
        "asset": AssetManifest,
        "asset-package": AssetPackage,
    }
    return models[kind].model_json_schema()


def all_schemas() -> dict[str, dict[str, Any]]:
    """Return every public schema keyed by its repository filename."""
    return {filename: schema_for(kind) for kind, filename in SCHEMA_FILENAMES.items()}
