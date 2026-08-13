#!/usr/bin/env python3
"""qBittorrent takarito - ami mar nincs a torrentek kozott, az mehet.

A program bejelentkezik egy qBittorrent WebUI-ba, lekeri, hogy eppen milyen
torrentek vannak benne (es azok milyen fajlokat / konyvtarakat hasznalnak),
majd a megadott konyvtar(ak)ban - peldaul egy Samba megosztason - megkeresi
azokat a fajlokat es konyvtarakat, amikhez nem tartozik torrent. Ezeket
alapbol csak KIIRJA; torolni kulon kapcsoloval (--torol) fog.

Kulso csomag nem kell hozza, csak Python 3.7 vagy ujabb.

Gyors pelda (eloszor mindig szarazon!):

    python qbt_cleanup.py --user admin ^
        --konyvtar \\\\192.168.1.38\\downloads ^
        --konyvtar \\\\192.168.1.38\\downloads\\rss

Ha jonak tunik a lista, ugyanaz a parancs a vegen: --torol --igen

A jelszot nem kotelezo a parancssorba irni: ha nincs megadva, bekeri
(vagy a QBT_PASSWORD kornyezeti valtozobol veszi).

Ket uzemmod van:

  --mod felso      (alapertelmezett) csak a megadott konyvtar(ak) legfelso
                   szintjet nezi, es a NEVEK alapjan dont: amelyik fajl vagy
                   konyvtar neve nem egyezik egyetlen torrent gyokerevel sem,
                   az felesleges. Ehhez nem kell tudni, hogy a qBittorrent
                   milyen utvonalon latja a fajlokat - ez a jo valasztas
                   akkor, ha a qBittorrent NAS-on / dokkerben fut, es maskepp
                   latja a konyvtarat, mint ez a gep.

  --mod fa         a teljes konyvtarfat bejarja, es a qBittorrent
                   utvonalaival veti ossze. Ehhez utvonal-megfeleltetes kell
                   (--utvonal), ha a qBittorrent maskepp latja a megosztast.
                   Peldaul a qBittorrent szerint /downloads, itt meg
                   \\\\192.168.1.38\\downloads:

                       --utvonal /downloads=\\\\192.168.1.38\\downloads

Tobb konyvtar is megadhato. Ezek automatikusan vedik egymast: ha a
\\\\192.168.1.38\\downloads\\rss is vizsgalt konyvtar, akkor a szulojenek
takaritasakor az "rss" mappat nem bantja a program.
"""

import argparse
import fnmatch
import getpass
import http.cookiejar
import json
import os
import shutil
import ssl
import stat
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "/api/v2"

# Ezeket soha nem bantjuk (a NAS vagy az operacios rendszer keszitette oket).
# Sajat minta a --kivetel kapcsoloval adhato hozza, ez a lista pedig a
# --nincs-gyari-kivetel kapcsoloval kapcsolhato ki.
DEFAULT_EXCLUDES = [
    ".recycle",
    "#recycle",
    "@Recycle",
    "@eaDir",
    ".@__thumb",
    "lost+found",
    ".Trash-*",
    "$RECYCLE.BIN",
    "System Volume Information",
    ".unwanted",  # ide teszi a qBittorrent a nem kert fajlokat
]

# A qBittorrent ezt biggyeszti a felkesz fajlok vegere (ha be van kapcsolva).
INCOMPLETE_SUFFIX = ".!qB"


class QbtError(Exception):
    """WebUI vagy fajlrendszer hiba - ilyenkor semmit nem torlunk."""


# ------------------------------------------------------------------ WebUI

