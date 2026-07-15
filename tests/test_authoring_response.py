from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from igess.authoring.response import AuthoringError, CommandResponse


def test_authoring_error_is_a_domain_exception_with_defensive_defaults() -> None:
    first = AuthoringError("invalid_change", "Change is invalid")
    second = AuthoringError("model_invalid", "Model is invalid")

    first.details["field"] = "base_cost"
    first.result["state"] = "failed"

    assert isinstance(first, Exception)
    assert str(first) == "Change is invalid"
    assert first.code == "invalid_change"
    assert second.details == {}
    assert second.result == {}


def test_authoring_error_copies_details_and_can_carry_failed_status_result() -> None:
    details = {"entity": "generator", "id": "mine"}
    failed_status = {
        "structural_valid": False,
        "smoke_eligible": False,
        "state": "failed",
        "missing_requirements": [
            {"code": "invalid_reference", "message": "generator mine references ore"}
        ],
    }

    error = AuthoringError("model_invalid", "Model validation failed", details, failed_status)
    details["id"] = "changed"
    failed_status["state"] = "changed"

    assert error.details == {"entity": "generator", "id": "mine"}
    assert error.result["state"] == "failed"


def test_command_response_is_frozen_and_has_independent_mutable_defaults() -> None:
    first = CommandResponse("model.status", True, "status", "Model is incomplete")
    second = CommandResponse("model.status", True, "status", "Model is ready")

    first.details["source"] = "workbook"
    first.result["state"] = "incomplete"

    assert second.details == {}
    assert second.result == {}
    with pytest.raises(FrozenInstanceError):
        first.message = "changed"  # type: ignore[misc]


def test_payload_has_the_stable_outer_schema_and_returns_defensive_copies() -> None:
    details = {"entity": "resource"}
    result = {"state": "incomplete", "warnings": []}
    response = CommandResponse(
        command="model.status",
        ok=True,
        code="status",
        message="模型有效但尚不完整",
        details=details,
        result=result,
    )
    details["entity"] = "changed"
    result["state"] = "changed"

    payload = response.to_payload()

    assert list(payload) == [
        "schema_version",
        "command",
        "ok",
        "code",
        "message",
        "details",
        "result",
    ]
    assert payload == {
        "schema_version": 1,
        "command": "model.status",
        "ok": True,
        "code": "status",
        "message": "模型有效但尚不完整",
        "details": {"entity": "resource"},
        "result": {"state": "incomplete", "warnings": []},
    }

    payload["details"]["entity"] = "mutated"
    assert response.to_payload()["details"] == {"entity": "resource"}


def test_json_is_deterministic_unicode_and_exactly_one_object() -> None:
    response = CommandResponse(
        "model.apply",
        False,
        "invalid_change",
        "资源 gold 无效",
        {"field": "dimension"},
        {},
    )

    first = response.to_json()
    second = response.to_json()

    assert first == second
    assert first.startswith('{"schema_version":1,"command":"model.apply"')
    assert "资源 gold 无效" in first
    assert "\\u8d44" not in first
    assert "\n" not in first
    assert json.loads(first) == response.to_payload()


def test_human_lines_render_direct_status_in_protocol_order_without_repeating_ids() -> None:
    response = CommandResponse(
        "model.status",
        True,
        "status",
        "Model is valid but incomplete",
        result={
            "missing_requirements": [
                {
                    "code": "resource_without_source",
                    "message": "resource gold has no production source",
                    "entity": "resource",
                    "id": "gold",
                },
                {
                    "code": "missing_cost",
                    "message": "base cost is required",
                    "entity": "generator",
                    "id": "mine",
                },
            ],
            "warnings": [
                {"code": "stale_exports", "message": "Committed exports are stale"},
                {"code": "plain", "message": "resource gold warning", "entity": "resource", "id": "gold"},
            ],
        },
    )

    assert response.human_lines() == [
        "Model is valid but incomplete",
        "Missing requirements:",
        "- resource gold has no production source",
        "- [generator:mine] base cost is required",
        "Warnings:",
        "- Committed exports are stale",
        "- resource gold warning",
    ]


def test_human_lines_use_nested_status_then_changed_files_and_known_artifacts() -> None:
    response = CommandResponse(
        "model.apply",
        True,
        "applied",
        "Applied resource:gold",
        result={
            "status": {
                "missing_requirements": [],
                "warnings": [
                    {
                        "code": "balance",
                        "message": "income is unusually high",
                        "entity": "activity",
                        "id": "gather",
                    }
                ],
            },
            "changed_files": ["economy.yaml", "data-tables/Datas/resources.xlsx"],
            "config": "economy.yaml",
            "datas": "data-tables/Datas",
            "tables": "data-tables/Datas/__tables__.xlsx",
            "readme": "README.md",
            "run_script": "run.ps1",
            "output_dir": "runs/run-1/output",
            "report_index": "runs/run-1/report/index.html",
            "ignored": {"secret": "must not be stringified"},
        },
    )

    lines = response.human_lines()

    assert lines == [
        "Applied resource:gold",
        "Warnings:",
        "- [activity:gather] income is unusually high",
        "Changed files:",
        "- economy.yaml",
        "- data-tables/Datas/resources.xlsx",
        "Artifacts:",
        "- config: economy.yaml",
        "- datas: data-tables/Datas",
        "- tables: data-tables/Datas/__tables__.xlsx",
        "- readme: README.md",
        "- run_script: run.ps1",
        "- output_dir: runs/run-1/output",
        "- report_index: runs/run-1/report/index.html",
    ]
    assert all("secret" not in line and "must not" not in line for line in lines)


def test_human_lines_only_contains_message_when_there_are_no_typed_details() -> None:
    response = CommandResponse(
        "model.simulate",
        True,
        "simulated",
        "Simulation completed",
        result={"run": {"nested": "object"}, "changed_files": []},
    )

    assert response.human_lines() == ["Simulation completed"]


def test_human_lines_do_not_mistake_an_id_substring_for_a_readable_reference() -> None:
    response = CommandResponse(
        "model.status",
        True,
        "status",
        "Model is incomplete",
        result={
            "warnings": [
                {
                    "code": "balance",
                    "message": "resource balance warning",
                    "entity": "resource",
                    "id": "a",
                }
            ]
        },
    )

    assert response.human_lines()[-1] == "- [resource:a] resource balance warning"
