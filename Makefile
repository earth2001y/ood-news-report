.PHONY: help format check

RUFF := .venv/bin/ruff

help:
	@echo "make format  - ruff check --fix と ruff format でコードを整形"
	@echo "make check   - ruff check と ruff format --check で静的検査のみ実行(変更しない)"

format:
	$(RUFF) check --fix .
	$(RUFF) format .

check:
	$(RUFF) check .
	$(RUFF) format --check .
