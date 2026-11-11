@echo off
rem Doble clic para iniciar StemDeck en modo dev (GPU), solo para este PC, y abrir
rem el navegador. Para el celular o la tablet: "Compartir StemDeck en la red.cmd".
rem La logica esta en scripts\windows\dev-start.ps1.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\dev-start.ps1"
if errorlevel 1 pause
