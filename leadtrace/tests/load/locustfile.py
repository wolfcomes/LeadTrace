from __future__ import annotations

import os
from dataclasses import dataclass

from locust import HttpUser, between, events, task


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    visitor_username: str
    visitor_password: str
    reviewer_username: str
    reviewer_password: str
    paper_id: str
    changeset_id: str


def _config() -> ScenarioConfig:
    return ScenarioConfig(
        visitor_username=os.environ.get("LEADTRACE_LOAD_VISITOR_USERNAME", ""),
        visitor_password=os.environ.get("LEADTRACE_LOAD_VISITOR_PASSWORD", ""),
        reviewer_username=os.environ.get("LEADTRACE_LOAD_REVIEWER_USERNAME", ""),
        reviewer_password=os.environ.get("LEADTRACE_LOAD_REVIEWER_PASSWORD", ""),
        paper_id=os.environ.get("LEADTRACE_LOAD_PAPER_ID", ""),
        changeset_id=os.environ.get("LEADTRACE_LOAD_CHANGESET_ID", ""),
    )


class AuthenticatedUser(HttpUser):
    abstract = True
    wait_time = between(0.5, 2.0)
    username = ""
    password = ""
    csrf_token = ""

    def on_start(self) -> None:
        if not self.username or not self.password:
            self.environment.runner.quit()
            raise RuntimeError("load-test credentials are not configured")
        with self.client.post(
            "/api/v1/auth/login",
            json={"username": self.username, "password": self.password},
            name="login",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure("login_failed")
                return
            self.csrf_token = str(response.json().get("csrf_token", ""))


class VisitorUser(AuthenticatedUser):
    weight = 4

    def on_start(self) -> None:
        config = _config()
        self.username = config.visitor_username
        self.password = config.visitor_password
        super().on_start()

    @task(5)
    def paper_list(self) -> None:
        self.client.get("/api/v1/papers?page=1&page_size=20", name="Paper list")

    @task(2)
    def search(self) -> None:
        self.client.get(
            "/api/v1/papers?page=1&page_size=20&search=kinase",
            name="search",
        )

    @task(3)
    def paper_detail(self) -> None:
        paper_id = _config().paper_id
        if paper_id:
            self.client.get(f"/api/v1/papers/{paper_id}", name="Paper detail metadata")


class ReviewerUser(AuthenticatedUser):
    weight = 1
    version: int | None = None

    def on_start(self) -> None:
        config = _config()
        self.username = config.reviewer_username
        self.password = config.reviewer_password
        super().on_start()
        if not config.changeset_id:
            return
        response = self.client.get(
            f"/api/v1/review/changesets/{config.changeset_id}",
            name="changeset detail",
        )
        if response.status_code == 200:
            self.version = int(response.json()["version"])

    @task(4)
    def assigned_pdf_range(self) -> None:
        paper_id = _config().paper_id
        if paper_id:
            self.client.get(
                f"/api/v1/papers/{paper_id}/source-pdf",
                headers={"Range": "bytes=0-65535"},
                name="cached PDF page",
            )

    @task(2)
    def save_changeset(self) -> None:
        config = _config()
        if not config.changeset_id or self.version is None:
            return
        with self.client.patch(
            f"/api/v1/review/changesets/{config.changeset_id}",
            headers={"X-CSRF-Token": self.csrf_token},
            json={
                "expected_version": self.version,
                "title": "Load-test draft",
                "reason": "Concurrency and latency gate",
            },
            name="changeset save",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                self.version = int(response.json()["version"])
            elif response.status_code == 409:
                response.success()
                current = response.json().get("details", {}).get("current_version")
                if isinstance(current, int):
                    self.version = current


P95_TARGETS_MS = {
    ("POST", "login"): 500,
    ("GET", "Paper list"): 500,
    ("GET", "Paper detail metadata"): 1000,
    ("PATCH", "changeset save"): 750,
    ("GET", "search"): 1000,
    ("GET", "cached PDF page"): 500,
}


@events.quitting.add_listener
def enforce_p95_targets(environment, **_: object) -> None:
    failures: list[str] = []
    for (method, name), target_ms in P95_TARGETS_MS.items():
        entry = environment.stats.get(name, method)
        if entry.num_requests == 0:
            failures.append(f"{name}: no samples")
            continue
        p95 = entry.get_response_time_percentile(0.95)
        if p95 > target_ms:
            failures.append(f"{name}: p95 {p95}ms exceeds {target_ms}ms")
    if environment.stats.total.fail_ratio > 0.01:
        failures.append(
            f"failure ratio {environment.stats.total.fail_ratio:.2%} exceeds 1%"
        )
    if failures:
        environment.process_exit_code = 1
        for failure in failures:
            print(f"LOAD_GATE_FAILURE {failure}")
