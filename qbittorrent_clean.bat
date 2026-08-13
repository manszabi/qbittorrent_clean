@echo off
setlocal EnableExtensions
title qBittorrent takarito

rem ---------------------------------------------------------------------------
rem  qBittorrent takarito - inditas Windows alatt.
rem
rem  Ez a fajl szandekosan nagyon egyszeru: megkeresi a Pythont, es atadja a
rem  vezerlest az indit.py-nak. Minden fuggoseg-ellenorzes ott van, mert azt
rem  lehet tesztelni - a cmd.exe-t nem.
rem
rem  Ezert nincs benne tobbsoros zarojeles blokk sem: ha a fajl valahogy megis
rem  LF sorveggel keruline a gepre, a cmd akkor sem tud rajta elcsuszni.
rem
rem  Ekezetet sem tartalmaz: a cmd a rendszer kodlapjaval olvas.
rem ---------------------------------------------------------------------------

cd /d "%~dp0"

echo ============================================================
echo   qBittorrent takarito   [indito v2]
echo ============================================================
echo.

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if defined PY goto :python_megvan
python -c "import sys" >nul 2>&1 && set "PY=python"
if defined PY goto :python_megvan
goto :nincs_python

:python_megvan
if not exist "indit.py" goto :nincs_indito
%PY% indit.py
if errorlevel 1 goto :hiba
endlocal
exit /b 0

:nincs_python
echo [HIBA] Nem talalhato Python a rendszeren.
echo.
echo  Telepitsd innen: https://www.python.org/downloads/
echo  A telepitonel pipald be az "Add python.exe to PATH" opciot,
echo  valamint a "tcl/tk and IDLE" komponenst.
goto :hiba

:nincs_indito
echo [HIBA] Nem talalom az indit.py fajlt ebben a mappaban:
echo        %CD%
echo  Ugy tunik, hianyos a kicsomagolt mappa.
goto :hiba

:hiba
echo.
pause
endlocal
exit /b 1
