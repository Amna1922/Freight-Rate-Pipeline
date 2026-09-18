 
#!/usr/bin/env sh
set -eu
exec uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
