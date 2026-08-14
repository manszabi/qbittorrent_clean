"""A torlesi naplo (qbt_naplo.py) ellenorzese: sorok, oszlopok, rotalas
merethatarnal es hetfonkent, tomorites, regi fajlok eldobasa."""
import sys
from pathlib import Path

# A vizsgalt program a repo gyokereben van.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gzip
import shutil
import tempfile
import time
from datetime import datetime

import qbt_cleanup as q
import qbt_naplo

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


def sorok(fajl):
    """Egy naplofajl sorai (tomoritve is)."""
    if str(fajl).endswith(".gz"):
        with gzip.open(fajl, "rt", encoding="utf-8") as fh:
            return fh.read().splitlines()
    return Path(fajl).read_text(encoding="utf-8").splitlines()


def mezok(sor):
    return sor.split("\t")


tmp = Path(tempfile.mkdtemp(prefix="qbt-naplo-teszt-"))

# ------------------------------------------------------------- a naplo sorai

naplo_ut = tmp / "elso" / "torlesek.log"
naplo = qbt_naplo.nyitas(naplo_ut)
check_true("a naplo a hianyzo konyvtarat is letrehozza", naplo is not None)

naplo.rogzit(q.Candidate(Path("/mnt/dl/Regi.Film.2011"), True, 4096), True)
naplo.rogzit(q.Candidate(Path("/mnt/dl/arva.mkv"), False, 100), True,
             "kukaba: /mnt/kuka/arva.mkv", kukaba=True)
naplo.rogzit(q.Candidate(Path("/mnt/dl/zart.mkv"), False, 7), False,
             "SIKERTELEN: [Errno 13] tiltva")
naplo.close()

sor_lista = sorok(naplo_ut)
check("fejlec az elso sorban", mezok(sor_lista[0]), list(qbt_naplo.OSZLOPOK))
check("harom bejegyzes keszult", len(sor_lista) - 1, 3)

elso = mezok(sor_lista[1])
check("oszlopok szama", len(elso), len(qbt_naplo.OSZLOPOK))
try:
    datetime.strptime(elso[0], qbt_naplo.IDO_ALAK)
    check("az ido ertelmezheto", elso[0][:2], "20")
except ValueError:
    check("az ido ertelmezheto", elso[0], "ev-ho-nap ora:perc:mp")
check("konyvtar es nev kulon oszlopban", (elso[4], elso[5]),
      (str(Path("/mnt/dl")), "Regi.Film.2011"))
check("konyvtar tipus", elso[2], "konyvtar")
check("meret bajtban", elso[3], "4096")
check("torolt elem muvelete", elso[1], "torolve")

masodik = mezok(sor_lista[2])
check("kukas elem muvelete", masodik[1], "kukaba")
check_true("es a kuka helye is benne van", "kuka" in masodik[6], masodik)

harmadik = mezok(sor_lista[3])
check("sikertelen torles muvelete", harmadik[1], "sikertelen")
check_true("a hibauzenettel egyutt", "Errno 13" in harmadik[6], harmadik)

# tabulator / sortores a fajlnevben nem vaghatja szet a sort (Linuxon lehet)
naplo = qbt_naplo.nyitas(naplo_ut)
naplo.rogzit(q.Candidate(Path("/mnt/dl/csunya\tnev\nket sorban.mkv"), False, 1),
             True)
naplo.close()
utolso = sorok(naplo_ut)[-1]
check("a tabulatoros fajlnev sem tori szet a sort",
      len(mezok(utolso)), len(qbt_naplo.OSZLOPOK))
check("a naplo sorainak szama", len(sorok(naplo_ut)) - 1, 4)

# ------------------------------------------------------- rotalas merethatarnal

meretes = tmp / "meret" / "torlesek.log"
naplo = qbt_naplo.nyitas(meretes, max_bytes=400, backup_count=3)
for i in range(60):
    naplo.rogzit(q.Candidate(Path(f"/mnt/dl/f{i:04d}.mkv"), False, i), True)
naplo.close()

tomoritettek = sorted(meretes.parent.glob("*.gz"))
check_true("a merethatarnal uj fajlt kezdett", len(tomoritettek) > 0)
check("a megtartas hatarat betartja", len(tomoritettek), 3)
check_true("az elo naplo a merethatar alatt maradt",
           meretes.stat().st_size <= 400, meretes.stat().st_size)
