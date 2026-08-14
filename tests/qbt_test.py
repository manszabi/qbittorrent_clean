"""A qBittorrent takarito (qbt_cleanup.py) ellenorzese: hamis WebUI
kiszolgalo + valodi ideiglenes konyvtarak, valodi torlessel."""
import sys
from pathlib import Path

# A vizsgalt program a repo gyokereben van.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import io
import os
import shutil
import stat
import tempfile
import unicodedata
from pathlib import Path

from fake_qbt import FILES, PASSWORD, TORRENTS, USER, build_tree, start_server

import qbt_cleanup as q

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


URL, server = start_server()

# ----------------------------------------------------------- utvonal-logika

check("normalize_remote windows",
      q.normalize_remote("D:\\letoltes\\film\\"), "D:/letoltes/film")
check("normalize_remote UNC",
      q.normalize_remote("\\\\192.168.1.38\\downloads\\"), "//192.168.1.38/downloads")
check("root_name konyvtaras torrent", q.root_name(TORRENTS[0]), "Film.Egy.2024")
check("root_name egyfajlos torrent", q.root_name(TORRENTS[2]), "hetivideo.mkv")
check("root_name content_path nelkul",
      q.root_name({"name": "Csak Nev", "save_path": "/downloads",
                   "content_path": ""}), "Csak Nev")
check("root_name szokozos mentesi ut",
      q.root_name({"name": "x", "save_path": "/le toltes",
                   "content_path": "/le toltes/Valami.2020/"}), "Valami.2020")

maps = [q.parse_map("/downloads=/mnt/share"),
        q.parse_map("/downloads/rss=/mnt/share/rss")]
check("apply_maps leghosszabb nyer",
      q.apply_maps("/downloads/rss/x.mkv", maps), str(Path("/mnt/share/rss/x.mkv")))
check("apply_maps altalanos szabaly",
      q.apply_maps("/downloads/Film/a.mkv", maps), str(Path("/mnt/share/Film/a.mkv")))
check("apply_maps pontos egyezes", q.apply_maps("/downloads", maps), "/mnt/share")
check("apply_maps nem ide tartozik", q.apply_maps("/media/egyeb/x", maps), None)
check("apply_maps szabaly nelkul valtozatlan",
      q.apply_maps("/downloads/x", []), "/downloads/x")
check("apply_maps nem vag felbe nevet",
      q.apply_maps("/downloads2/x", [q.parse_map("/downloads=/mnt/s")]), None)
try:
    q.parse_map("nincs-egyenlosegjel")
    check("parse_map hibas alak", "nem dobott hibat", "ValueError")
except ValueError:
    check("parse_map hibas alak", "ValueError", "ValueError")

check("is_root_like gyoker", q.is_root_like(Path("/")), True)
check("is_root_like rendes ut", q.is_root_like(Path("/mnt/share")), False)
check("is_root_like UNC megosztas",
      q.is_root_like(Path("\\\\192.168.1.38\\downloads")), False)
check("is_root_like UNC per-jelesen",
      q.is_root_like(Path("//192.168.1.38/downloads")), False)

check("norm_key: ketfele ekezet-kodolas egyezik",
      q.norm_key(unicodedata.normalize("NFD", "Árvíztűrő")),
      q.norm_key("árvíztűrő"))
check("norm_key: kerhetjuk, hogy szamitson a kis-nagybetu",
      q.norm_key("Film", ignore_case=False) == q.norm_key("film", ignore_case=False),
      False)
check("is_excluded mintaval", q.is_excluded(".Trash-1000", q.DEFAULT_EXCLUDES), True)
check("is_excluded rendes nev", q.is_excluded("Film.Egy.2024", q.DEFAULT_EXCLUDES),
      False)

# --------------------------------------------- ketfele ekezet-kodolas (NFC/NFD)
#
# A Samba / macOS ugyanazt az ekezetes nevet ketfelekeppen is tarolhatja. A
# nevek OSSZEHASONLITASA emiatt normalizalt alakon tortenik, a LEVAGAS viszont
# hosszal dolgozik - ha a ketto elcsuszik, a program a torrenthez tartozo
# konyvtarat is feleslegesnek latja, es letorli. Ezert kulon ellenorizzuk.

