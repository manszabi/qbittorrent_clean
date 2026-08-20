#!/usr/bin/env python3
"""Indito: megnezi, hogy minden fuggoseg megvan-e, es elinditja a feluletet.

A Windows parancsfajl (qbittorrent_clean.bat) szandekosan csak annyit csinal,
hogy megkeresi a Pythont, es atadja a vezerlest ennek a fajlnak. Minden
ellenorzes itt van, mert a Python kodot lehet tesztelni - a cmd.exe-t nem.

Ez a fajl szandekosan regi Python nyelvtannal keszult (nincs f-string, nincs
tipus-annotacio), hogy egy tul regi Python is le tudja forditani, es ertheto
uzenetet tudjon adni a verziorol - a tobbi fajl mar a mai nyelvtant hasznalja,
azokat egy regi Python el sem tudna olvasni.

A program a sajat mappajaban keszit egy virtualis kornyezetet (.venv), es
abban fut - Windowson es Linuxon egyarant. Ez a fajl inditja el a valtast:
eloszor a rendszer Pythonjaval fut le (mert azt hivja a parancsfajl), majd
ugyanezt a fajlt ujrainditja a .venv ertelmezojevel. A csomagok is oda
kerulnek, tehat a program sosem turkal a rendszer Pythonjaban.

Kimenete szandekosan ekezet nelkuli: a Windows parancssor a rendszer
kodlapjaval ir, es az ekezetes betuk ott konnyen szemette valnak.
"""

import os
import subprocess
import sys

MIN_VERZIO = (3, 10)

# A program ezeket hasznalja a Python szabvany konyvtarabol.
ALAP_MODULOK = ["json", "ssl", "shutil", "urllib.request", "http.cookiejar",
                "unicodedata", "dataclasses", "argparse", "logging", "gzip",
                "threading", "concurrent.futures", "enum"]

ITT = os.path.dirname(os.path.abspath(__file__))


def keret(szoveg):
    print("=" * 60)
    print("  " + szoveg)
    print("=" * 60)
    print("")


def verzio_gond():
    """Uzenet, ha tul regi a Python; kulonben None."""
    if sys.version_info[:2] < MIN_VERZIO:
        return ("Tul regi Python: %s (legalabb %d.%d kell)."
                % (sys.version.split()[0], MIN_VERZIO[0], MIN_VERZIO[1]))
    return None


def hianyzo_modulok(modulok=None):
    """A felsorolt modulok kozul melyik nem importalhato."""
    hianyzik = []
    for modul in (ALAP_MODULOK if modulok is None else modulok):
        try:
            __import__(modul)
        except ImportError:
            hianyzik.append(modul)
    return hianyzik


def csomag_sorok(utvonal):
    """A requirements.txt valodi csomag-sorai (a megjegyzesek nelkul).

    A kodolast kotelezo megadni: e nelkul a rendszer kodlapja dontene, es a
    fajl egy ekezetes megjegyzestol elszallna."""
    try:
        with open(utvonal, encoding="utf-8") as fh:
            sorok = fh.read().splitlines()
    except (OSError, ValueError):
        return []
    return [s.strip() for s in sorok if s.strip() and not s.strip().startswith("#")]


def sajat_kornyezetben():
    """A most futo ertelmezo egy virtualis kornyezetbol jon-e."""
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def csomagok_telepitese(utvonal, venvben=None):
    """pip install -r ..., ha kell. Igaz, ha minden rendben.

    A masodik proba attol fugg, hol vagyunk. Sajat kornyezetben a --user
    telepites nem letezik (a pip vissza is utasitja), ott a pip hianya a
    szokasos gond - azt az ensurepip potolja. A rendszer Pythonjanal
    forditva: ott a jogosultsag szokott hianyozni, arra jo a --user."""
    if not csomag_sorok(utvonal):
        print("[OK]   Kulso csomag nem szukseges.")
        return True
    if venvben is None:
        venvben = sajat_kornyezetben()
    print("[..]   Kulso csomagok telepitese...")
    alap = [sys.executable, "-m", "pip", "install",
            "--disable-pip-version-check", "-r", utvonal]
    if _futtat(alap):
        print("[OK]   Csomagok rendben.")
        return True
    if venvben:
        print("[..]   A pip potlasa a sajat kornyezetben...")
        masodik = _futtat([sys.executable, "-m", "ensurepip", "--upgrade"]) \
            and _futtat(alap)
    else:
        print("[..]   Ujraprobalom felhasznaloi modban...")
        masodik = _futtat(alap[:4] + ["--user"] + alap[4:])
    if masodik:
        print("[OK]   Csomagok rendben.")
        return True
    print("[HIBA] Nem sikerult telepiteni a szukseges csomagokat.")
    return False


