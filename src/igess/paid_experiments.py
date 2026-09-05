"""Run paired purchase plans through the existing formal-run lifecycle."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .development_diagnostics import DevelopmentDiagnostics
from .formal_run import FormalRunExecutor, PreparedRun
from .payments import PaymentExperiment
from .paid_reporting import summarize_paid_run, write_paid_report


def execute_paid_experiment(prepared, adapter, experiment: PaymentExperiment, registry, output_dir, project_root):
    model = prepared.model
    if experiment.profile not in model.player_profiles:
        raise ValueError(f"Unknown experiment profile: {experiment.profile}")
    for scenario_id in experiment.scenarios:
        if scenario_id not in model.scenarios:
            raise ValueError(f"Unknown experiment scenario: {scenario_id}")
    for plan in experiment.plans:
        plan.validate_model(model, experiment.profile)
    output_dir = Path(output_dir)
    # Never mix an old successful report with a partially completed experiment.
    output_dir.mkdir(parents=True, exist_ok=False)
    payload = {
        "schema_version": 1, "status": "running",
        "data_status": experiment.plans[0].data_status,
        "currency": experiment.plans[0].currency,
        "source": experiment.plans[0].source,
        "profile_id": experiment.profile,
        "random_seed": model.config.random_seed,
        "base_model_digest": prepared.model_digest,
        "plans": [plan.payload() for plan in experiment.plans],
        "runs": [],
    }
    diagnostics = DevelopmentDiagnostics(project_root)
    executor = FormalRunExecutor(registry, diagnostics=diagnostics)
    write_paid_report(payload, output_dir)
    try:
        for scenario_id in experiment.scenarios:
            for plan in experiment.plans:
                lane_model = replace(
                    model, payment_plan=plan,
                    scenarios={**model.scenarios, scenario_id: replace(model.scenarios[scenario_id], profiles=[experiment.profile])},
                )
                digest = plan.digest(prepared.model_digest + ":profile=" + experiment.profile)
                lane_prepared = replace(
                    prepared, model=lane_model, model_digest=digest,
                    manifest_metadata={
                        **prepared.manifest_metadata,
                        "paid_simulation": {
                            "plan": plan.payload(), "base_model_digest": prepared.model_digest,
                            "profile_id": experiment.profile, "paired_random_seed": model.config.random_seed,
                        },
                    },
                )
                run_dir = registry.new_run_dir(scenario_id)
                record = registry.write_status(
                    run_dir, status="running", scenario_id=scenario_id,
                    message=f"Paid simulation: {plan.id}", kind="formal",
                    model_digest=digest, engine_id=prepared.engine_id,
                    output_dir=run_dir / "output", report_dir=run_dir / "report",
                    report_index=run_dir / "report" / "index.html",
                )
                outcome = executor.execute(PreparedRun(lane_prepared, adapter, record))
                record = outcome.record
                lane = {
                    "scenario_id": scenario_id, "plan_id": plan.id,
                    "run_id": record.run_id, "status": record.status,
                    "message": record.message,
                    "model_digest": digest,
                    "run_dir": str(record.output_dir.resolve()),
                    "report_index": str(record.report_index.resolve()),
                }
                payload["runs"].append(lane)
                if record.status == "success":
                    lane.update(summarize_paid_run(record.output_dir, lane_model, scenario_id, experiment.profile))
                write_paid_report(payload, output_dir)
        payload["status"] = "success" if all(row["status"] == "success" for row in payload["runs"]) else "failed"
    except Exception as error:
        payload["status"] = "failed"
        payload["error"] = str(error)
        write_paid_report(payload, output_dir)
        raise
    write_paid_report(payload, output_dir)
    return payload
