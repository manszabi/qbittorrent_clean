@echo off
setlocal EnableExtensions
title qBittorrent takarito - parancssor

rem ---------------------------------------------------------------------------
rem  A takarito parancssoros inditasa (utemezett futtatashoz vagy ha nem kell
rem  az ablak). Alapbol csak MEGMUTATJA, mit torolne.
rem
rem  A tenyleges torleshez ird at lent a TOROL sort erre:
rem      set "TOROL=--torol --igen"
rem  Az --igen azert kell, mert utemezett futtataskor nincs, aki valaszoljon a
rem  megerosito kerdesre - enelkul a program inkabb leall.
rem
rem  A program itt is a sajat .venv kornyezeteben fut: ha meg nincs,
rem  a qbt_cleanup.py elso dolga elkesziteni.
rem
rem  Ekezetet szandekosan nem tartalmaz, es nincs benne tobbsoros zarojeles
rem  blokk sem - lasd a qbittorrent_clean.bat magyarazatat.
rem ---------------------------------------------------------------------------

cd /d "%~dp0"

rem --- Beallitasok ------------------------------------------------------------
set "URL=http://192.168.1.38:30024/"
set "FELHASZNALO=admin"

rem A jelszot ne ide ird: a program a QBT_PASSWORD kornyezeti valtozobol is
rem elfogadja, utemezett futtatasnal ott a helye.
rem     setx QBT_PASSWORD titkos

rem A vizsgalt konyvtarak. Az egymasba agyazottakat is sorold fel (a downloads
rem alatti rss mappat kulon), kulonben a szulo takaritasakor felesleges
rem elemnek latszana! Szokozos utvonalat tegyel idezojelbe:
rem     --konyvtar "\\192.168.1.38\le toltes"
set "KONYVTARAK=--konyvtar \\192.168.1.38\downloads --konyvtar \\192.168.1.38\downloads\rss"

rem Ures = csak proba (nem torol). Torleshez:  set "TOROL=--torol --igen"
set "TOROL="

rem Torles helyett kukaba mozgatas (biztonsagosabb). Peldaul:
rem set "KUKA=--kuka \\192.168.1.38\downloads\.kuka"
set "KUKA="

rem Biztonsagi hatar: ennel tobb elemnel inkabb alljon le. Kikapcsolas: ures.
set "HATAR=--max-torles 100"

rem A torlesekrol naplo keszul ide:
rem   %%APPDATA%%\qbittorrent_clean\naplo\torlesek.log
rem Mashova iranyitas: set "NAPLO=--naplo D:\naplok\torlesek.log"
rem Kikapcsolas:       set "NAPLO=--nincs-naplo"
set "NAPLO="

echo ============================================================
echo   qBittorrent takarito - parancssor   [indito v4]
echo ============================================================
echo.

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if defined PY goto :python_megvan
python -c "import sys" >nul 2>&1 && set "PY=python"
if defined PY goto :python_megvan
python3 -c "import sys" >nul 2>&1 && set "PY=python3"
if defined PY goto :python_megvan
echo [HIBA] Nem talalhato Python a rendszeren.
echo  Telepitsd innen: https://www.python.org/downloads/
echo  Ha szerinted mar telepitve van, kapcsold ki a Windows sajat python.exe
echo  hivatkozasat: Gepbeallitasok - Alkalmazasok - Specialis
echo  alkalmazasbeallitasok - Alkalmazasvegrehajtasi alnevek.
goto :hiba

:python_megvan
if not exist "qbt_cleanup.py" goto :nincs_program
%PY% qbt_cleanup.py --url "%URL%" --user "%FELHASZNALO%" %KONYVTARAK% %KUKA% %HATAR% %NAPLO% %TOROL%
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
