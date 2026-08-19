"""A grafikus felulet (qbt_gui.py) ellenorzese: valodi Tkinter ablak, hamis
qBittorrent WebUI es valodi ideiglenes konyvtarfa, valodi torlessel.

Fejnelkuli gepen: xvfb-run -a python3 tests/gui_test.py
"""
import sys
from pathlib import Path

# A vizsgalt program a repo gyokereben van.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import shutil
import stat
import tempfile
import time
import tkinter as tk

from fake_qbt import PASSWORD, USER, build_tree, start_server

import qbt_gui

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


# --- a parbeszedablakok helyettesitese, hogy a teszt ne alljon meg -----------

class Parbeszed:
    """Feljegyzi, mit kerdezett volna a program, es elore megadott valaszt ad."""

    def __init__(self):
        self.hibak = []
        self.figyelmeztetesek = []
        self.igen = True

    def showerror(self, cim, uzenet, **kw):
        self.hibak.append(uzenet)

    def showwarning(self, cim, uzenet, **kw):
        self.figyelmeztetesek.append(uzenet)

    def showinfo(self, cim, uzenet, **kw):
        pass

    def askyesno(self, cim, uzenet, **kw):
        self.kerdes = uzenet
        return self.igen


parbeszed = Parbeszed()
qbt_gui.messagebox = parbeszed

URL, server = start_server()
tmp = Path(tempfile.mkdtemp(prefix="qbt-gui-teszt-"))
share, rss = build_tree(tmp)

# A beallitasok ne a valodi helyukre keruljenek.
beallitas = tmp / "beallitasok.json"
qbt_gui.beallitas_fajl = lambda: beallitas

try:
    root = tk.Tk()
except tk.TclError as exc:  # pragma: no cover - kijelzo nelkuli gep
    print(f"Nincs elerheto kijelzo ({exc}). "
          f"Hasznald: xvfb-run -a python3 {sys.argv[0]}")
    raise SystemExit(1) from exc
root.withdraw()
app = qbt_gui.TakaritoApp(root)

# a naplo se a valodi helyere keruljon
qbt_naplo_ut = tmp / "naplo" / "torlesek.log"
app.v_naplo.set(str(qbt_naplo_ut))


def varakozas(mire, masodperc=20):
    """A hattermunka bevarasa: kozben az ablakot is porgetjuk, mert az
    eredmenyt az ablak dolgozza fel a sorbol."""
    veg = time.time() + masodperc
    while time.time() < veg:
        root.update()
        if mire():
            return True
        time.sleep(0.02)
    return False


def sorok():
    return [app.fa.item(s, "values") for s in app.fa.get_children()]


def nevek():
    return sorted(Path(sor[3]).name for sor in sorok())


# --- felulet felepitese -----------------------------------------------------

check_true("az ablak felepult", app.fa is not None)
check("a torles gomb indulaskor tiltott", str(app.b_torles["state"]), "disabled")
check("indulaskor a fa mod beallitasai tiltottak",
      str(app.cb_pontos["state"]), "disabled")
app.v_mod.set("fa")
app._mod_valtas()
check("fa modban engedelyezve", str(app.cb_pontos["state"]), "normal")
app.v_mod.set("felso")
app._mod_valtas()

check("a kuka mezo alapbol tiltott", str(app.e_kuka["state"]), "disabled")
app.v_kuka_be.set(True)
app._kuka_valtas()
check("bepipalva engedelyezett", str(app.e_kuka["state"]), "normal")
app.v_kuka_be.set(False)
app._kuka_valtas()

# --- konyvtarak felvetele ---------------------------------------------------

app._konyvtar_felvesz(str(share))
app._konyvtar_felvesz(str(rss))
app._konyvtar_felvesz(str(share))  # ugyanaz megegyszer: nem kerulhet be ketszer
check("a ket konyvtar felkerult", list(app.lista_kony.get(0, "end")),
      [str(share), str(rss)])

parbeszed.hibak = []
app._konyvtar_felvesz(str(tmp / "nincs-ilyen"))
check("nem letezo konyvtarra szol", len(parbeszed.hibak), 1)
parbeszed.hibak = []
app._konyvtar_felvesz("/")
check("a gyokerkonyvtarat visszautasitja", len(parbeszed.hibak), 1)
check("es nem is kerult be", list(app.lista_kony.get(0, "end")),
      [str(share), str(rss)])

# --- kapcsolat probaja ------------------------------------------------------

app.v_url.set(URL)
app.v_user.set(USER)
app.v_pw.set("rossz jelszo")
parbeszed.hibak = []
app.kapcsolat_proba()
check_true("rossz jelszo: megjott a valasz",
           varakozas(lambda: not app.dolgozik and parbeszed.hibak))
