#!/usr/bin/env python3
"""qBittorrent takarito - ami mar nincs a torrentek kozott, az mehet.

A program bejelentkezik egy qBittorrent WebUI-ba, lekeri, hogy eppen milyen
torrentek vannak benne (es azok milyen fajlokat / konyvtarakat hasznalnak),
majd a megadott konyvtar(ak)ban - peldaul egy Samba megosztason - megkeresi
azokat a fajlokat es konyvtarakat, amikhez nem tartozik torrent. Ezeket
alapbol csak KIIRJA; torolni kulon kapcsoloval (--torol) fog.

Kulso csomag nem kell hozza, csak Python 3.10 vagy ujabb.

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

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import functools
import getpass
import http.cookiejar
import itertools
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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import qbt_naplo

API = "/api/v2"

# Ennel regebbi Pythonon a program nem indul el (a regebbi kiadasok mar nem
# kapnak biztonsagi javitast sem).
MIN_PYTHON = (3, 10)

# Ezeket soha nem bantjuk (a NAS vagy az operacios rendszer keszitette oket).
# Sajat minta a --kivetel kapcsoloval adhato hozza, ez a lista pedig a
# --nincs-gyari-kivetel kapcsoloval kapcsolhato ki.
DEFAULT_EXCLUDES: tuple[str, ...] = (
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
)

# A qBittorrent ezt biggyeszti a felkesz fajlok vegere (ha be van kapcsolva).
INCOMPLETE_SUFFIX = ".!qB"

# Windowson egy utvonal alapbol 260 karakter lehet - egy hosszu kiadasi nev es
# egy alkonyvtar (Subs, Sample) ezt konnyen atlepi, es akkor a fajl "nem
# letezik" a program szamara. A "\\?\" eloteg feloldja a korlatot (kb. 32000
# karakterig). Csak akkor tesszuk ki, ha tenyleg hosszu az ut: az eloteges
# alakot a rendszer nyersen veszi (nincs / -> \ atirasa, nincs "." es ".."),
# ezert felesleges kockazat lenne mindenhol hasznalni.
WINDOWS_UT_HATAR = 240

# A qBittorrent egy torrentjenek leiroja (a WebUI JSON valasza), illetve egy
# utvonal-megfeleltetes: (a qBittorrent szerinti ut, a helyi ut).
Torrent = Mapping[str, Any]
PathMap = tuple[str, str]


class QbtError(Exception):
    """WebUI vagy fajlrendszer hiba - ilyenkor semmit nem torlunk."""


class SafetyStop(QbtError):
    """Biztonsagi fek: a beallitasokbol az kovetkezne, hogy szinte mindent
    torolne (nincs torrent, vagy rossz az utvonal-megfeleltetes)."""


# ------------------------------------------------------------------ WebUI

class QbtClient:
    """A qBittorrent WebUI (v2 API) minimalis kliense, csak a szabvany
    konyvtarral."""

    def __init__(
        self,
        url: str,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30,
        insecure: bool = False,
    ) -> None:
        self.base = url.rstrip("/")
        if not self.base.startswith(("http://", "https://")):
            self.base = "http://" + self.base
        self.username = username
        self.password = password
        self.timeout = timeout
        ctx: ssl.SSLContext | None = None
        if insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=ctx),
        )

    def _call(
        self,
        path: str,
        params: dict[str, str] | None = None,
        post: bool = False,
    ) -> str:
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
            with contextlib.suppress(OSError):  # a valasz mar elszallhatott
                body = exc.read().decode("utf-8", "replace").strip()
            if exc.code == 403:
                raise QbtError(
                    "A WebUI elutasitotta a kerest (403). Rossz jelszo, lejart "
                    "munkamenet, vagy a WebUI-ban be van kapcsolva a kulso "
                    "hivatkozas tiltasa."
                ) from exc
            raise QbtError(
                f"HTTP {exc.code} a {path} hivasnal"
                + (f": {body}" if body else "")
            ) from exc
        except urllib.error.URLError as exc:
            raise QbtError(
                f"Nem sikerult elerni a qBittorrent WebUI-t ({self.base}): "
                f"{exc.reason}"
            ) from exc
        except OSError as exc:
            raise QbtError(f"Halozati hiba a {path} hivasnal: {exc}") from exc

    def login(self) -> None:
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
                f"Sikertelen bejelentkezes (a WebUI valasza: {answer!r}). "
                "Ellenorizd a felhasznalonevet es a jelszot."
            )

    def version(self) -> str:
        return self._call(API + "/app/version").strip()

    def torrents(self) -> list[dict[str, Any]]:
        data = self._json(API + "/torrents/info", None, "torrents/info")
        if not isinstance(data, list):
            raise QbtError("Varatlan valasz a torrents/info hivasra")
        return data

    def files(self, torrent_hash: str) -> list[dict[str, Any]]:
        data = self._json(API + "/torrents/files", {"hash": torrent_hash},
                          "torrents/files")
        if not isinstance(data, list):
            raise QbtError(f"Varatlan fajllista a(z) {torrent_hash} torrenthez")
        return data

    def _json(self, path: str, params: dict[str, str] | None, what: str) -> Any:
        text = self._call(path, params)
        try:
            return json.loads(text)
        except ValueError as exc:
            raise QbtError(f"Ertelmezhetetlen valasz a {what} hivasra") from exc


# --------------------------------------------------------- utvonal-kezeles

def _nfc(text: str) -> str:
    """Egysegesitett Unicode alak. A Samba / macOS ugyanazt az ekezetes betut
    ketfelekeppen is tarolhatja ("o" + kalap, vagy egyben)."""
    return unicodedata.normalize("NFC", text)


def norm_key(text: str, ignore_case: bool = True) -> str:
    """Osszehasonlitashoz hasznalt alak. A Samba / macOS ugyanazt a nevet
    maskepp is kodolhatja (ekezetek), ezert egysegesitjuk, es alapbol a
    kis/nagybetut sem nezzuk - igy inkabb megtartunk valamit, mint hogy
    tevedesbol toroljuk."""
    text = _nfc(text)
    return text.casefold() if ignore_case else text


def path_key(value: str | os.PathLike[str], ignore_case: bool = True) -> str:
    """Egy teljes utvonal osszehasonlitasi kulcsa.

    A Windows visszafele dolo perjelet hasznal, a qBittorrent (es a UNC alak)
    viszont elore dolot. Ha a ketto keveredik, egyetlen utvonal sem egyezne
    meg, es a program a torrentekhez tartozo fajlokat is feleslegesnek latna -
    ezert itt egysegesitjuk, es a vegzodo perjelet is levagjuk.
    """
    text = str(value).replace("\\", "/")
    while len(text) > 1 and text.endswith("/"):
        text = text[:-1]
    return norm_key(text, ignore_case)


def under(key: str, parent_key: str) -> bool:
    """Igaz, ha a `key` maga a `parent_key`, vagy alatta van. Mindketto
    path_key() alakban var."""
    if key == parent_key:
        return True
    prefix = parent_key if parent_key.endswith("/") else parent_key + "/"
    return key.startswith(prefix)


def strip_prefix(text: str, prefix: str, ignore_case: bool = True) -> str | None:
    """A `text` maradeka a `prefix` utan, vagy None, ha nem azzal kezdodik.

    Azert kell ehhez kulon fuggveny, mert a levagas hosszal dolgozik, a
    normalizalas viszont valtoztathat a hosszon: a casefold() peldaul a nemet
    "sz"-bol ket betut csinal, az ekezetek osszevonasa pedig rovidit. Ha a
    hasonlitas a normalizalt, a levagas meg az eredeti alakon tortenne (mint
    korabban), akkor mas helyre esne a vagas, es hibas utvonal jonne ki.
    Ezert eloszor mindket oldalt NFC-re hozzuk - ez rogziti a hosszakat -, es
    csak az igy kimert eleje-reszt vetjuk ossze.
    """
    text_nfc = _nfc(text)
    prefix_nfc = _nfc(prefix)
    head = text_nfc[:len(prefix_nfc)]
    if len(head) < len(prefix_nfc):
        return None
    same = (head.casefold() == prefix_nfc.casefold() if ignore_case
            else head == prefix_nfc)
    return text_nfc[len(prefix_nfc):] if same else None


def normalize_remote(path: str) -> str:
    """A qBittorrent Windows alatt visszafele dolo perjelet ad vissza; a UNC
    eleji ket perjelet megtartjuk."""
    if not path:
        return ""
    text = str(path).replace("\\", "/")
    prefix = ""
    if text.startswith("//"):
        prefix, text = "//", text[2:]
    while "//" in text:  # a dupla perjel kulonben elrontana az osszevetest
        text = text.replace("//", "/")
    while len(text) > 1 and text.endswith("/"):
        text = text[:-1]
    return prefix + text


# ------------------------------------------------------------------ konyvtar

def hosszu_ut(path: str | os.PathLike[str]) -> str:
    r"""A fajlrendszeri hivasokhoz hasznalt alak.

    Windowson a tul hosszu utvonalat \\?\ (halozati megosztasnal \\?\UNC\)
    eloteggel adjuk at, kulonben a 260 karakteres korlat miatt "nem letezo"
    fajlt jelentene a rendszer. Mashol valtozatlanul hagyjuk."""
    szoveg = os.fspath(path)
    if sys.platform != "win32":
        return szoveg
    if len(szoveg) < WINDOWS_UT_HATAR or szoveg.startswith("\\\\?\\"):
        return szoveg
    # Az eloteges alak csak abszolut, visszafele dolo perjeles utat fogad el.
    szoveg = os.path.abspath(szoveg)
    if szoveg.startswith("\\\\"):  # \\gep\megosztas -> \\?\UNC\gep\megosztas
        return "\\\\?\\UNC\\" + szoveg[2:]
    return "\\\\?\\" + szoveg


def normalize_target(raw: str | os.PathLike[str]) -> Path:
    """A megadott konyvtar egysegesitese. A UNC utvonalat (\\\\gep\\megosztas)
    nem 'oldjuk fel', mert a resolve() halozati megosztason lassu lehet es
    Windowson at is irhatja az alakjat; csak a felesleges vegzodest vagjuk le."""
    path = Path(os.path.expanduser(str(raw)))
    text = str(path)
    if not text.startswith(("\\\\", "//")):
        try:
            path = path.resolve()
        except OSError:
            path = Path(os.path.abspath(text))
    return path


def is_unc(path: str | os.PathLike[str]) -> bool:
    return str(path).startswith(("\\\\", "//"))


def is_root_like(path: Path) -> bool:
    """Gyoker konyvtar (/, C:\\), amit biztonsagi okbol nem takaritunk. A UNC
    megosztas gyokere (\\\\gep\\megosztas) viszont rendben van - tipikusan pont
    az a letoltesi konyvtar."""
    if is_unc(path):
        # \\gep\megosztas maga rendben; a \\gep resze mar nem letezo konyvtar
        return False
    return len(path.parts) < 2 or str(path) == path.anchor


def parse_map(entry: str) -> PathMap:
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
        raise ValueError(f"Ures utvonal a megfeleltetesben: {entry!r}")
    # A helyi oldalt ugyanugy egysegesitjuk, mint a --konyvtar erteket,
    # kulonben ket alakban allna ugyanaz az utvonal, es semmi nem egyezne.
    return (remote, str(normalize_target(local)))


@functools.lru_cache(maxsize=16)
def _rendezett_maps(maps: tuple[PathMap, ...]) -> tuple[tuple[str, str, str], ...]:
    """A megfeleltetesek elokeszitett, sorbarendezett alakja.

    A leghosszabb (legpontosabb) illeszkedes nyer, ezert hossz szerint
    rendezunk. Ezt - es az egysegesitest - egyszer vegezzuk el, nem minden
    egyes fajlnal ujra: 'fajlonkent' modban ez tizezerszer futna le.
    Az eredmeny: (a hasonlitashoz hasznalt eleje, a tiszta tavoli ut, a helyi
    ut)."""
    elemek = []
    for src, dst in sorted(maps, key=lambda m: len(m[0]), reverse=True):
        tiszta = normalize_remote(src)
        prefix = tiszta if tiszta.endswith("/") else tiszta + "/"
        elemek.append((prefix, tiszta, dst))
    return tuple(elemek)


def apply_maps(
    remote_path: str,
    maps: Sequence[PathMap],
    ignore_case: bool = True,
) -> str | None:
    """A qBittorrent utvonalabol helyi utvonal. Ha nincs szabaly, valtozatlanul
    hagyjuk. Ha van szabaly, de egyik sem illik ra, None (nem itt van)."""
    remote = normalize_remote(remote_path)
    if not remote:
        return None
    if not maps:
        return remote
    remote_kulcs = norm_key(remote, ignore_case)
    for prefix, tiszta, dst in _rendezett_maps(tuple(maps)):
        if remote_kulcs == norm_key(tiszta, ignore_case):
            return dst
        rest = strip_prefix(remote, prefix, ignore_case)
        if rest:
            return str(Path(dst) / rest)
    return None


def root_name(torrent: Torrent, ignore_case: bool = True) -> str:
    """A torrent gyoker-eleme: az a fajl vagy konyvtar, ami a mentesi
    konyvtarban letrejon."""
    content = normalize_remote(torrent.get("content_path") or "")
    save = normalize_remote(torrent.get("save_path") or "")
    if content and save:
        rest = strip_prefix(content, save.rstrip("/") + "/", ignore_case)
        if rest:
            first = rest.split("/", 1)[0]
            if first:
                return first
    if content:
        return content.rsplit("/", 1)[-1]
    return (torrent.get("name") or "").strip()


def kesz_kulcs(kulcs: str, ignore_case: bool = True) -> str:
    """A felkesz letoltes nevebol a vegleges nev.

    A qBittorrent a meg tolto fajl vegere .!qB-t biggyeszt. A torrent adataiban
    a VEGLEGES nev szerepel, a lemezen viszont a .!qB-s - ezert a vegzodest az
    osszehasonlitas elott vagjuk le.

    Szandekosan itt, egyetlen helyen: korabban minden felvetelnel kulon kellett
    volna felvenni a .!qB-s valtozatot is, es pont az volt a hiba, hogy az
    egyik agban lemaradt - igy a 'fa' mod letorolte a folyamatban levo
    letoltest. Raadasul igy fele akkora a halmaz, amit fejben kell tartani."""
    veg = norm_key(INCOMPLETE_SUFFIX, ignore_case)
    return kulcs[:-len(veg)] if kulcs.endswith(veg) else kulcs


def owned_names(torrents: Iterable[Torrent], ignore_case: bool = True) -> set[str]:
    """A torrentek gyoker-neveinek halmaza (a 'felso' modhoz)."""
    names: set[str] = set()
    for torrent in torrents:
        name = root_name(torrent, ignore_case)
        if name:
            names.add(norm_key(name, ignore_case))
    return names


def owned_paths(
    torrents: Iterable[Torrent],
    files_by_hash: Mapping[str, Sequence[Mapping[str, Any]]],
    maps: Sequence[PathMap],
    target: str | os.PathLike[str],
    ignore_case: bool = True,
) -> tuple[set[str], set[str]]:
    """Azok a helyi utvonalak, amik a qBittorrenthez tartoznak.

    Ket halmazt ad vissza:
      roots - ezek (es ami alattuk van) erintetlenek maradnak,
      dirs  - ezekbe bele kell nezni, mert alattuk van megtartando elem.
    """
    roots: set[str] = set()
    dirs: set[str] = set()
    target_key = path_key(target, ignore_case)

    def add(remote: str) -> None:
        local = apply_maps(remote, maps, ignore_case)
        if not local:
            return
        try:
            local_path = Path(local)
        except (OSError, ValueError):
            return
        key = path_key(local_path, ignore_case)
        if not under(key, target_key):
            return  # nem a vizsgalt konyvtarban van
        roots.add(key)
        parent = local_path.parent
        while True:
            pkey = path_key(parent, ignore_case)
            if not under(pkey, target_key):
                break  # a vizsgalt konyvtar folott mar nincs mit vedeni
            if pkey in dirs:
                break  # ezt (es a folotte levoket) mar felvettuk
            dirs.add(pkey)
            if pkey == target_key or parent == parent.parent:
                break
            parent = parent.parent

    for torrent in torrents:
        save = normalize_remote(torrent.get("save_path") or "")
        download = normalize_remote(torrent.get("download_path") or "")
        content = normalize_remote(torrent.get("content_path") or "")
        name = root_name(torrent, ignore_case)
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

@dataclass(slots=True)
class Candidate:
    """Egy torlesre jelolt elem."""

    path: Path
    is_dir: bool
    size: int
    reason: str = ""

    def __post_init__(self) -> None:
        self.path = Path(self.path)


def entry_size(path: str | os.PathLike[str], is_dir: bool) -> int:
    """Egy fajl vagy egy egesz konyvtar merete bajtban.

    Szandekosan os.scandir()-rel jarja be a fat, es a bejegyzes sajat
    stat()-jat kerdezi: Windowson ez a konyvtar beolvasasakor mar megkapott
    adatbol dolgozik, tehat NEM kell fajlonkent kulon kerdes a kiszolgalotol.
    Egy Samba megosztason ez konyvtaranként egy fordulo, nem fajlonkent egy -
    nagy megosztason ez a kulonbseg masodpercekben merheto.

    Olvashatatlan alkonyvtaron nem akad el: azt a reszt kihagyja."""
    if not is_dir:
        try:
            return os.stat(hosszu_ut(path), follow_symlinks=False).st_size
        except OSError:
            return 0
    total = 0
    varolista = [os.fspath(path)]
    while varolista:
        aktualis = varolista.pop()
        try:
            with os.scandir(hosszu_ut(aktualis)) as bejegyzesek:
                for entry in bejegyzesek:
                    try:
                        if entry.is_symlink():
                            continue  # szimbolikus linkbe nem megyunk bele
                        if entry.is_dir(follow_symlinks=False):
                            varolista.append(
                                os.path.join(aktualis, entry.name))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


class Kivetelek:
    """Elore feldolgozott kivetel-mintak.

    A mintakat egyszer hozzuk osszehasonlithato alakra, nem minden egyes
    fajlnevnel ujra. A mintaillesztes (fnmatch) draga, ezert a csillagot /
    kerdojelet nem tartalmazo neveket kulon halmazban tartjuk: azoknal eleg
    egy keresés."""

    __slots__ = ("mintak", "pontos")

    def __init__(self, patterns: Iterable[str] = (), ignore_case: bool = True):
        self.pontos: set[str] = set()
        self.mintak: list[str] = []
        for pattern in patterns:
            kulcs = norm_key(pattern, ignore_case)
            if any(jel in kulcs for jel in "*?["):
                self.mintak.append(kulcs)
            else:
                self.pontos.add(kulcs)

    def talal(self, kulcs: str) -> bool:
        """A `kulcs` mar norm_key() alakban var."""
        return kulcs in self.pontos or any(
            fnmatch.fnmatchcase(kulcs, minta) for minta in self.mintak)


def is_excluded(name: str, patterns: Iterable[str] = (),
                ignore_case: bool = True) -> bool:
    return Kivetelek(patterns, ignore_case).talal(norm_key(name, ignore_case))


def too_young(path: str | os.PathLike[str], min_age_days: float) -> bool:
    """Frissen modositott elem: hagyjuk beken (pl. eppen most kerult oda)."""
    if min_age_days <= 0:
        return False
    try:
        mtime = os.stat(hosszu_ut(path), follow_symlinks=False).st_mtime
    except OSError:
        return False
    return (time.time() - mtime) < min_age_days * 86400


def scandir_sorted(path: str | os.PathLike[str]) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(hosszu_ut(path)) as it:
            return sorted(it, key=lambda e: e.name)
    except OSError as exc:
        raise QbtError(
            f"Nem tudom beolvasni a konyvtarat ({path}): {exc}") from exc


def plan_toplevel(
    target: str | os.PathLike[str],
    names: set[str],
    excludes: Iterable[str] = (),
    ignore_case: bool = True,
    min_age_days: float = 0,
    protected: Iterable[str | os.PathLike[str]] = (),
) -> list[Candidate]:
    """Csak a legfelso szint, nevek alapjan."""
    out: list[Candidate] = []
    kivetelek = Kivetelek(excludes, ignore_case)
    protected_keys = {path_key(p, ignore_case) for p in protected}
    for entry in scandir_sorted(target):
        full = Path(target) / entry.name
        if path_key(full, ignore_case) in protected_keys:
            continue
        if kivetelek.talal(norm_key(entry.name, ignore_case)):
            continue
        if kesz_kulcs(norm_key(entry.name, ignore_case), ignore_case) in names:
            continue  # a torrente (a felkesz .!qB valtozata is)
        if too_young(full, min_age_days):
            continue
        if entry.is_symlink():
            out.append(Candidate(full, False, 0, "nem tartozik torrenthez (link)"))
            continue
        is_dir = entry.is_dir(follow_symlinks=False)
        out.append(Candidate(full, is_dir, entry_size(full, is_dir),
                             "nem tartozik torrenthez"))
    return out


def plan_tree(
    target: str | os.PathLike[str],
    roots: set[str],
    dirs: set[str],
    excludes: Iterable[str] = (),
    ignore_case: bool = True,
    min_age_days: float = 0,
    protected: Iterable[str | os.PathLike[str]] = (),
    on_warn: Callable[[str], None] | None = None,
) -> list[Candidate]:
    """Teljes konyvtarfa, utvonalak alapjan.

    Szandekosan nem rekurziv: egy melyen agazo megosztason a rekurzio
    elfogyna (RecursionError), es a takaritas a felenel allna le.

    Egy alkonyvtar olvasasi hibaja (jogosultsag, halozati akadas) nem allitja
    le az egeszet: azt az agat kihagyjuk - ami ott van, azt nem toroljuk -, es
    szolunk rola az `on_warn` hivason keresztul. Magat a vizsgalt konyvtarat
    viszont tudnunk kell olvasni, kulonben nem tudjuk, mi van benne."""
    out: list[Candidate] = []
    kivetelek = Kivetelek(excludes, ignore_case)
    protected_keys = {path_key(p, ignore_case) for p in protected}
    gyoker = Path(target)
    varolista = [gyoker]
    while varolista:
        path = varolista.pop()
        try:
            bejegyzesek = scandir_sorted(path)
        except QbtError as exc:
            if path == gyoker:
                raise
            if on_warn:
                on_warn(str(exc))
            continue
        for entry in bejegyzesek:
            full = path / entry.name
            key = path_key(full, ignore_case)
            if key in protected_keys:
                continue
            if kivetelek.talal(norm_key(entry.name, ignore_case)):
                continue
            if kesz_kulcs(key, ignore_case) in roots:
                continue  # a torrente: se o, se ami alatta van
            if entry.is_symlink():
                if key not in dirs:
                    out.append(Candidate(full, False, 0,
                                         "nem tartozik torrenthez (link)"))
                continue
            is_dir = entry.is_dir(follow_symlinks=False)
            if is_dir and key in dirs:
                varolista.append(full)  # van alatta megtartando elem
                continue
            if too_young(full, min_age_days):
                continue
            out.append(Candidate(full, is_dir, entry_size(full, is_dir),
                                 "nem tartozik torrenthez"))
    out.sort(key=lambda c: path_key(c.path, ignore_case))
    return out


def plan_all(
    torrents: Sequence[Torrent],
    files_by_hash: Mapping[str, Sequence[Mapping[str, Any]]],
    targets: Sequence[Path],
    mode: str = "felso",
    maps: Sequence[PathMap] = (),
    excludes: Iterable[str] = (),
    ignore_case: bool = True,
    min_age_days: float = 0,
    extra_protected: Iterable[str | os.PathLike[str]] = (),
    allow_empty: bool = False,
    on_note: Callable[[Path, int], None] | None = None,
    on_warn: Callable[[str], None] | None = None,
) -> list[Candidate]:
    """A teljes terv: mely elemekhez nem tartozik mar torrent.

    A vizsgalt konyvtarak vedik egymast: ha az egyik a masik alkonyvtara (pl.
    downloads es downloads/rss), akkor a szulo takaritasakor nem esik aldozatul.

    SafetyStop-ot dob, ha a beallitasokbol az kovetkezne, hogy szinte mindent
    torolne - ilyenkor sokkal valoszinubb, hogy a beallitas rossz, mint hogy
    tenyleg minden felesleges.
    """
    if not torrents and not allow_empty:
        raise SafetyStop("A qBittorrentben egyetlen torrent sincs, igy MINDENT "
                         "torolne.")
    excludes = tuple(excludes)
    extra_protected = tuple(extra_protected)
    names = owned_names(torrents, ignore_case) if mode == "felso" else set()
    candidates: list[Candidate] = []
    for target in targets:
        protected = [t for t in targets if t != target] + list(extra_protected)
        if mode == "felso":
            candidates += plan_toplevel(target, names, excludes, ignore_case,
                                        min_age_days, protected)
        else:
            roots, dirs = owned_paths(torrents, files_by_hash, maps, target,
                                      ignore_case)
            if on_note:
                on_note(target, len(roots))
            if not roots and not allow_empty:
                raise SafetyStop(
                    f"Egyetlen torrent-elem sem esik a(z) {target} konyvtarba. "
                    "Valoszinuleg utvonal-megfeleltetes kell (TAVOLI=HELYI). "
                    "Igy MINDENT torolne, ezert leallok.")
            candidates += plan_tree(target, roots, dirs, excludes, ignore_case,
                                    min_age_days, protected, on_warn)
    return candidates


# ------------------------------------------------------------------ torles

def human(size: float) -> str:
    """Ember szamara olvashato meret."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            return f"{int(size)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size)} B"  # pragma: no cover - a ciklus mindig visszater