nfd_save = unicodedata.normalize("NFD", "/le toltes/Videó")
nfc_save = unicodedata.normalize("NFC", "/le toltes/Videó")
check("root_name: NFD mentesi ut, NFC tartalom",
      q.root_name({"name": "x", "save_path": nfd_save,
                   "content_path": nfc_save + "/Film.2024"}), "Film.2024")
check("root_name: NFC mentesi ut, NFD tartalom",
      q.root_name({"name": "x", "save_path": nfc_save,
                   "content_path": nfd_save + "/Film.2024"}), "Film.2024")
check("apply_maps: ketfele ekezet-kodolas is egyezik",
      q.apply_maps(nfd_save + "/Film.2024/a.mkv", [q.parse_map(nfc_save + "=/mnt/s")]),
      str(Path("/mnt/s/Film.2024/a.mkv")))
check("strip_prefix: nem illeszkedo eleje", q.strip_prefix("/a/b", "/c/"), None)
check("strip_prefix: kis-nagybetu szamit, ha kerjuk",
      q.strip_prefix("/A/b", "/a/", ignore_case=False), None)

check("apply_maps: --kis-nagy-betu eseten a megfeleltetes is figyel ra",
      q.apply_maps("/DOWNLOADS/x", [q.parse_map("/Downloads=/mnt/s")],
                   ignore_case=False), None)
check("apply_maps: alapbol viszont nem szamit",
      q.apply_maps("/DOWNLOADS/x", [q.parse_map("/Downloads=/mnt/s")]),
      str(Path("/mnt/s/x")))

# --------------------------------------------------- perjelek egysegesitese
#
# A Windows visszafele dolo perjelet hasznal, a qBittorrent elore dolot. Ha a
# ketto keveredne, a 'fa' mod egyetlen torrent-elemet sem talalna meg.

check("path_key: a ketfele perjel ugyanaz",
      q.path_key("D:\\letoltes\\Film\\"), q.path_key("d:/letoltes/film"))
check("normalize_remote: a dupla perjelet osszevonja",
      q.normalize_remote("//gep//megosztas//a/"), "//gep/megosztas/a")
win_torrent = [{"hash": "w", "name": "Film", "save_path": "D:\\letoltes",
                "download_path": "", "content_path": "D:\\letoltes\\Film"}]
win_roots, _ = q.owned_paths(win_torrent, {}, [], "D:\\letoltes")
check("owned_paths: Windows-utvonal megfeleltetes nelkul is egyezik",
      sorted(win_roots), ["d:/letoltes/film"])
check("kesz_kulcs: a .!qB vegzodest levagja",
      q.kesz_kulcs(q.norm_key("Film.mkv" + q.INCOMPLETE_SUFFIX)), "film.mkv")
check("kesz_kulcs: mast nem bant", q.kesz_kulcs(q.norm_key("Film.mkv")), "film.mkv")

# --------------------------------------------------------- WebUI kliens

bad = q.QbtClient(URL, USER, "rossz jelszo", timeout=5)
try:
    bad.login()
    check("rossz jelszo", "nem dobott hibat", "QbtError")
except q.QbtError as exc:
    check_true("rossz jelszo -> QbtError", "bejelentkezes" in str(exc).lower(), exc)

client = q.QbtClient(URL, USER, PASSWORD, timeout=5)
client.login()
check("app/version", client.version(), "v4.6.5")
check("torrents/info darabszam", len(client.torrents()), 3)
check("torrents/files", [f["name"] for f in client.files("aaa")],
      ["Film.Egy.2024/film.mkv", "Film.Egy.2024/film.srt"])

dead = q.QbtClient("http://127.0.0.1:1", "a", "b", timeout=2)
try:
    dead.login()
    check("elerhetetlen kiszolgalo", "nem dobott hibat", "QbtError")