class QbtClient:
    """A qBittorrent WebUI (v2 API) minimalis kliense, csak a szabvany
    konyvtarral."""

    def __init__(self, url, username=None, password=None, timeout=30,
                 insecure=False):
        self.base = url.rstrip("/")
        if not self.base.startswith(("http://", "https://")):
            self.base = "http://" + self.base
        self.username = username
        self.password = password
        self.timeout = timeout
        ctx = None
        if insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=ctx),
        )

    def _call(self, path, params=None, post=False):
        url = self.base + path
        data = None
        if params and post:
            data = urllib.parse.urlencode(params).encode("utf-8")
        elif params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, data=data)
        # A WebUI ellenorzi a keres eredetet (CSRF vedelem).
        req.add_header("Referer", self.base)
        req.add_header("Origin", self.base)
        req.add_header("User-Agent", "qbt_cleanup.py")
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace").strip()
            except Exception:  # pragma: no cover
                pass
            if exc.code == 403:
                raise QbtError(
                    "A WebUI elutasitotta a kerest (403). Rossz jelszo, lejart "
                    "munkamenet, vagy a WebUI-ban be van kapcsolva a kulso "
                    "hivatkozas tiltasa."
                ) from exc
            raise QbtError(
                "HTTP %s a %s hivasnal%s"
                % (exc.code, path, (": " + body) if body else "")
            ) from exc
        except urllib.error.URLError as exc:
            raise QbtError(
                "Nem sikerult elerni a qBittorrent WebUI-t (%s): %s"
                % (self.base, exc.reason)
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise QbtError("Halozati hiba a %s hivasnal: %s" % (path, exc)) from exc

    def login(self):
        """Bejelentkezes. Ures felhasznalonevnel kihagyjuk - van, ahol a helyi
        halozatrol nem ker azonositast a WebUI."""
        if not self.username:
            return
        answer = self._call(
            API + "/auth/login",
            {"username": self.username, "password": self.password or ""},
            post=True,
        ).strip()
        if answer.lower() != "ok.":
            raise QbtError(
                "Sikertelen bejelentkezes (a WebUI valasza: %r). Ellenorizd a "
                "felhasznalonevet es a jelszot." % answer
            )

    def version(self):
        return self._call(API + "/app/version").strip()

    def torrents(self):
        data = self._json(API + "/torrents/info", None, "torrents/info")
        if not isinstance(data, list):
            raise QbtError("Varatlan valasz a torrents/info hivasra")
        return data

    def files(self, torrent_hash):
        data = self._json(API + "/torrents/files", {"hash": torrent_hash},
                          "torrents/files")
        if not isinstance(data, list):
            raise QbtError("Varatlan fajllista a(z) %s torrenthez" % torrent_hash)
        return data

    def _json(self, path, params, what):
        text = self._call(path, params)
        try:
            return json.loads(text)
        except ValueError as exc:
            raise QbtError("Ertelmezhetetlen valasz a %s hivasra" % what) from exc


# --------------------------------------------------------- utvonal-kezeles

def norm_key(text, ignore_case=True):
    """Osszehasonlitashoz hasznalt alak. A Samba / macOS ugyanazt a nevet
    maskepp is kodolhatja (ekezetek), ezert egysegesitjuk, es alapbol a
    kis/nagybetut sem nezzuk - igy inkabb megtartunk valamit, mint hogy
    tevedesbol toroljuk."""
    text = unicodedata.normalize("NFC", text)
    return text.casefold() if ignore_case else text


def normalize_remote(path):
    """A qBittorrent Windows alatt visszafele dolo perjelet ad vissza; a UNC
    eleji ket perjelet megtartjuk."""
    if not path:
        return ""
    path = path.replace("\\", "/")
    prefix = ""
    if path.startswith("//"):
        prefix, path = "//", path[2:]
    while len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return prefix + path


# ------------------------------------------------------------------ konyvtar

def normalize_target(raw):
    """A megadott konyvtar egysegesitese. A UNC utvonalat (\\\\gep\\megosztas)
    nem 'oldjuk fel', mert a resolve() halozati megosztason lassu lehet es
    Windowson at is irhatja az alakjat; csak a felesleges vegzodest vagjuk le."""
    path = Path(os.path.expanduser(str(raw)))
    text = str(path)
    if not text.startswith("\\\\") and not text.startswith("//"):
        try:
            path = path.resolve()
        except OSError:
            path = Path(os.path.abspath(text))
    return path


def is_unc(path):
    text = str(path)
    return text.startswith("\\\\") or text.startswith("//")


def is_root_like(path):
    """Gyoker konyvtar (/, C:\\), amit biztonsagi okbol nem takaritunk. A UNC
    megosztas gyokere (\\\\gep\\megosztas) viszont rendben van - tipikusan pont
    az a letoltesi konyvtar."""
    if is_unc(path):
        # \\gep\megosztas maga rendben; a \\gep resze mar nem letezo konyvtar
        return False
    return len(path.parts) < 2 or str(path) == path.anchor


def parse_map(entry):
    """A '--utvonal TAVOLI=HELYI' feldolgozasa. Az elso egyenlosegjelnel
    vagunk, igy a helyi oldal lehet meghajtobetus (D:\\letoltes) vagy UNC
    (\\\\gep\\megosztas) utvonal is."""
    if "=" not in entry:
        raise ValueError(
            "Az utvonal-megfeleltetes alakja: TAVOLI=HELYI (pl. "
            "/downloads=\\\\192.168.1.38\\downloads)"
        )
    remote, local = entry.split("=", 1)
    remote = normalize_remote(remote.strip())
    local = local.strip()
    if not remote or not local:
        raise ValueError("Ures utvonal a megfeleltetesben: %r" % entry)
    # A helyi oldalt ugyanugy egysegesitjuk, mint a --konyvtar erteket,
    # kulonben ket alakban allna ugyanaz az utvonal, es semmi nem egyezne.
    return (remote, str(normalize_target(local)))


def apply_maps(remote_path, maps):
    """A qBittorrent utvonalabol helyi utvonal. Ha nincs szabaly, valtozatlanul
    hagyjuk. Ha van szabaly, de egyik sem illik ra, None (nem itt van)."""
    remote_path = normalize_remote(remote_path)
    if not remote_path:
        return None
    if not maps:
        return remote_path
    key = norm_key(remote_path)
    # A leghosszabb (legpontosabb) illeszkedes nyer.
    for src, dst in sorted(maps, key=lambda m: len(m[0]), reverse=True):
        src_key = norm_key(src).rstrip("/")
        if key == src_key:
            return dst
        if key.startswith(src_key + "/"):
            rest = remote_path[len(src.rstrip("/")) + 1:]
            return str(Path(dst) / rest)
    return None


def root_name(torrent):
    """A torrent gyoker-eleme: az a fajl vagy konyvtar, ami a mentesi
    konyvtarban letrejon."""
    content = normalize_remote(torrent.get("content_path") or "")
    save = normalize_remote(torrent.get("save_path") or "")
    if content and save:
        save_slash = save.rstrip("/") + "/"
        if norm_key(content).startswith(norm_key(save_slash)):
            first = content[len(save_slash):].split("/", 1)[0]
            if first:
                return first
    if content:
        return content.rsplit("/", 1)[-1]
    return (torrent.get("name") or "").strip()


def owned_names(torrents, ignore_case=True):
    """A torrentek gyoker-neveinek halmaza (a 'felso' modhoz)."""
    names = set()
    for torrent in torrents:
        name = root_name(torrent)
        if name:
            names.add(norm_key(name, ignore_case))
            names.add(norm_key(name + INCOMPLETE_SUFFIX, ignore_case))
    return names


def owned_paths(torrents, files_by_hash, maps, target, ignore_case=True):
    """Azok a helyi utvonalak, amik a qBittorrenthez tartoznak.

    Ket halmazt ad vissza:
      roots - ezek (es ami alattuk van) erintetlenek maradnak,
      dirs  - ezekbe bele kell nezni, mert alattuk van megtartando elem.
    """
    roots = set()
    dirs = set()
    target = Path(target)
    target_key = norm_key(str(target), ignore_case).rstrip("/\\")

    def under_target(key):
        return key == target_key or key.startswith(target_key + norm_key(os.sep))

    def add(remote):
        local = apply_maps(remote, maps)
        if not local:
            return
        try:
            local_path = Path(local)
        except (OSError, ValueError):
            return
        key = norm_key(str(local_path), ignore_case).rstrip("/\\")
        if not under_target(key):
            return  # nem a vizsgalt konyvtarban van
        roots.add(key)
        parent = local_path.parent
        while True:
            pkey = norm_key(str(parent), ignore_case).rstrip("/\\")
            dirs.add(pkey)
            if pkey == target_key or parent == parent.parent:
                break
            parent = parent.parent

    for torrent in torrents:
        save = normalize_remote(torrent.get("save_path") or "")
        download = normalize_remote(torrent.get("download_path") or "")
        content = normalize_remote(torrent.get("content_path") or "")
        name = root_name(torrent)
        files = files_by_hash.get(torrent.get("hash") or "")

        if files:
            # Pontos mod: fajlonkent. Igy a torrent sajat konyvtaraban levo
            # idegen fajl is felesleges elemnek szamit.
            for item in files:
                rel = normalize_remote(item.get("name") or "")
                if not rel:
                    continue
                for base in (save, download):
                    if base:
                        add(base + "/" + rel)
                        add(base + "/" + rel + INCOMPLETE_SUFFIX)
        else:
            # A tenyleges hely a legpontosabb, de a befejezetlen torrent mas
            # konyvtarban is lehet, ezert minden szoba johetot felveszunk.
            if content:
                add(content)
            for base in (save, download):
                if base and name:
                    add(base + "/" + name)

    return roots, dirs


# ---------------------------------------------------------------- tervezes

class Candidate:
    """Egy torlesre jelolt elem."""

    def __init__(self, path, is_dir, size, reason=""):
        self.path = Path(path)
        self.is_dir = is_dir
        self.size = size
        self.reason = reason

    def __repr__(self):  # pragma: no cover - csak hibakeresehez
        return "Candidate(%r, dir=%s, size=%d)" % (
            str(self.path), self.is_dir, self.size)


def entry_size(path, is_dir):
    """Egy fajl vagy egy egesz konyvtar merete bajtban."""
    if not is_dir:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        # Szimbolikus linkbe nem megyunk bele.
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in files:
            full = os.path.join(root, name)
            try:
                if not os.path.islink(full):
                    total += os.path.getsize(full)
            except OSError:
                pass
    return total


def is_excluded(name, patterns, ignore_case=True):
    key = norm_key(name, ignore_case)
    for pattern in patterns:
        if fnmatch.fnmatchcase(key, norm_key(pattern, ignore_case)):
            return True
    return False


def too_young(path, min_age_days):
    """Frissen modositott elem: hagyjuk beken (pl. eppen most kerult oda)."""
    if min_age_days <= 0:
        return False
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return False
    return (time.time() - mtime) < min_age_days * 86400


def scandir_sorted(path):
    try:
        with os.scandir(path) as it:
            return sorted(it, key=lambda e: e.name)
    except OSError as exc:
        raise QbtError("Nem tudom beolvasni a konyvtarat (%s): %s" % (path, exc))


def plan_toplevel(target, names, excludes, ignore_case=True, min_age_days=0,
                  protected=()):
    """Csak a legfelso szint, nevek alapjan."""
    out = []
    protected_keys = {norm_key(str(p), ignore_case).rstrip("/\\") for p in protected}
    for entry in scandir_sorted(target):
        full = Path(target) / entry.name
        if norm_key(str(full), ignore_case).rstrip("/\\") in protected_keys:
            continue
        if is_excluded(entry.name, excludes, ignore_case):
            continue
        if norm_key(entry.name, ignore_case) in names:
            continue
        if too_young(full, min_age_days):
            continue
        if entry.is_symlink():
            out.append(Candidate(full, False, 0, "nem tartozik torrenthez (link)"))
            continue
        is_dir = entry.is_dir(follow_symlinks=False)
        out.append(Candidate(full, is_dir, entry_size(full, is_dir),
                             "nem tartozik torrenthez"))
    return out


def plan_tree(target, roots, dirs, excludes, ignore_case=True, min_age_days=0,
              protected=()):
    """Teljes konyvtarfa, utvonalak alapjan."""
    out = []
    protected_keys = {norm_key(str(p), ignore_case).rstrip("/\\") for p in protected}

    def walk(path):
        for entry in scandir_sorted(path):
            full = Path(path) / entry.name
            key = norm_key(str(full), ignore_case).rstrip("/\\")
            if key in protected_keys:
                continue
            if is_excluded(entry.name, excludes, ignore_case):
                continue
            if key in roots:
                continue  # a torrente: se o, se ami alatta van
            if entry.is_symlink():
                if key not in dirs:
                    out.append(Candidate(full, False, 0,
                                         "nem tartozik torrenthez (link)"))
                continue
            is_dir = entry.is_dir(follow_symlinks=False)
            if is_dir and key in dirs:
                walk(full)  # van alatta megtartando elem
                continue
            if too_young(full, min_age_days):
                continue
            out.append(Candidate(full, is_dir, entry_size(full, is_dir),
                                 "nem tartozik torrenthez"))

    walk(Path(target))
    return out


# ------------------------------------------------------------------ torles

def human(size):
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            return "%d B" % size if unit == "B" else "%.1f %s" % (value, unit)
        value /= 1024
    return "%d B" % size  # pragma: no cover


def force_remove(func, path, _exc):
    """A megosztason az irasvedett jelzo miatt is elszallhat a torles: levesszuk
    a jelzot, es ujraprobaljuk."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    func(path)


def rmtree(path):
    """Konyvtar torlese az irasvedett fajlok kezelesevel egyutt."""
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=force_remove)
    else:
        shutil.rmtree(path, onerror=force_remove)


def remove_file(path):
    try:
        os.remove(path)
    except PermissionError:
        force_remove(os.remove, path, None)


def remove_entry(candidate, target, trash_dir=None):
    """Torles, vagy athelyezes a kukaba. Kivetelt nem dob: (siker, uzenet)."""
    path = candidate.path
    try:
        if trash_dir:
            try:
                rel = path.relative_to(Path(target))
            except ValueError:
                rel = Path(path.name)
            dest = Path(trash_dir) / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() or dest.is_symlink():
                dest = dest.with_name(
                    "%s.%s" % (dest.name, time.strftime("%Y%m%d-%H%M%S")))
            shutil.move(str(path), str(dest))
            return True, "kukaba: %s" % dest
        if path.is_symlink() or not candidate.is_dir:
            remove_file(path)
        else:
            rmtree(path)
        return True, "torolve"
    except OSError as exc:
        return False, "SIKERTELEN: %s" % exc


# --------------------------------------------------------------------- main

def build_parser():
    parser = argparse.ArgumentParser(
        prog="qbt_cleanup.py",
        description="A qBittorrentben mar nem szereplo fajlok es konyvtarak "
                    "kilistazasa, majd kulon keresre torlese.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Alapbol SEMMIT nem torol, csak kiirja, mit torolne. "
               "A tenyleges torleshez: --torol",
    )
    parser.add_argument("--url", default=os.environ.get(
        "QBT_URL", "http://192.168.1.38:30024/"),
        help="a qBittorrent WebUI cime (alap: %(default)s)")
    parser.add_argument("--user", default=os.environ.get("QBT_USER", ""),
                        help="WebUI felhasznalonev (ures: nem jelentkezik be)")
    parser.add_argument("--password", default=None,
                        help="WebUI jelszo (ha nincs: QBT_PASSWORD, vagy bekeri)")
    parser.add_argument("--konyvtar", "--dir", dest="konyvtarak", required=True,
                        action="append", metavar="KONYVTAR",
                        help="a vizsgalando konyvtar; tobbszor is megadhato "
                             "(az egymasba agyazottak vedik egymast)")
    parser.add_argument("--mod", choices=("felso", "fa"), default="felso",
                        help="felso: csak a legfelso szint, nevek alapjan "
                             "(alap); fa: teljes konyvtarfa, utvonalak alapjan")
    parser.add_argument("--utvonal", action="append", default=[],
                        metavar="TAVOLI=HELYI",
                        help="utvonal-megfeleltetes a 'fa' modhoz, tobbszor is "
                             "megadhato (pl. /downloads=D:\\\\letoltes)")
    parser.add_argument("--pontos", action="store_true",
                        help="'fa' modban fajlonkent kerdezi le a torrenteket, "
                             "igy a torrent sajat konyvtaraban levo idegen "
                             "fajlok is feleslegesnek szamitanak")
    parser.add_argument("--kivetel", action="append", default=[], metavar="MINTA",
                        help="soha ne bantsa (mintaillesztes a nevre), tobbszor")
    parser.add_argument("--nincs-gyari-kivetel", dest="no_default_excludes",
                        action="store_true",
                        help="a gyari kivetel-lista (NAS mappak) kikapcsolasa")
    parser.add_argument("--min-kor", dest="min_age", type=float, default=0,
                        metavar="NAP",
                        help="csak az ennel regebben modositott elemeket "
                             "torolje (alap: 0 = mindegy)")
    parser.add_argument("--kuka", default=None, metavar="KONYVTAR",
                        help="torles helyett ide mozgassa az elemeket")
    parser.add_argument("--max-torles", dest="max_delete", type=int, default=0,
                        metavar="DB",
                        help="ha ennel tobb elemet torolne, inkabb alljon le "
                             "(alap: 0 = nincs korlat)")
    parser.add_argument("--torol", action="store_true",
                        help="tenylegesen toroljon (enelkul csak kiir)")
    parser.add_argument("--igen", action="store_true",
                        help="ne kerdezzen ra a torlesre")
    parser.add_argument("--ures-lista-ok", dest="allow_empty", action="store_true",
                        help="akkor is dolgozzon, ha egyetlen torrentet sem "
                             "talalt (VESZELYES: mindent torolne)")
    parser.add_argument("--kis-nagy-betu", dest="case_sensitive",
                        action="store_true",
                        help="a nevek osszehasonlitasanal szamitson a kis- es "
                             "nagybetu (alap: nem szamit)")
    parser.add_argument("--nem-biztonsagos-tls", dest="insecure",
                        action="store_true",
                        help="https-nel ne ellenorizze a tanusitvanyt")
    parser.add_argument("--idokorlat", dest="timeout", type=float, default=30,
                        metavar="MP", help="halozati idokorlat (alap: 30 mp)")
    return parser


def confirm(count, size, trash_dir):
    print()
    what = ("athelyez a kukaba (%s)" % trash_dir) if trash_dir else "TOROL VEGLEG"
    print("Ez %d elemet %s, osszesen %s." % (count, what, human(size)))
    try:
        answer = input("Biztos? Ird be, hogy 'igen': ").strip().lower()
    except EOFError:
        return False
    return answer in ("igen", "i", "yes", "y")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover
            pass

    args = build_parser().parse_args(argv)
    ignore_case = not args.case_sensitive

    targets = []
    for raw in args.konyvtarak:
        target = normalize_target(raw)
        if not target.exists():
            print("Nincs ilyen konyvtar: %s" % target, file=sys.stderr)
            return 2
        if not target.is_dir():
            print("Nem konyvtar: %s" % target, file=sys.stderr)
            return 2
        if is_root_like(target):
            print("Biztonsagi okbol a gyoker konyvtarat nem takaritom: %s"
                  % target, file=sys.stderr)
            return 2
        # Ugyanaz a konyvtar ketszer megadva ketszer is torolne (masodszor mar
        # hibaval), ezert csak egyszer vesszuk fel.
        if not any(norm_key(str(target), ignore_case) == norm_key(str(t), ignore_case)
                   for t in targets):
            targets.append(target)

    try:
        maps = [parse_map(entry) for entry in args.utvonal]
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    excludes = list(args.kivetel)
    if not args.no_default_excludes:
        excludes += DEFAULT_EXCLUDES

    trash_dir = None
    if args.kuka:
        trash_dir = normalize_target(args.kuka)
        try:
            trash_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print("Nem tudom letrehozni a kukat (%s): %s" % (trash_dir, exc),
                  file=sys.stderr)
            return 2
        if any(trash_dir == t for t in targets):
            print("A kuka nem lehet maga a vizsgalt konyvtar.", file=sys.stderr)
            return 2

    password = args.password
    if password is None:
        password = os.environ.get("QBT_PASSWORD")
    if args.user and password is None:
        if sys.stdin.isatty():
            password = getpass.getpass("qBittorrent jelszo (%s): " % args.user)
        else:
            print("Nincs jelszo (--password vagy QBT_PASSWORD).", file=sys.stderr)
            return 2

    client = QbtClient(args.url, args.user, password, args.timeout, args.insecure)
    try:
        client.login()
        version = client.version()
        torrents = client.torrents()
        files_by_hash = {}
        if args.mod == "fa" and args.pontos:
            for torrent in torrents:
                thash = torrent.get("hash") or ""
                if thash:
                    files_by_hash[thash] = client.files(thash)
    except QbtError as exc:
        print("Hiba: %s" % exc, file=sys.stderr)
        print("Semmit nem toroltem.", file=sys.stderr)
        return 1

    print("qBittorrent %s (%s) - %d torrent"
          % (version, client.base, len(torrents)))
    print("Uzemmod: %s%s"
          % (args.mod, " (pontos)" if args.pontos and args.mod == "fa" else ""))
    for target in targets:
        print("Vizsgalt konyvtar: %s" % target)

    if not torrents and not args.allow_empty:
        print()
        print("A qBittorrentben egyetlen torrent sincs, igy MINDENT torolne. "
              "Ha tenyleg ezt akarod: --ures-lista-ok", file=sys.stderr)
        return 2

    names = owned_names(torrents, ignore_case) if args.mod == "felso" else set()

    candidates = []
    try:
        for target in targets:
            protected = [t for t in targets if t != target]
            if trash_dir:
                protected.append(trash_dir)
            if args.mod == "felso":
                found = plan_toplevel(target, names, excludes, ignore_case,
                                      args.min_age, protected)
            else:
                roots, dirs = owned_paths(torrents, files_by_hash, maps, target,
                                          ignore_case)
                print("A(z) %s alatt talalt torrent-elemek: %d"
                      % (target, len(roots)))
                if not roots and not args.allow_empty:
                    print()
                    print("Egyetlen torrent-elem sem esik a(z) %s konyvtarba. "
                          "Valoszinuleg utvonal-megfeleltetes kell (--utvonal "
                          "TAVOLI=HELYI). Igy MINDENT torolne, ezert leallok. "
                          "Ha tenyleg ezt akarod: --ures-lista-ok" % target,
                          file=sys.stderr)
                    return 2
                found = plan_tree(target, roots, dirs, excludes, ignore_case,
                                  args.min_age, protected)
            candidates.extend(found)
    except QbtError as exc:
        print("Hiba: %s" % exc, file=sys.stderr)
        print("Semmit nem toroltem.", file=sys.stderr)
        return 1

    total = sum(c.size for c in candidates)
    print()
    if not candidates:
        print("Nincs felesleges elem - nincs mit tenni.")
        return 0

    print("Felesleges elemek (%d db, %s):" % (len(candidates), human(total)))
    for cand in candidates:
        print("  [%s] %10s  %s" % ("D" if cand.is_dir else "F",
                                   human(cand.size), cand.path))

    if not args.torol:
        print()
        print("Ez csak proba volt, semmit nem toroltem. "
              "Tenyleges torleshez tedd hozza: --torol")
        return 0

    if args.max_delete and len(candidates) > args.max_delete:
        print()
        print("Tobb elemet torolne (%d), mint a megadott hatar (%d). Leallok."
              % (len(candidates), args.max_delete), file=sys.stderr)
        return 2

    if not args.igen:
        if not sys.stdin.isatty():
            print("Nem interaktiv futas: a torleshez --igen kell.",
                  file=sys.stderr)
            return 2
        if not confirm(len(candidates), total, trash_dir):
            print("Megsem toroltem semmit.")
            return 0

    print()
    freed = 0
    failed = 0
    # Kukazasnal a legkulso vizsgalt konyvtarhoz kepest szamoljuk az utvonalat,
    # igy az egymasba agyazott konyvtarak szerkezete megmarad a kukaban is
    # (pl. rss\tavalyi.mkv), es nem utik egymast az azonos nevu fajlok.
    owners = sorted(targets, key=lambda t: len(str(t)))
    for cand in candidates:
        owner = next((t for t in owners if t in cand.path.parents), owners[0])
        ok, message = remove_entry(cand, owner, trash_dir)
        if ok:
            freed += cand.size
        else:
            failed += 1
        print("  %10s  %s  (%s)" % (human(cand.size), cand.path, message))

    print()
    print("Kesz: %d elem, %s felszabadulva.%s"
          % (len(candidates) - failed, human(freed),
             ("  %d elem sikertelen!" % failed) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
