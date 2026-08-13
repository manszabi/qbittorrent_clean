@echo off
setlocal EnableExtensions
title qBittorrent takarito

rem ---------------------------------------------------------------------------
rem  qBittorrent takarito inditasa Windows alatt.
rem
rem  Alapbol csak MEGMUTATJA, mit torolne. A tenyleges torleshez ird at lent a
rem  TOROL sort erre:  set "TOROL=--torol"
rem
rem  Megjegyzes: ez a fajl szandekosan ekezet nelkuli, mert a cmd.exe a
rem  parancsfajlokat a rendszer kodlapjaval olvassa, es az ekezetes karakterek
rem  elronthatjak a vegrehajtast.
rem ---------------------------------------------------------------------------

cd /d "%~dp0"

rem --- Beallitasok ------------------------------------------------------------
set "URL=http://192.168.1.38:30024/"
set "FELHASZNALO=admin"

rem A vizsgalt konyvtarak. Az egymasba agyazottakat is sorold fel (a downloads
rem alatti rss mappat kulon), kulonben a szulo takaritasakor felesleges elemnek
rem latszana!
set "KONYVTARAK=--konyvtar \\192.168.1.38\downloads --konyvtar \\192.168.1.38\downloads\rss"

rem Ures = csak proba (nem torol). Torleshez:  set "TOROL=--torol"
set "TOROL="

rem Torles helyett kukaba mozgatas (biztonsagosabb). Peldaul:
rem set "KUKA=--kuka \\192.168.1.38\downloads\.kuka"
set "KUKA="

echo ============================================================
echo   qBittorrent takarito
echo ============================================================
echo.

rem --- Python kereses ---------------------------------------------------------
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [HIBA] Nem talalhato Python a rendszeren.
    echo.
    echo  Telepitsd a Python 3-at innen: https://www.python.org/downloads/
    echo  A telepitonel pipald be az "Add python.exe to PATH" opciot.
    goto :error
)

%PY% -c "import sys;sys.exit(0 if sys.version_info>=(3,7) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [HIBA] Tul regi Python verzio, legalabb 3.7 szukseges.
    goto :error
)

rem --- Inditas ----------------------------------------------------------------
%PY% qbt_cleanup.py --url "%URL%" --user "%FELHASZNALO%" %KONYVTARAK% %KUKA% %TOROL%
set "KOD=%ERRORLEVEL%"

echo.
if "%KOD%"=="0" (
    echo [OK]   Kesz.
) else (
    echo [FIGYELEM] A program %KOD% hibakoddal lepett ki - nezd at a fenti sorokat.
)

:error
echo.
pause
endlocal