except q.QbtError:
    check("elerhetetlen kiszolgalo", "QbtError", "QbtError")

# ------------------------------------------------------- proba-konyvtarfa

def names_of(cands, base):
    return sorted(str(Path(c.path).relative_to(base)).replace("\\", "/")
                  for c in cands)


tmp = Path(tempfile.mkdtemp(prefix="qbt-teszt-"))
share, rss = build_tree(tmp)

# --- 'felso' mod: nevek alapjan, a ket konyvtar vedi egymast
names = q.owned_names(TORRENTS)
cands = q.plan_toplevel(share, names, q.DEFAULT_EXCLUDES, protected=[rss])
check("felso mod: mit torolne (downloads)", names_of(cands, share),
      ["Regi.Film.2011", "arvalt.mkv"])
check("felso mod: az rss alkonyvtar vedve van",
      any(Path(c.path).name == "rss" for c in cands), False)
check("felso mod: @eaDir vedve van",
      any(Path(c.path).name == "@eaDir" for c in cands), False)
check("felso mod: a Regi.Film.2011 merete",
      [c.size for c in cands if Path(c.path).name == "Regi.Film.2011"], [4096])

cands_rss = q.plan_toplevel(rss, names, q.DEFAULT_EXCLUDES, protected=[share])
check("felso mod: mit torolne (rss)", names_of(cands_rss, rss), ["tavalyi.mkv"])

# --- vedelem az rss nelkul: latszik, hogy tenyleg kellett a masodik konyvtar
cands_veszely = q.plan_toplevel(share, names, q.DEFAULT_EXCLUDES)
check("vedelem nelkul az rss is aldozat lenne",
      "rss" in names_of(cands_veszely, share), True)

# --- kis/nagybetu: a Samba maskepp irhatja
big = Path(tmp) / "downloads" / "FILM.EGY.2024"
check("kis-nagybetu: azonos nevet megtart",
      q.norm_key("FILM.EGY.2024") in names, True)

# --- 'fa' mod utvonal-megfeleltetessel, fajllista nelkul
share_maps = [("/downloads", str(share)), ("/downloads/rss", str(rss))]
roots, dirs = q.owned_paths(TORRENTS, {}, share_maps, share)
cands = q.plan_tree(share, roots, dirs, q.DEFAULT_EXCLUDES, protected=[rss])
check("fa mod: mit torolne", names_of(cands, share),
      ["Regi.Film.2011", "arvalt.mkv"])
check("fa mod: a torrent sajat konyvtaraban nem turkal",
      any("Film.Egy.2024" in str(c.path) for c in cands), False)

# --- 'fa' mod pontos (fajlonkenti) osszehasonlitassal
roots, dirs = q.owned_paths(TORRENTS, FILES, share_maps, share)
cands = q.plan_tree(share, roots, dirs, q.DEFAULT_EXCLUDES, protected=[rss])
check("pontos mod: az idegen fajl is felesleges", names_of(cands, share),
      ["Film.Egy.2024/mintakep.jpg", "Regi.Film.2011", "arvalt.mkv"])

# --- rossz utvonal-megfeleltetes: nem talal semmit (a program ilyenkor leall)
roots, dirs = q.owned_paths(TORRENTS, {}, [("/valami/mas", str(share))], share)
check("rossz megfeleltetes -> ures halmaz", len(roots), 0)

# --- felkesz (.!qB) fajlok: a qBittorrent ezt biggyeszti a vegere
felkesz = share / "Sorozat S01" / ("e03.mkv" + q.INCOMPLETE_SUFFIX)
felkesz.write_bytes(b"k" * 16)
felkesz_gyoker = share / ("Uj.Film.2025" + q.INCOMPLETE_SUFFIX)
felkesz_gyoker.write_bytes(b"u" * 16)
felkesz_tor = [*TORRENTS, {"hash": "ddd", "name": "Uj.Film.2025",
                           "save_path": "/downloads", "download_path": "",
                           "content_path": "/downloads/Uj.Film.2025"}]

