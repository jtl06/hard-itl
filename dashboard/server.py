from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "dashboard" / "state.json"
LOG_PATH = ROOT / "dashboard" / "orchestrator.log"

PROCESS: subprocess.Popen[str] | None = None
LOCK = threading.Lock()

HTML = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>HIL Agent Dashboard</title>
  <style>
    :root {
      --bg: #0b1320;
      --panel: #121e33;
      --panel2: #172742;
      --text: #e9f0ff;
      --muted: #95a8c8;
      --ok: #33d17a;
      --warn: #f6c453;
      --err: #ff6b6b;
      --run: #4da3ff;
      --border: #2a3f62;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background: radial-gradient(circle at 15% 0%, #1b2a4a 0%, var(--bg) 45%);
      color: var(--text);
    }
    .wrap {
      max-width: 1860px;
      width: min(96vw, 1860px);
      margin: 0 auto;
      padding: 18px;
      display: grid;
      gap: 14px;
    }
    .top {
      background: linear-gradient(130deg, var(--panel), var(--panel2));
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      display: grid;
      gap: 10px;
    }
    .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .pill { border-radius: 999px; padding: 4px 10px; font-size: 12px; border: 1px solid var(--border); color: var(--muted); }
    .progress-wrap { width: 100%; height: 10px; border-radius: 999px; background: #0a1528; border: 1px solid var(--border); overflow: hidden; }
    .progress-bar { height: 100%; width: 0%; background: linear-gradient(90deg, #2d75ff, #33d17a); transition: width 250ms ease; }
    .status-running { color: var(--run); }
    .status-completed { color: var(--ok); }
    .status-fallback { color: var(--warn); }
    .status-failed, .status-error { color: var(--err); }
    label { font-size: 13px; color: var(--muted); }
    input, select, button {
      background: #0f1a2d;
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 10px;
      font-size: 13px;
    }
    button { cursor: pointer; background: #1d3359; }
    button:hover { filter: brightness(1.1); }
    .dashboard-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(300px, 1fr));
      grid-template-areas:
        "planner coder load"
        "debugger coordinator load"
        "overall overall uart"
        "overall overall tracker";
      gap: 12px;
    }
    .card {
      background: linear-gradient(145deg, #121f36, #0f1a2d);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      min-height: 160px;
    }
    .card h3 { margin: 0 0 8px 0; font-size: 15px; }
    .meta { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      color: #d8e5ff;
      font-size: 12px;
      line-height: 1.4;
      max-height: 210px;
      overflow: auto;
      padding: 8px;
      border-radius: 8px;
      border: 1px solid #21355a;
      background: #0a1528;
    }
    .agent-status { font-weight: 700; text-transform: uppercase; font-size: 11px; letter-spacing: .04em; }
    .area-planner { grid-area: planner; }
    .area-coder { grid-area: coder; }
    .area-debugger { grid-area: debugger; }
    .area-coordinator { grid-area: coordinator; }
    .area-load { grid-area: load; }
    .area-overall { grid-area: overall; min-height: 350px; }
    .area-uart { grid-area: uart; }
    .area-tracker { grid-area: tracker; }
    .area-load { min-height: 350px; }
    .chart-grid {
      display: grid;
      gap: 8px;
    }
    .chart-row {
      display: grid;
      grid-template-columns: 90px 1fr 88px;
      align-items: center;
      gap: 8px;
      font-size: 12px;
    }
    .bar-wrap {
      width: 100%;
      height: 12px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: #0a1528;
      overflow: hidden;
    }
    .bar-fill {
      height: 100%;
      width: 0%;
      transition: width 280ms ease;
      background: linear-gradient(90deg, #4da3ff, #33d17a);
    }
    @media (max-width: 1400px) {
      .dashboard-grid {
        grid-template-columns: repeat(2, minmax(280px, 1fr));
        grid-template-areas:
          "planner coder"
          "debugger coordinator"
          "load load"
          "overall overall"
          "uart tracker";
      }
    }
    @media (max-width: 920px) {
      .dashboard-grid {
        grid-template-columns: 1fr;
        grid-template-areas:
          "planner"
          "coder"
          "debugger"
          "coordinator"
          "load"
          "overall"
          "uart"
          "tracker";
      }
    }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <section class=\"top\">
      <div class=\"row\">
        <h2 style=\"margin:0\">HIL Multi-Agent Dashboard</h2>
        <span id=\"overall_status\" class=\"pill\">idle</span>
        <span id=\"overall_progress\" class=\"pill\">0/0</span>
      </div>
      <div class=\"progress-wrap\"><div id=\"progress_bar\" class=\"progress-bar\"></div></div>
      <div class=\"row\">
        <label>Case
          <select id=\"case\">
            <option value=\"uart_demo\">uart_demo (baud hunt)</option>
            <option value=\"framing_hunt\">framing_hunt</option>
            <option value=\"parity_hunt\">parity_hunt</option>
            <option value=\"signature_check\">signature_check</option>
          </select>
        </label>
        <label>Runs <input id=\"runs\" type=\"number\" value=\"8\" min=\"1\" max=\"100\"></label>
        <label id=\"target_baud_wrap\">Target Baud <input id=\"target_baud\" type=\"number\" value=\"76200\" min=\"1200\" step=\"1\"></label>
        <label id=\"target_frame_wrap\" style=\"display:none;\">Target Frame
          <select id=\"target_frame\">
            <option value=\"8N1\">8N1</option>
            <option value=\"7E1\">7E1</option>
            <option value=\"8E1\">8E1</option>
          </select>
        </label>
        <label id=\"target_parity_wrap\" style=\"display:none;\">Target Parity
          <select id=\"target_parity\">
            <option value=\"none\">none</option>
            <option value=\"even\">even</option>
            <option value=\"odd\">odd</option>
          </select>
        </label>
        <label id=\"target_magic_wrap\" style=\"display:none;\">Target Magic <input id=\"target_magic\" value=\"0xC0FFEE42\"></label>
        <label>Mode
          <select id=\"mode\"><option value=\"mock\">mock</option><option value=\"real\">real</option></select>
        </label>
        <button id=\"start_btn\">Start Run</button>
      </div>
      <div id=\"proc_info\" class=\"meta\"></div>
      <div id=\"overall_msg\" class=\"meta\"></div>
    </section>

    <section class=\"dashboard-grid\">
      <article class=\"card area-planner\">
        <h3>Planner</h3>
        <div class=\"meta\">Plans next run params from current evidence.</div>
        <div id=\"planner_status\" class=\"agent-status\">idle</div>
        <div id=\"planner_task\" class=\"meta\">Waiting for run.</div>
        <pre id=\"planner_fragment\">Evidence -> Hypothesis -> Next action will appear here.</pre>
      </article>
      <article class=\"card area-coder\">
        <h3>Coder</h3>
        <div class=\"meta\">Suggests minimal instrumentation/fix ideas.</div>
        <div id=\"coder_status\" class=\"agent-status\">idle</div>
        <div id=\"coder_task\" class=\"meta\">Waiting for run.</div>
        <pre id=\"coder_fragment\">Evidence -> Hypothesis -> Next action will appear here.</pre>
      </article>
      <article class=\"card area-debugger\">
        <h3>Debugger</h3>
        <div class=\"meta\">Checks feasibility and risks.</div>
        <div id=\"critic_status\" class=\"agent-status\">idle</div>
        <div id=\"critic_task\" class=\"meta\">Waiting for run.</div>
        <pre id=\"critic_fragment\">Evidence -> Hypothesis -> Next action will appear here.</pre>
      </article>
      <article class=\"card area-coordinator\">
        <h3>Coordinator</h3>
        <div class=\"meta\">Merges outputs into one runbook.</div>
        <div id=\"summarizer_status\" class=\"agent-status\">idle</div>
        <div id=\"summarizer_task\" class=\"meta\">Waiting for run.</div>
        <pre id=\"summarizer_fragment\">Evidence -> Hypothesis -> Next action will appear here.</pre>
      </article>
      <article class=\"card area-load\">
        <h3>Agent Load / Time</h3>
        <div class=\"meta\">Cumulative active-time split (updates every 1s).</div>
        <div class=\"chart-grid\">
          <div class=\"chart-row\"><div>Planner</div><div class=\"bar-wrap\"><div id=\"bar_planner\" class=\"bar-fill\"></div></div><div id=\"pct_planner\">0.0%</div></div>
          <div class=\"chart-row\"><div>Coder</div><div class=\"bar-wrap\"><div id=\"bar_coder\" class=\"bar-fill\"></div></div><div id=\"pct_coder\">0.0%</div></div>
          <div class=\"chart-row\"><div>Debugger</div><div class=\"bar-wrap\"><div id=\"bar_critic\" class=\"bar-fill\"></div></div><div id=\"pct_critic\">0.0%</div></div>
          <div class=\"chart-row\"><div>Coordinator</div><div class=\"bar-wrap\"><div id=\"bar_summarizer\" class=\"bar-fill\"></div></div><div id=\"pct_summarizer\">0.0%</div></div>
        </div>
        <div id=\"chart_meta\" class=\"meta\"></div>
      </article>
      <article class=\"card area-overall\">
        <h3>Overall Output</h3>
        <pre id=\"overall_output\">No output yet. Start a run to populate the merged summarizer output.</pre>
      </article>
      <article class=\"card area-uart\">
        <h3>Latest UART</h3>
        <pre id=\"latest_uart\">No UART lines yet. Start a run to stream latest uart.log tail.</pre>
      </article>
      <article class=\"card area-tracker\">
        <h3>Run Tracker</h3>
        <pre id=\"history\">No runs yet.</pre>
      </article>
    </section>
  </div>

<script>
async function startRun() {
  try {
    const caseId = document.getElementById('case').value;
    const payload = {
      case: caseId,
      runs: Number(document.getElementById('runs').value || 8),
      mode: document.getElementById('mode').value,
    };
    if (caseId === 'uart_demo') {
      payload.target_baud = Number(document.getElementById('target_baud').value || 0);
    } else if (caseId === 'framing_hunt') {
      payload.target_frame = document.getElementById('target_frame').value;
    } else if (caseId === 'parity_hunt') {
      payload.target_parity = document.getElementById('target_parity').value;
    } else if (caseId === 'signature_check') {
      payload.target_magic = document.getElementById('target_magic').value;
    }
    const res = await fetch('/api/run', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
    });
    const data = await res.json().catch(() => ({ok:false, message: 'Failed to parse start response'}));
    const msg = data.message || `HTTP ${res.status}`;
    document.getElementById('proc_info').textContent = msg;
    if (!res.ok) {
      document.getElementById('overall_msg').textContent = msg;
    }
  } catch (err) {
    document.getElementById('proc_info').textContent = `Start failed: ${String(err)}`;
    document.getElementById('overall_msg').textContent = 'Unable to reach dashboard backend.';
  }
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = (value === undefined || value === null || value === '') ? '—' : value;
}

function applyStatusClass(id, status) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'pill status-' + (status || 'idle');
}

function applyAgentStatus(id, status) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = (status || 'idle');
  el.style.color =
    status === 'done' ? 'var(--ok)' :
    status === 'running' ? 'var(--run)' :
    status === 'fallback' ? 'var(--warn)' :
    status === 'error' ? 'var(--err)' :
    'var(--muted)';
}

function renderStateBundle(bundle) {
  const state = bundle.state || {};
  const p = bundle.process || {};
  const o = state.overall || {};

  setText('overall_status', o.status || 'idle');
  applyStatusClass('overall_status', o.status || 'idle');
  setText('overall_progress', `${o.current_run || 0}/${o.runs_total || 0}`);
  setText('overall_msg', o.message || '');
  const total = Number(o.runs_total || 0);
  const cur = Number(o.current_run || 0);
  const pct = total > 0 ? Math.max(0, Math.min(100, (cur / total) * 100)) : 0;
  document.getElementById('progress_bar').style.width = `${pct}%`;

  for (const name of ['planner','coder','critic','summarizer']) {
    const a = (state.agents || {})[name] || {};
    applyAgentStatus(`${name}_status`, a.status || 'idle');
      setText(`${name}_task`, a.task || 'Waiting for run.');
      setText(`${name}_fragment`, a.fragment || 'Evidence -> Hypothesis -> Next action will appear here.');
  }

  setText('overall_output', state.overall_output || 'No output yet. Start a run to populate summarizer output.');
  setText('latest_uart', (state.latest_uart || []).join('\\n') || 'No UART lines yet.');
  const history = (state.history || []).map(r =>
    (String(r.guess_key || '') !== '')
      ? `run ${r.run}: ${String(r.status || '').toUpperCase()}  guess=${r.guess_value}  target=${r.target_value}  errors=${r.error_count}  id=${r.run_id}`
      : `run ${r.run}: ${String(r.status || '').toUpperCase()}  rate=${r.uart_rate}  buf=${r.buffer_size}  errors=${r.error_count}  id=${r.run_id}`
  ).join('\\n');
  setText('history', history || 'No runs yet.');

  const procMsg = p.running
    ? `process: running (pid=${p.pid || 'n/a'})`
    : `process: idle` + (p.exit_code !== null && p.exit_code !== undefined ? ` (last exit=${p.exit_code})` : '');
  const logMsg = (p.log_tail || []).join('\\n');
  setText('proc_info', procMsg + (logMsg ? '\\n' + logMsg : ''));
  renderAgentChart(state);
}

function updateTargetVisibility() {
  const c = document.getElementById('case').value;
  document.getElementById('target_baud_wrap').style.display = c === 'uart_demo' ? '' : 'none';
  document.getElementById('target_frame_wrap').style.display = c === 'framing_hunt' ? '' : 'none';
  document.getElementById('target_parity_wrap').style.display = c === 'parity_hunt' ? '' : 'none';
  document.getElementById('target_magic_wrap').style.display = c === 'signature_check' ? '' : 'none';
}

function renderAgentChart(state) {
  const m = state.agent_metrics || {};
  const roles = ['planner', 'coder', 'critic', 'summarizer'];
  const now = Date.now() / 1000;
  const vals = {};
  let total = 0;
  for (const r of roles) {
    const e = m[r] || {};
    let active = Number(e.active_s || 0);
    if ((e.last_status || '') === 'running') {
      active += Math.max(0, now - Number(e.last_change_epoch || now));
    }
    vals[r] = active;
    total += active;
  }
  for (const r of roles) {
    const pct = total > 0 ? (vals[r] / total) * 100 : 0;
    const bar = document.getElementById(`bar_${r}`);
    const label = document.getElementById(`pct_${r}`);
    if (bar) bar.style.width = `${pct}%`;
    if (label) label.textContent = `${pct.toFixed(1)}% (${vals[r].toFixed(1)}s)`;
  }
  setText('chart_meta', `Total active time: ${total.toFixed(1)}s`);
}

async function refreshOnce() {
  try {
    const res = await fetch('/api/state');
    const state = await res.json();
    const p = await (await fetch('/api/process')).json();
    renderStateBundle({state, process: p});
  } catch (_) {
    setText('overall_msg', 'Waiting for state...');
  }
}

function initSSE() {
  const es = new EventSource('/api/stream');
  es.onmessage = (ev) => {
    try {
      const bundle = JSON.parse(ev.data);
      renderStateBundle(bundle);
    } catch (_) {}
  };
  es.onerror = () => {
    setText('overall_msg', 'SSE disconnected, retrying...');
  };
}

document.getElementById('start_btn').addEventListener('click', startRun);
document.getElementById('case').addEventListener('change', updateTargetVisibility);
refreshOnce();
initSSE();
setInterval(refreshOnce, 1000);
updateTargetVisibility();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(HTML)
            return
        if parsed.path == "/api/state":
            self._send_json(self._read_state())
            return
        if parsed.path == "/api/process":
            with LOCK:
                running = PROCESS is not None and PROCESS.poll() is None
                pid = PROCESS.pid if PROCESS is not None else None
                exit_code = None if running or PROCESS is None else PROCESS.poll()
            self._send_json({"running": running, "pid": pid, "exit_code": exit_code, "log_tail": self._read_log_tail()})
            return
        if parsed.path == "/api/stream":
            self._send_sse_stream()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/api/start", "/api/run"}:
            self._handle_start()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_start(self) -> None:
        try:
            content_len = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_len) if content_len else b"{}"
            payload = json.loads(body.decode("utf-8") or "{}")

            case = str(payload.get("case", "uart_demo"))
            runs = int(payload.get("runs", 8))
            mode = str(payload.get("mode", "mock"))
            target_baud = int(payload.get("target_baud", 0))
            target_frame = str(payload.get("target_frame", ""))
            target_parity = str(payload.get("target_parity", ""))
            target_magic = str(payload.get("target_magic", ""))

            with LOCK:
                global PROCESS
                if PROCESS is not None and PROCESS.poll() is None:
                    self._send_json({"ok": False, "message": "Run already in progress."}, code=409)
                    return

                init_state = {
                    "overall": {
                        "status": "running",
                        "message": f"Launching run: case={case} mode={mode} runs={runs}",
                        "case_id": case,
                        "mode": mode,
                        "runs_total": runs,
                        "current_run": 0,
                        "updated_at": "",
                    },
                    "agents": {
                        "planner": {"status": "idle", "task": "Waiting", "fragment": ""},
                        "coder": {"status": "idle", "task": "Waiting", "fragment": ""},
                        "critic": {"status": "idle", "task": "Waiting", "fragment": ""},
                        "summarizer": {"status": "idle", "task": "Waiting", "fragment": ""},
                    },
                    "latest_uart": [],
                    "last_analysis": {},
                    "overall_output": "",
                    "history": [],
                }
                STATE_PATH.write_text(json.dumps(init_state, indent=2), encoding="utf-8")
                LOG_PATH.write_text("", encoding="utf-8")

                cmd = [
                    sys.executable,
                    "orchestrator.py",
                    "--case",
                    case,
                    "--runs",
                    str(runs),
                "--mode",
                mode,
                "--target-baud",
                str(target_baud),
                "--target-frame",
                target_frame,
                "--target-parity",
                target_parity,
                "--target-magic",
                target_magic,
                "--state-file",
                str(STATE_PATH),
                    "--live-uart",
                    "--trace",
                ]
                logf = LOG_PATH.open("a", encoding="utf-8")
                PROCESS = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT),
                    stdout=logf,
                    stderr=logf,
                    text=True,
                )

            self._send_json({"ok": True, "message": f"Started {mode} run for case={case} runs={runs}."})
        except Exception as exc:
            fail_state = {
                "overall": {
                    "status": "failed",
                    "message": f"Failed to start run: {exc}",
                    "case_id": "",
                    "mode": "",
                    "runs_total": 0,
                    "current_run": 0,
                    "updated_at": "",
                },
                "agents": {
                    "planner": {"status": "idle", "task": "Waiting", "fragment": ""},
                    "coder": {"status": "idle", "task": "Waiting", "fragment": ""},
                    "critic": {"status": "idle", "task": "Waiting", "fragment": ""},
                    "summarizer": {"status": "idle", "task": "Waiting", "fragment": ""},
                },
                "latest_uart": [],
                "last_analysis": {},
                "overall_output": "",
                "history": [],
            }
            STATE_PATH.write_text(json.dumps(fail_state, indent=2), encoding="utf-8")
            self._send_json({"ok": False, "message": f"Failed to start run: {exc}"}, code=500)

    def _send_sse_stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_payload = ""
        try:
            while True:
                bundle = {
                    "state": self._read_state(),
                    "process": self._read_process(),
                }
                payload = json.dumps(bundle)
                if payload != last_payload:
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_payload = payload
                else:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _read_state(self) -> dict:
        if not STATE_PATH.exists():
            return {
                "overall": {
                    "status": "idle",
                    "message": "No run yet. Click Start Run.",
                    "case_id": "",
                    "mode": "",
                    "runs_total": 0,
                    "current_run": 0,
                    "updated_at": "",
                },
                "agents": {
                    "planner": {"status": "idle", "task": "", "fragment": ""},
                    "coder": {"status": "idle", "task": "", "fragment": ""},
                    "critic": {"status": "idle", "task": "", "fragment": ""},
                    "summarizer": {"status": "idle", "task": "", "fragment": ""},
                },
                "latest_uart": [],
                "overall_output": "",
                "history": [],
            }
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"overall": {"status": "error", "message": "Failed to parse state file."}}

    def _read_log_tail(self, max_lines: int = 8) -> list[str]:
        if not LOG_PATH.exists():
            return []
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-max_lines:]

    def _read_process(self) -> dict:
        with LOCK:
            running = PROCESS is not None and PROCESS.poll() is None
            pid = PROCESS.pid if PROCESS is not None else None
            exit_code = None if running or PROCESS is None else PROCESS.poll()
        return {"running": running, "pid": pid, "exit_code": exit_code, "log_tail": self._read_log_tail()}

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    host = "127.0.0.1"
    port = 8765
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Dashboard running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