check_true("rossz jelszonal hibauzenet",
           parbeszed.hibak and "bejelentkezes" in parbeszed.hibak[0].lower(),
           parbeszed.hibak)

app.v_pw.set(PASSWORD)
app.kapcsolat_proba()
check_true("jo jelszoval kapcsolodik",
           varakozas(lambda: not app.dolgozik and "Kapcsolodva"
                     in app.v_allapot.get().replace("ó", "o").replace("á", "a")))
check_true("kiirja a torrentek szamat", "3 torrent" in app.v_allapot.get(),
           app.v_allapot.get())

# --- vizsgalat --------------------------------------------------------------

app.vizsgalat()
check_true("a vizsgalat lefutott", varakozas(lambda: not app.dolgozik and app.elemek))
check("a felesleges elemek jelennek meg", nevek(),
      ["Regi.Film.2011", "arvalt.mkv", "tavalyi.mkv"])
check("alapbol minden ki van pipalva",
      [sor[0] for sor in sorok()], ["☑", "☑", "☑"])
check("a torles gomb engedelyezve", str(app.b_torles["state"]), "normal")
check_true("a torrentes fajlokhoz nem nyul",
           all("Film.Egy.2024" not in sor[3] for sor in sorok()))
check_true("az rss konyvtar sincs a listan",
           all(Path(sor[3]).name != "rss" for sor in sorok()))
check_true("kiirja az osszmeretet", "kipipálva" in app.v_allapot.get(),
           app.v_allapot.get())

# --- pipalgatas -------------------------------------------------------------

elso = app.fa.get_children()[0]
app.pipa_valt(elso)
check("kipipalas visszavonasa", app.fa.item(elso, "values")[0], "☐")
check("egy elem lekerult a listarol", len(app.pipaltak), 2)
app.mindet_valt()  # ha nincs mind kipipalva, elobb mindet bepipalja
check("mindet be", len(app.pipaltak), 3)
app.mindet_valt()
check("mindet ki", len(app.pipaltak), 0)
check("uresen a torles gomb tiltott", str(app.b_torles["state"]), "disabled")
app.mindet_valt()
check("ujra mindet be", len(app.pipaltak), 3)

# --- torles a kukaba --------------------------------------------------------

kuka = tmp / "kuka"
app.v_kuka_be.set(True)
app.v_kuka.set(str(kuka))
app._kuka_valtas()
app.pipa_valt(app.fa.get_children()[0])  # a Regi.Film.2011 maradjon meg
parbeszed.igen = True
app.torles()
check_true("a torles lefutott",
           varakozas(lambda: not app.dolgozik and len(app.elemek) < 3))
check("a megmaradt elem a listan van", nevek(), ["Regi.Film.2011"])
check("a kipipaltak elkerultek",
      (share / "arvalt.mkv").exists() or (rss / "tavalyi.mkv").exists(), False)
check("a kukaban megvannak",
      (kuka / "arvalt.mkv").exists() and (kuka / "rss" / "tavalyi.mkv").exists(),
      True)
check("a ki nem pipalt elem megmaradt", (share / "Regi.Film.2011").exists(), True)
check("a torrentes tartalom megmaradt",
      (share / "Film.Egy.2024" / "film.mkv").exists()
      and (rss / "hetivideo.mkv").exists(), True)
check("torles utan a megmaradt sor nincs bepipalva",
      [sor[0] for sor in sorok()], ["☐"])
check("igy a torles gomb is tiltott", str(app.b_torles["state"]), "disabled")

# --- torlesi naplo ----------------------------------------------------------

naplo_sorok = qbt_naplo_ut.read_text(encoding="utf-8").splitlines()
check_true("a felulet is naploz", len(naplo_sorok) > 1, naplo_sorok)
naplozott = sorted(s.split("\t")[5] for s in naplo_sorok[1:])
check("a kukaba mozgatott elemek bekerultek", naplozott,
      ["arvalt.mkv", "tavalyi.mkv"])
check("a muvelet 'kukaba'",
      sorted({s.split("\t")[1] for s in naplo_sorok[1:]}), ["kukaba"])

# --- vegleges torles, es a "megsem" valasz ----------------------------------

app.v_kuka_be.set(False)
app._kuka_valtas()
app.pipa_valt(app.fa.get_children()[0])
parbeszed.igen = False
app.torles()
check_true("a megerosites 'nem' valasza megallitja", app.elemek and
           (share / "Regi.Film.2011").exists())
check_true("a kerdes szol a veglegessegrol", "VÉGLEGES" in parbeszed.kerdes,
           parbeszed.kerdes)