nevek_felkesz = q.owned_names(felkesz_tor)
cands = q.plan_toplevel(share, nevek_felkesz, q.DEFAULT_EXCLUDES, protected=[rss])
check("felso mod: a felkesz (.!qB) gyokeret megtartja",
      any(Path(c.path).name == felkesz_gyoker.name for c in cands), False)

felkesz_maps = [("/downloads", str(share)), ("/downloads/rss", str(rss))]
felkesz_fajlok = {**FILES, "bbb": [{"name": "Sorozat S01/e01.mkv"},
                                   {"name": "Sorozat S01/e02.mkv"},
                                   {"name": "Sorozat S01/e03.mkv"}]}
r_f, d_f = q.owned_paths(felkesz_tor, felkesz_fajlok, felkesz_maps, share)
cands = q.plan_tree(share, r_f, d_f, q.DEFAULT_EXCLUDES, protected=[rss])
check("fa+pontos mod: a felkesz fajlt is megtartja",
      any(q.INCOMPLETE_SUFFIX in str(c.path) for c in cands), False)
felkesz.unlink()
felkesz_gyoker.unlink()

# --- min-kor: a frissen modositott elemet meghagyja
cands = q.plan_toplevel(share, names, q.DEFAULT_EXCLUDES, min_age_days=1,
                        protected=[rss])
check("min-kor 1 nap: a friss elemeket meghagyja", names_of(cands, share), [])

# --- melyen agazo fa: a bejaras nem lehet rekurziv (RecursionError)
#
# A rekurzios korlatot ideiglenesen lejjebb vesszuk, kulonben a probahoz olyan
# melyen kellene konyvtarat gyartani, amit a fajlrendszer mar nem is birna
# (a teljes utvonal hossza korlatos).


def verem_melyseg():
    melyseg, keret = 0, sys._getframe()
    while keret is not None:
        melyseg += 1
        keret = keret.f_back
    return melyseg


melyfa = Path(tmp) / "melyfa"
kurzor = melyfa
for i in range(250):
    kurzor = kurzor / f"m{i:03d}"
kurzor.mkdir(parents=True)
(kurzor / "legalul.mkv").write_bytes(b"m" * 8)
melyfa_dirs = {q.path_key(p) for p in [kurzor, *kurzor.parents]}
regi_korlat = sys.getrecursionlimit()
sys.setrecursionlimit(verem_melyseg() + 120)  # keveseb, mint a fa melysege
try:
    melyfa_cands = q.plan_tree(melyfa, set(), melyfa_dirs)
    check("melyen agazo fat is bejar (nem rekurziv)",
          [Path(c.path).name for c in melyfa_cands], ["legalul.mkv"])
except RecursionError:
    check("melyen agazo fat is bejar (nem rekurziv)", "RecursionError",
          "nincs hiba")
finally:
    sys.setrecursionlimit(regi_korlat)
shutil.rmtree(str(melyfa))

# --- olvashatatlan alkonyvtar: azt az agat kihagyja, de nem all le
#
# A tesztet rootkent futtatva a jogosultsag nem korlatoz, ezert magat az
# os.scandir hivast csereljuk le arra a konyvtarra.
melyebb = share / "Film.Egy.2024"
tiltott_kulcs = q.path_key(melyebb)
eredeti_scandir = os.scandir


def tiltakozo_scandir(ut):
    if q.path_key(str(ut)) == tiltott_kulcs:
        raise PermissionError(13, "Hozzaferes megtagadva")
    return eredeti_scandir(ut)


