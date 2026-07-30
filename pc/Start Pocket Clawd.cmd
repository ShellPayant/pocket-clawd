@echo off
REM Double-click this to start sending usage to your console.
REM
REM It uses the PowerShell pusher, so nothing needs installing on Windows.
REM Add -Hotspot if your console connects through a hotspot hosted by this PC
REM (that's the workaround for home WiFi that is 5GHz or WPA3 only).
REM
REM Close the window to stop.

title Pocket Clawd
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0clawd-pusher.ps1" %*
pause
