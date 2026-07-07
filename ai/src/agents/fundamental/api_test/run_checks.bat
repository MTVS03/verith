@echo off
setlocal
cd /d C:\verith\ai
chcp 65001 >nul

echo [1/4] Running fundamental tests...
C:\verith\.venv\Scripts\python.exe -m pytest src\agents\fundamental\tests -v
if errorlevel 1 exit /b 1

echo.
echo [2/4] Checking Qwen endpoint...
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.check_qwen
if errorlevel 1 exit /b 1

echo.
echo [3/4] Writing sample payload...
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.make_sample_payload
if errorlevel 1 exit /b 1

echo.
echo [4/4] Running 10-company batch...
C:\verith\.venv\Scripts\python.exe -m src.agents.fundamental.api_test.batch_demo
if errorlevel 1 exit /b 1

echo.
echo DONE. Summary:
echo C:\verith\ai\src\agents\fundamental\api_test\out\summary.md
endlocal
