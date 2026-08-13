#!/usr/bin/env python3
"""Indito: megnezi, hogy minden fuggoseg megvan-e, es elinditja a feluletet.

A Windows parancsfajl (qbittorrent_clean.bat) szandekosan csak annyit csinal,
hogy megkeresi a Pythont, es atadja a vezerlest ennek a fajlnak. Minden
ellenorzes itt van, mert a Python kodot lehet tesztelni - a cmd.exe-t nem.

Ez a fajl szandekosan regi Python nyelvtannal keszult (nincs f-string, nincs
tipus-annotacio), hogy egy tul regi Python is el tudja indítani, es ertheto
uzenetet tudjon adni a verziorol.

Kimenete szandekosan ekezet nelkuli: a Windows parancssor a rendszer
kodlapjaval ir, es az ekezetes betuk ott konnyen szemette valnak.
"""

import os
import subprocess
import sys

MIN_VERZIO = (3, 7)

# A program ezeket hasznalja a Python szabvany konyvtarabol.
ALAP_MODULOK = ["json", "ssl", "shutil", "urllib.request", "http.cookiejar"]

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
    """A requirements.txt valodi csomag-sorai (a megjegyzesek nelkul)."""
    try:
        fh = open(utvonal, "r")
    except IOError:
        return []
    try:
        sorok = fh.read().splitlines()
    finally:
        fh.close()
    return [s.strip() for s in sorok if s.strip() and not s.strip().startswith("#")]


def csomagok_telepitese(utvonal):
    """pip install -r ..., ha kell. Igaz, ha minden rendben."""
    if not csomag_sorok(utvonal):
        print("[OK]   Kulso csomag nem szukseges.")
        return True
    print("[..]   Kulso csomagok telepitese...")
    alap = [sys.executable, "-m", "pip", "install", "-r", utvonal]
    if _futtat(alap):
        print("[OK]   Csomagok rendben.")
        return True
    print("[..]   Ujraprobalom felhasznaloi modban...")
    if _futtat(alap[:4] + ["--user"] + alap[4:]):
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

    for fajl in ("qbt_gui.py", "qbt_cleanup.py"):
        if not os.path.isfile(os.path.join(ITT, fajl)):
            print("[HIBA] Nem talalom a(z) %s fajlt itt: %s" % (fajl, ITT))
            print("       Ugy tunik, hianyos a kicsomagolt mappa.")
            return False
    print("[OK]   A program fajljai megvannak.")
    return True


def main(indit=True):
    keret("qBittorrent takarito")
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
