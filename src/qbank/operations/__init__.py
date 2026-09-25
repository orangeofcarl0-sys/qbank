"""Validated, transactional question mutations and source queries.

The public surface is re-exported from focused submodules; callers continue to
import from ``qbank.operations`` exactly as before the package reorganization.
Package-internal collaboration helpers live in ``qbank.operations.common`` and
``qbank.operations.patch`` and are not re-exported here.
"""

from __future__ import annotations

from qbank.operations.add import add_question as add_question
from qbank.operations.add import add_question_in_context as add_question_in_context
from qbank.operations.common import MutationServices as MutationServices
from qbank.operations.common import question_dict as question_dict
from qbank.operations.delete import delete_question as delete_question
from qbank.operations.delete import delete_question_in_context as delete_question_in_context
from qbank.operations.ingest import IngestEntry as IngestEntry
from qbank.operations.ingest import IngestPlanningContext as IngestPlanningContext
from qbank.operations.ingest import QuestionMutationPlan as QuestionMutationPlan
from qbank.operations.ingest import ingest_questions as ingest_questions
from qbank.operations.ingest import ingest_questions_in_context as ingest_questions_in_context
from qbank.operations.patch import apply_patch as apply_patch
from qbank.operations.patch import apply_patch_in_context as apply_patch_in_context
from qbank.operations.patch import diff_questions as diff_questions
from qbank.operations.query import query_questions as query_questions
from qbank.operations.query import query_questions_in_context as query_questions_in_context
from qbank.operations.studio_save import StudioSavePlan as StudioSavePlan
from qbank.operations.studio_save import StudioSaveRequest as StudioSaveRequest
from qbank.operations.studio_save import (
    save_studio_question_in_context as save_studio_question_in_context,
)

__all__ = [
    "IngestEntry",
    "IngestPlanningContext",
    "MutationServices",
    "QuestionMutationPlan",
    "StudioSavePlan",
    "StudioSaveRequest",
    "add_question",
    "add_question_in_context",
    "apply_patch",
    "apply_patch_in_context",
    "delete_question",
    "delete_question_in_context",
    "diff_questions",
    "ingest_questions",
    "ingest_questions_in_context",
    "query_questions",
    "query_questions_in_context",
    "question_dict",
    "save_studio_question_in_context",
]