parbeszed.igen = True
app.torles()
check_true("vegleges torles lefutott",
           varakozas(lambda: not app.dolgozik and not app.elemek))
check("a konyvtar eltunt", (share / "Regi.Film.2011").exists(), False)
check("nincs tobb sor a listaban", sorok(), [])
naplo_sorok = qbt_naplo_ut.read_text(encoding="utf-8").splitlines()
check("a vegleges torles is naploba kerult",
      [s.split("\t")[1] for s in naplo_sorok[1:] if "Regi.Film" in s], ["torolve"])
check("egyetlen fejleccel", naplo_sorok.count(naplo_sorok[0]), 1)

# kikapcsolva ne naplozzon
app.v_naplo_be.set(False)
elozo = qbt_naplo_ut.stat().st_size
(share / "meg.egy.mkv").write_bytes(b"m" * 12)
app.vizsgalat()
varakozas(lambda: not app.dolgozik and app.elemek)
parbeszed.igen = True
app.torles()
varakozas(lambda: not app.dolgozik and not app.elemek)
check("kikapcsolt naplonal nem ir", qbt_naplo_ut.stat().st_size, elozo)
check("de a torles megtortent", (share / "meg.egy.mkv").exists(), False)
app.v_naplo_be.set(True)

# --- ures vizsgalat es a biztonsagi fek -------------------------------------

app.vizsgalat()
check_true("masodszorra nincs mit tenni",
           varakozas(lambda: not app.dolgozik and "nincs felesleges"
                     in app.v_allapot.get().lower()), app.v_allapot.get())

ures_url, ures_server = start_server(torrents=[])
app.v_url.set(ures_url)
parbeszed.hibak = []
app.vizsgalat()
check_true("nulla torrentnel leall", varakozas(
    lambda: not app.dolgozik and parbeszed.hibak))
check_true("es meg is mondja, miert",
           parbeszed.hibak and "MINDENT" in parbeszed.hibak[0], parbeszed.hibak)
check("es semmit nem torolt",
      (share / "Film.Egy.2024" / "film.mkv").exists(), True)
ures_server.shutdown()

app.v_url.set(URL)
app.v_mod.set("fa")  # utvonal-megfeleltetes nelkul semmi nem egyezik
app._mod_valtas()
parbeszed.hibak = []
app.vizsgalat()
check_true("fa modban rossz utvonalnal leall", varakozas(
    lambda: not app.dolgozik and parbeszed.hibak))
check_true("es utvonal-megfeleltetest javasol",
           parbeszed.hibak and "utvonal-megfeleltetes" in parbeszed.hibak[0],
           parbeszed.hibak)

app.lista_ut.insert("end", f"/downloads={share}")
app.lista_ut.insert("end", f"/downloads/rss={rss}")
app.v_pontos.set(True)
app.vizsgalat()
check_true("fa modban helyes utvonallal lefut",
           varakozas(lambda: not app.dolgozik and app.elemek))
check("a torrent mappajaban levo idegen fajlt is megtalalja", nevek(),
      ["mintakep.jpg"])
app.v_mod.set("felso")
app.v_pontos.set(False)
app._mod_valtas()
check("felso modban a megfeleltetesek megmaradnak",
      len(app.lista_ut.get(0, "end")), 2)

# --- beallitasok mentese / betoltese ----------------------------------------

app.v_pw_mentes.set(False)
app.beallitasok_mentese(csendben=True)
check_true("a beallitas-fajl letrejott", beallitas.is_file())
check_true("jelszo nelkul nem menti el a jelszot",
           '"jelszo": ""' in beallitas.read_text(encoding="utf-8"))
app.v_pw_mentes.set(True)
app.beallitasok_mentese(csendben=True)
check_true("kerésre elmenti a jelszot",
           PASSWORD in beallitas.read_text(encoding="utf-8"))

app.lista_kony.delete(0, "end")
app.v_url.set("http://elrontva/")
app.beallitasok_betoltese()
check("betoltes utan visszaall a cim", app.v_url.get(), URL)
check("es a konyvtarak is", list(app.lista_kony.get(0, "end")),
      [str(share), str(rss)])

# a fajlban jelszo is lehet, ezert csak a tulajdonos olvashassa
if os.name != "nt":
    check("a beallitas-fajlt csak a tulajdonos olvashatja",
          stat.S_IMODE(beallitas.stat().st_mode), 0o600)

# kezzel elrontott beallitas-fajl: nem szabad elszallni rajta
elmentett = beallitas.read_text(encoding="utf-8")
beallitas.write_text('{"konyvtarak": "nem lista", "utvonalak": 5, "mod": 7}',
                     encoding="utf-8")
app.beallitasok_betoltese()
check("elrontott beallitas-fajl: a konyvtarlista ures marad",
      list(app.lista_kony.get(0, "end")), [])