check_true("a tomoritett fajl valoban gzip",
           meretes.parent.glob("*.gz") and sorok(tomoritettek[0])[0]
           == qbt_naplo.FEJLEC)

# a nev szerinti sorrend legyen idorendben is - kulonben a megtartas rossz
# fajlokat dobna el
ido_szerint = [p.name for p in
               sorted(meretes.parent.glob("*.gz"), key=lambda f: f.stat().st_mtime)]
check("a rotalt nevek idorendben allnak", [p.name for p in tomoritettek],
      ido_szerint)

# a legfrissebb .gz sorai kozvetlenul az elo naplo elottiek legyenek
utolso_gz = mezok(sorok(tomoritettek[-1])[-1])[5]
elso_elo = mezok(sorok(meretes)[1])[5]
check("a megtartottak a legfrissebbek",
      int(elso_elo[1:5]) - int(utolso_gz[1:5]), 1)

# --------------------------------------------------------- rotalas hetfonkent

heti = tmp / "het" / "torlesek.log"
naplo = qbt_naplo.nyitas(heti, max_bytes=0)  # meret miatt sose rotaljon
naplo.rogzit(q.Candidate(Path("/mnt/dl/mult.mkv"), False, 1), True)
check("meretre nem rotal", len(list(heti.parent.glob("*.gz"))), 0)
naplo.handler.hatarido = time.time() - 1  # mintha uj het kezdodott volna
naplo.rogzit(q.Candidate(Path("/mnt/dl/most.mkv"), False, 2), True)
naplo.close()
check("a het fordulojan uj fajlt kezd", len(list(heti.parent.glob("*.gz"))), 1)
check("a regi sorok a tomoritett fajlba kerultek",
      [mezok(s)[5] for s in sorok(next(heti.parent.glob("*.gz")))[1:]],
      ["mult.mkv"])
check("az uj fajlban csak az uj sor van",
      [mezok(s)[5] for s in sorok(heti)[1:]], ["most.mkv"])

# a kovetkezo hatarido tenyleg hetfo 00:00 legyen
kovetkezo = datetime.fromtimestamp(naplo.handler.hatarido)
check("a kovetkezo forduló hetfo", kovetkezo.weekday(), 0)
check("es ejfelkor", (kovetkezo.hour, kovetkezo.minute, kovetkezo.second),
      (0, 0, 0))
check_true("a jovoben van, de egy heten belul",
           0 < (kovetkezo - datetime.now()).total_seconds() <= 7 * 86400,
           kovetkezo)

# 2026-08-10 hetfo: a het barmely napjarol a kovetkezo hetfo 08-17 legyen
for nap in range(7):
    mikor = datetime(2026, 8, 10 + nap, 13, 45)
    kov = datetime.fromtimestamp(qbt_naplo._kovetkezo_hetfo(mikor))
    check(f"{mikor:%m-%d} utani forduló", (kov.month, kov.day, kov.hour),
          (8, 17, 0))

# ---------------------------------------- korabbi fajl folytatasa, hibatures

folytatas = tmp / "folyt" / "torlesek.log"
naplo = qbt_naplo.nyitas(folytatas)
naplo.rogzit(q.Candidate(Path("/mnt/dl/a.mkv"), False, 1), True)
naplo.close()
naplo = qbt_naplo.nyitas(folytatas)  # ujraindulas: ugyanabba a fajlba ir
naplo.rogzit(q.Candidate(Path("/mnt/dl/b.mkv"), False, 2), True)
naplo.close()
check("ujrainditas utan folytatja a fajlt",
      [mezok(s)[5] for s in sorok(folytatas)[1:]], ["a.mkv", "b.mkv"])
check("es nem ir masodik fejlecet", sorok(folytatas).count(qbt_naplo.FEJLEC), 1)

# nem irhato hely: nem szall el, csak nem naploz
akadaly = tmp / "akadaly"
akadaly.write_text("nem konyvtar", encoding="utf-8")
import io

regi_err = sys.stderr
sys.stderr = io.StringIO()
try:
    rossz = qbt_naplo.nyitas(akadaly / "torlesek.log")
    kiirt = sys.stderr.getvalue()
finally:
    sys.stderr = regi_err
check("nem irhato helyen nem szall el", rossz, None)
check_true("de szol rola", "naplot nem tudom megnyitni" in kiirt, kiirt)

shutil.rmtree(str(tmp), ignore_errors=True)

print()
print("MINDEN NAPLO TESZT SIKERES" if not fail else "VOLT HIBA")
sys.exit(fail)
