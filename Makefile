PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: venv install demo clean

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r requirements.txt

install: venv
	@echo "Environment ready"

demo: install
	PYTHONPATH=. $(PY) orchestrator.py --case uart_demo --runs 8 --mode mock

clean:
	rm -rf $(VENV)
	rm -rf runs/run_*
