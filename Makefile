PYTHON ?= python3
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: venv install demo clean

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r requirements.txt

install: venv
	@echo "Local environment ready."

demo: install
	PYTHONPATH=. $(PY) scripts/demo.py

clean:
	rm -rf $(VENV)
	rm -rf runs/run_*
