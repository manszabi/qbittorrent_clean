"""Windows 11 specifikus ellenorzesek - Linuxon futtatva is.

A tesztek a Windows-szabalyokat szimulaljak: hosszu utvonalak (MAX_PATH),
UNC megosztas, kis-nagybetu, meghajto-gyoker, AppData, DPI, konzolkodlap.
Ahol lehet, a CPython sajat, Windowsra irt modulja (ntpath) a merce - az
Linuxon is importalhato, tehat a szabalyt a "hivatalos" forrastol kerdezzuk.
"""
import sys
from pathlib import Path

# A vizsgalt program a repo gyokereben van.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import contextlib
import ntpath
import os
import tempfile
from pathlib import PureWindowsPath

import qbt_cleanup as q
import qbt_naplo

# A naplok alapertelmezett helye a felhasznalo allapot-konyvtara. A teszt ne
# irjon oda: sajat, ideiglenes helyre iranyitjuk at.
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix="qbt-teszt-allapot-")

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        print(f"ok    {name:<46} {got!r}")
    else:
        fail = 1
        print(f"HIBA  {name:<46} kapott={got!r}  vart={want!r}")


def check_true(name, cond, info=""):
    check(name, bool(cond), True)
    if not cond and info:
        print(f"      {info}")


@contextlib.contextmanager
def windowsnak_latszunk():
    """A program azt hiszi, Windowson fut - az utvonal-kezelest is azzal a
    modullal vegezzuk, amit ott hasznalna (ntpath)."""
    regi_platform = sys.platform
    regi_abspath = os.path.abspath
    sys.platform = "win32"
    os.path.abspath = ntpath.abspath
    try:
        yield
    finally:
        sys.platform = regi_platform
        os.path.abspath = regi_abspath


# ------------------------------------------------------ 1. hosszu utvonalak

HOSSZU_NEV = "Valami.Nagyon.Hosszu.Kiadasi.Nev.2024.2160p.UHD.BluRay.x265-CSOPORT"
MELY = "C:\\Users\\Kis Bela\\Downloads\\" + "\\".join([HOSSZU_NEV] * 4) + "\\Subs\\hu.srt"
ROVID = "C:\\Letoltes\\Film.mkv"

check_true("a proba-utvonal tenyleg atlepi a 260 karaktert", len(MELY) > 260,
           len(MELY))

with windowsnak_latszunk():
    rovid_eredmeny = q.hosszu_ut(ROVID)
    mely_eredmeny = q.hosszu_ut(MELY)
    unc_eredmeny = q.hosszu_ut(
        "\\\\192.168.1.38\\downloads\\" + "\\".join([HOSSZU_NEV] * 4))
    mar_eloteges = q.hosszu_ut("\\\\?\\C:\\" + "x" * 300)
    perjeles = q.hosszu_ut("C:/Users/Kis Bela/" + "/".join([HOSSZU_NEV] * 4))

check("rovid utat nem bant", rovid_eredmeny, ROVID)
check_true("hosszu uthoz kiteszi a \\\\?\\ eloteget",
           mely_eredmeny.startswith("\\\\?\\C:\\"), mely_eredmeny[:20])
check_true("a megosztas eloteget UNC alakban kapja",
           unc_eredmeny.startswith("\\\\?\\UNC\\192.168.1.38\\downloads"),
           unc_eredmeny[:50])
check_true("a mar eloteges utat nem duplazza",
           mar_eloteges.count("\\\\?\\") == 1, mar_eloteges[:20])
check_true("az eloteges alakban nincs elore dolo perjel",
           "/" not in perjeles, perjeles[:60])
check_true("a CPython szerint is abszolut Windows-ut",
           ntpath.isabs(mely_eredmeny) and ntpath.isabs(unc_eredmeny))
check("es a normpath sem valtoztat rajta", ntpath.normpath(mely_eredmeny),
      mely_eredmeny)
check("mas rendszeren viszont nem nyul hozza", q.hosszu_ut(MELY), MELY)

# a hatart tudatosan a 260 ALATT huztuk meg: a fajlnev meg hozzajon
check_true("a hatar a 260-as korlat alatt van",
           q.WINDOWS_UT_HATAR < 260, q.WINDOWS_UT_HATAR)

