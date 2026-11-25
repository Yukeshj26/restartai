.PHONY: install run test golden clean docker-build docker-run

install:
	pip install -r requirements-dev.txt

run:
	uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

test:
	python -m pytest -v

golden:
	python -m pytest tests/integration/test_golden_scenario.py -v

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

docker-build:
	docker build -t restartai:latest .

docker-run:
	docker run -p 8000:8000 restartai:latest