def force_remove(func: Callable[[Any], Any], path: Any, _exc: object = None) -> None:
    """A megosztason az irasvedett jelzo miatt is elszallhat a torles: levesszuk
    a jelzot, es ujraprobaljuk.

    A meglevo jogokhoz HOZZAADUNK, nem felulirjuk oket: egy konyvtarnak a
    belepesi (x) jog is kell, e nelkul a masodik probalkozas is elszallna."""
    try:
        mode = os.stat(hosszu_ut(path), follow_symlinks=False).st_mode
    except OSError:
        mode = 0
    extra = stat.S_IWRITE | stat.S_IREAD
    if stat.S_ISDIR(mode):
        extra |= stat.S_IEXEC
    with contextlib.suppress(OSError):
        os.chmod(hosszu_ut(path), stat.S_IMODE(mode) | extra)
    # Az shutil a konyvtar beolvasasanak hibajara is minket hiv: olyankor a
    # visszakapott iteratort le kell zarni, kulonben nyitva marad a leiro.
    result = func(path)
    close = getattr(result, "close", None)
    if close is not None:
        close()


def rmtree(path: str | os.PathLike[str]) -> None:
    """Konyvtar torlese az irasvedett fajlok kezelesevel egyutt."""
    if sys.version_info >= (3, 12):
        shutil.rmtree(hosszu_ut(path), onexc=force_remove)
    else:  # pragma: no cover - csak a regebbi Pythonokon fut
        shutil.rmtree(hosszu_ut(path), onerror=force_remove)