share_maps2 = [("/downloads", str(share)), ("/downloads/rss", str(rss))]
roots2, dirs2 = q.owned_paths(TORRENTS, FILES, share_maps2, share)
os.scandir = tiltakozo_scandir
try:
    gondok = []
    cands = q.plan_tree(share, roots2, dirs2, q.DEFAULT_EXCLUDES,
                        protected=[rss], on_warn=gondok.append)
    check("olvashatatlan alkonyvtar: a tobbi resz elkeszul",
          names_of(cands, share), ["Regi.Film.2011", "arvalt.mkv"])
    check("es szol rola", len(gondok), 1)
    check_true("a hibauzenetben ott a konyvtar",
               gondok and "Film.Egy.2024" in gondok[0], gondok)
    check_true("a tiltott konyvtar tartalma nem lett torlesre jelolve",
               all("Film.Egy.2024" not in str(c.path) for c in cands))
finally:
    os.scandir = eredeti_scandir

# magat a vizsgalt konyvtarat viszont tudnunk kell olvasni
tiltott_kulcs = q.path_key(share)
os.scandir = tiltakozo_scandir
try:
    q.plan_tree(share, roots2, dirs2, q.DEFAULT_EXCLUDES)
    check("a vizsgalt konyvtar olvasasi hibaja megallit", "nem dobott hibat",
          "QbtError")
except q.QbtError:
    check("a vizsgalt konyvtar olvasasi hibaja megallit", "QbtError", "QbtError")
finally:
    os.scandir = eredeti_scandir

# --- force_remove: a konyvtarbol nem veheti el a belepesi (x) jogot, kulonben
#     a masodik torlesi probalkozas is elszallna
zart = Path(tmp) / "zart"
zart.mkdir()
(zart / "benne.txt").write_bytes(b"x")
os.chmod(str(zart), 0o500)
q.force_remove(lambda _p: None, str(zart))
check("force_remove: a konyvtar bejarhato marad",
      bool(stat.S_IMODE(os.stat(str(zart)).st_mode) & stat.S_IXUSR), True)
check("force_remove: es irhato is lett",
      bool(stat.S_IMODE(os.stat(str(zart)).st_mode) & stat.S_IWUSR), True)
shutil.rmtree(str(zart))

check("owner_target: ures konyvtarlista sem szall el",
      q.owner_target(Path("/a/b/c.mkv"), []), Path("/a/b"))
check("owner_target: a legkulso konyvtart valasztja",
      q.owner_target(Path("/a/b/c.mkv"), [Path("/a/b"), Path("/a")]), Path("/a"))

shutil.rmtree(str(tmp))

# ----------------------------------------------------- teljes futas (main)

def run_main(argv):
    out = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = out
    try:
        code = q.main(argv)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return code, out.getvalue()


tmp = Path(tempfile.mkdtemp(prefix="qbt-teszt-"))
share, rss = build_tree(tmp)
base = ["--url", URL, "--user", USER, "--password", PASSWORD,
        "--konyvtar", str(share), "--konyvtar", str(rss)]

code, out = run_main(base)
check("main: proba futas visszateresi ertek", code, 0)
check_true("main: kiirja, hogy semmit nem torolt", "csak proba" in out, out)
check_true("main: felsorolja a felesleges elemeket",
           "Regi.Film.2011" in out and "tavalyi.mkv" in out, out)
check("main: proba futas nem torolt", (share / "Regi.Film.2011").exists(), True)

code, out = run_main(base + ["--torol", "--igen", "--max-torles", "1"])
check("main: max-torles hatar leallit", code, 2)
check("main: a hatar miatt nem torolt", (share / "arvalt.mkv").exists(), True)

code, out = run_main(base + ["--torol"])
check("main: --igen nelkul, nem interaktivan leall", code, 2)
check("main: es nem torolt", (share / "arvalt.mkv").exists(), True)

# kukaba mozgatas - a kuka most szandekosan a vizsgalt konyvtaron belul van,
# igy az is kiderul, hogy sajat magat nem eszi meg
kuka = share / ".kuka"
code, out = run_main(base + ["--torol", "--igen", "--kuka", str(kuka)])
check("main: kukas futas", code, 0)
check("main: az elem elkerult", (share / "arvalt.mkv").exists(), False)
check("main: a kukaban megvan", (kuka / "arvalt.mkv").exists(), True)
check("main: az rss-beli elem a kukaban is az rss ala kerult",
      (kuka / "rss" / "tavalyi.mkv").exists(), True)
