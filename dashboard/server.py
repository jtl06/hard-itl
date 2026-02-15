from __future__ import annotations

import json
import os
import signal
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
PROCESS_PAUSED = False
LOCK = threading.Lock()
GPU_CACHE: dict[str, object] = {
    "ts": 0.0,
    "has_good": False,
    "data": {"available": False, "message": "Waiting for GPU metrics..."},
    "last_good": {},
}
GPU_UNIFIED_MEM_NOTE = (
    "Unified memory expected on DGX Spark. nvidia-smi may not report dedicated VRAM usage.\n"
    "Use: top, htop, free"
)
DGX_SPARK_MAX_POWER_W = 140.0

HTML = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>EdgeCase Dashboard</title>
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
    .row .spacer-right { margin-left: auto; }
    .brand-tag {
      margin-left: auto;
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
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
        "debugger coordinator validator"
        "overall uart tracker"
        "overall system tracker";
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
    .card-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }
    .card-head h3 { margin: 0; }
    .card-head .meta {
      margin: 0;
      font-size: 11px;
      text-align: right;
      max-width: 68%;
      line-height: 1.25;
    }
    .meta { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      color: #d8e5ff;
      font-size: 12px;
      line-height: 1.4;
      max-height: none;
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
    .area-validator { grid-area: validator; }
    .area-overall { grid-area: overall; min-height: 180px; }
    .area-uart { grid-area: uart; }
    .area-tracker { grid-area: tracker; }
    .area-system { grid-area: system; }
    .area-load { min-height: 180px; }
    .area-uart, .area-tracker, .area-system { min-height: 140px; }
    .area-overall, .area-tracker, .area-planner, .area-coder, .area-debugger, .area-coordinator, .area-validator {
      display: flex;
      flex-direction: column;
    }
    #overall_output, #history {
      flex: 1;
      height: 100%;
      max-height: none;
    }
    #planner_fragment, #coder_fragment, #critic_fragment, #summarizer_fragment, #verifier_fragment {
      flex: 1;
      min-height: 0;
    }
    .chart-grid {
      display: grid;
      gap: 8px;
    }
    .confidence-bar-wrap {
      width: 100%;
      height: 10px;
      border-radius: 999px;
      border: 1px solid #21355a;
      background: linear-gradient(90deg, #ff6bb0 0%, #f6c453 55%, #33d17a 100%);
      overflow: hidden;
      margin: 0 0 8px 0;
      position: relative;
    }
    .confidence-bar-mask {
      position: absolute;
      right: 0;
      top: 0;
      bottom: 0;
      width: 100%;
      transition: width 220ms ease;
      background: #0a1528;
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
      background: linear-gradient(90deg, #33d17a 0%, #f6c453 55%, #ff6bb0 100%);
      overflow: hidden;
      position: relative;
    }
    .bar-fill {
      position: absolute;
      right: 0;
      top: 0;
      bottom: 0;
      width: 100%;
      transition: width 280ms ease;
      background: #0a1528;
    }
    .ok-text { color: var(--ok); font-weight: 700; }
    .err-text { color: var(--err); font-weight: 700; }
    #history .ok-text, #history .err-text { font-weight: 700; }
    @media (max-width: 1400px) {
      .dashboard-grid {
        grid-template-columns: repeat(2, minmax(280px, 1fr));
        grid-template-areas:
          "planner coder"
          "debugger coordinator"
          "load validator"
          "overall overall"
          "uart tracker"
          "system tracker";
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
          "validator"
          "overall"
          "uart"
          "tracker"
          "system";
      }
    }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <section class=\"top\">
      <div class=\"row\">
        <h2 style=\"margin:0\">EdgeCase Dashboard</h2>
        <span class=\"brand-tag\">jtl06</span>
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
        <label id=\"target_baud_wrap\">Target Baud
          <select id=\"target_baud\">
            <option value=\"9600\">9600</option>
            <option value=\"19200\">19200</option>
            <option value=\"38400\">38400</option>
            <option value=\"57600\">57600</option>
            <option value=\"74880\">74880</option>
            <option value=\"115200\" selected>115200</option>
            <option value=\"230400\">230400</option>
            <option value=\"460800\">460800</option>
            <option value=\"921600\">921600</option>
            <option value=\"1000000\">1000000</option>
            <option value=\"1500000\">1500000</option>
            <option value=\"2000000\">2000000</option>
          </select>
        </label>
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
          <select id=\"mode\"><option value=\"demo\">demo</option><option value=\"real\">real</option></select>
        </label>
        <label>Agent Mode
          <select id=\"agent_mode\">
            <option value=\"sequential\">sequential</option>
            <option value=\"parallel\">parallel</option>
          </select>
        </label>
        <label>NIM Model
          <select id=\"nim_model\">
            <option value=\"nvidia/nemotron-nano-9b-v2\">Nemotron Nano 9B</option>
            <option value=\"nvidia/nemotron-30b\">Nemotron 30B</option>
          </select>
        </label>
        <button id=\"start_btn\">Start Run</button>
        <button id=\"pause_btn\" type=\"button\">Pause</button>
        <button id=\"reset_btn\" class=\"spacer-right\" type=\"button\">Clear / Reset</button>
      </div>
      <div id=\"proc_info\" class=\"meta\"></div>
      <div id=\"overall_msg\" class=\"meta\"></div>
    </section>

    <section class=\"dashboard-grid\">
      <article class=\"card area-planner\">
        <div class=\"card-head\">
          <h3>Planner</h3>
          <div class=\"meta\">Plans next run params from evidence</div>
        </div>
        <div id=\"planner_status\" class=\"agent-status\">idle</div>
        <div id=\"planner_task\" class=\"meta\">Waiting for run.</div>
        <pre id=\"planner_fragment\">Evidence -> Hypothesis -> Next action will appear here.</pre>
      </article>
      <article class=\"card area-coder\">
        <div class=\"card-head\">
          <h3>Coder</h3>
          <div class=\"meta\">Suggests minimal instrumentation/fix ideas</div>
        </div>
        <div id=\"coder_status\" class=\"agent-status\">idle</div>
        <div id=\"coder_task\" class=\"meta\">Waiting for run.</div>
        <pre id=\"coder_fragment\">Evidence -> Hypothesis -> Next action will appear here.</pre>
      </article>
      <article class=\"card area-debugger\">
        <div class=\"card-head\">
          <h3>Debugger</h3>
          <div class=\"meta\">Checks feasibility and risk</div>
        </div>
        <div id=\"critic_status\" class=\"agent-status\">idle</div>
        <div id=\"critic_task\" class=\"meta\">Waiting for run.</div>
        <pre id=\"critic_fragment\">Evidence -> Hypothesis -> Next action will appear here.</pre>
      </article>
      <article class=\"card area-coordinator\">
        <div class=\"card-head\">
          <h3>Coordinator</h3>
          <div class=\"meta\">Merges outputs into one runbook</div>
        </div>
        <div id=\"summarizer_status\" class=\"agent-status\">idle</div>
        <div id=\"summarizer_task\" class=\"meta\">Waiting for run.</div>
        <pre id=\"summarizer_fragment\">Evidence -> Hypothesis -> Next action will appear here.</pre>
      </article>
      <article class=\"card area-load\">
        <div class=\"card-head\">
          <h3>Agent Load / Time</h3>
          <div class=\"meta\">Cumulative active-time split</div>
        </div>
        <div class=\"chart-grid\">
          <div class=\"chart-row\"><div>Planner</div><div class=\"bar-wrap\"><div id=\"bar_planner\" class=\"bar-fill\"></div></div><div id=\"pct_planner\">0.0%</div></div>
          <div class=\"chart-row\"><div>Coder</div><div class=\"bar-wrap\"><div id=\"bar_coder\" class=\"bar-fill\"></div></div><div id=\"pct_coder\">0.0%</div></div>
          <div class=\"chart-row\"><div>Debugger</div><div class=\"bar-wrap\"><div id=\"bar_critic\" class=\"bar-fill\"></div></div><div id=\"pct_critic\">0.0%</div></div>
          <div class=\"chart-row\"><div>Coordinator</div><div class=\"bar-wrap\"><div id=\"bar_summarizer\" class=\"bar-fill\"></div></div><div id=\"pct_summarizer\">0.0%</div></div>
          <div class=\"chart-row\"><div>Verifier</div><div class=\"bar-wrap\"><div id=\"bar_verifier\" class=\"bar-fill\"></div></div><div id=\"pct_verifier\">0.0%</div></div>
        </div>
        <div id=\"chart_meta\" class=\"meta\"></div>
      </article>
      <article class=\"card area-validator\">
        <div class=\"card-head\">
          <h3>Validator</h3>
          <div class=\"meta\">Confidence + coder correctness checks</div>
        </div>
        <div id=\"verifier_status\" class=\"agent-status\">idle</div>
        <div id=\"verifier_task\" class=\"meta\">Waiting for merged output.</div>
        <div class=\"meta\" id=\"confidence_label\">Confidence Trend: n/a</div>
        <div class=\"confidence-bar-wrap\"><div id=\"confidence_mask\" class=\"confidence-bar-mask\"></div></div>
        <pre id=\"verifier_fragment\">Evidence -> Hypothesis -> Next action will appear here.</pre>
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
      <article class=\"card area-system\">
        <div class=\"card-head\">
          <h3>System Utilization</h3>
          <div class=\"meta\">from <code>nvidia-smi</code></div>
        </div>
        <pre id=\"system_stats\">Waiting for GPU metrics...</pre>
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
      agent_mode: document.getElementById('agent_mode').value,
      nim_model: document.getElementById('nim_model').value,
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

async function resetRunState() {
  try {
    const res = await fetch('/api/reset', { method: 'POST' });
    const data = await res.json().catch(() => ({ok:false, message: 'Failed to parse reset response'}));
    const msg = data.message || `HTTP ${res.status}`;
    document.getElementById('proc_info').textContent = msg;
    if (!res.ok) {
      document.getElementById('overall_msg').textContent = msg;
    } else {
      await refreshOnce();
    }
  } catch (err) {
    document.getElementById('proc_info').textContent = `Reset failed: ${String(err)}`;
    document.getElementById('overall_msg').textContent = 'Unable to reach dashboard backend.';
  }
}

async function togglePauseRun() {
  try {
    const btn = document.getElementById('pause_btn');
    const wantPause = btn && btn.textContent !== 'Resume';
    const res = await fetch('/api/pause', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ pause: wantPause }),
    });
    const data = await res.json().catch(() => ({ok:false, message: 'Failed to parse pause response'}));
    const msg = data.message || `HTTP ${res.status}`;
    document.getElementById('proc_info').textContent = msg;
    if (!res.ok) {
      document.getElementById('overall_msg').textContent = msg;
    }
  } catch (err) {
    document.getElementById('proc_info').textContent = `Pause failed: ${String(err)}`;
  }
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = (value === undefined || value === null || value === '') ? '—' : value;
}