def remove_file(path: str | os.PathLike[str]) -> None:
    try:
        os.remove(hosszu_ut(path))
    except PermissionError:
        force_remove(os.remove, hosszu_ut(path))


def owner_target(
    path: str | os.PathLike[str],
    targets: Sequence[str | os.PathLike[str]],
) -> Path:
    """Melyik vizsgalt konyvtarhoz kepest szamoljuk az elem utvonalat (a
    kukaban ez alapjan jon letre a konyvtar-szerkezet). Egymasba agyazott
    konyvtaraknal a legkulsot valasztjuk, igy nem utik egymast az azonos nevu
    fajlok (pl. rss\\film.mkv es film.mkv)."""
    owners = sorted((Path(t) for t in targets), key=lambda t: len(str(t)))
    if not owners:
        return Path(path).parent
    parents = Path(path).parents
    return next((t for t in owners if t in parents), owners[0])


def _letezik(path: str | os.PathLike[str]) -> bool:
    """Van-e mar ilyen nevu elem (a torott szimbolikus linket is beleertve)."""
    return os.path.lexists(hosszu_ut(path))


def _free_trash_path(dest: Path) -> Path:
    """Szabad nev a kukaban. Az idobelyeg mellett sorszam is kell: egy
    masodpercen belul tobb azonos nevu elem is erkezhet."""
    if not _letezik(dest):
        return dest
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for counter in itertools.count():
        suffix = f".{stamp}" if not counter else f".{stamp}-{counter}"
        candidate = dest.with_name(dest.name + suffix)
        if not _letezik(candidate):
            return candidate
    raise AssertionError  # pragma: no cover - a ciklus vegtelen