check("main: a kuka megmaradt", kuka.is_dir(), True)
check("main: a torrentes fajlok megvannak",
      (share / "Film.Egy.2024" / "film.mkv").exists()
      and (rss / "hetivideo.mkv").exists(), True)
check("main: az rss konyvtar megvan", rss.exists(), True)

# tenyleges torles: uj szemet, a kuka pedig kivetel
(share / "ujabb.szemet.mkv").write_bytes(b"h" * 32)
(share / "Masik.Regi.2012").mkdir()
(share / "Masik.Regi.2012" / "x.mkv").write_bytes(b"i" * 128)
code, out = run_main(base + ["--torol", "--igen", "--kivetel", ".kuka"])
check("main: torles visszateresi ertek", code, 0)
check("main: a felesleges konyvtar eltunt", (share / "Masik.Regi.2012").exists(),
      False)
check("main: a felesleges fajl eltunt", (share / "ujabb.szemet.mkv").exists(),
      False)
check("main: a kivetelnek jelolt kuka megmaradt", kuka.is_dir(), True)
check("main: a torrentes tartalom megmaradt",
      sorted(p.name for p in share.iterdir()),
      [".kuka", "@eaDir", "Film.Egy.2024", "Sorozat S01", "rss"])

code, out = run_main(base + ["--kivetel", ".kuka"])
check_true("main: masodszorra mar nincs mit tenni", "Nincs felesleges" in out, out)

# hibas jelszo: semmit nem szabad torolni
(share / "szemet.mkv").write_bytes(b"x")
code, out = run_main(["--url", URL, "--user", USER, "--password", "rossz",
                      "--konyvtar", str(share), "--torol", "--igen"])
check("main: rossz jelszo -> hibakod", code, 1)
check("main: rossz jelszonal nem torol", (share / "szemet.mkv").exists(), True)

# elerhetetlen kiszolgalo
code, out = run_main(["--url", "http://127.0.0.1:1", "--user", "a",
                      "--password", "b", "--konyvtar", str(share),
                      "--torol", "--igen", "--idokorlat", "2"])
check("main: elerhetetlen WebUI -> hibakod", code, 1)
check("main: elerhetetlen WebUI-nal nem torol", (share / "szemet.mkv").exists(),
      True)

# nem letezo konyvtar
code, out = run_main(["--url", URL, "--user", USER, "--password", PASSWORD,
                      "--konyvtar", str(tmp / "nincs-ilyen")])
check("main: nem letezo konyvtar -> 2", code, 2)

# ertelmetlen szamok: az argparse alljon le (2-es kod), ne "sikeres" futas
for rossz in (["--min-kor", "-1"], ["--idokorlat", "0"], ["--max-torles", "-5"]):
    try:
        code, out = run_main(base + rossz)
    except SystemExit as exc:  # argparse igy jelez
        code = exc.code
    check(f"main: {' '.join(rossz)} visszautasitva", code, 2)

# a 'fa' mod kapcsoloi 'felso' modban nem csendben vesznek el
code, out = run_main(base + ["--pontos"])
check_true("main: szol, ha a --pontos nem szamit", "--pontos csak a 'fa'" in out,
           out)

# kuka: ket azonos nevu elem kulonbozo helyrol - a masodik nem irhatja felul az
# elsot (egy masodpercen belul is)
kuka2 = Path(tmp) / "kuka2"
kuka2.mkdir()
forras = Path(tmp) / "forras"
(forras / "alatta").mkdir(parents=True)
(forras / "x.mkv").write_bytes(b"1")
(forras / "alatta" / "x.mkv").write_bytes(b"22")
ok1, _ = q.remove_entry(q.Candidate(forras / "x.mkv", False, 1), forras, kuka2)
ok2, _ = q.remove_entry(q.Candidate(forras / "alatta" / "x.mkv", False, 2),
                        forras / "alatta", kuka2)
