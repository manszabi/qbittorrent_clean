"""A sajat Python kornyezet (.venv) kezelesenek vizsgalata.

Ket dolgot ellenoriz:
  * a dontesi logikat (mikor kell atvaltani, mikor nem) - ez gyors, es minden
    gepen ugyanaz,
  * es egy VALODI kornyezet letrehozasat egy ideiglenes mappaban: a
    gyerekfolyamat tenyleg abbol indul-e. Ez az egyetlen resz, ami par
    masodpercig tart, viszont pont ez a lenyeg.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import io
import shutil
import tempfile

import qbt_kornyezet as kornyezet

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        print(f"ok    {name:<52} {got!r}")
    else:
        fail = 1
        print(f"HIBA  {name:<52} kapott={got!r}  vart={want!r}")


def csendben(fuggveny, *args, **kw):
    """Lefuttat valamit, es visszaadja: (eredmeny, kiirt szoveg)."""
    regi = sys.stderr
    sys.stderr = io.StringIO()
    try:
        return fuggveny(*args, **kw), sys.stderr.getvalue()
    finally:
        sys.stderr = regi


class Kornyezet:
    """A kornyezeti valtozok ideiglenes atallitasa (a teszt sose fuggjon
    attol, hogy a futtato gepen eppen mi van beallitva)."""

    def __init__(self, **ertekek):
        self.ertekek = ertekek
        self.regi = {}

    def __enter__(self):
        for kulcs, ertek in self.ertekek.items():
            self.regi[kulcs] = os.environ.get(kulcs)
            if ertek is None:
                os.environ.pop(kulcs, None)
            else:
                os.environ[kulcs] = ertek
        return self

    def __exit__(self, *_kivetel):
        for kulcs, ertek in self.regi.items():
            if ertek is None:
                os.environ.pop(kulcs, None)
            else:
                os.environ[kulcs] = ertek


TISZTA = {kornyezet.KIHAGYAS: None, kornyezet.ATVALTVA: None}

tmp = Path(tempfile.mkdtemp(prefix="qbt-kornyezet-teszt-"))

# --- utvonalak --------------------------------------------------------------

check("a kornyezet a program melle kerul",
      kornyezet.venv_konyvtar(tmp), tmp / ".venv")
check("Windowson a Scripts alatt van az ertelmezo",
      kornyezet.venv_python(tmp, windows=True),
      tmp / ".venv" / "Scripts" / "python.exe")
check("maskepp a bin alatt",
      kornyezet.venv_python(tmp, windows=False), tmp / ".venv" / "bin" / "python")
check("a fajlnev is rendszerfuggo",
      kornyezet.venv_python(tmp).name,
      "python.exe" if sys.platform == "win32" else "python")

# --- mikor kell atvaltani ---------------------------------------------------

with Kornyezet(**TISZTA):
    check("ures mappaban meg nincs kornyezet",
          kornyezet.van_sajat_kornyezet(tmp), False)
    check("nem abbol futunk", kornyezet.sajat_kornyezetben(tmp), False)
    check("nincs kikapcsolva", kornyezet.kihagyando(), False)

with Kornyezet(**{**TISZTA, kornyezet.KIHAGYAS: "1"}):
    check("QBT_VENV_KIHAGY=1: kikapcsolva", kornyezet.kihagyando(), True)
    check("es akkor nem is valtunk at",
          csendben(kornyezet.ertelmezo, tmp)[0], None)

for ertek in ("0", "", "nem", "false", "off"):
    with Kornyezet(**{**TISZTA, kornyezet.KIHAGYAS: ertek}):
        check(f"QBT_VENV_KIHAGY={ertek!r}: ez nem kikapcsolas",
              kornyezet.kihagyando(), False)

with Kornyezet(**{**TISZTA, kornyezet.ATVALTVA: "1"}):
    check("a mar atvaltott folyamat nem indit ujabbat",
          kornyezet.kihagyando(), True)

# A sajat prefixunkkel hivva: "mar jo helyen vagyunk" - es akkor nincs valtas.
sajat = Path(sys.prefix)
with Kornyezet(**TISZTA):
    check("a futo ertelmezo sajat prefixet felismeri",
          kornyezet.sajat_kornyezetben(sajat.parent
                                       if sajat.name == ".venv" else sajat),
          sajat.name == ".venv")

# --- nem irhato mappa: ne probalkozzon minden inditaskor ---------------------

# Nem letezo mappa: ugyanaz az ag, es rendszergazdakent is ellenorizheto.
with Kornyezet(**TISZTA):
    eredmeny, uzenet_nincs = csendben(kornyezet.letrehozas, tmp / "nincs-ilyen")
check("irhatatlan helyen nem indit alfolyamatot", eredmeny, None)
check("es meg is mondja, miert", "nem lehet irni" in uzenet_nincs, True)

if os.name != "nt" and os.getuid() != 0:  # rendszergazdanak minden irhato
    zart = tmp / "zart"
    zart.mkdir()
    zart.chmod(0o500)
    try:
        with Kornyezet(**TISZTA):
            eredmeny, uzenet_zart = csendben(kornyezet.letrehozas, zart)
        check("nem irhato mappaban nincs kornyezet", eredmeny, None)
        check("ott is szol rola", "nem lehet irni" in uzenet_zart, True)
    finally:
        zart.chmod(0o700)

# --- valodi kornyezet -------------------------------------------------------

with Kornyezet(**TISZTA):
    ertelmezo, uzenet = csendben(kornyezet.letrehozas, tmp)

if ertelmezo is None:  # pragma: no cover - venv modul nelkuli gep
    print("FIGYELEM: ezen a gepen nem hozhato letre venv, a tobbi teszt kimarad")
    print(uzenet)
else:
    check("a kornyezet letrejott", ertelmezo.is_file(), True)
    check("es szolt is rola", "Virtualis kornyezet keszitese" in uzenet, True)
    check("a keszet mar megtalalja", kornyezet.van_sajat_kornyezet(tmp), True)

    # Masodszor hivva nem indit uj folyamatot: a kesz kornyezetet adja vissza,
    # kiiras nelkul. (Igy nem lassul minden inditas.)
    with Kornyezet(**TISZTA):
        ismet, uzenet2 = csendben(kornyezet.letrehozas, tmp)
    check("a meglevot valtozatlanul hasznalja", ismet, ertelmezo)
    check("es masodszor nem is beszel rola", uzenet2, "")

    # A gyerekfolyamat tenyleg a kornyezetbol indul-e? Ez a lenyeg: a program
    # ettol fut mindenhol ugyanabban a Pythonban.
    gyerek = subprocess.run(
        [str(ertelmezo), "-c", "import sys; print(sys.prefix)"],
        capture_output=True, text=True, check=False)
    check("a kornyezet ertelmezoje a .venv-et hasznalja",
          Path(gyerek.stdout.strip()).resolve(), (tmp / ".venv").resolve())

    # Az ujrainditas: a gyerek kilepesi kodja jon vissza valtozatlanul...
    with Kornyezet(**TISZTA):
        kod, _ = csendben(kornyezet.ujrainditas,
                          ["-c", "import sys; sys.exit(7)"], tmp)
    check("az ujrainditas a gyerek kilepesi kodjat adja", kod, 7)

    # ...es a gyerekben mar be van allitva a jelzo, tehat nem indit tovabbi
    # folyamatot (vegtelen lanc kizarva).
    program = ("import os, sys; "
               f"sys.exit(0 if os.environ.get({kornyezet.ATVALTVA!r}) "
               "else 1)")
    with Kornyezet(**TISZTA):
        kod, _ = csendben(kornyezet.ujrainditas, ["-c", program], tmp)
    check("a gyerek megkapja a 'mar atvaltottam' jelzot", kod, 0)

    # Kikapcsolva nem indul gyerekfolyamat.
    with Kornyezet(**{**TISZTA, kornyezet.KIHAGYAS: "1"}):
        kod, _ = csendben(kornyezet.ujrainditas,
                          ["-c", "import sys; sys.exit(7)"], tmp)
    check("kikapcsolva nem indit semmit", kod, None)

    # "Frissitettem a Pythont, es azota nem indul": a kornyezet a pyvenv.cfg
    # "home" sorabol talalja meg az alap Pythont. Ha az mar nincs meg, a
    # kornyezetet ujra kell epiteni - kulonben csak inditaskor, ertelmetlen
    # hibaval derulne ki.
    cfg = tmp / ".venv" / "pyvenv.cfg"
    eredeti_cfg = cfg.read_text(encoding="utf-8")
    cfg.write_text(eredeti_cfg.replace("home = ", "home = /nincs-ilyen-hely"),
                   encoding="utf-8")
    check("eltunt alap Python: a kornyezet nem hasznalhato",
          kornyezet.van_sajat_kornyezet(tmp), False)
    with Kornyezet(**TISZTA):
        javitott, uzenet3 = csendben(kornyezet.letrehozas, tmp)
    check("es a program magatol helyrehozza", javitott, ertelmezo)
    check("szolva rola", "Virtualis kornyezet keszitese" in uzenet3, True)
    check("utana ujra rendben van", kornyezet.van_sajat_kornyezet(tmp), True)

    # Hianyzo vagy ertelmezhetetlen pyvenv.cfg: inkabb hisszuk jonak, mint
    # hogy feleslegesen eldobjunk egy mukodo kornyezetet.
    cfg.write_text("ez nem kulcs-ertek\n", encoding="utf-8")
    check("ertelmezhetetlen pyvenv.cfg: nem dobjuk el a kornyezetet",
          kornyezet.van_sajat_kornyezet(tmp), True)
    cfg.unlink()
    check("hianyzo pyvenv.cfg eseten sem", kornyezet.van_sajat_kornyezet(tmp),
          True)

    # A belepes ugyanazt csinalja, csak a szkriptet es a kapcsolokat is atadja.
    forras = tmp / "proba.py"
    forras.write_text("import sys; print(' '.join(sys.argv[1:]))\n",
                      encoding="utf-8")
    with Kornyezet(**TISZTA):
        kod, _ = csendben(kornyezet.belepes, str(forras), ["egy", "ketto"], tmp)
    check("a belepes a szkriptet is elinditja", kod, 0)

shutil.rmtree(str(tmp), ignore_errors=True)

print()
print("MINDEN KORNYEZET TESZT SIKERES" if not fail else "VOLT HIBA")
sys.exit(fail)