def _futtat(parancs):
    try:
        return subprocess.call(parancs) == 0
    except OSError:
        return False


def ellenorzes():
    """Minden fuggoseg-ellenorzes. Hiba eseten kiirja, mi a teendo, es
    hamissal ter vissza."""
    print("[OK]   Python: %s" % sys.version.split()[0])

    gond = verzio_gond()
    if gond:
        print("[HIBA] " + gond)
        print("       Telepitsd a friss Pythont: "
              "https://www.python.org/downloads/")
        return False

    hianyzik = hianyzo_modulok()
    if hianyzik:
        print("[HIBA] Hianyzik a Python alap modulja: %s" % ", ".join(hianyzik))
        print("       Telepitsd ujra a Pythont a hivatalos telepitovel.")
        return False
    print("[OK]   Alap modulok megvannak.")

    if hianyzo_modulok(["tkinter"]):
        print("[HIBA] Hianyzik a tkinter - enelkul nincs grafikus felulet.")
        print("       Inditsd el a Python telepitot ujra (Modify), es pipald")
        print("       be a 'tcl/tk and IDLE' komponenst.")
        print("")
        print("       Addig is hasznalhato a parancssoros valtozat:")
        print("       qbt_takaritas.bat")
        return False
    print("[OK]   tkinter megvan.")

    if not csomagok_telepitese(os.path.join(ITT, "requirements.txt")):
        return False

    for fajl in ("qbt_gui.py", "qbt_cleanup.py", "qbt_naplo.py"):
        if not os.path.isfile(os.path.join(ITT, fajl)):
            print("[HIBA] Nem talalom a(z) %s fajlt itt: %s" % (fajl, ITT))
            print("       Ugy tunik, hianyos a kicsomagolt mappa.")
            return False
    print("[OK]   A program fajljai megvannak.")
    return True


def kornyezet_valtas():
    """Atvaltas a program sajat kornyezetere (.venv).

    Vissza: a gyerekfolyamat kilepesi kodja, ha atvaltottunk - ilyenkor a
    munkat mar ott vegeztuk el, itt csak tovabbadjuk a kodot. None, ha nem
    kellett (mar a .venv-ben vagyunk, vagy nem sikerult letrehozni).

    A qbt_kornyezet importja szandekosan itt van, nem a fajl elejen: az a
    modul mar mai nyelvtannal keszult, egy tul regi Python el sem tudna
    olvasni - a verzio-ellenorzes viszont pont azert van elotte, hogy ilyenkor
    ertheto uzenetet adjunk."""
    sys.path.insert(0, ITT)
    import qbt_kornyezet
    return qbt_kornyezet.belepes(os.path.join(ITT, "indit.py"), kiir=print)


def main(indit=True, valtas=None):
    """A teljes inditas. Az `indit` hamisra allitva csak ellenoriz (ezt
    hasznalja a teszt), a `valtas` pedig a sajat kornyezetre valtast kapcsolja.

    A `valtas` alapertelmezese szandekosan az `indit`: a kornyezetre valtas
    ugyanezt a fajlt inditja el ujra, tehat ha a hivo eppen NEM akart
    programot inditani, akkor a gyerekfolyamat sem indithat feluletet."""
    if valtas is None:
        valtas = indit
    keret("qBittorrent takarito")

    # A verziot a kornyezet-valtas ELOTT nezzuk meg: a sajat kornyezetet is
    # ez a Python keszitene, es egy tul regi Pythontol ertheto uzenet jar.
    gond = verzio_gond()
    if gond:
        print("[HIBA] " + gond)
        print("       Telepitsd a friss Pythont: "
              "https://www.python.org/downloads/")
        return 1

    if valtas:
        kod = kornyezet_valtas()
        if kod is not None:
            return kod

    if not ellenorzes():
        return 1
    if not indit:
        return 0
    print("")
    print("Indul a grafikus felulet...")
    sys.path.insert(0, ITT)
    import qbt_gui
    return qbt_gui.main()


if __name__ == "__main__":
    sys.exit(main())
