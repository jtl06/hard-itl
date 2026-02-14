Goal: “Multi-agent HIL debugger for Pi UART using Logic Analyzer truth layer”

Interfaces you have now: “UART stream; LA capture exports (CSV) later; SSH to Pi”

NIM endpoint: http://<DGX_HOST>:8000/v1 and model name meta/llama-3.1-8b-instruct

Required deliverables:

runner/ that launches tests on Pi over SSH, captures UART logs

agents/ (planner/analyst/triage) that read an artifact bundle per run

runs/run_x/ evidence bundles (manifest, uart log, summary, triage)

a demo script: “fail → diagnose → tweak param → pass”

Hard constraints:

“Runner is the only module allowed to touch hardware”

“Everything must run with make demo”

“No cloud dependencies; use the local NIM endpoint”

Stretch goals:

LA export ingestion later (la_uart.csv)

simple dashboard (optional)