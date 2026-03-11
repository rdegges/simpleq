"""Dashboard and metrics HTTP helpers for SimpleQ."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from jinja2 import Template

from simpleq._sync import run_sync

_DASHBOARD_TEMPLATE = Template(
    """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>SimpleQ Dashboard</title>
    <style>
      :root {
        color-scheme: light;
        --bg: #f6f3ee;
        --panel: #ffffff;
        --ink: #1c1a18;
        --muted: #6f665f;
        --accent: #0f766e;
        --border: #d7cfc4;
      }
      body {
        margin: 0;
        padding: 2rem;
        font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
        background:
          radial-gradient(circle at top right, rgba(15, 118, 110, 0.12), transparent 24rem),
          linear-gradient(180deg, #f7f5f2 0%, #efe7dd 100%);
        color: var(--ink);
      }
      h1, h2 { margin-top: 0; }
      .grid {
        display: grid;
        gap: 1rem;
        grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
      }
      .card {
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 1rem;
        padding: 1.25rem;
        box-shadow: 0 10px 25px rgba(28, 26, 24, 0.05);
      }
      table {
        width: 100%;
        border-collapse: collapse;
      }
      th, td {
        text-align: left;
        padding: 0.35rem 0;
        border-bottom: 1px solid #efe7dd;
      }
      .muted { color: var(--muted); }
      .total {
        font-size: 2rem;
        color: var(--accent);
      }
      a { color: var(--accent); text-decoration: none; }
    </style>
  </head>
  <body>
    <div class="grid">
      <section class="card">
        <h1>SimpleQ Dashboard</h1>
        <div class="total">${{ "%.6f"|format(total_cost) }}</div>
        <p class="muted">Estimated local SQS request spend tracked by this process.</p>
        <p><a href="/metrics">Prometheus Metrics</a></p>
      </section>
      <section class="card">
        <h2>Queues</h2>
        <table>
          <thead>
            <tr>
              <th>Queue</th>
              <th>Visible</th>
              <th>DLQ visible</th>
              <th>In flight</th>
              <th>Delayed</th>
            </tr>
          </thead>
          <tbody>
            {% for queue in queues %}
            <tr>
              <td>{{ queue.name }}</td>
              <td>{{ queue.available_messages }}</td>
              <td>{{ queue.dlq_available_messages if queue.dlq_available_messages is not none else "n/a" }}</td>
              <td>{{ queue.in_flight_messages }}</td>
              <td>{{ queue.delayed_messages }}</td>
            </tr>
            {% else %}
            <tr>
              <td colspan="5" class="muted">No queues discovered.</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </section>
      <section class="card">
        <h2>Cost Tracker</h2>
        <table>
          <thead>
            <tr>
              <th>Queue</th>
              <th>Requests</th>
              <th>Processed</th>
              <th>Retried</th>
              <th>Decode errors</th>
            </tr>
          </thead>
          <tbody>
            {% for name, metrics in cost_metrics.items() %}
            <tr>
              <td>{{ name }}</td>
              <td>{{ metrics.total_requests }}</td>
              <td>{{ metrics.jobs_processed }}</td>
              <td>{{ metrics.jobs_retried }}</td>
              <td>{{ metrics.get("jobs_decode_failed", 0) }}</td>
            </tr>
            {% else %}
            <tr>
              <td colspan="5" class="muted">No local metrics yet.</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </section>
    </div>
  </body>
</html>
"""
)


class Dashboard:
    """Render SimpleQ runtime data as HTML."""

    def __init__(self, simpleq: Any, *, queue_names: list[str] | None = None) -> None:
        self.simpleq = simpleq
        self.queue_names = queue_names

    async def queue_stats(self) -> list[Any]:
        """Fetch queue stats for the configured or discovered queues."""
        queue_names = self.queue_names or await self.simpleq.list_queues()
        stats = []
        for name in queue_names:
            queue = self.simpleq.queue(name, fifo=name.endswith(".fifo"))
            stats.append(await queue.stats())
        return stats

    async def render(self) -> str:
        """Render the dashboard HTML."""
        queues = await self.queue_stats()
        return _DASHBOARD_TEMPLATE.render(
            total_cost=self.simpleq.cost_tracker.total_cost(),
            queues=queues,
            cost_metrics=self.simpleq.cost_tracker.snapshot(),
        )

    def render_sync(self) -> str:
        """Synchronous wrapper for :meth:`render`."""
        return run_sync(self.render())


def create_dashboard_server(
    simpleq: Any,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    queue_names: list[str] | None = None,
) -> ThreadingHTTPServer:
    """Create an HTTP server that serves the dashboard and metrics."""
    dashboard = Dashboard(simpleq, queue_names=queue_names)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/metrics":
                payload = simpleq.metrics.render()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.end_headers()
                self.wfile.write(payload)
                return

            if self.path != "/":
                self.send_response(404)
                self.end_headers()
                return

            payload = dashboard.render_sync().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)
