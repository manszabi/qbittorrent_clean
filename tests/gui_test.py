"""A grafikus felulet (qbt_gui.py) ellenorzese: valodi Tkinter ablak, hamis
qBittorrent WebUI es valodi ideiglenes konyvtarfa, valodi torlessel.

Fejnelkuli gepen: xvfb-run -a python3 tests/gui_test.py
"""
import sys
from pathlib import Path

# A vizsgalt program a repo gyokereben van.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import shutil
import tempfile
import time
import tkinter as tk

from fake_qbt import PASSWORD, USER, build_tree, start_server

import qbt_cleanup as engine
import qbt_gui

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        print("ok    %-46s %r" % (name, got))
    else:
        fail = 1
        print("HIBA  %-46s kapott=%r  vart=%r" % (name, got, want))


def check_true(name, cond, info=""):
    check(name, bool(cond), True)
    if not cond and info:
        print("      %s" % info)


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
    print("Nincs elerheto kijelzo (%s). Hasznald: xvfb-run -a python3 %s"
          % (exc, sys.argv[0]))
    raise SystemExit(1)
root.withdraw()
app = qbt_gui.TakaritoApp(root)


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
check_true("a torles lefutott", varakozas(lambda: not app.dolgozik and len(app.elemek) < 3))
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

app.lista_ut.insert("end", "/downloads=%s" % share)
app.lista_ut.insert("end", "/downloads/rss=%s" % rss)
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

root.destroy()
server.shutdown()
shutil.rmtree(str(tmp), ignore_errors=True)

print()
print("MINDEN GUI TESZT SIKERES" if not fail else "VOLT HIBA")
sys.exit(fail)
