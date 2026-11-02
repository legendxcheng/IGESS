"""Submit Fish runs to an existing IGESS Dashboard; never start a local simulation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4


DEFAULT_SERVER = "http://127.0.0.1:8771"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FormalForm(HTMLParser):
    """Select the formal form's token, never the service restart token."""

    def __init__(self, action):
        super().__init__()
        self.action = action
        self.inside = False
        self.token = None
        self.select = None
        self.scenarios = set()
        self.resumes = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.inside = attrs.get("action") == self.action
        if not self.inside:
            return
        if tag == "input" and attrs.get("name") == "_csrf":
            self.token = attrs.get("value")
        if tag == "select":
            self.select = attrs.get("name")
        if tag == "option" and "disabled" not in attrs:
            if self.select == "scenario":
                self.scenarios.add(attrs.get("value"))
            if self.select == "resume_run_id":
                self.resumes.add(attrs.get("value"))

    def handle_endtag(self, tag):
        if tag == "form":
            self.inside = False
        if tag == "select":
            self.select = None


class DashboardClient:
    def __init__(self, server, project, timeout=10):
        parsed = urlsplit(server)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            raise ValueError("--server must be a local HTTP origin, e.g. http://127.0.0.1:8771")
        self.server = server.rstrip("/")
        self.project = Path(project).resolve()
        # Same config identity as dashboard_projects.discover_dashboard_projects.
        identity = str((self.project / "economy.yaml").resolve()).casefold()
        self.prefix = "/p/p-" + sha256(identity.encode()).hexdigest()[:16]
        self.url = self.server + self.prefix + "/"
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def get(self, url, *, json_response=True):
        with self.opener.open(url, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if json_response else body

    def status(self):
        return {"ok": True, "state": "current_project_task", "dashboard_url": self.url,
                "task_url": self.url + "task", "current_task": self.get(self.url + "task")}

    def submit(self, scenario, resume_run_id, jobs_root):
        server = self.get(self.server + "/server/status")
        if not server.get("instance_id") or server.get("restarting"):
            raise ValueError("Dashboard is restarting or does not support instance identity")
        form = FormalForm(self.prefix + "/formal")
        form.feed(self.get(self.url, json_response=False))
        before = self.get(self.url + "task")
        if before.get("instance_id") != server["instance_id"]:
            raise ValueError("Dashboard instance changed before submission; no task submitted")
        if before.get("state") == "running":
            raise ValueError("This project already has a running task; inspect its Dashboard")
        if not form.token or scenario not in form.scenarios:
            raise ValueError("Formal scenario unavailable; inspect model checks and available scenarios in Dashboard")
        if resume_run_id and resume_run_id not in form.resumes:
            raise ValueError("Continuation run is not available in this Dashboard's project history")
        body = {"_csrf": form.token, "scenario": scenario}
        if resume_run_id:
            body["resume_run_id"] = resume_run_id
        receipt = {
            "ok": False, "state": "submission_unknown", "transport": "dashboard",
            "server": self.server, "instance_id": server["instance_id"],
            "project": str(self.project), "scenario": scenario, "resume_run_id": resume_run_id,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "dashboard_url": self.url, "task_url": self.url + "task",
            "message": "Inspect Dashboard before retrying; acceptance has not been confirmed.",
        }
        directory = Path(jobs_root).resolve() / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8])
        directory.mkdir(parents=True)
        path = directory / "submission.json"
        receipt["receipt_path"] = str(path)
        save(path, receipt)  # Persist uncertainty before sending a mutating request.
        request = Request(self.url + "formal", data=urlencode(body).encode(),
                          headers={"Origin": self.server, "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                receipt["message"] = f"Unexpected HTTP {response.status}; inspect Dashboard before retrying."
        except HTTPError as exc:
            if exc.code == 303 and exc.headers.get("Location") == self.prefix + "/":
                receipt.update(ok=True, state="accepted", message="Dashboard accepted the task; completion is not yet verified.")
            elif exc.code in {400, 403, 404, 405, 409, 429, 503}:
                receipt.update(state="rejected", message=f"Dashboard rejected submission: HTTP {exc.code}.")
            else:
                receipt["message"] = f"HTTP {exc.code}; inspect Dashboard before retrying."
            exc.close()
        except (OSError, ValueError) as exc:
            receipt["message"] = f"{type(exc).__name__}: {exc}; inspect Dashboard before retrying."
        save(path, receipt)
        return receipt


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["submit", "status"])
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--project", default="projects/fish_source")
    parser.add_argument("--scenario")
    parser.add_argument("--resume-run-id")
    parser.add_argument("--jobs-root", default=".scratch/fish-dashboard")
    args = parser.parse_args(argv)
    if args.action == "submit" and not args.scenario:
        parser.error("submit requires --scenario")
    if args.action == "status" and (args.scenario or args.resume_run_id):
        parser.error("status is read-only and accepts no scenario or continuation")
    if args.resume_run_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", args.resume_run_id):
        parser.error("Invalid --resume-run-id")
    try:
        client = DashboardClient(args.server, args.project)
        result = (client.status() if args.action == "status" else
                  client.submit(args.scenario, args.resume_run_id, args.jobs_root))
    except (OSError, ValueError) as exc:
        result = {"ok": False, "state": "not_submitted", "message": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