# ------------------------------------------------------- 2. gyoker konyvtar

check("meghajto gyokere: nem takaritjuk",
      q.is_root_like(PureWindowsPath("C:\\")), True)
check("perjeles alakban is", q.is_root_like(PureWindowsPath("C:/")), True)
check("egy szinttel lejjebb viszont rendben",
      q.is_root_like(PureWindowsPath("C:\\Letoltes")), False)
check("a megosztas gyokere is rendben (tipikusan az a letoltesi konyvtar)",
      q.is_root_like(PureWindowsPath("\\\\gep\\megosztas")), False)
check("a megosztas alkonyvtara is", q.is_root_like(PureWindowsPath(
    "\\\\gep\\megosztas\\rss")), False)

# --------------------------------------------------------- 3. kis-nagybetu

# A Windows nem tesz kulonbseget: ha a qBittorrent maskepp irja a nevet, mint
# a fajlrendszer, akkor is ugyanarrol az elemrol van szo.
check("a meghajtobetu es a nev kis-nagybetuje nem szamit",
      q.path_key("D:\\Letoltes\\Film.EGY.2024"),
      q.path_key("d:/letoltes/film.egy.2024"))
check("a megosztas neve sem", q.path_key("\\\\GEP\\Megosztas\\A"),
      q.path_key("\\\\gep\\megosztas\\a"))
check("a --kis-nagy-betu kapcsoloval viszont szamit",
      q.path_key("D:\\A", ignore_case=False) == q.path_key("d:\\a", False),
      False)

# a torrent Windowsos utvonala es a helyi ut egyezzen
win_torrent = [{"hash": "w", "name": "Film", "save_path": "D:\\letoltes",
                "download_path": "", "content_path": "D:\\letoltes\\Film"}]
roots, dirs = q.owned_paths(win_torrent, {}, [], "D:/Letoltes")
check("a Windows-utvonalas torrent a helyi konyvtarban is megvan",
      sorted(roots), ["d:/letoltes/film"])

# ------------------------------------------------------------ 4. kuka nevek

# A kukaba mozgatott elem neve a meglevo fajl neve + idobelyeg. Windowson a
# nev nem vegzodhet ponttal vagy szokozzel, es nem lehet foglalt eszkoznev.
tmp = Path(tempfile.mkdtemp(prefix="qbt-win-teszt-"))
(tmp / "film.mkv").write_bytes(b"x")
uj = q._free_trash_path(tmp / "film.mkv")
check_true("utkozeskor idobelyeges nevet ad", uj.name.startswith("film.mkv."),
           uj.name)
check_true("a nev nem vegzodik ponttal vagy szokozzel",
           uj.name == uj.name.rstrip(". "), repr(uj.name))
tiltott = '<>:"/\\|?*'
check_true("nincs benne Windowson tiltott karakter",
           not any(jel in uj.name for jel in tiltott), uj.name)
if hasattr(ntpath, "isreserved"):  # Python 3.13+
    check("a CPython szerint sem foglalt eszkoznev",
          ntpath.isreserved(uj.name), False)

# --------------------------------------------------- 5. AppData es naplohely

regi_appdata = os.environ.get("APPDATA")
os.environ["APPDATA"] = "C:\\Users\\Kis Bela\\AppData\\Roaming"
try:
    with windowsnak_latszunk():
        naplo_win = qbt_naplo.naplo_konyvtar()
        esemeny_win = qbt_naplo.esemeny_naplo_fajl()
    naplo_linux = qbt_naplo.naplo_konyvtar()
finally:
    if regi_appdata is None:
        del os.environ["APPDATA"]
    else:
        os.environ["APPDATA"] = regi_appdata

check_true("Windowson a naplo az AppData ala kerul",
           "AppData" in str(naplo_win) and "qbittorrent_clean" in str(naplo_win),
           naplo_win)
check_true("az esemenynaplo is oda", str(esemeny_win).endswith("esemenyek.log"),
           esemeny_win)
check_true("mas rendszeren viszont nem az AppData szamit (akkor sem, ha be van "
           "allitva)", "AppData" not in str(naplo_linux), naplo_linux)

# --------------------------------------------------------------- 6. DPI

