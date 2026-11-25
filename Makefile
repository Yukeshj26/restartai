.PHONY: install run test clean lint

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

test:
	pytest -v

lint:
	python -m compileall app tests

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
