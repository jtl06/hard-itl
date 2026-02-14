PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: venv install demo mock real demo-live demo-real nim-smoke clean

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r requirements.txt

install: venv
	@echo "Environment ready"

demo: install
	PYTHONPATH=. $(PY) orchestrator.py --case uart_demo --runs 8 --mode mock

mock: demo

real: demo-real

nim-smoke: install
	tools/smoke_concurrency.sh

demo-live: install
	PYTHONPATH=. $(PY) orchestrator.py --case uart_demo --runs 8 --mode mock --live --show-agent-fragments

demo-real: install
	PYTHONPATH=. $(PY) orchestrator.py --case uart_demo --runs 8 --mode real --live --show-agent-fragments

clean:
	rm -rf $(VENV)
	rm -rf runs/run_*
