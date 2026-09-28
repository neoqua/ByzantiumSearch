@echo off
rem Double-click friendly wrapper: runs stop.ps1 without changing the system execution policy.
rem Pass-through args: stop.cmd -Volumes
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
if errorlevel 1 pause
