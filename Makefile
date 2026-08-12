.PHONY: help format check test

RUFF := .venv/bin/ruff
PYTHON := .venv/bin/python3

help:
	@echo "make format  - ruff check --fix と ruff format でコードを整形"
	@echo "make check   - ruff check と ruff format --check で静的検査のみ実行(変更しない)"
	@echo "make test    - pytest でテストを実行"

format:
	$(RUFF) check --fix .
	$(RUFF) format .

check:
	$(RUFF) check .
	$(RUFF) format --check .

test:
	$(PYTHON) -m pytest
