#!/usr/bin/env bash
# RestartAI Runner Script for Linux / macOS / WSL

set -e

COMMAND="${1:-run}"

case "$COMMAND" in
    install)
        echo "Installing dependencies..."
        python -m pip install -r requirements-dev.txt
        ;;
    run)
        echo "Starting RestartAI at http://127.0.0.1:8000..."
        uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
        ;;
    test)
        echo "Running pytest test suite..."
        python -m pytest -v
        ;;
    golden)
        echo "Running non-negotiable golden scenario test..."
        python -m pytest tests/integration/test_golden_scenario.py -v
        ;;
    clean)
        echo "Cleaning cache files..."
        find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
        ;;
    *)
        echo "Usage: ./run.sh [install|run|test|golden|clean]"
        exit 1
        ;;
esac
