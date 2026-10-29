"""Step ramp for Locust: add RAMP_STEP_USERS users every RAMP_STEP_SECONDS until a step breaks the target or
RAMP_MAX_USERS is reached. Loaded together with locustfile.py by loadtest/ramp.py.

A step is "broken" when more than 1 % of its requests failed (errors, 503 shed, timeouts) or its p95 response time
went over 1 s. Each finished step is printed and written to RAMP_OUT (JSON), with the client's view (Locust: what
users experienced) next to the server's view (the API's /traffic.json: time spent inside the API). The difference
is time spent queueing in the network stack, plus the load generator's own delays.
"""
import json
import os
import urllib.request

from locust import LoadTestShape

MAX_FAIL_RATIO = 0.01
MAX_P95_MS = 1000


class StepRamp(LoadTestShape):
    step_users = int(os.environ.get("RAMP_STEP_USERS", 50))
    step_seconds = int(os.environ.get("RAMP_STEP_SECONDS", 10))
    max_users = int(os.environ.get("RAMP_MAX_USERS", 3000))

    def __init__(self):
        super().__init__()
        self.step = 0
        self.mark = (0, 0)
        self.steps = []
        self.verdict = None

    def tick(self):
        step = int(self.get_run_time() // self.step_seconds)
        if step > self.step:   # the previous step just ended: judge it
            healthy = self.judge()
            self.step = step
            if not healthy:
                return None
        users = (self.step + 1) * self.step_users
        if users > self.max_users:
            self.finish(f"reached RAMP_MAX_USERS={self.max_users} without breaking")
            return None
        return users, self.step_users   # spawn the step's new users within about a second

    def judge(self):
        total = self.runner.stats.total
        requests, failures = total.num_requests - self.mark[0], total.num_failures - self.mark[1]
        self.mark = (total.num_requests, total.num_failures)
        users = (self.step + 1) * self.step_users
        row = {
            "users": users,
            "target_rps": round(users * (0.9 * 1 + 0.1 * 0.5)),   # 9/10 nodes at 1/s, 1/10 viewers at 0.5/s
            "rps": round(requests / self.step_seconds, 1),
            "fail_pct": round(100 * failures / requests, 2) if requests else 0.0,
            "p50_ms": total.get_current_response_time_percentile(0.5),
            "p95_ms": total.get_current_response_time_percentile(0.95),
            "p99_ms": total.get_current_response_time_percentile(0.99),
            "locust_cpu_pct": round(self.runner.current_cpu_usage),
            **self.server_view(),
        }
        self.steps.append(row)
        print("step " + "  ".join(f"{k}={v}" for k, v in row.items()), flush=True)
        reasons = []
        if row["fail_pct"] > 100 * MAX_FAIL_RATIO:
            reasons.append(f"{row['fail_pct']} % of requests failed")
        if (row["p95_ms"] or 0) > MAX_P95_MS:
            reasons.append(f"p95 {row['p95_ms']} ms > {MAX_P95_MS} ms")
        if reasons:
            self.finish(f"broke at {users} users (~{row['target_rps']} req/s offered): " + ", ".join(reasons))
            return False
        self.save()
        return True

    def server_view(self):
        """The API's own numbers for the last 10 s; empty if it does not answer (that is a result too)."""
        try:
            with urllib.request.urlopen(f"{self.runner.environment.host}/traffic.json", timeout=2) as resp:
                w = json.load(resp)
            return {"server_rps": w["rps"], "server_p99_ms": w["p99_ms"], "server_in_flight_peak": w["in_flight_peak"],
                    "server_shed_total": w["shed_total"], "server_connections_total": w["connections_total"]}
        except (OSError, ValueError, KeyError):
            return {"server": "no answer"}

    def finish(self, verdict):
        self.verdict = verdict
        print(f"RESULT: {verdict}", flush=True)
        self.save()

    def save(self):
        out = os.environ.get("RAMP_OUT")
        if out:
            with open(out, "w") as f:
                json.dump({"verdict": self.verdict, "step_users": self.step_users, "step_seconds": self.step_seconds,
                           "max_fail_ratio": MAX_FAIL_RATIO, "max_p95_ms": MAX_P95_MS, "steps": self.steps}, f, indent=1)