check("es az uzemmod ervenyes ertek marad", app.v_mod.get(), "felso")
beallitas.write_text("ez nem is JSON", encoding="utf-8")
app.beallitasok_betoltese()
check("olvashatatlan beallitas-fajlt is elvisel", app.v_mod.get(), "felso")
beallitas.write_text(elmentett, encoding="utf-8")
app.beallitasok_betoltese()

# --- a talalati lista adagolt feltoltese ------------------------------------
#
# Egy nagy megosztason tizezer sor is johet. Egyszerre kiteve az ablak
# masodpercekre megallna, ezert adagokban tesszuk ki oket.

sok = [qbt_gui.engine.Candidate(share / f"p{i:05d}.mkv", False, i)
       for i in range(qbt_gui.BETOLTES_ADAG * 2 + 7)]
app._elemek_kiirasa(sok)
check("elsore csak az elso adag kerul ki", len(app.fa.get_children()),
      qbt_gui.BETOLTES_ADAG)
kesz = []
app._elemek_kiirasa(sok, keszen=lambda: kesz.append(True))
check_true("a tobbi adagokban toltodik be", varakozas(lambda: kesz))
check("a vegen minden sor a helyen van", len(app.fa.get_children()), len(sok))
check("es a sorok az elemekre mutatnak", len(app.sor_index), len(sok))
app._elemek_kiirasa([])

# --- megszakitas ------------------------------------------------------------

regi_plan_lassu = qbt_gui.engine.plan_all


def lassu_plan(torrentek, fajlok, konyvtarak, beallitas, figyelo):
    """Sokaig tarto atnezes utanzata - kozben figyeli a megszakitast."""
    for _ in range(500):
        figyelo.ellenoriz()
        time.sleep(0.01)
    return []


qbt_gui.engine.plan_all = lassu_plan
app.vizsgalat()
check("munka kozben a megszakitas gomb elerheto", str(app.b_megall["state"]),
      "normal")
app.megszakitas()
check_true("megszakitasra leall a vizsgalat",
           varakozas(lambda: not app.dolgozik), app.v_allapot.get())
check_true("es meg is mondja", "Megszakítva" in app.v_allapot.get(),
           app.v_allapot.get())
check("utana a megszakitas gomb ujra tiltott", str(app.b_megall["state"]),
      "disabled")
qbt_gui.engine.plan_all = regi_plan_lassu

# a torles ket elem kozott all meg: amihez nem nyultunk, az megmarad
(share / "megmarad.mkv").write_bytes(b"m" * 32)
jelolt = qbt_gui.engine.Candidate(share / "megmarad.mkv", False, 32)
app.megallj.set()
valasz = app._torles_szal([0], [jelolt], [share], None, None)
app.megallj.clear()
check("megszakitva egyetlen elemet sem torol", valasz[1], set())
check("es jelzi, hogy megszakadt", valasz[4], True)
check("a fajl a helyen maradt", (share / "megmarad.mkv").exists(), True)
(share / "megmarad.mkv").unlink()

# --- varatlan hiba a hatterszalban --------------------------------------------
#
# Ha egy hiba kicsuszna a hattermunkabol, az ablak orokre "dolgozik"
# allapotban ragadna: a gombok tiltva, a halado csik pedig porogne.

regi_plan = qbt_gui.engine.plan_all


def robban(*args, **kw):
    raise ValueError("szandekos proba-hiba")


qbt_gui.engine.plan_all = robban
parbeszed.hibak = []
app.vizsgalat()
check_true("varatlan hiba utan is visszakapjuk a vezerlest",
           varakozas(lambda: not app.dolgozik and parbeszed.hibak),
           app.v_allapot.get())
check_true("es lathato a hibauzenet is",
           parbeszed.hibak and "szandekos proba-hiba" in parbeszed.hibak[0],
           parbeszed.hibak)
check("a probagomb ujra hasznalhato", str(app.b_proba["state"]), "normal")
qbt_gui.engine.plan_all = regi_plan

# --- kilepes munka kozben ----------------------------------------------------

app.dolgozik = True
parbeszed.igen = False
app.kilepes()          # a "nem" valasz nem zarhatja be az ablakot
check_true("munka kozben rakerdez a kilepesre",
           "félbemarad" in parbeszed.kerdes, parbeszed.kerdes)
check_true("es a 'nem' valasz nem zarja be", bool(root.winfo_exists()))
app.dolgozik = False

root.destroy()
server.shutdown()
shutil.rmtree(str(tmp), ignore_errors=True)

print()
print("MINDEN GUI TESZT SIKERES" if not fail else "VOLT HIBA")
sys.exit(fail)
