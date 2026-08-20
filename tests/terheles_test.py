"""Terheles- es meresi teszt: nagy megosztas, sok torrent.

Nem csak azt nezi, hogy a program JOL mukodik-e, hanem azt is, hogy
ELFOGADHATO IDO alatt: egy valodi letoltokonyvtarban tizezres nagysagrendu
bejegyzes van, es egy qBittorrentben ezer torrent sem ritka.

A meresek a futas vegen tablazatban is megjelennek - a hatarok szandekosan
bosegesek, hogy egy terhelt gepen se legyen szeszelyes a teszt; a nagysagrendi
elcsuszast viszont elkapjak.
"""
import sys
from pathlib import Path

# A vizsgalt program a repo gyokereben van.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import shutil
import tempfile
import time
import tracemalloc

from fake_qbt import PASSWORD, USER, Viselkedes, start_server

import qbt_cleanup as q

# A naplok alapertelmezett helye a felhasznalo allapot-konyvtara. A teszt ne
# irjon oda: sajat, ideiglenes helyre iranyitjuk at.
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix="qbt-teszt-allapot-")

fail = 0
meresek = []


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


def meres(nev, mit, hatar_mp):
    """Lefuttat valamit, meri az idejet, es felveszi a tablazatba."""
    kezdet = time.monotonic()
    eredmeny = mit()
    eltelt = time.monotonic() - kezdet
    meresek.append((nev, f"{eltelt:.2f} mp", f"< {hatar_mp:g} mp"))
    check_true(f"{nev}: idoben", eltelt < hatar_mp, f"{eltelt:.2f} mp")
    return eredmeny


# --------------------------------------------------------- nagy konyvtarfa

TETELEK = 8000          # ennyi bejegyzes a legfelso szinten
KONYVTARAK, FAJLOK = 200, 40   # a fa modhoz: 200 konyvtar, egyenkent 40 fajl

tmp = Path(tempfile.mkdtemp(prefix="qbt-terheles-"))
lapos = tmp / "lapos"
lapos.mkdir()
for i in range(TETELEK):
    (lapos / f"elem{i:05d}.mkv").write_bytes(b"")

# minden otvenedikhez tartozik torrent
nevek = {q.norm_key(f"elem{i:05d}.mkv") for i in range(0, TETELEK, 50)}

terv = q._Terv.keszit(q.Beallitas(), [], q.Figyelo())
tracemalloc.start()
jeloltek = meres(f"felso mod, {TETELEK} bejegyzes",
                 lambda: q.plan_toplevel(lapos, nevek, terv), 10)
_, csucs = tracemalloc.get_traced_memory()
tracemalloc.stop()
meresek.append(("ehhez tobbletmemoria", f"{csucs / 1024 / 1024:.1f} MB",
                "< 32 MB"))
check("felso mod: a torrentesek maradnak", len(jeloltek),
      TETELEK - len(nevek))
check_true("es nem eszi meg a memoriat", csucs < 32 * 1024 * 1024,
           f"{csucs / 1024 / 1024:.1f} MB")

melyfa = tmp / "melyfa"
for k in range(KONYVTARAK):
    konyvtar = melyfa / f"sorozat{k:03d}"
    konyvtar.mkdir(parents=True)
    for f in range(FAJLOK):
        (konyvtar / f"resz{f:03d}.mkv").write_bytes(b"")

# minden konyvtar tartalmabol az elso fajl "torrentes": igy a program minden
# konyvtarba belep, es minden fajlt megvizsgal - ez a legdragabb eset.
roots = {q.path_key(melyfa / f"sorozat{k:03d}" / "resz000.mkv")
         for k in range(KONYVTARAK)}
dirs = {q.path_key(melyfa / f"sorozat{k:03d}") for k in range(KONYVTARAK)}
dirs.add(q.path_key(melyfa))

jeloltek = meres(f"fa mod, {KONYVTARAK * FAJLOK} bejegyzes",
                 lambda: q.plan_tree(melyfa, roots, dirs, terv), 15)
check("fa mod: a torrentes fajlok maradnak", len(jeloltek),
      KONYVTARAK * (FAJLOK - 1))

# Eletszeru eset: a megosztas nagy resze torrentekhez tartozik, es csak par
# elem felesleges. Ilyenkor a program a bejegyzesek tobbsegen csak "atlep" -
# ezert eri meg, hogy az osszehasonlitasi kulcsot a szuloebol allitja elo, es
# utvonal-objektumot csak a valoban felesleges elemekhez epit.
MARADEK = 2
rendezett = {q.path_key(melyfa / f"sorozat{k:03d}" / f"resz{f:03d}.mkv")
             for k in range(KONYVTARAK) for f in range(FAJLOK - MARADEK)}
jeloltek = meres(f"fa mod, rendezett megosztas ({KONYVTARAK * FAJLOK} bejegyzes)",
                 lambda: q.plan_tree(melyfa, rendezett, dirs, terv), 15)
check("rendezett megosztas: csak a felesleges elemek maradnak",
      len(jeloltek), KONYVTARAK * MARADEK)

shutil.rmtree(str(tmp), ignore_errors=True)

# ------------------------------------------- sok torrent fajllistaja (CPU)

# Ez a legdragabb szamitas: fajlonkent kell eldonteni, hova esik a torrent
# tartalma. A meresek szerint korabban a pathlib vitte az ido felet, ezert a
# fuggveny most szoveg-kulcsokkal dolgozik.
NAGY_TORRENT, NAGY_FAJL = 500, 200
nagy_torrentek = [{"hash": f"n{t:04d}", "name": f"Kiadas{t}",
                   "save_path": "/downloads", "download_path": "",
                   "content_path": f"/downloads/Kiadas{t}"}
                  for t in range(NAGY_TORRENT)]
