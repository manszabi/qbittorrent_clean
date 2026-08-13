@echo off
setlocal EnableExtensions
title qBittorrent takarito - parancssor

rem ---------------------------------------------------------------------------
rem  A takarito parancssoros inditasa (utemezett futtatashoz vagy ha nem kell
rem  az ablak). Alapbol csak MEGMUTATJA, mit torolne.
rem
rem  A tenyleges torleshez ird at lent a TOROL sort erre:
rem      set "TOROL=--torol"
rem
rem  Ekezetet szandekosan nem tartalmaz, es nincs benne tobbsoros zarojeles
rem  blokk sem - lasd a qbittorrent_clean.bat magyarazatat.
rem ---------------------------------------------------------------------------

cd /d "%~dp0"

rem --- Beallitasok ------------------------------------------------------------
set "URL=http://192.168.1.38:30024/"
set "FELHASZNALO=admin"

rem A vizsgalt konyvtarak. Az egymasba agyazottakat is sorold fel (a downloads
rem alatti rss mappat kulon), kulonben a szulo takaritasakor felesleges
rem elemnek latszana!
set "KONYVTARAK=--konyvtar \\192.168.1.38\downloads --konyvtar \\192.168.1.38\downloads\rss"

rem Ures = csak proba (nem torol). Torleshez:  set "TOROL=--torol"
set "TOROL="

rem Torles helyett kukaba mozgatas (biztonsagosabb). Peldaul:
rem set "KUKA=--kuka \\192.168.1.38\downloads\.kuka"
set "KUKA="

echo ============================================================
echo   qBittorrent takarito - parancssor   [indito v2]
echo ============================================================
echo.

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if defined PY goto :python_megvan
python -c "import sys" >nul 2>&1 && set "PY=python"
if defined PY goto :python_megvan
echo [HIBA] Nem talalhato Python a rendszeren.
echo  Telepitsd innen: https://www.python.org/downloads/
goto :hiba

:python_megvan
if not exist "qbt_cleanup.py" goto :nincs_program
%PY% qbt_cleanup.py --url "%URL%" --user "%FELHASZNALO%" %KONYVTARAK% %KUKA% %TOROL%
if errorlevel 1 goto :hiba
echo.
echo [OK]   Kesz.
echo.
pause
endlocal
exit /b 0

:nincs_program
echo [HIBA] Nem talalom a qbt_cleanup.py fajlt ebben a mappaban:
echo        %CD%
goto :hiba

:hiba
echo.
echo [FIGYELEM] Nezd at a fenti sorokat.
echo.
pause
endlocal
exit /b 1
