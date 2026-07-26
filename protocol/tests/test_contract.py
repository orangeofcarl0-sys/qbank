from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from qbank.studio_sidecar.application import StudioApplication


def test_protocol_schema_is_valid_and_matches_dispatch() -> None:
    path = Path(__file__).parents[1] / "studio-protocol-v1.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(contract)
    documented = {item["name"] for item in contract["methods"]}
    implemented = set(StudioApplication()._methods)
    assert documented == implemented
    assert contract["protocolVersion"] == "1.0"


def test_every_write_method_is_explicitly_classified() -> None:
    path = Path(__file__).parents[1] / "studio-protocol-v1.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    writes = {item["name"] for item in contract["methods"] if item["access"] == "write"}
    assert writes == {
        "repository.rebuildIndex",
        "question.save",
        "question.update",
        "question.create",
        "question.copy",
        "question.import",
        "question.delete",
        "question.bulkUpdate",
        "taxonomy.update",
        "taxonomy.rename",
        "taxonomy.merge",
        "taxonomy.delete",
        "taxonomy.bulkEdit",
        "view.save",
        "view.rename",
        "view.delete",
        "asset.open",
        "asset.create",
        "asset.replace",
        "asset.render",
        "asset.reconcile",
        "paper.create",
        "paper.save",
        "paper.addQuestions",
        "paper.build",
    }