function setHtml(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
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
  const overallMsgEl = document.getElementById('overall_msg');
  if (overallMsgEl) {
    const msg = String(o.message || '').toLowerCase();
    overallMsgEl.classList.remove('ok-text', 'err-text');
    if (msg.includes('successful') || msg.includes('pass')) overallMsgEl.classList.add('ok-text');
    if (msg.includes('failed') || msg.includes('fail') || msg.includes('error')) overallMsgEl.classList.add('err-text');
  }
  const total = Number(o.runs_total || 0);
  const cur = Number(o.current_run || 0);
  const pct = total > 0 ? Math.max(0, Math.min(100, (cur / total) * 100)) : 0;
  document.getElementById('progress_bar').style.width = `${pct}%`;

  for (const name of ['planner','coder','critic','summarizer','verifier']) {
    const a = (state.agents || {})[name] || {};
    applyAgentStatus(`${name}_status`, a.status || 'idle');
      setText(`${name}_task`, a.task || 'Waiting for run.');
      setText(`${name}_fragment`, a.fragment || 'Evidence -> Hypothesis -> Next action will appear here.');
  }

  setText('overall_output', state.overall_output || 'No output yet. Start a run to populate summarizer output.');
  setText('latest_uart', (state.latest_uart || []).join('\\n') || 'No UART lines yet.');
  const historyRows = (state.history || []).map(r => {
    const status = String(r.status || '').toUpperCase();
    const statusClass = status === 'PASS' ? 'ok-text' : (status === 'FAIL' ? 'err-text' : '');
    const body = (String(r.guess_key || '') !== '')
      ? `run ${r.run}: <span class="${statusClass}">${status}</span>  guess=${r.guess_value}  target=${r.target_value}  errors=${r.error_count}  id=${r.run_id}`
      : `run ${r.run}: <span class="${statusClass}">${status}</span>  rate=${r.uart_rate}  buf=${r.buffer_size}  errors=${r.error_count}  id=${r.run_id}`;
    return body;
  });
  setHtml('history', historyRows.length ? historyRows.join('<br>') : 'No runs yet.');
  const procMsg = p.running
    ? `process: running (pid=${p.pid || 'n/a'})`
    : `process: idle` + (p.exit_code !== null && p.exit_code !== undefined ? ` (last exit=${p.exit_code})` : '');
  const logMsg = (p.log_tail || []).join('\\n');
  setText('proc_info', procMsg + (logMsg ? '\\n' + logMsg : ''));
  const pauseBtn = document.getElementById('pause_btn');
  if (pauseBtn) {
    pauseBtn.disabled = !p.running;
    pauseBtn.textContent = p.paused ? 'Resume' : 'Pause';
  }
  renderConfidenceSparkline(state);
  renderSystemStats(p.gpu || {});
  renderAgentChart(state);
}

