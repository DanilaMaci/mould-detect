"""Request metrics for services/api, kept in memory (reset on restart).

Two views of the same requests:
- Prometheus counters and a latency histogram (/metrics): totals since start, which a collector scrapes every few
  seconds and turns into rates and approximate percentiles (histogram_quantile).
- A rolling window of the last WINDOW_S seconds (/traffic.json): exact percentiles of recent requests, for the live
  traffic page and the load tests.
Labels only take values from a fixed set (route names, method, status class): a label per raw path would let anyone
create unlimited time series by requesting random URLs.
"""
import bisect
import threading
import time
from collections import deque

BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)   # seconds
WINDOW_S = 60


def percentile(sorted_values, p):
    """Nearest-rank percentile of an ascending list (p in 0..100); None for an empty list."""
    if not sorted_values:
        return None
    rank = max(1, -(-len(sorted_values) * p // 100))   # ceil(n * p / 100)
    return sorted_values[int(rank) - 1]


class Metrics:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.requests = {}         # (route, method, status) -> count
        self.buckets = {}          # route -> list of counts per bucket (not cumulative; made cumulative on export)
        self.sums = {}             # route -> total seconds
        self.counts = {}           # route -> requests
        self.in_flight = 0
        self.shed = 0              # requests refused with 503 because too many were in flight
        self.connections = 0       # TCP connections accepted; requests / connections = how well keep-alive works
        self.seconds = deque()     # one bucket per clock second: [second, durations, status counts, peak in flight]

    def started(self):
        with self.lock:
            self.in_flight += 1
            bucket = self._bucket(int(self.clock()))
            bucket[3] = max(bucket[3], self.in_flight)   # peak per second: averages hide the moments that shed

    def finished(self, route, method, status, seconds, live=True):
        """live=False: count for Prometheus only, not in the traffic window (the traffic page's own polling)."""
        with self.lock:
            self.in_flight -= 1
            key = (route, method, status)
            self.requests[key] = self.requests.get(key, 0) + 1
            b = self.buckets.setdefault(route, [0] * (len(BUCKETS) + 1))
            b[bisect.bisect_left(BUCKETS, seconds)] += 1   # le semantics: value <= bound
            self.sums[route] = self.sums.get(route, 0.0) + seconds
            self.counts[route] = self.counts.get(route, 0) + 1
            if not live:
                return
            bucket = self._bucket(int(self.clock()))
            bucket[1].append(seconds)
            bucket[2][status] = bucket[2].get(status, 0) + 1

    def connected(self):
        with self.lock:
            self.connections += 1

    def shed_one(self):
        with self.lock:
            self.shed += 1

    def _bucket(self, sec):
        """The bucket of clock second `sec`, created when the first event of that second happens (lock held)."""
        if not self.seconds or self.seconds[-1][0] != sec:
            self.seconds.append([sec, [], {}, self.in_flight])
            self._trim(sec)
        return self.seconds[-1]

    def _trim(self, sec):
        while self.seconds and self.seconds[0][0] <= sec - WINDOW_S:
            self.seconds.popleft()

    def window(self, seconds=10):
        """Live view of the last `seconds` complete seconds: request rate, error share, latency percentiles, status
        codes; plus one point per second of the whole window for the page's charts."""
        with self.lock:
            now = int(self.clock())
            self._trim(now)
            buckets = {b[0]: (list(b[1]), dict(b[2]), b[3]) for b in self.seconds}
            in_flight, shed, connections = self.in_flight, self.shed, self.connections
        series, durations, status, peak = [], [], {}, 0
        for sec in range(now - WINDOW_S + 1, now + 1):   # oldest first; the current second is still filling
            d, st, top = buckets.get(sec, ([], {}, 0))
            d = sorted(d)
            series.append({"t": sec, "rps": len(d), "errors": sum(n for c, n in st.items() if c >= 500),
                           "p50_ms": ms(percentile(d, 50)), "p99_ms": ms(percentile(d, 99)), "in_flight_peak": top})
            if now - seconds <= sec < now:
                peak = max(peak, top)
                durations += d
                for c, n in st.items():
                    status[c] = status.get(c, 0) + n
        durations.sort()
        errors = sum(n for c, n in status.items() if c >= 500)
        return {
            "rps": round(len(durations) / seconds, 1),
            "error_pct": round(100 * errors / len(durations), 1) if durations else 0.0,
            "p50_ms": ms(percentile(durations, 50)),
            "p95_ms": ms(percentile(durations, 95)),
            "p99_ms": ms(percentile(durations, 99)),
            "in_flight": in_flight,
            "in_flight_peak": peak,
            "shed_total": shed,
            "connections_total": connections,
            "status": {str(c): status[c] for c in sorted(status)},
            "series": series,
        }

    def prometheus(self, extra=()):
        """Text exposition format 0.0.4 (https://prometheus.io/docs/instrumenting/exposition_formats/).
        `extra`: (name, type, help, value) for gauges computed by the caller."""
        with self.lock:
            requests, buckets = dict(self.requests), {k: list(v) for k, v in self.buckets.items()}
            sums, counts, in_flight, shed = dict(self.sums), dict(self.counts), self.in_flight, self.shed
            connections = self.connections
        out = ["# HELP api_http_requests_total Requests answered, by route, method and status code.",
               "# TYPE api_http_requests_total counter"]
        out += [f'api_http_requests_total{{route="{r}",method="{m}",status="{s}"}} {n}'
                for (r, m, s), n in sorted(requests.items())]
        out += ["# HELP api_http_request_duration_seconds Time from request line to response sent.",
                "# TYPE api_http_request_duration_seconds histogram"]
        for route in sorted(buckets):
            total = 0
            for bound, n in zip((*BUCKETS, "+Inf"), buckets[route]):
                total += n
                out.append(f'api_http_request_duration_seconds_bucket{{route="{route}",le="{bound}"}} {total}')
            out.append(f'api_http_request_duration_seconds_sum{{route="{route}"}} {sums[route]:.6f}')
            out.append(f'api_http_request_duration_seconds_count{{route="{route}"}} {counts[route]}')
        gauges = [("api_http_requests_in_flight", "gauge", "Requests being handled right now.", in_flight),
                  ("api_http_requests_shed_total", "counter", "Requests refused with 503: too many in flight.", shed),
                  ("api_http_connections_total", "counter", "TCP connections accepted.", connections),
                  *extra]
        for name, kind, text, value in gauges:
            out += [f"# HELP {name} {text}", f"# TYPE {name} {kind}", f"{name} {value}"]
        return "\n".join(out) + "\n"


def ms(seconds):
    return None if seconds is None else round(seconds * 1000, 2)
