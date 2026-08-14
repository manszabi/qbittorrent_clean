"""Az indito (indit.py) fuggoseg-ellenorzeseinek vizsgalata.

Ez az a resz, ami korabban a .bat fajlban volt - es pont azert kerult
Pythonba, hogy tesztelheto legyen."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import io
import shutil
import tempfile

import indit

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        print(f"ok    {name:<46} {got!r}")
    else:
        fail = 1
        print(f"HIBA  {name:<46} kapott={got!r}  vart={want!r}")


def csendben(fuggveny, *args, **kw):
    """Lefuttat valamit, es visszaadja: (eredmeny, kiirt szoveg)."""
    regi = sys.stdout
    sys.stdout = io.StringIO()
    try:
        eredmeny = fuggveny(*args, **kw)
        return eredmeny, sys.stdout.getvalue()
    finally:
        sys.stdout = regi


# --- verzio -----------------------------------------------------------------

check("a futo Python verziojat elfogadja", indit.verzio_gond(), None)

regi_verzio = indit.MIN_VERZIO
indit.MIN_VERZIO = (99, 0)
gond = indit.verzio_gond()
check("tul regi verziot kiszur", bool(gond and "Tul regi" in gond), True)
indit.MIN_VERZIO = regi_verzio

# --- modulok ----------------------------------------------------------------

check("a meglevo modulokra nem panaszkodik",
      indit.hianyzo_modulok(["json", "ssl"]), [])
check("a hianyzot megtalalja",
      indit.hianyzo_modulok(["nincs_ilyen_modul_xyz"]), ["nincs_ilyen_modul_xyz"])
check("alapbol a program altal hasznaltakat nezi",
      indit.hianyzo_modulok(), [])

# --- requirements.txt -------------------------------------------------------

tmp = Path(tempfile.mkdtemp(prefix="qbt-indit-teszt-"))

csak_megjegyzes = tmp / "csak_megjegyzes.txt"
csak_megjegyzes.write_text("# semmi\n\n   \n# meg egy megjegyzes\n",
                           encoding="utf-8")
check("csak megjegyzes: nincs telepitendo", indit.csomag_sorok(csak_megjegyzes), [])

valodi = tmp / "valodi.txt"
valodi.write_text("# megjegyzes\nrequests>=2.0\n\n  pyserial\n", encoding="utf-8")
check("a valodi csomag-sorokat kiszedi", indit.csomag_sorok(valodi),
      ["requests>=2.0", "pyserial"])
check("nem letezo fajl: ures lista",
      indit.csomag_sorok(tmp / "nincs-ilyen.txt"), [])

# a repo sajat requirements.txt-je szandekosan csak megjegyzes
check("a repo requirements.txt-je nem kivan csomagot",
      indit.csomag_sorok(REPO / "requirements.txt"), [])

# --- telepites --------------------------------------------------------------

hivasok = []
indit._futtat = lambda parancs: (hivasok.append(parancs), sikeres.pop(0))[1]

sikeres = []
eredmeny, kiirt = csendben(indit.csomagok_telepitese, csak_megjegyzes)
check("nincs csomag: nem indit pip-et", (eredmeny, hivasok), (True, []))
check("es meg is mondja", "nem szukseges" in kiirt, True)

hivasok, sikeres = [], [True]
eredmeny, kiirt = csendben(indit.csomagok_telepitese, valodi)
check("van csomag: elsore telepit", (eredmeny, len(hivasok)), (True, 1))
check("a pip parancs a fajlra mutat",
      str(valodi) in [str(x) for x in hivasok[0]], True)

hivasok, sikeres = [], [False, True]
eredmeny, kiirt = csendben(indit.csomagok_telepitese, valodi)
check("ha nem megy, felhasznaloi modban ujraprobalja",
      (eredmeny, len(hivasok)), (True, 2))
check("a masodik probaban ott a --user", "--user" in hivasok[1], True)

hivasok, sikeres = [], [False, False]
eredmeny, kiirt = csendben(indit.csomagok_telepitese, valodi)
check("ha egyik sem megy, hibat jelez", eredmeny, False)
check("es kiirja a hibat", "[HIBA]" in kiirt, True)

# --- teljes ellenorzes ------------------------------------------------------

indit._futtat = lambda parancs: True
eredmeny, kiirt = csendben(indit.ellenorzes)
check("a repoban minden fuggoseg megvan", eredmeny, True)
check("a program fajljait is megnezi", "program fajljai" in kiirt, True)

regi_itt = indit.ITT
indit.ITT = str(tmp)  # itt nincs se qbt_gui.py, se qbt_cleanup.py
eredmeny, kiirt = csendben(indit.ellenorzes)
check("hianyos mappat eszrevesz", eredmeny, False)
check("es megmondja, mi hianyzik", "qbt_gui.py" in kiirt, True)
indit.ITT = regi_itt

eredmeny, kiirt = csendben(indit.main, indit=False)
check("main indites nelkul: rendben", eredmeny, 0)

shutil.rmtree(str(tmp), ignore_errors=True)

print()
print("MINDEN INDITO TESZT SIKERES" if not fail else "VOLT HIBA")
sys.exit(fail)