function renderConfidenceSparkline(state) {
  const label = document.getElementById('confidence_label');
  const mask = document.getElementById('confidence_mask');
  if (!label || !mask) return;
  const stream = state.confidence_stream || [];
  const vals = stream.length
    ? stream.map(p => Number((p || {}).value))
    : (state.history || []).map(r => Number(r.confidence));
  const clean = vals
    .filter(v => Number.isFinite(v))
    .map(v => Math.max(0, Math.min(1, v)));
  if (!clean.length) {
    label.textContent = 'Confidence Trend: n/a';
    mask.style.width = '100%';
    return;
  }
  const latest = clean[clean.length - 1];
  label.textContent = `Confidence Trend: ${(latest * 100).toFixed(1)}%`;
  mask.style.width = `${(100 - latest * 100).toFixed(1)}%`;
}

function renderSystemStats(gpu) {
  const el = document.getElementById('system_stats');
  if (!el) return;
  const hasExisting = Boolean((el.textContent || '').trim()) &&
    !String(el.textContent || '').startsWith('Waiting for GPU metrics');

  // Ignore transient unavailable/N-A samples and keep last good values on screen.
  if (!gpu || gpu.available === false || Number(gpu.gpu_count || 0) !== 1) {
    if (!hasExisting) {
      setText('system_stats', gpu?.message || 'nvidia-smi unavailable');
    }
    return;
  }
  const unifiedUsed = Number(gpu.unified_mem_used_mb || gpu.vram_used_mb || 0);
  const unifiedTotal = Number(gpu.unified_mem_total_mb || gpu.vram_total_mb || 0);
  const vramPct = unifiedTotal > 0
    ? ((unifiedUsed / Math.max(1, unifiedTotal)) * 100).toFixed(1)
    : '0.0';
  const lines = [
    `GPUs: ${gpu.gpu_count ?? 'n/a'}`,
    `Compute Util: ${Number(gpu.util_percent || 0).toFixed(1)}%`,
    `Unified Mem: ${Math.round(unifiedUsed)} / ${Math.round(unifiedTotal)} MB (${vramPct}%)`,
    `Power: ${Number(gpu.power_w || 0).toFixed(1)} / ${Number(gpu.power_limit_w || 0).toFixed(1)} W`,
    `Temp: ${Number(gpu.temp_c || 0).toFixed(1)} C`,
  ];
  if (gpu.sample_status === 'stale') {
    lines.push(`Sample: stale (${gpu.message || 'using last good reading'})`);
  } else {
    lines.push('Sample: fresh');
  }
  setText('system_stats', lines.join('\\n'));
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
  const roles = ['planner', 'coder', 'critic', 'summarizer', 'verifier'];
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
    if (bar) bar.style.width = `${(100 - pct).toFixed(1)}%`;
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
document.getElementById('pause_btn').addEventListener('click', togglePauseRun);
document.getElementById('reset_btn').addEventListener('click', resetRunState);
document.getElementById('case').addEventListener('change', updateTargetVisibility);
refreshOnce();
initSSE();
setInterval(refreshOnce, 450);
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
        if parsed.path == "/api/pause":
            self._handle_pause()
            return
        if parsed.path == "/api/reset":
            self._handle_reset()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_start(self) -> None:
        try:
            content_len = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_len) if content_len else b"{}"
            payload = json.loads(body.decode("utf-8") or "{}")

            case = str(payload.get("case", "uart_demo"))
            runs = int(payload.get("runs", 8))
            requested_mode = str(payload.get("mode", "demo"))
            mode = "mock" if requested_mode == "demo" else requested_mode
            target_baud = int(payload.get("target_baud", 0))
            target_frame = str(payload.get("target_frame", ""))
            target_parity = str(payload.get("target_parity", ""))
            target_magic = str(payload.get("target_magic", ""))
            agent_mode = str(payload.get("agent_mode", "sequential"))
            nim_model = str(payload.get("nim_model", "")).strip()

            with LOCK:
                global PROCESS
                global PROCESS_PAUSED
                if PROCESS is not None and PROCESS.poll() is None:
                    self._send_json({"ok": False, "message": "Run already in progress."}, code=409)
                    return

                run_env = dict(os.environ)
                if mode == "real":
                    if not run_env.get("PICO_SDK_PATH"):
                        default_sdk = Path.home() / "pico-sdk"
                        if default_sdk.exists():
                            run_env["PICO_SDK_PATH"] = str(default_sdk)
                    if not run_env.get("PICO_SDK_PATH"):
                        self._send_json(
                            {
                                "ok": False,
                                "message": (
                                    "Real mode requires PICO_SDK_PATH for real firmware builds. "
                                    "Export PICO_SDK_PATH (or install at ~/pico-sdk) and restart make gui."
                                ),
                            },
                            code=400,
                        )
                        return

                init_state = {
                    "overall": {
                        "status": "running",
                        "message": f"Launching run: case={case} mode={requested_mode} agent_mode={agent_mode} runs={runs}",
                        "case_id": case,
                        "mode": requested_mode,
                        "runs_total": runs,
                        "current_run": 0,
                        "updated_at": "",
                    },
                    "agents": {
                        "planner": {"status": "idle", "task": "Waiting", "fragment": ""},
                        "coder": {"status": "idle", "task": "Waiting", "fragment": ""},
                        "critic": {"status": "idle", "task": "Waiting", "fragment": ""},
                        "summarizer": {"status": "idle", "task": "Waiting", "fragment": ""},
                        "verifier": {"status": "idle", "task": "Waiting", "fragment": ""},
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
                    "--nim-mode",
                    agent_mode,
                    "--nim-model",
                    nim_model,
                    "--state-file",
                    str(STATE_PATH),
                    "--live-uart",
                    "--trace",
                ]
                logf = LOG_PATH.open("a", encoding="utf-8")
                PROCESS = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT),
                    env=run_env,
                    stdout=logf,
                    stderr=logf,
                    text=True,
                )
                PROCESS_PAUSED = False

            self._send_json({"ok": True, "message": f"Started {requested_mode} run for case={case} runs={runs}."})
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
                    "verifier": {"status": "idle", "task": "Waiting", "fragment": ""},
                },
                "latest_uart": [],
                "last_analysis": {},
                "overall_output": "",
                "history": [],
            }
            STATE_PATH.write_text(json.dumps(fail_state, indent=2), encoding="utf-8")
            self._send_json({"ok": False, "message": f"Failed to start run: {exc}"}, code=500)

    def _handle_pause(self) -> None:
        try:
            content_len = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_len) if content_len else b"{}"
            payload = json.loads(body.decode("utf-8") or "{}")
            want_pause = bool(payload.get("pause", True))
        except Exception:
            want_pause = True

        with LOCK:
            global PROCESS_PAUSED
            running = PROCESS is not None and PROCESS.poll() is None
            if not running or PROCESS is None:
                self._send_json({"ok": False, "message": "No active run to pause/resume."}, code=409)
                return
            try:
                if want_pause:
                    os.kill(PROCESS.pid, signal.SIGSTOP)
                    PROCESS_PAUSED = True
                    self._send_json({"ok": True, "message": f"Paused run (pid={PROCESS.pid})."})
                else:
                    os.kill(PROCESS.pid, signal.SIGCONT)
                    PROCESS_PAUSED = False
                    self._send_json({"ok": True, "message": f"Resumed run (pid={PROCESS.pid})."})
            except Exception as exc:
                self._send_json({"ok": False, "message": f"Pause/resume failed: {exc}"}, code=500)

    def _handle_reset(self) -> None:
        with LOCK:
            global PROCESS_PAUSED
            running = PROCESS is not None and PROCESS.poll() is None
            if running:
                self._send_json({"ok": False, "message": "Cannot reset while a run is in progress."}, code=409)
                return
            PROCESS_PAUSED = False
        reset_state = {
            "overall": {
                "status": "idle",
                "message": "State cleared. Ready for next run.",
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
                "verifier": {"status": "idle", "task": "Waiting", "fragment": ""},
            },
            "agent_metrics": {
                "planner": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": time.time()},
                "coder": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": time.time()},
                "critic": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": time.time()},
                "summarizer": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": time.time()},
                "verifier": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": time.time()},
            },
            "latest_uart": [],
            "last_analysis": {},
            "overall_output": "",
            "history": [],
        }
        STATE_PATH.write_text(json.dumps(reset_state, indent=2), encoding="utf-8")
        LOG_PATH.write_text("", encoding="utf-8")
        self._send_json({"ok": True, "message": "Dashboard state reset."})

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
                time.sleep(0.45)
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
                    "verifier": {"status": "idle", "task": "", "fragment": ""},
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
            global PROCESS_PAUSED
            running = PROCESS is not None and PROCESS.poll() is None
            pid = PROCESS.pid if PROCESS is not None else None
            exit_code = None if running or PROCESS is None else PROCESS.poll()
            paused = bool(PROCESS_PAUSED) if running else False
            if not running:
                PROCESS_PAUSED = False
        return {
            "running": running,
            "paused": paused,
            "pid": pid,
            "exit_code": exit_code,
            "log_tail": self._read_log_tail(),
            "gpu": self._read_gpu_stats(),
        }

    def _read_gpu_stats(self) -> dict:
        now = time.time()
        cached_ts = float(GPU_CACHE.get("ts", 0.0))
        if now - cached_ts < 2.0:
            return dict(GPU_CACHE.get("data", {}))

        def _stale_from_last_good(reason: str) -> dict | None:
            last_good = GPU_CACHE.get("last_good", {})
            if not isinstance(last_good, dict) or not last_good:
                return None
            stale = dict(last_good)
            stale["sample_status"] = "stale"
            stale["message"] = reason
            return stale

        cmd = [
            "nvidia-smi",
            "--query-gpu=index,utilization.gpu,memory.used,memory.total,power.draw,power.limit,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=1.2)
        except FileNotFoundError:
            stale = _stale_from_last_good(f"nvidia-smi not found\n{GPU_UNIFIED_MEM_NOTE}")
            if stale is not None:
                GPU_CACHE["ts"] = now
                GPU_CACHE["data"] = stale
                return stale
            data = {"available": False, "message": f"nvidia-smi not found\n{GPU_UNIFIED_MEM_NOTE}"}
            GPU_CACHE["ts"] = now
            GPU_CACHE["data"] = data
            return data
        except Exception as exc:
            stale = _stale_from_last_good(f"nvidia-smi failed: {exc}")
            if stale is not None:
                GPU_CACHE["ts"] = now
                GPU_CACHE["data"] = stale
                return stale
            data = {"available": False, "message": f"nvidia-smi failed: {exc}\n{GPU_UNIFIED_MEM_NOTE}"}
            GPU_CACHE["ts"] = now
            GPU_CACHE["data"] = data
            return data

        if cp.returncode != 0:
            detail = cp.stderr.strip() or cp.stdout.strip() or f"exit {cp.returncode}"
            stale = _stale_from_last_good(f"nvidia-smi error: {detail}")
            if stale is not None:
                GPU_CACHE["ts"] = now
                GPU_CACHE["data"] = stale
                return stale
            data = {"available": False, "message": f"nvidia-smi error: {detail}\n{GPU_UNIFIED_MEM_NOTE}"}
            GPU_CACHE["ts"] = now
            GPU_CACHE["data"] = data
            return data

        rows = [ln.strip() for ln in cp.stdout.splitlines() if ln.strip()]
        if not rows:
            stale = _stale_from_last_good("nvidia-smi returned no GPU rows")
            if stale is not None:
                GPU_CACHE["ts"] = now
                GPU_CACHE["data"] = stale
                return stale
            data = {"available": False, "message": "nvidia-smi returned no GPU rows"}
            GPU_CACHE["ts"] = now
            GPU_CACHE["data"] = data
            return data

        def _f(text: str) -> float:
            text = text.strip()
            if not text or text.upper() == "N/A":
                return 0.0
            try:
                return float(text)
            except ValueError:
                return 0.0

        per_gpu: list[dict] = []
        util_total = 0.0
        mem_used_total = 0.0
        mem_total_total = 0.0
        power_total = 0.0
        power_limit_total = 0.0
        temp_total = 0.0
        for row in rows:
            parts = [p.strip() for p in row.split(",")]
            if len(parts) < 7:
                continue
            idx = int(_f(parts[0]))
            util = _f(parts[1])
            mem_used = _f(parts[2])
            mem_total = _f(parts[3])
            power = _f(parts[4])
            power_limit = _f(parts[5])
            temp = _f(parts[6])
            per_gpu.append(
                {
                    "index": idx,
                    "util": util,
                    "mem_used": int(mem_used),
                    "mem_total": int(mem_total),
                    "power": power,
                    "power_limit": power_limit,
                    "temp": temp,
                }
            )
            util_total += util
            mem_used_total += mem_used
            mem_total_total += mem_total
            power_total += power
            power_limit_total += power_limit
            temp_total += temp

        gpu_count = len(per_gpu)
        if gpu_count == 0:
            data = {"available": False, "message": "unable to parse nvidia-smi output"}
            GPU_CACHE["ts"] = now
            GPU_CACHE["data"] = data
            return data
        if gpu_count != 1:
            stale = _stale_from_last_good(f"ignored sample: expected 1 GPU, got {gpu_count}")
            if stale is not None:
                GPU_CACHE["ts"] = now
                GPU_CACHE["data"] = stale
                return stale
            data = {"available": False, "message": f"ignored sample: expected 1 GPU, got {gpu_count}"}
            GPU_CACHE["ts"] = now
            GPU_CACHE["data"] = data
            return data
        unified_used_mb, unified_total_mb = self._read_unified_mem_mb()
        data = {
            "available": True,
            "gpu_count": gpu_count,
            "util_percent": util_total / gpu_count,
            "vram_used_mb": int(mem_used_total),
            "vram_total_mb": int(mem_total_total),
            "unified_mem_used_mb": int(unified_used_mb),
            "unified_mem_total_mb": int(unified_total_mb),
            "power_w": power_total,
            "power_limit_w": DGX_SPARK_MAX_POWER_W,
            "temp_c": temp_total / gpu_count,
            "per_gpu": per_gpu,
            "sample_status": "fresh",
            "message": "",
        }
        GPU_CACHE["has_good"] = True
        GPU_CACHE["last_good"] = dict(data)
        GPU_CACHE["ts"] = now
        GPU_CACHE["data"] = data
        return data

    @staticmethod
    def _read_unified_mem_mb() -> tuple[int, int]:
        total_kb = 0
        avail_kb = 0
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        total_kb = int(parts[1])
                elif line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        avail_kb = int(parts[1])
            if total_kb <= 0:
                return 0, 0
            used_kb = max(0, total_kb - avail_kb)
            return used_kb // 1024, total_kb // 1024
        except Exception:
            return 0, 0

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