check("kuka: mindket athelyezes sikerult", (ok1, ok2), (True, True))
check("kuka: az azonos nevu elem nem irta felul az elsot",
      sorted(p.stat().st_size for p in kuka2.iterdir()), [1, 2])
shutil.rmtree(str(forras))
shutil.rmtree(str(kuka2))

# 'fa' mod megfeleltetes nelkul: nem talal torrent-elemet, ezert leall
code, out = run_main(base + ["--mod", "fa", "--torol", "--igen"])
check("main: fa mod rossz utvonallal leall", code, 2)
check("main: es nem torolt", (share / "szemet.mkv").exists(), True)

# 'fa' mod helyes megfeleltetessel
code, out = run_main(base + ["--mod", "fa", "--pontos",
                             "--utvonal", "/downloads=" + str(share),
                             "--utvonal", "/downloads/rss=" + str(rss),
                             "--torol", "--igen"])
check("main: fa mod helyes utvonallal", code, 0)
check("main: fa mod torolte a szemetet", (share / "szemet.mkv").exists(), False)
check("main: fa+pontos mod az idegen fajlt is torolte",
      (share / "Film.Egy.2024" / "mintakep.jpg").exists(), False)
check("main: fa+pontos mod a torrent fajljait meghagyta",
      (share / "Film.Egy.2024" / "film.mkv").exists()
      and (share / "Film.Egy.2024" / "film.srt").exists(), True)

# torlesi naplo: a valodi torlesrol keszuljon bejegyzes
naplo_fajl = tmp / "naplo" / "torlesek.log"
(share / "naplozando.mkv").write_bytes(b"n" * 24)
code, out = run_main(base + ["--torol", "--igen", "--kivetel", ".kuka",
                             "--naplo", str(naplo_fajl)])
naplo_sorok = naplo_fajl.read_text(encoding="utf-8").splitlines()
check("main: a naplo elkeszult", naplo_fajl.is_file(), True)
check_true("main: kiirja a naplo helyet", str(naplo_fajl) in out, out)
naplozott = [s.split("\t") for s in naplo_sorok[1:]]
check("main: a torolt fajl bekerult a naploba",
      [(m[1], m[5]) for m in naplozott], [("torolve", "naplozando.mkv")])
check("main: a konyvtar oszlop a fajl helye", naplozott[0][4], str(share))
check("main: a meret is megvan", naplozott[0][3], "24")

# --nincs-naplo eseten ne keszuljon semmi
(share / "naplo.nelkul.mkv").write_bytes(b"n" * 8)
elozo_meret = naplo_fajl.stat().st_size
code, out = run_main(base + ["--torol", "--igen", "--kivetel", ".kuka",
                             "--naplo", str(naplo_fajl), "--nincs-naplo"])
check("main: --nincs-naplo eseten nem ir a naploba",
      naplo_fajl.stat().st_size, elozo_meret)
check("main: de a torles megtortent", (share / "naplo.nelkul.mkv").exists(),
      False)

# proba futas (nem torol) ne hozzon letre naplot
proba_naplo = tmp / "proba-naplo" / "torlesek.log"
run_main(base + ["--kivetel", ".kuka", "--naplo", str(proba_naplo)])
check("main: a proba futas nem nyit naplot", proba_naplo.exists(), False)

# irasvedett fajl (Samban eloszeretettel fordul elo) + ugyanaz a konyvtar
# ketszer megadva
ro = share / "irasvedett.mkv"
ro.write_bytes(b"j" * 16)
os.chmod(str(ro), 0o444)
code, out = run_main(base + ["--konyvtar", str(share), "--torol", "--igen"])
check("main: ismetelt --konyvtar nem okoz hibat", code, 0)
check("main: az irasvedett fajl is torlodott", ro.exists(), False)
check_true("main: nem volt sikertelen torles", "SIKERTELEN" not in out, out)

shutil.rmtree(str(tmp), ignore_errors=True)
server.shutdown()

print()
print("MINDEN QBT TESZT SIKERES" if not fail else "VOLT HIBA")
sys.exit(fail)
