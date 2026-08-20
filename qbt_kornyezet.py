#!/usr/bin/env python3
"""A program sajat Python kornyezete (.venv).

A program a sajat mappajaban keszit egy virtualis kornyezetet (.venv), es
MINDIG abban fut - Windowson es Linuxon egyarant. Igy a takarito ugyanazt a
Pythont es ugyanazokat a csomagokat hasznalja minden gepen, es nem tud
elromlani attol, hogy a rendszer Pythonjaban valaki mast telepit vagy torol.

Hogyan mukodik: barmelyik belepesi pontot inditjak (indit.py, qbt_gui.py,
qbt_cleanup.py), az elso dolga megnezni, hogy a .venv ertelmezojevel fut-e.
Ha nem, letrehozza a kornyezetet (ha meg nincs), es ugyanazt a szkriptet
ujrainditja a .venv Pythonjaval, valtozatlan parancssorral. A gyerekfolyamat
kimenete es hibakodja a hivoe marad, tehat kivulrol semmi nem valtozik.

Miert alfolyamat, es nem os.execv? Windowson az execv nem lecsereli, hanem
uj folyamatot indit es a regit kilepteti: a hivo parancsfajl ilyenkor azonnal
visszakapna a vezerlest (es rogton kiirna a "kesz" uzenetet), mikozben a
program meg futna. Az alfolyamat mindket rendszeren ugyanugy viselkedik.

Ha a kornyezet nem hozhato letre (nincs irasi jog a mappara, vagy a
disztribucio kulon csomagba tette a venv modult), a program nem all le: szol
egy figyelmeztetest, es a rendszer Pythonjaval megy tovabb.

Kikapcsolas: QBT_VENV_KIHAGY=1 kornyezeti valtozo. Ez kell a fejlesztoi
munkahoz es a CI-hez, ahol a futtato kornyezet mar adott.

A kimenete szandekosan ekezet nelkuli: a Windows parancssor a rendszer
kodlapjaval ir, ott az ekezetes betuk konnyen szemette valnak.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

# A kornyezet neve es helye: a program mappajaban, a web_downloader-rel
# azonos modon.
VENV_NEV: Final = ".venv"

# "Ne hasznalj sajat kornyezetet" - a fejlesztoknek es a CI-nek.
KIHAGYAS: Final = "QBT_VENV_KIHAGY"
# Ezt mi magunk tesszuk a gyerekfolyamat kornyezetebe: ha barmi miatt megsem
# a .venv-bol indulna, akkor sem indit ujra egy harmadikat (vegtelen lanc).
ATVALTVA: Final = "QBT_VENV_ATVALTVA"

# A megszakitas (Ctrl+C) szokasos kilepesi kodja.
MEGSZAKITVA: Final = 130

GYOKER: Final = Path(__file__).resolve().parent

# Ezeket a valaszokat vesszuk "nem"-nek a kornyezeti valtozoban.
_NEMEK: Final = frozenset({"", "0", "nem", "false", "no", "off"})


def _kiir(uzenet: str) -> None:
    """Alapertelmezett uzenetkiiras: a hiba-kimenetre.

    Azert oda, mert a parancssoros valtozat kimenete (a felesleges fajlok
    listaja) tovabb szokott menni egy fajlba vagy egy masik programba - oda
    nem valo bele az inditasrol szolo fecseges."""
    print(uzenet, file=sys.stderr, flush=True)


def _igaz(ertek: str | None) -> bool:
    return bool(ertek) and str(ertek).strip().lower() not in _NEMEK


def kihagyando() -> bool:
    """Kertek-e, hogy ne hasznaljunk sajat kornyezetet."""
    return _igaz(os.environ.get(KIHAGYAS)) or _igaz(os.environ.get(ATVALTVA))


def venv_konyvtar(gyoker: Path | None = None) -> Path:
    """A virtualis kornyezet mappaja (alapbol a program melle)."""
    return (gyoker or GYOKER) / VENV_NEV


def venv_python(gyoker: Path | None = None,
                windows: bool | None = None) -> Path:
    """A kornyezet ertelmezojenek utvonala.

    A `windows` kapcsolo csak a teszteknek kell: enelkul a masik rendszer
    elrendezeset semelyik gepen nem lehetne ellenorizni."""
    hova = venv_konyvtar(gyoker)
    nt = sys.platform == "win32" if windows is None else windows
    return hova / "Scripts" / "python.exe" if nt else hova / "bin" / "python"


def _azonos(egyik: Path, masik: Path) -> bool:
    """Ugyanaz a konyvtar-e. Elsore a fajlrendszert kerdezzuk (ez atlat a
    symlinkeken es a Windows rovid nevein is), es csak ha valamelyik ut nem
    letezik, akkor hasonlitunk szoveget."""
    try:
        return os.path.samefile(egyik, masik)
    except OSError:
        return (os.path.normcase(os.path.normpath(str(egyik)))
                == os.path.normcase(os.path.normpath(str(masik))))


def sajat_kornyezetben(gyoker: Path | None = None) -> bool:
    """Igaz, ha a most futo ertelmezo mar a program .venv-jebol jon."""
    return _azonos(Path(sys.prefix), venv_konyvtar(gyoker))


def _alap_python_megvan(hova: Path) -> bool:
    """Megvan-e meg az a Python, amibol a kornyezet keszult.

    Linuxon a .venv/bin/python egy symlink az alap Pythonra: ha azt
    frissitettek vagy eltavolitottak, a link elszakad, es azt az is_file() maga
    megmondja. Windowson viszont a python.exe egy masolat, ami a pyvenv.cfg
    "home" sorabol talalja meg a Python konyvtarat - ha az mar nincs meg, a
    hiba csak inditaskor, ertelmetlen uzenettel derulne ki (ez a klasszikus
    "frissitettem a Pythont, es azota nem indul" eset). Ezert inkabb
    beleolvasunk a fajlba: ez nem folyamatinditas, csak egy par soros fajl.

    Bizonytalan esetben (nincs fajl, nincs "home" sor) igent mondunk: a
    kornyezet eldobasa dragabb tevedes lenne, mint egy felesleges proba."""
    try:
        sorok = (hova / "pyvenv.cfg").read_text(encoding="utf-8",
                                                errors="replace").splitlines()
    except OSError:
        return True
    for sor in sorok:
        kulcs, egyenlo, ertek = sor.partition("=")
        if egyenlo and kulcs.strip().lower() == "home":
            return Path(ertek.strip()).is_dir()
    return True


def van_sajat_kornyezet(gyoker: Path | None = None) -> bool:
    """Letezik-e (es ep-e) a kesz kornyezet."""
    return (venv_python(gyoker).is_file()
            and _alap_python_megvan(venv_konyvtar(gyoker)))


def _futtat(parancs: Sequence[str]) -> bool:
    try:
        return subprocess.call(list(parancs)) == 0
    except OSError:
        return False


def letrehozas(gyoker: Path | None = None,
               kiir: Callable[[str], None] = _kiir) -> Path | None:
    """A kornyezet letrehozasa, ha meg nincs. Vissza: az ertelmezo utja.

    Ha a kornyezet mar all, azonnal visszater - ez egy fajlrendszer-kerdes,
    nem indit alfolyamatot, tehat minden tovabbi inditas ingyen van.

    Ha a `python -m venv` nem megy (a Debian-fele disztribuciok kulon
    csomagba teszik a pip-et), pip nelkul is megprobaljuk: a takaritonak nincs
    kulso fuggosege, annak egy pip nelkuli kornyezet is tokeletes."""
    utvonal = venv_python(gyoker)
    hova = venv_konyvtar(gyoker)
    if utvonal.is_file() and _alap_python_megvan(hova):
        return utvonal
    if not sys.executable:  # beagyazott Python: nincs mivel letrehozni
        return None
    if not os.access(hova.parent, os.W_OK):
        # Nem irhato mappa (pl. Program Files alatt): a venv ugyis elszallna.
        # Igy legalabb nem indul feleslegesen alfolyamat minden inditaskor.
        kiir("[FIGYELEM] A program mappajaba nem lehet irni, ezert nincs "
             "sajat kornyezet:")
        kiir(f"           {hova.parent}")
        return None
    # Ha van mar mappa, de nem hasznalhato (frissitett vagy eltavolitott
    # Python), ugyanez a parancs helyre is teszi: ujrairja a beallitasait es
    # az inditoit.
    kiir(f"[..]   Virtualis kornyezet keszitese (egyszeri): {hova}")
    parancsok = [[sys.executable, "-m", "venv", str(hova)],
                 [sys.executable, "-m", "venv", "--without-pip", str(hova)]]
    for parancs in parancsok:
        if _futtat(parancs) and utvonal.is_file():
            kiir("[OK]   A kornyezet keszen all.")
            return utvonal
    return None


def ertelmezo(gyoker: Path | None = None,
              kiir: Callable[[str], None] = _kiir) -> Path | None:
    """Melyik ertelmezovel kell futni? None = maradhat a mostani.

    Akkor adunk vissza utvonalat, ha van sajat kornyezet, es nem abbol
    futunk. Ha a kornyezet nem hozhato letre, csak figyelmeztetunk: a program
    a rendszer Pythonjaval is elmegy."""
    if kihagyando() or sajat_kornyezetben(gyoker):
        return None
    keszen = letrehozas(gyoker, kiir)
    if keszen is None:
        kiir("[FIGYELEM] Nem sikerult a sajat kornyezet (.venv) letrehozasa.")
        kiir("           A rendszer Pythonjaval megyek tovabb.")
        if sys.platform.startswith("linux"):
            kiir("           Debian/Ubuntu alatt: sudo apt install python3-venv")
    return keszen


def ujrainditas(argumentumok: Sequence[str],
                gyoker: Path | None = None,
                kiir: Callable[[str], None] = _kiir) -> int | None:
    """A program ujrainditasa a sajat kornyezet ertelmezojevel.

    Vissza: a gyerekfolyamat kilepesi kodja, vagy None, ha nem kellett (mar
    jo helyen futunk), illetve ha nem sikerult - ilyenkor a hivo egyszeruen
    folytatja a sajat folyamataban."""
    hova = ertelmezo(gyoker, kiir)
    if hova is None:
        return None
    kornyezet = dict(os.environ)
    kornyezet[ATVALTVA] = "1"
    try:
        return subprocess.call([str(hova), *argumentumok], env=kornyezet)
    except KeyboardInterrupt:  # pragma: no cover - a felhasznalo szakitotta meg
        return MEGSZAKITVA
    except OSError as exc:
        kiir(f"[FIGYELEM] A sajat kornyezet nem indult ({exc}).")
        kiir("           A rendszer Pythonjaval megyek tovabb.")
        return None


def belepes(szkript: str, argv: Sequence[str] | None = None,
            gyoker: Path | None = None,
            kiir: Callable[[str], None] = _kiir) -> int | None:
    """Belepesi pontok egysoros hasznalata:

        kod = qbt_kornyezet.belepes(__file__)
        sys.exit(main() if kod is None else kod)

    A parancssori kapcsolokat valtozatlanul adja tovabb."""
    ervek = list(sys.argv[1:] if argv is None else argv)
    return ujrainditas([szkript, *ervek], gyoker, kiir)
