@echo off
rem Doble clic para iniciar StemDeck en modo dev (GPU) compartido en la red local:
rem el celular o la tablet en la misma Wi-Fi entran por la direccion https que
rem muestra esta ventana (y el codigo QR que se abre). La logica esta en
rem scripts\windows\dev-start.ps1 (-Lan).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\dev-start.ps1" -Lan
if errorlevel 1 pause