# A Tk alapbol nem DPI-tudatos, es a CPython Windows-manifestje sem allitja be
# (csak a hosszu utvonalakat engedelyezi), ezert nekunk kell szolni a
# rendszernek - kulonben 125-150%-os nagyitasnal minden betu elmosodott.
import qbt_gui

hivasok = []


class HamisShcore:
    def SetProcessDpiAwareness(self, ertek):   # a Windows API neve
        hivasok.append(ertek)
        return 0


import ctypes

regi_oledll = getattr(ctypes, "OleDLL", None)   # Linuxon nincs ilyen
ctypes.OleDLL = lambda nev: HamisShcore()
try:
    with windowsnak_latszunk():
        qbt_gui.dpi_tudatossag()
    kint = list(hivasok)
    qbt_gui.dpi_tudatossag()          # Linuxon nem szabad hivnia
finally:
    if regi_oledll is None:
        del ctypes.OleDLL
    else:
        ctypes.OleDLL = regi_oledll

check("Windowson beallitja a DPI-tudatossagot", kint, [1])
check("mas rendszeren nem nyul hozza", hivasok, [1])

# --------------------------------------------------- 7. konzol es kodlapok

# A magyar Windows parancssora cp852 kodlappal ir. A program sajat uzenetei
# ezert szandekosan ekezet nelkuliek; a fajlnevek viszont ekezetesek lehetnek,
# ezert a kimenetet UTF-8-ra allitjuk at, "replace" hibakezelessel.
for modul in ("qbt_cleanup.py", "qbt_naplo.py", "indit.py"):
    forras = (REPO / modul).read_text(encoding="utf-8")
    gond = []
    for sor_szam, sor in enumerate(forras.splitlines(), 1):
        try:
            sor.encode("cp852")
        except UnicodeEncodeError:
            gond.append(sor_szam)
    check(f"{modul}: minden sora kiirhato cp852 kodlapon", gond, [])


class HamisFolyam:
    def __init__(self):
        self.hivas = None

    def reconfigure(self, **kw):
        self.hivas = kw


regi_out, regi_err = sys.stdout, sys.stderr
sys.stdout, sys.stderr = HamisFolyam(), HamisFolyam()
try:
    q._utf8_kimenet()
    beallitas = (sys.stdout.hivas, sys.stderr.hivas)
finally:
    sys.stdout, sys.stderr = regi_out, regi_err
check("a kimenet UTF-8-ra all at, tureses hibakezelessel", beallitas,
      ({"encoding": "utf-8", "errors": "replace"},) * 2)

# reconfigure nelkuli (regi vagy helyettesitett) folyam sem okoz hibat
sys.stdout, sys.stderr = object(), object()
try:
    q._utf8_kimenet()
    rendben = True
except Exception:  # noqa: BLE001 - pont ezt nezzuk
    rendben = False
finally:
    sys.stdout, sys.stderr = regi_out, regi_err
check("reconfigure nelkuli folyamon sem szall el", rendben, True)

# ------------------------------------------------- 8. fajlkezelo megnyitasa

# Windowson az os.startfile a jaratos ut; mashol kulon folyamatban inditunk
# fajlkezelot, hogy a felulet ne varjon ra.
inditott = []
regi_startfile = getattr(os, "startfile", None)
os.startfile = inditott.append
regi_kulon = qbt_gui.kulon_inditas
qbt_gui.kulon_inditas = inditott.append
osztaly = qbt_gui.TakaritoApp.__new__(qbt_gui.TakaritoApp)
osztaly.v_naplo = type("V", (), {"get": staticmethod(lambda: str(tmp / "naplo.log"))})()
try:
    with windowsnak_latszunk():
        qbt_gui.TakaritoApp.naplo_megnyitas(osztaly)
finally:
    qbt_gui.kulon_inditas = regi_kulon
    if regi_startfile is None:
        del os.startfile
    else:
        os.startfile = regi_startfile
check("Windowson az os.startfile nyitja meg a naplo mappajat",
      [str(x) for x in inditott], [str(tmp)])

import shutil

shutil.rmtree(str(tmp), ignore_errors=True)

print()
print("MINDEN WINDOWS TESZT SIKERES" if not fail else "VOLT HIBA")
sys.exit(fail)