def remove_entry(
    candidate: Candidate,
    target: str | os.PathLike[str],
    trash_dir: str | os.PathLike[str] | None = None,
) -> tuple[bool, str]:
    """Torles, vagy athelyezes a kukaba. Kivetelt nem dob: (siker, uzenet)."""
    path = candidate.path
    try:
        if trash_dir:
            try:
                rel = path.relative_to(Path(target))
            except ValueError:
                rel = Path(path.name)
            dest = _free_trash_path(Path(trash_dir) / rel)
            os.makedirs(hosszu_ut(dest.parent), exist_ok=True)
            shutil.move(hosszu_ut(path), hosszu_ut(dest))
            return True, f"kukaba: {dest}"
        if path.is_symlink() or not candidate.is_dir:
            remove_file(path)
        else:
            rmtree(path)
        return True, "torolve"
    except OSError as exc:
        return False, f"SIKERTELEN: {exc}"


# --------------------------------------------------------------------- main

def nemnegativ_szam(szoveg: str) -> float:
    ertek = float(szoveg)  # az argparse maga jelenti, ha nem szam
    if ertek < 0:
        raise argparse.ArgumentTypeError("nem lehet negativ")
    return ertek


def pozitiv_szam(szoveg: str) -> float:
    ertek = float(szoveg)
    if ertek <= 0:
        raise argparse.ArgumentTypeError("nullanal nagyobbnak kell lennie")
    return ertek


