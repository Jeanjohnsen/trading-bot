$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

. .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir backend --reload
