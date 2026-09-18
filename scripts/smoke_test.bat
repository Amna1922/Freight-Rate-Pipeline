@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0.."
set "UVICORN_PID_FILE=%TEMP%\freight-rate-uvicorn.pid"
set "PYTHON=.venv\Scripts\python.exe"

echo Starting PostgreSQL...
docker compose up -d db
if errorlevel 1 goto :fail

echo Waiting for PostgreSQL readiness...
set /a attempts=0
:wait_db
docker compose exec -T db pg_isready -U freight -d freight >nul 2>&1
if not errorlevel 1 goto :db_ready
set /a attempts+=1
if !attempts! GEQ 60 (
  echo PostgreSQL did not become ready within 120 seconds.
  goto :fail
)
timeout /t 2 /nobreak >nul
goto :wait_db

:db_ready
echo PostgreSQL is ready.

echo Ensuring database tables exist...
%PYTHON% -c "import asyncio; from app.db import init_models; asyncio.run(init_models())"
if errorlevel 1 goto :fail

echo Running tests...
%PYTHON% -m pytest tests/ -v
if errorlevel 1 goto :fail

echo Starting Uvicorn...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath '%PYTHON%' -ArgumentList '-m','uvicorn','app.main:app','--port','8000' -WorkingDirectory '%CD%' -PassThru; Set-Content -LiteralPath '%UVICORN_PID_FILE%' -Value $p.Id"
if errorlevel 1 goto :fail
timeout /t 5 /nobreak >nul

echo Checking health endpoint...
curl.exe --fail --silent --show-error http://127.0.0.1:8000/health
if errorlevel 1 goto :fail
echo.

echo Checking freight-rate endpoint...
curl.exe --fail --silent --show-error "http://127.0.0.1:8000/v1/logistics/freight/rate?origin=CNSHA&destination=USLAX&mode=ocean&container=40HC"
if errorlevel 1 goto :fail
echo.

echo Smoke test passed.
call :cleanup
exit /b 0

:fail
echo Smoke test failed.
call :cleanup
exit /b 1

:cleanup
if exist "%UVICORN_PID_FILE%" (
  set /p UVICORN_PID=<"%UVICORN_PID_FILE%"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-Process -Id %UVICORN_PID% -ErrorAction SilentlyContinue; if ($p) { Stop-Process -Id $p.Id -Force }"
  del /q "%UVICORN_PID_FILE%" >nul 2>&1
)
docker compose down
exit /b 0
