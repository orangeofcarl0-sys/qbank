"""Shared Pydantic base classes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "1.0"
SchemaVersion = Literal["1.0"]


class StrictModel(BaseModel):
    """Forbid undeclared input and result fields."""

    model_config = ConfigDict(extra="forbid")


class ResultModel(StrictModel):
    """Typed result with temporary mapping-style compatibility access."""

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """Return one result field like a read-only mapping."""
        return getattr(self, key, default)