def nemnegativ_egesz(szoveg: str) -> int:
    ertek = int(szoveg)
    if ertek < 0:
        raise argparse.ArgumentTypeError("nem lehet negativ")
    return ertek


def build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument("--min-kor", dest="min_age", type=nemnegativ_szam,
                        default=0, metavar="NAP",
                        help="csak az ennel regebben modositott elemeket "
                             "torolje (alap: 0 = mindegy)")
    parser.add_argument("--kuka", default=None, metavar="KONYVTAR",
                        help="torles helyett ide mozgassa az elemeket")
    parser.add_argument("--max-torles", dest="max_delete", type=nemnegativ_egesz,
                        default=0, metavar="DB",
                        help="ha ennel tobb elemet torolne, inkabb alljon le "
                             "(alap: 0 = nincs korlat)")
    parser.add_argument("--naplo", default=None, metavar="FAJL",
                        help=f"a torlesi naplo helye "
                             f"(alap: {qbt_naplo.alap_naplo_fajl()})")
    parser.add_argument("--nincs-naplo", dest="no_naplo", action="store_true",
                        help="ne vezessen torlesi naplot")
    parser.add_argument("--naplo-meret", dest="naplo_meret", type=pozitiv_szam,
                        default=qbt_naplo.ALAP_MERET / (1024 * 1024),
                        metavar="MB",
                        help="ekkora naplofajl utan kezdjen ujat "
                             "(alap: %(default)s MB; hetfonkent ugyis ujat kezd)")
    parser.add_argument("--naplo-tartas", dest="naplo_tartas",
                        type=nemnegativ_egesz, default=qbt_naplo.ALAP_TARTAS,
                        metavar="DB",
                        help="ennyi lezart (tomoritett) naplofajlt tartson meg "
                             "(alap: %(default)s)")
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
    parser.add_argument("--idokorlat", dest="timeout", type=pozitiv_szam,
                        default=30, metavar="MP",
                        help="halozati idokorlat (alap: 30 mp)")
    return parser


