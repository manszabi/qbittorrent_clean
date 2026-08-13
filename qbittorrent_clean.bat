@echo off
setlocal EnableExtensions
title qBittorrent takarito

rem ---------------------------------------------------------------------------
rem  qBittorrent takarito - inditas Windows alatt.
rem
rem  Ellenorzi a Pythont es a szukseges modulokat, a hianyzo csomagokat
rem  telepiti, majd elinditja a grafikus feluletet (qbt_gui.py).
rem
rem  Megjegyzes: ez a fajl szandekosan ekezet nelkuli, mert a cmd.exe a
rem  parancsfajlokat a rendszer kodlapjaval olvassa, es az ekezetes karakterek
rem  elronthatjak a vegrehajtast.
rem ---------------------------------------------------------------------------

cd /d "%~dp0"

echo ============================================================
echo   qBittorrent takarito
echo ============================================================
echo.

rem --- 1. Python kereses (eloszor a "py" launcher, aztan a "python") ---------
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [HIBA] Nem talalhato Python a rendszeren.
    echo.
    echo  Telepitsd a Python 3-at innen: https://www.python.org/downloads/
    echo  A telepitonel pipald be az "Add python.exe to PATH" opciot,
    echo  valamint a "tcl/tk and IDLE" komponenst.
    goto :error
)

set "PYVER=ismeretlen"
for /f "delims=" %%v in ('%PY% -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%v"
echo [OK]   Python megtalalva: %PY%  (verzio: %PYVER%)

rem --- 2. Verzio ellenorzes (3.7 vagy ujabb kell) ----------------------------
%PY% -c "import sys;sys.exit(0 if sys.version_info>=(3,7) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [HIBA] Tul regi Python verzio: %PYVER%
    echo        Legalabb Python 3.7 szukseges.
    goto :error
)

rem --- 3. A program altal hasznalt modulok ----------------------------------
rem  Ezek mind a Python resze, kulon telepites nelkul. Ha megis hianyzik
rem  valamelyik, az szinte biztosan csonka Python telepites.
%PY% -c "import json,ssl,shutil,urllib.request,http.cookiejar" >nul 2>&1
if errorlevel 1 (
    echo [HIBA] Hianyzik a Python egy alap modulja (json / ssl / urllib).
    echo        Telepitsd ujra a Pythont a hivatalos telepitovel.
    goto :error
)
echo [OK]   Alap modulok megvannak.

rem --- 4. tkinter (a grafikus felulethez kell, pip-pel NEM telepitheto) ------
%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo [HIBA] Hianyzik a tkinter modul - enelkul nincs grafikus felulet.
    echo.
    echo  Inditsd el a Python telepitot ujra ("Modify"), es pipald be a
    echo  "tcl/tk and IDLE" komponenst. Addig is hasznalhato a parancssoros
    echo  valtozat:  qbt_takaritas.bat
    goto :error
)
echo [OK]   tkinter megvan.

rem --- 5. Kulso csomagok (requirements.txt) ---------------------------------
rem  A program szandekosan nem hasznal kulso csomagot, ezert a
rem  requirements.txt csak megjegyzeseket tartalmaz. Ha egyszer mégis kerul
rem  bele valodi sor, ez a resz telepiti.
if not exist requirements.txt goto :nincs_csomag
%PY% -c "import sys,pathlib;sorok=[s.strip() for s in pathlib.Path('requirements.txt').read_text(encoding='utf-8').splitlines()];sys.exit(1 if any(s and not s.startswith('#') for s in sorok) else 0)" >nul 2>&1
if not errorlevel 1 goto :nincs_csomag

echo [..]   Kulso csomagok ellenorzese / telepitese...
%PY% -m pip install -r requirements.txt >nul 2>&1
if not errorlevel 1 goto :csomag_kesz
echo [..]   Ujraprobalom felhasznaloi modban...
%PY% -m pip install --user -r requirements.txt
if not errorlevel 1 goto :csomag_kesz
echo [HIBA] Nem sikerult telepiteni a szukseges csomagokat.
goto :error

:csomag_kesz
echo [OK]   Csomagok rendben.
goto :program_ellenorzes

:nincs_csomag
echo [OK]   Kulso csomag nem szukseges.

:program_ellenorzes

rem --- 6. A program megletenek ellenorzese ----------------------------------
if not exist qbt_gui.py (
    echo [HIBA] Nem talalom a qbt_gui.py fajlt ebben a mappaban:
    echo        %CD%
    goto :error
)

rem --- 7. Inditas -----------------------------------------------------------
echo.
echo Indul a grafikus felulet...
echo.
%PY% qbt_gui.py
set "KOD=%ERRORLEVEL%"
if not "%KOD%"=="0" (
    echo.
    echo [FIGYELEM] A program %KOD% hibakoddal lepett ki.
    goto :error
)
endlocal
exit /b 0

:error
echo.
pause
endlocal
exit /b 1
