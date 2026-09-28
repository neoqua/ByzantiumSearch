@echo off
rem Double-click friendly wrapper: runs start.ps1 without changing the system execution policy.
rem Pass-through args: start.cmd -HostMode   /   start.cmd -NoBuild
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
