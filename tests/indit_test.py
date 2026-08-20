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
eredmeny, kiirt = csendben(indit.csomagok_telepitese, valodi, venvben=False)
check("ha nem megy, felhasznaloi modban ujraprobalja",
      (eredmeny, len(hivasok)), (True, 2))
check("a masodik probaban ott a --user", "--user" in hivasok[1], True)

# Sajat kornyezetben a --user telepites nem letezik: ott a pip hianyzik,
# azt az ensurepip potolja.
hivasok, sikeres = [], [False, True, True]
eredmeny, kiirt = csendben(indit.csomagok_telepitese, valodi, venvben=True)
check("sajat kornyezetben nem --user-rel probal",
      (eredmeny, len(hivasok)), (True, 3))
check("hanem az ensurepip-pel", "ensurepip" in hivasok[1], True)
check("es utana ujra telepit", hivasok[2], hivasok[0])
check("a --user meg sem jelenik",
      any("--user" in p for p in hivasok), False)

hivasok, sikeres = [], [False, False]
eredmeny, kiirt = csendben(indit.csomagok_telepitese, valodi, venvben=False)
check("ha egyik sem megy, hibat jelez", eredmeny, False)
check("es kiirja a hibat", "[HIBA]" in kiirt, True)

# A "hol futunk" kerdes magatol is eldol: a teszt csak azt nezi, hogy a
# valasz a Python sajat adataibol jon (sys.prefix / sys.base_prefix).
check("a sajat kornyezet felismerese logikai valasz",
      isinstance(indit.sajat_kornyezetben(), bool), True)

# --- teljes ellenorzes ------------------------------------------------------

indit._futtat = lambda parancs: True

# A tkinter megletet szandekosan nem a futtato gepre bizzuk: van, ahol a
# python3-tk nincs telepitve, es akkor a teszt a program helyett a gepet
# minositene. Magat az ellenorzest fentebb, kulon vizsgaljuk.
regi_hianyzo = indit.hianyzo_modulok
indit.hianyzo_modulok = lambda modulok=None: []

eredmeny, kiirt = csendben(indit.ellenorzes)
check("a repoban minden fuggoseg megvan", eredmeny, True)
check("a program fajljait is megnezi", "program fajljai" in kiirt, True)

# hianyzo tkinter: ertheto uzenet, es a parancssoros valtozat ajanlasa
indit.hianyzo_modulok = lambda modulok=None: (["tkinter"]
                                              if modulok == ["tkinter"] else [])
eredmeny, kiirt = csendben(indit.ellenorzes)
check("hianyzo tkinter eseten leall", eredmeny, False)
check("es megmondja, mit kell telepiteni", "tcl/tk" in kiirt, True)
check("es ajanlja a parancssoros valtozatot", "qbt_takaritas.bat" in kiirt, True)

# hianyzo alap modul: mas uzenet
indit.hianyzo_modulok = lambda modulok=None: (["json"] if modulok is None else [])
eredmeny, kiirt = csendben(indit.ellenorzes)
check("hianyzo alap modul eseten is leall", eredmeny, False)
check("es a Python ujratelepiteset javasolja", "Telepitsd ujra" in kiirt, True)

indit.hianyzo_modulok = lambda modulok=None: []

regi_itt = indit.ITT
indit.ITT = str(tmp)  # itt nincs se qbt_gui.py, se qbt_cleanup.py
eredmeny, kiirt = csendben(indit.ellenorzes)
check("hianyos mappat eszrevesz", eredmeny, False)
check("es megmondja, mi hianyzik", "qbt_gui.py" in kiirt, True)
indit.ITT = regi_itt

eredmeny, kiirt = csendben(indit.main, indit=False, valtas=False)
check("main indites nelkul: rendben", eredmeny, 0)

# A sajat kornyezetre valtas: ha megtortent, a gyerekfolyamat kilepesi kodja
# jon vissza, es itt mar nem futtatunk semmit.
regi_valtas = indit.kornyezet_valtas
indit.kornyezet_valtas = lambda: 3
eredmeny, kiirt = csendben(indit.main, indit=False)
check("atvaltas utan a gyerek kodjaval terunk vissza", eredmeny, 3)
check("es itt mar nem ellenorzunk semmit", "program fajljai" in kiirt, False)

indit.kornyezet_valtas = lambda: None
eredmeny, kiirt = csendben(indit.main, indit=False)
check("ha nem kellett valtani, itt folytatjuk", eredmeny, 0)
check("es lefutnak az ellenorzesek", "program fajljai" in kiirt, True)
indit.kornyezet_valtas = regi_valtas

# Tul regi Python eseten meg a kornyezet-valtas elott megallunk: azt a
# kornyezetet is ez a Python keszitene el.
regi_verzio = indit.MIN_VERZIO
indit.MIN_VERZIO = (99, 0)
indit.kornyezet_valtas = lambda: 3
eredmeny, kiirt = csendben(indit.main, indit=False)
check("tul regi Python: nem is probal kornyezetet valtani", eredmeny, 1)
check("es megmondja, mi a baj", "Tul regi" in kiirt, True)
indit.MIN_VERZIO = regi_verzio
indit.kornyezet_valtas = regi_valtas
indit.hianyzo_modulok = regi_hianyzo

shutil.rmtree(str(tmp), ignore_errors=True)

print()
print("MINDEN INDITO TESZT SIKERES" if not fail else "VOLT HIBA")
sys.exit(fail)
