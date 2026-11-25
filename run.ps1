<#
.SYNOPSIS
    RestartAI convenience runner script for PowerShell / Windows.
.DESCRIPTION
    Commands:
      .\run.ps1 install   - Install dependencies from requirements.txt
      .\run.ps1 run       - Launch FastAPI app via uvicorn (port 8000, reload enabled)
      .\run.ps1 test      - Run all pytest unit and integration tests
      .\run.ps1 clean     - Clean cache files
#>
param(
    [Parameter(Position=0)]
    [ValidateSet("install", "run", "test", "golden", "clean")]
    [string]$Command = "run"
)

switch ($Command) {
    "install" {
        Write-Host "Installing dependencies..." -ForegroundColor Cyan
        pip install -r requirements-dev.txt
    }
    "run" {
        Write-Host "Starting RestartAI at http://127.0.0.1:8000..." -ForegroundColor Green
        uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
    }
    "test" {
        Write-Host "Running pytest test suite..." -ForegroundColor Cyan
        python -m pytest -v
    }
    "golden" {
        Write-Host "Running locked Golden Scenario regression test..." -ForegroundColor Magenta
        python -m pytest tests/integration/test_golden_scenario.py -v
    }
    "clean" {
        Write-Host "Cleaning cache directories..." -ForegroundColor Yellow
        Get-ChildItem -Path . -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -Path . -Recurse -Directory -Filter ".pytest_cache" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
}