nagy_fajlok = {f"n{t:04d}": [f"Kiadas{t}/resz{i:03d}.mkv" for i in range(NAGY_FAJL)]
               for t in range(NAGY_TORRENT)}

roots, _ = meres(f"owned_paths {NAGY_TORRENT * NAGY_FAJL} fajlra",
                 lambda: q.owned_paths(nagy_torrentek, nagy_fajlok,
                                       [("/downloads", "/mnt/share")],
                                       "/mnt/share"), 3)
check("minden fajl megtartando elemkent szerepel", len(roots),
      NAGY_TORRENT * NAGY_FAJL)

# a torlesi ciklus: elemenkent kell eldonteni, melyik vizsgalt konyvtarba esik
celok = [Path("/mnt/share"), Path("/mnt/share/rss"), Path("/mnt/masik")]
utak = [Path(f"/mnt/share/Kiadas{i}/resz.mkv") for i in range(20000)]
meres("owner_target 20 000 torolt elemre",
      lambda: [q.owner_target(u, celok) for u in utak], 1)

# memoria: a WebUI teljes valasza vs. csak a fajlnevek
def valasz(t, i):
    """A qBittorrent /torrents/files valaszanak egy eleme (a valodi mezokkel)."""
    return {"index": i, "name": f"Kiadas{t}/resz{i:03d}.mkv", "size": 1234567890,
            "progress": 1.0, "priority": 1, "is_seed": True,
            "piece_range": [i * 100, i * 100 + 99], "availability": 1.0}


def melyseg(obj, latott=None):
    """Rekurziv memoriameret."""
    latott = set() if latott is None else latott
    if id(obj) in latott:
        return 0
    latott.add(id(obj))
    n = sys.getsizeof(obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            n += melyseg(k, latott) + melyseg(v, latott)
    elif isinstance(obj, (list, tuple, set)):
        for x in obj:
            n += melyseg(x, latott)
    return n


MINTA_TORRENT, MINTA_FAJL = 100, 200
teljes = {f"m{t}": [valasz(t, i) for i in range(MINTA_FAJL)]
          for t in range(MINTA_TORRENT)}
csak_nev = {h: [f["name"] for f in lista] for h, lista in teljes.items()}
m_teljes, m_nev = melyseg(teljes), melyseg(csak_nev)
meresek.append((f"fajllista memoriaban ({MINTA_TORRENT}x{MINTA_FAJL}), teljes valasz",
                f"{m_teljes / 1024 / 1024:.1f} MB", "-"))
MB = 1024 * 1024
meresek.append(("ugyanez csak a nevekkel (a valasztott)",
                f"{m_nev / MB:.1f} MB", f"< {m_teljes / MB / 2:.1f} MB"))
check_true("a nevek onmagukban feleannyit sem foglalnak",
           m_nev < m_teljes / 2, f"{m_nev} vs {m_teljes}")
del teljes, csak_nev

# ------------------------------------------------- sok torrent, lassu WebUI

TORRENT_DB = 24
KESES = 0.05            # egy fajllista-lekeres ennyi ideig tart

viselkedes = Viselkedes()
viselkedes.keses = KESES
URL, server = start_server(viselkedes=viselkedes)
kliens = q.QbtClient(URL, USER, PASSWORD, q.Halozat(timeout=10, szalak=8))
kliens.login()
hashek = [f"t{i:04d}" for i in range(TORRENT_DB)]

kezdet = time.monotonic()
for h in hashek[:6]:            # a sorban lekeres arat mintaval merjuk
    kliens.files(h)
egyenkent = (time.monotonic() - kezdet) / 6 * TORRENT_DB

viselkedes.egyszerre_csucs = 0
parhuzamos = meres(f"fajllista {TORRENT_DB} torrenthez (parhuzamosan)",
                   lambda: kliens.files_many(hashek), egyenkent)
meresek.append(("ugyanez egyenkent (becsult)", f"{egyenkent:.2f} mp", "-"))
check("minden torrenthez megjott a lista", len(parhuzamos), TORRENT_DB)
check_true("es valoban parhuzamosan kerdezte", viselkedes.egyszerre_csucs > 1,
           viselkedes.egyszerre_csucs)

# --- a lekert torrentek szurese: amelyik nem ide esik, azt nem kerdezzuk le
sok_torrent = [{"hash": f"t{i:04d}", "name": f"Film{i}",
                "save_path": "/media/mashol" if i % 100 else "/downloads",
                "download_path": "",
                "content_path": f"/media/mashol/Film{i}"} for i in range(2000)]
beallitas = q.Beallitas(mode=q.Mod.FA, maps=(("/downloads", "/mnt/share"),))
kellenek = meres("2000 torrent kozul a lenyegesek kivalasztasa",
                 lambda: q.erintett_torrentek(sok_torrent, [Path("/mnt/share")],
                                              beallitas), 1)
check("csak a vizsgalt konyvtarba esoket kerdezzuk le", len(kellenek), 20)
meresek.append(("igy elmarado WebUI hivas", f"{2000 - len(kellenek)} db", "-"))

server.shutdown()

# ------------------------------------------------------------------ osszegzes

print()
print(f"{'meres':<46}{'eredmeny':>14}   {'hatar':>10}")
print("-" * 74)
for nev, ertek, hatar in meresek:
    print(f"{nev:<46}{ertek:>14}   {hatar:>10}")

print()
print("MINDEN TERHELESI TESZT SIKERES" if not fail else "VOLT HIBA")
sys.exit(fail)