def confirm(count: int, size: int, trash_dir: Path | None) -> bool:
    print()
    what = f"athelyez a kukaba ({trash_dir})" if trash_dir else "TOROL VEGLEG"
    print(f"Ez {count} elemet {what}, osszesen {human(size)}.")
    try:
        answer = input("Biztos? Ird be, hogy 'igen': ").strip().lower()
    except EOFError:
        return False
    return answer in ("igen", "i", "yes", "y")


def _utf8_kimenet() -> None:
    """A Windows parancssor alapbol nem UTF-8: az utvonalakban levo ekezetes
    betuk enelkul kiirhatatlanok lennenek (UnicodeEncodeError)."""
    for adatfolyam in (sys.stdout, sys.stderr):
        reconfigure = getattr(adatfolyam, "reconfigure", None)
        if reconfigure is None:  # a tesztekben egy sima StringIO all itt
            continue
        with contextlib.suppress(OSError, ValueError):  # pragma: no cover
            reconfigure(encoding="utf-8", errors="replace")


def _celkonyvtarak(nyers: Iterable[str], ignore_case: bool) -> list[Path]:
    """A --konyvtar ertekek ellenorzese. Hiba eseten QbtError."""
    targets: list[Path] = []
    latott: set[str] = set()
    for raw in nyers:
        target = normalize_target(raw)
        if not target.exists():
            raise QbtError(f"Nincs ilyen konyvtar: {target}")
        if not target.is_dir():
            raise QbtError(f"Nem konyvtar: {target}")
        if is_root_like(target):
            raise QbtError(
                f"Biztonsagi okbol a gyoker konyvtarat nem takaritom: {target}")
        # Ugyanaz a konyvtar ketszer megadva ketszer is torolne (masodszor mar
        # hibaval), ezert csak egyszer vesszuk fel.
        kulcs = path_key(target, ignore_case)
        if kulcs not in latott:
            latott.add(kulcs)
            targets.append(target)
    return targets


