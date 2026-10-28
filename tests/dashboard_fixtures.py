"""In-process task double for existing HTTP routing/observability tests.

Fresh-code and process-lifecycle acceptance uses real children in
test_dashboard_task_processes, never this double.
"""

from igess.authoring.response import CommandResponse


class InlineTaskRunner:
    def __init__(self, service, config, tables):
        self.service, self.config, self.tables = service, config, tables

    def run(self, operation, scenario=""):
        service = self.service
        if operation == "check":
            if service.is_authoring:
                payload = service.model_status().to_payload()
                return {"status": payload, "authoring": payload}
            lint = service.lint(self.config, self.tables)
            return {"status": {"ok": lint.ok, "message": lint.message}, "authoring": None,
                    "scenarios": service.available_scenarios(self.config), "scenario_error": ""}
        if operation == "advise":
            result = service.run_advice(self.config, self.tables, scenario)
        elif service.is_authoring:
            result = service.run_authoring_scenario(scenario)
        else:
            result = service.run_scenario(self.config, self.tables, scenario)
        if isinstance(result, CommandResponse):
            return {"state": "success" if result.ok else "failed", "message": result.message,
                    "diagnostic": result.to_payload(), "run_id": result.result.get("run_id")}
        return {"state": getattr(result, "status", "success"),
                "message": getattr(result, "message", "Task complete"),
                "run_id": getattr(result, "run_id", None)}

    def close(self):
        pass