def _main(argv: Sequence[str] | None) -> int:
    _utf8_kimenet()

    args = build_parser().parse_args(argv)
    ignore_case = not args.case_sensitive

    try:
        targets = _celkonyvtarak(args.konyvtarak, ignore_case)
        maps = [parse_map(entry) for entry in args.utvonal]
    except (QbtError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.pontos and args.mod != "fa":
        print("Figyelem: a --pontos csak a 'fa' modban szamit, most nem hasznalom.",
              file=sys.stderr)
    if args.utvonal and args.mod != "fa":
        print("Figyelem: az --utvonal csak a 'fa' modban szamit.", file=sys.stderr)

    excludes = list(args.kivetel)
    if not args.no_default_excludes:
        excludes += DEFAULT_EXCLUDES

    trash_dir: Path | None = None
    if args.kuka:
        trash_dir = normalize_target(args.kuka)
        try:
            trash_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"Nem tudom letrehozni a kukat ({trash_dir}): {exc}",
                  file=sys.stderr)
            return 2
        kuka_kulcs = path_key(trash_dir, ignore_case)
        if any(kuka_kulcs == path_key(t, ignore_case) for t in targets):
            print("A kuka nem lehet maga a vizsgalt konyvtar.", file=sys.stderr)
            return 2

    password = args.password
    if password is None:
        password = os.environ.get("QBT_PASSWORD")
    if args.user and password is None:
        if sys.stdin.isatty():
            password = getpass.getpass(f"qBittorrent jelszo ({args.user}): ")
        else:
            print("Nincs jelszo (--password vagy QBT_PASSWORD).", file=sys.stderr)
            return 2

    client = QbtClient(args.url, args.user, password, args.timeout, args.insecure)
    try:
        client.login()
        version = client.version()
        torrents = client.torrents()
        files_by_hash: dict[str, list[dict[str, Any]]] = {}
        if args.mod == "fa" and args.pontos:
            for torrent in torrents:
                thash = torrent.get("hash") or ""
                if thash:
                    files_by_hash[thash] = client.files(thash)
    except QbtError as exc:
        print(f"Hiba: {exc}", file=sys.stderr)
        print("Semmit nem toroltem.", file=sys.stderr)
        return 1

    print(f"qBittorrent {version} ({client.base}) - {len(torrents)} torrent")
    pontos_jelzo = " (pontos)" if args.pontos and args.mod == "fa" else ""
    print(f"Uzemmod: {args.mod}{pontos_jelzo}")
    for target in targets:
        print(f"Vizsgalt konyvtar: {target}")

    def note(target: Path, count: int) -> None:
        print(f"A(z) {target} alatt talalt torrent-elemek: {count}")

    gondok: list[str] = []

    try:
        candidates = plan_all(
            torrents, files_by_hash, targets, args.mod, maps, excludes,
            ignore_case, args.min_age,
            extra_protected=[trash_dir] if trash_dir else (),
            allow_empty=args.allow_empty, on_note=note, on_warn=gondok.append)
    except SafetyStop as exc:
        print()
        print(f"{exc} Ha tenyleg ezt akarod: --ures-lista-ok", file=sys.stderr)
        return 2
    except QbtError as exc:
        print(f"Hiba: {exc}", file=sys.stderr)
        print("Semmit nem toroltem.", file=sys.stderr)
        return 1

    if gondok:
        print()
        print(f"Figyelem: {len(gondok)} konyvtarat nem tudtam beolvasni - "
              "ezekben nem takaritottam:", file=sys.stderr)
        for gond in gondok[:10]:
            print(f"  {gond}", file=sys.stderr)
        if len(gondok) > 10:
            print(f"  ... es meg {len(gondok) - 10}.", file=sys.stderr)

    total = sum(c.size for c in candidates)
    print()
    if not candidates:
        print("Nincs felesleges elem - nincs mit tenni.")
        return 0

    print(f"Felesleges elemek ({len(candidates)} db, {human(total)}):")
    for cand in candidates:
        print(f"  [{'D' if cand.is_dir else 'F'}] {human(cand.size):>10}  "
              f"{cand.path}")

    if not args.torol:
        print()
        print("Ez csak proba volt, semmit nem toroltem. "
              "Tenyleges torleshez tedd hozza: --torol")
        return 0

    if args.max_delete and len(candidates) > args.max_delete:
        print()
        print(f"Tobb elemet torolne ({len(candidates)}), mint a megadott hatar "
              f"({args.max_delete}). Leallok.", file=sys.stderr)
        return 2

    if not args.igen:
        if not sys.stdin.isatty():
            print("Nem interaktiv futas: a torleshez --igen kell.",
                  file=sys.stderr)
            return 2
        if not confirm(len(candidates), total, trash_dir):
            print("Megsem toroltem semmit.")
            return 0

    naplo = None
    if not args.no_naplo:
        naplo = qbt_naplo.nyitas(args.naplo,
                                 int(args.naplo_meret * 1024 * 1024),
                                 args.naplo_tartas)

    print()
    freed = 0
    failed = 0
    try:
        for cand in candidates:
            ok, message = remove_entry(cand, owner_target(cand.path, targets),
                                       trash_dir)
            if ok:
                freed += cand.size
            else:
                failed += 1
            if naplo:
                naplo.rogzit(cand, ok, message, kukaba=bool(trash_dir))
            print(f"  {human(cand.size):>10}  {cand.path}  ({message})")
    finally:
        if naplo:
            naplo.close()

    print()
    maradt = f"  {failed} elem sikertelen!" if failed else ""
    print(f"Kesz: {len(candidates) - failed} elem, {human(freed)} "
          f"felszabadulva.{maradt}")
    if naplo:
        print(f"A torlesek naploja: {naplo.path}")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < MIN_PYTHON:
        kell = ".".join(str(x) for x in MIN_PYTHON)
        print(f"Tul regi Python: {sys.version.split()[0]} (legalabb {kell} kell).",
              file=sys.stderr)
        return 2
    try:
        return _main(argv)
    except KeyboardInterrupt:  # pragma: no cover - kezi megszakitas
        print("\nMegszakitva. A hatralevo elemekhez nem nyultam.",
              file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
