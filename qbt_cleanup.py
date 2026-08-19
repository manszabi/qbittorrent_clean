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

Amire a program figyel:
  * egy atmeneti halozati hiba nem buktatja el a takaritast (ujraprobalkozas),
  * a lejart WebUI munkamenetbe ujra bejelentkezik,
  * a --pontos modhoz csak a vizsgalt konyvtarba eso torrentek fajllistajat
    keri le, es azt is parhuzamosan,
  * hiba eseten egyetlen fajlhoz sem nyul.

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
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

import qbt_naplo

__version__ = "2.2"

API: Final = "/api/v2"

# Ennel regebbi Pythonon a program nem indul el (a regebbi kiadasok mar nem
# kapnak biztonsagi javitast sem).
MIN_PYTHON: Final = (3, 10)

# Ezeket soha nem bantjuk (a NAS vagy az operacios rendszer keszitette oket).
# Sajat minta a --kivetel kapcsoloval adhato hozza, ez a lista pedig a
# --nincs-gyari-kivetel kapcsoloval kapcsolhato ki.
DEFAULT_EXCLUDES: Final[tuple[str, ...]] = (
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
INCOMPLETE_SUFFIX: Final = ".!qB"

# Windowson egy utvonal alapbol 260 karakter lehet - egy hosszu kiadasi nev es
# egy alkonyvtar (Subs, Sample) ezt konnyen atlepi, es akkor a fajl "nem
# letezik" a program szamara. A "\\?\" eloteg feloldja a korlatot (kb. 32000
# karakterig). Csak akkor tesszuk ki, ha tenyleg hosszu az ut: az eloteges
# alakot a rendszer nyersen veszi (nincs / -> \ atirasa, nincs "." es ".."),
# ezert felesleges kockazat lenne mindenhol hasznalni.
WINDOWS_UT_HATAR: Final = 240

# Egy utvonal ennyi darabbol all legalabb, ha nem gyoker konyvtar ("/" + nev).
GYOKER_RESZEK: Final = 2

# --- halozat -----------------------------------------------------------------
# Ezekre a valaszokra van ertelme ujraprobalni: mindegyik atmeneti allapot
# (torlodas, ujraindulo kiszolgalo, halozati akadas). A 4xx tobbi tagja - rossz
# jelszo, nem letezo hivas - hiaba jonne ujra, ugyanaz lenne a valasz.
UJRAPROBALHATO: Final = frozenset({408, 429, 500, 502, 503, 504})
HTTP_TILTVA: Final = 403                # lejart munkamenet vagy rossz jelszo
MAX_RETRY_AFTER: Final = 30             # a Retry-After fejlecet ennyire vagjuk
ALAP_PROBAK: Final = 3                  # ennyiszer probalunk egy hivast
PROBA_SZUNET: Final = 1.0               # az elso ujraprobalkozas elotti szunet
ALAP_SZALAK: Final = 8                  # a fajllista-lekeres parhuzamossaga
MAX_SZALAK: Final = 16

# A takaritas kozben ilyen surun (elemenkent) nezzuk meg, kertek-e megszakitast,
# es adunk visszajelzest a hivonak. Fajlonkent hivni feleslegesen draga lenne.
JELZES_ELEMENKENT: Final = 200

# Egy meretegyseg (KB, MB, ...) valtoszama, es a felsorolasokbol ennyi tetelt
# mutatunk meg - a tobbi csak darabszamkent jelenik meg.
EGYSEG: Final = 1024
MUTATOTT_RESZLET: Final = 10

# A qBittorrent egy torrentjenek leiroja (a WebUI JSON valasza), illetve egy
# utvonal-megfeleltetes: (a qBittorrent szerinti ut, a helyi ut).
Torrent = Mapping[str, Any]
PathMap = tuple[str, str]


class QbtError(Exception):
    """WebUI vagy fajlrendszer hiba - ilyenkor semmit nem torlunk."""


class SafetyStop(QbtError):
    """Biztonsagi fek: a beallitasokbol az kovetkezne, hogy szinte mindent
    torolne (nincs torrent, vagy rossz az utvonal-megfeleltetes)."""


class BeallitasHiba(QbtError):
    """A megadott kapcsolok nem jok (nincs ilyen konyvtar, rossz megfeleltetes).
    Ilyenkor nem a halozattal vagy a lemezzel van baj, hanem a keressel -
    ezert mas a visszateresi ertek is (2, nem 1)."""


class Megszakitva(Exception):
    """A felhasznalo kerte a leallast. Nem hiba: ami addig elkeszult, az jo -
    ezert kulon kivetel, nem QbtError."""


class Mod(str, Enum):
    """A ket uzemmod. Szoveg-alapu, igy a parancssori ertek (felso / fa) es a
    beallitas-fajlban tarolt szoveg valtozatlanul hasznalhato."""

    FELSO = "felso"
    FA = "fa"

    def __str__(self) -> str:  # a kiirasban a nyers ertek jelenjen meg
        return self.value


@dataclass(frozen=True, slots=True)
class Halozat:
    """A WebUI-hoz vezeto ut beallitasai egyben.

    Egy csomagban tartva a hivonak nem kell ot kulon parametert atadnia (es a
    kesobb hozzajovo beallitas sem torik el minden hivast)."""

    timeout: float = 30.0
    probak: int = ALAP_PROBAK       # 1 = nincs ujraprobalkozas
    insecure: bool = False
    szalak: int = ALAP_SZALAK       # a fajllista-lekeres parhuzamossaga


# ------------------------------------------------------------------ WebUI

class QbtClient:
    """A qBittorrent WebUI (v2 API) minimalis kliense, csak a szabvany
    konyvtarral."""

    def __init__(
        self,
        url: str,
        username: str | None = None,
        password: str | None = None,
        halozat: Halozat | None = None,
    ) -> None:
        self.base = url.rstrip("/")
        if not self.base.startswith(("http://", "https://")):
            self.base = "http://" + self.base
        self.username = username
        self.password = password
        self.halozat = halozat or Halozat()
        self.timeout = self.halozat.timeout
        ctx: ssl.SSLContext | None = None
        if self.halozat.insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=ctx),
        )
        # A tobb szalbol valo hasznalat rendben van: minden hivas sajat
        # kapcsolatot nyit, a sutis tarolot pedig a http.cookiejar maga zarja.
        # Az ujrabelepest viszont csak egy szal vegezze el (kulonben tizen
        # kuldenenek egyszerre bejelentkezest ugyanarra a lejart munkamenetre):
        # a szamlalobol latszik, hogy kozben mar belepett-e valaki.
        self._belepes_zar = threading.Lock()
        self._belepesek = 0
        # A hivo ideallithat egy "megszakitottak?" kerdest: az ujraprobalkozas
        # elotti varakozas ezt figyeli, kulonben a felulet Megszakitas gombja
        # utan is masodpercekig varna a valaszra.
        self.megszakitva: Callable[[], bool] | None = None

    # -- egyetlen hivas ----------------------------------------------------

    def _keres(self, path: str, params: dict[str, str] | None,
               post: bool) -> str:
        """Egy HTTP hivas, ujraprobalkozas nelkul."""
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
        req.add_header("User-Agent", f"qbt_cleanup.py/{__version__}")
        with self.opener.open(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", "replace")

    @staticmethod
    def _varakozas(exc: urllib.error.HTTPError, proba: int) -> float:
        """Mennyit varjunk az ujraprobalkozas elott.

        Ha a kiszolgalo megmondja (Retry-After), azt fogadjuk el - de legfeljebb
        MAX_RETRY_AFTER masodpercig, kulonben egy elgepelt fejleccel orakra
        megallithatna a takaritast. Kulonben duplazodo varakozas."""
        fejlec = ""
        with contextlib.suppress(AttributeError, TypeError):
            fejlec = (exc.headers.get("Retry-After") or "").strip()
        if fejlec:
            try:
                return max(0.0, min(float(fejlec), MAX_RETRY_AFTER))
            except ValueError:
                pass  # a datum alaku Retry-After-t nem ertelmezzuk
        return PROBA_SZUNET * (2 ** proba)

    def _var(self, mennyit: float) -> None:
        """Varakozas ket probalkozas kozott, a megszakitasra figyelve.

        Nem egyetlen hosszu alvas: kulonben a felulet Megszakitas gombja utan
        is vegig kellene varni a hatralevo masodperceket."""
        vege = time.monotonic() + mennyit
        while True:
            if self.megszakitva and self.megszakitva():
                raise Megszakitva
            maradt = vege - time.monotonic()
            if maradt <= 0:
                return
            time.sleep(min(0.2, maradt))

    def _ujra_belep(self) -> None:
        """Ujra bejelentkezes lejart munkamenet utan.

        Ha kozben egy masik szal mar belepett, nem lepunk be megegyszer: 16
        parhuzamos lekerdezesnel kulonben 16 bejelentkezes indulna egyszerre
        ugyanarra a lejart munkamenetre."""
        latott = self._belepesek
        with self._belepes_zar:
            if self._belepesek != latott:
                return  # mas szal kozben mar elintezte
            self.login()
            self._belepesek += 1

    def _call(
        self,
        path: str,
        params: dict[str, str] | None = None,
        post: bool = False,
        ujrabelepes: bool = True,
    ) -> str:
        """Egy WebUI hivas, atmeneti hibara ujraprobalkozassal.

        Egy halozati zokkeno (a NAS eppen ebred, a kiszolgalo ujraindul, a
        WebUI torlodik) korabban azonnal elbuktatta az egesz takaritast. A
        vegleges hibakon (rossz jelszo, nem letezo hivas) viszont nincs ertelme
        ujraprobalni: azok elsore elszallnak.

        Az ujrakuldes azert biztonsagos, mert az egyetlen POST hivas a
        bejelentkezes - azt ketszer elkuldeni sem valtoztat semmin. A tobbi
        hivas csak lekerdez."""
        utolso: Exception | None = None
        for proba in range(max(1, self.halozat.probak)):
            if proba:
                self._var(self._varakozas(utolso, proba - 1)
                          if isinstance(utolso, urllib.error.HTTPError)
                          else PROBA_SZUNET * (2 ** (proba - 1)))
            try:
                return self._keres(path, params, post)
            except urllib.error.HTTPError as exc:
                body = ""
                with contextlib.suppress(OSError):  # a valasz mar elszallhatott
                    body = exc.read().decode("utf-8", "replace").strip()
                if exc.code == HTTP_TILTVA:
                    # A qBittorrent egy ido utan elengedi a munkamenetet. Egy
                    # hosszu (fajlonkenti) lekerdezes ebbe konnyen belefut -
                    # ilyenkor eleg ujra bejelentkezni, nem kell elolrol
                    # kezdeni az egeszet. Ha a jelszo rossz, a belepes maga
                    # szall el, ertheto uzenettel.
                    if ujrabelepes and self.username and not post:
                        self._ujra_belep()
                        return self._call(path, params, post,
                                          ujrabelepes=False)
                    raise QbtError(
                        "A WebUI elutasitotta a kerest (403). Rossz jelszo, "
                        "lejart munkamenet, vagy a WebUI-ban be van kapcsolva "
                        "a kulso hivatkozas tiltasa."
                    ) from exc
                if exc.code not in UJRAPROBALHATO:
                    raise QbtError(
                        f"HTTP {exc.code} a {path} hivasnal"
                        + (f": {body}" if body else "")
                    ) from exc
                utolso = exc
            except urllib.error.URLError as exc:
                utolso = exc
            except OSError as exc:
                utolso = exc
        if isinstance(utolso, urllib.error.HTTPError):
            raise QbtError(
                f"HTTP {utolso.code} a {path} hivasnal, {self.halozat.probak} "
                "probalkozas utan is"
            ) from utolso
        if isinstance(utolso, urllib.error.URLError):
            raise QbtError(
                f"Nem sikerult elerni a qBittorrent WebUI-t ({self.base}): "
                f"{utolso.reason}"
            ) from utolso
        raise QbtError(f"Halozati hiba a {path} hivasnal: {utolso}") from utolso

    # -- a WebUI hivasai ---------------------------------------------------

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

    def fajlnevek(self, torrent_hash: str) -> list[str]:
        """Egy torrent fajljainak neve (a torrent gyokerehez kepest).

        A WebUI valaszabol csak a nev kell; a meret, az allapot es a
        darab-tartomanyok megtartasa merve 500 torrent x 200 fajl eseten 48 MB
        lenne a memoriaban, csak a nevekkel 10 MB."""
        return [str(item.get("name") or "") for item in self.files(torrent_hash)]

    def files_many(
        self,
        hashes: Sequence[str],
        on_progress: Callable[[int, int], None] | None = None,
        megszakitva: Callable[[], bool] | None = None,
    ) -> dict[str, list[str]]:
        """Tobb torrent fajlneveinek lekerese egyszerre.

        A qBittorrent API-ban nincs kotegelt lekeres: torrentenkent egy hivas
        kell. Egyenkent, egymas utan ez ezer torrentnel percekben merheto -
        pedig a legtobb ido varakozas. Ezert parhuzamosan kerdezzuk le; a
        parhuzamossag felso hatara MAX_SZALAK, hogy egy gyenge NAS-t se
        terheljunk tul."""
        eredmeny: dict[str, list[str]] = {}
        egyediek = list(dict.fromkeys(h for h in hashes if h))
        if not egyediek:
            return eredmeny
        szalak = max(1, min(self.halozat.szalak, MAX_SZALAK, len(egyediek)))
        kesz = 0
        pool = ThreadPoolExecutor(max_workers=szalak,
                                  thread_name_prefix="qbt-fajlok")
        try:
            munkak = {pool.submit(self.fajlnevek, h): h for h in egyediek}
            for munka in as_completed(munkak):
                eredmeny[munkak[munka]] = munka.result()
                kesz += 1
                if on_progress:
                    on_progress(kesz, len(egyediek))
                if megszakitva and megszakitva():
                    raise Megszakitva
        finally:
            # A meg el sem indult hivasokat eldobjuk, a folyamatban levokre nem
            # varunk: megszakitaskor (es hiba eseten) igy all meg azonnal.
            pool.shutdown(wait=False, cancel_futures=True)
        return eredmeny

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
    return len(path.parts) < GYOKER_RESZEK or str(path) == path.anchor


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
            # Szandekosan nem Path-tal fuzunk: fajlonkent hivjuk, es a merés
            # szerint a pathlib vitte az ido felet. Az eredmeny osszehasonlitasra
            # valo (a perjelek Windowson vegyesek lehetnek benne) - a path_key()
            # ugyis egysegesiti oket.
            return dst.rstrip("/\\") + "/" + rest
    return None


def root_name(torrent: Torrent, ignore_case: bool = True) -> str:
    """A torrent gyoker-eleme: az a fajl vagy konyvtar, ami a mentesi
    konyvtarban letrejon. Ha nincs ilyen, ures szoveg.

    Nincs gyoker-eleme annak a tobbfajlos torrentnek, amit a qBittorrent "ne
    hozzon letre almappat" tartalom-elrendezesevel adtak hozza: a fajljai
    kozvetlenul a mentesi konyvtarban vannak. A WebUI ilyenkor a content_path
    mezoben MAGAT A MENTESI KONYVTARAT kuldi (lasd a qBittorrent forrasaban a
    TorrentImpl::contentPath fuggvenyt), tehat a mentesi konyvtar neve latszana
    "gyoker-nevnek". Ez korabban azt jelentette, hogy a torrent sajat fajljait
    a program feleslegesnek latta - es letorolte volna oket. Most inkabb
    semmit nem allitunk: a hivo a fajllistabol tudja meg a neveket
    (gyokertelen_torrentek + owned_names)."""
    content = normalize_remote(torrent.get("content_path") or "")
    save = normalize_remote(torrent.get("save_path") or "").rstrip("/")
    if content and save:
        rest = strip_prefix(content, save + "/", ignore_case)
        if rest:
            first = rest.split("/", 1)[0]
            if first:
                return first
        if norm_key(content, ignore_case) == norm_key(save, ignore_case):
            return ""  # a fajlok kozvetlenul a mentesi konyvtarban vannak
    if content:
        return content.rsplit("/", 1)[-1]
    return (torrent.get("name") or "").strip()


def gyokertelen_torrentek(torrents: Iterable[Torrent],
                          ignore_case: bool = True) -> list[str]:
    """Azoknak a torrenteknek az azonositoja, amiknek nincs gyoker-elemuk.

    Ezekhez a fajllistat is le kell kerni - kulonben nem tudjuk, mi tartozik
    hozzajuk a mentesi konyvtarban. Ritka eset, ezert nem drag: a torrentek
    tobbsegenek van gyoker-konyvtara vagy egyetlen fajlja."""
    return [thash for torrent in torrents
            if (thash := (torrent.get("hash") or ""))
            and not root_name(torrent, ignore_case)]


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


def owned_names(
    torrents: Iterable[Torrent],
    files_by_hash: Mapping[str, Sequence[str]] | None = None,
    ignore_case: bool = True,
) -> set[str]:
    """A torrentek gyoker-neveinek halmaza (a 'felso' modhoz).

    Amelyik torrentnek nincs gyoker-eleme (lasd root_name), annak a
    fajllistajabol vesszuk a legfelso szintu neveket - kulonben a sajat
    fajljait feleslegesnek latnank."""
    names: set[str] = set()
    fajlok = files_by_hash or {}
    for torrent in torrents:
        name = root_name(torrent, ignore_case)
        if name:
            names.add(norm_key(name, ignore_case))
            continue
        for rel in fajlok.get(torrent.get("hash") or "", ()):
            elso = normalize_remote(rel).split("/", 1)[0]
            if elso:
                names.add(norm_key(elso, ignore_case))
    return names


def owned_paths(
    torrents: Iterable[Torrent],
    files_by_hash: Mapping[str, Sequence[str]],
    maps: Sequence[PathMap],
    target: str | os.PathLike[str],
    ignore_case: bool = True,
) -> tuple[set[str], set[str]]:
    """Azok a helyi utvonalak, amik a qBittorrenthez tartoznak.

    Ket halmazt ad vissza:
      roots - ezek (es ami alattuk van) erintetlenek maradnak,
      dirs  - ezekbe bele kell nezni, mert alattuk van megtartando elem.

    A `files_by_hash` ertekei fajlnevek (a torrent gyokerehez kepest), nem a
    WebUI teljes valaszai: 500 torrent x 200 fajl eseten a teljes valasz 48 MB
    lenne a memoriaban, csak a nevekkel 10 MB.

    Szandekosan nem hasznal Path objektumot: fajlonkent hivjuk, es a merés
    szerint a pathlib vitte az ido felet. A kulcsokat ugyanaz a path_key()
    keszíti, tehat az eredmeny valtozatlan."""
    roots: set[str] = set()
    dirs: set[str] = set()
    target_key = path_key(target, ignore_case)

    def add_kulcs(kulcs: str) -> None:
        """Egy megtartando elem - es a folotte levo konyvtarak - felvetele."""
        if not under(kulcs, target_key):
            return  # nem a vizsgalt konyvtarban van
        roots.add(kulcs)
        while True:
            vago = kulcs.rfind("/")
            if vago <= 0:
                return
            kulcs = kulcs[:vago]
            if kulcs in dirs:
                return  # ezt (es a folotte levoket) mar felvettuk
            if not under(kulcs, target_key):
                return  # a vizsgalt konyvtar folott mar nincs mit vedeni
            dirs.add(kulcs)
            if kulcs == target_key:
                return

    def add(remote: str) -> None:
        local = apply_maps(remote, maps, ignore_case)
        if local:
            add_kulcs(path_key(local, ignore_case))

    for torrent in torrents:
        save = normalize_remote(torrent.get("save_path") or "")
        download = normalize_remote(torrent.get("download_path") or "")
        content = normalize_remote(torrent.get("content_path") or "")
        name = root_name(torrent, ignore_case)
        files = files_by_hash.get(torrent.get("hash") or "")

        if files:
            # Pontos mod: fajlonkent. Igy a torrent sajat konyvtaraban levo
            # idegen fajl is felesleges elemnek szamit.
            for rel in files:
                tiszta = normalize_remote(rel)
                if not tiszta:
                    continue
                for base in (save, download):
                    if base:
                        add(base + "/" + tiszta)
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
        # Csak akkor alakitunk, ha kell: a tervezes mar Path-tal dolgozik, es
        # a folosleges ujraepites tizezres nagysagrendben merheto.
        if not isinstance(self.path, Path):
            self.path = Path(self.path)


def entry_size(path: str | os.PathLike[str], is_dir: bool) -> int:
    """Egy fajl vagy egy egesz konyvtar merete bajtban.

    Szandekosan os.scandir()-rel jarja be a fat, es a bejegyzes sajat
    stat()-jat kerdezi: Windowson ez a konyvtar beolvasasakor mar megkapott
    adatbol dolgozik, tehat NEM kell fajlonkent kulon kerdes a kiszolgalotol.
    Egy Samba megosztason ez konyvtarankent egy fordulo, nem fajlonkent egy -
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
    egy kereses."""

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


@dataclass(frozen=True, slots=True)
class Beallitas:
    """A takaritas osszes kapcsoloja egy helyen.

    Korabban ugyanez tizenket kulon parameterkent utazott a fuggvenyek kozott;
    egy uj kapcsolo minden hivast atirt, es konnyu volt elcsuszni a sorrendben.
    Igy a hivo egy csomagot ad at, a bovites pedig visszafele is jo marad."""

    mode: Mod = Mod.FELSO
    maps: tuple[PathMap, ...] = ()
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES
    ignore_case: bool = True
    min_age_days: float = 0.0
    # Amit a vizsgalt konyvtarakon kivul meg vedeni kell (tipikusan a kuka).
    extra_protected: tuple[Path, ...] = ()
    allow_empty: bool = False


@dataclass(frozen=True, slots=True)
class Figyelo:
    """Visszajelzes a takaritas kozben - es a megszakitas lehetosege.

    Mindegyik mezo elhagyhato: parancssorbol tobbnyire eleg a jelzes, a
    feluletnek viszont kell a haladas es a megallitas is. A megszakitast azert
    kerdezzuk (es nem esemenyt varunk), mert igy a hivo dontheti el, mit tekint
    megszakitasnak - a felulet egy Event-et, a parancssor a Ctrl+C-t."""

    on_note: Callable[[Path, int], None] | None = None
    on_warn: Callable[[str], None] | None = None
    on_progress: Callable[[str], None] | None = None
    megszakitva: Callable[[], bool] | None = None

    def jegyzet(self, target: Path, darab: int) -> None:
        if self.on_note:
            self.on_note(target, darab)

    def figyelmeztet(self, szoveg: str) -> None:
        if self.on_warn:
            self.on_warn(szoveg)

    def jelez(self, szoveg: str) -> None:
        if self.on_progress:
            self.on_progress(szoveg)

    def ellenoriz(self) -> None:
        """Megszakitast kertek? Akkor itt allunk meg - ket elem kozott, tehat
        felig torolt allapot nem maradhat utana."""
        if self.megszakitva and self.megszakitva():
            raise Megszakitva


@dataclass(frozen=True, slots=True)
class _Terv:
    """Egy konyvtar atnezesenek osszes kelleke, elokeszitett alakban.

    A kivetel-mintakat es a vedett utvonalakat egyszer hozzuk osszehasonlithato
    alakra, nem minden egyes fajlnal ujra."""

    beallitas: Beallitas
    kivetelek: Kivetelek
    vedett: frozenset[str]
    figyelo: Figyelo

    @classmethod
    def keszit(cls, beallitas: Beallitas, vedett: Iterable[Any],
               figyelo: Figyelo) -> _Terv:
        kis_nagy = beallitas.ignore_case
        return cls(
            beallitas=beallitas,
            kivetelek=Kivetelek(beallitas.excludes, kis_nagy),
            vedett=frozenset(path_key(x, kis_nagy) for x in vedett),
            figyelo=figyelo,
        )

    def bekenhagy(self, key: str, nev_kulcs: str) -> bool:
        """Igaz, ha ehhez az elemhez semmikepp nem nyulunk: masik vizsgalt
        konyvtar (vagy a kuka), illetve kivetel-minta."""
        return key in self.vedett or self.kivetelek.talal(nev_kulcs)


def plan_toplevel(target: str | os.PathLike[str], names: set[str],
                  terv: _Terv) -> list[Candidate]:
    """Csak a legfelso szint, nevek alapjan."""
    out: list[Candidate] = []
    kis_nagy = terv.beallitas.ignore_case
    for entry in scandir_sorted(target):
        terv.figyelo.ellenoriz()
        full = Path(target) / entry.name
        nev_kulcs = norm_key(entry.name, kis_nagy)
        if terv.bekenhagy(path_key(full, kis_nagy), nev_kulcs):
            continue
        if kesz_kulcs(nev_kulcs, kis_nagy) in names:
            continue  # a torrente (a felkesz .!qB valtozata is)
        if too_young(full, terv.beallitas.min_age_days):
            continue
        if entry.is_symlink():
            out.append(Candidate(full, False, 0, "nem tartozik torrenthez (link)"))
            continue
        is_dir = entry.is_dir(follow_symlinks=False)
        out.append(Candidate(full, is_dir, entry_size(full, is_dir),
                             "nem tartozik torrenthez"))
    return out


def plan_tree(target: str | os.PathLike[str], roots: set[str], dirs: set[str],
              terv: _Terv) -> list[Candidate]:
    """Teljes konyvtarfa, utvonalak alapjan.

    Szandekosan nem rekurziv: egy melyen agazo megosztason a rekurzio
    elfogyna (RecursionError), es a takaritas a felenel allna le.

    Egy alkonyvtar olvasasi hibaja (jogosultsag, halozati akadas) nem allitja
    le az egeszet: azt az agat kihagyjuk - ami ott van, azt nem toroljuk -, es
    szolunk rola a figyelon keresztul. Magat a vizsgalt konyvtarat viszont
    tudnunk kell olvasni, kulonben nem tudjuk, mi van benne."""
    # A talalatokat a mar kiszamolt osszehasonlitasi kulcsukkal egyutt gyujtjuk:
    # a vegen igy nem kell ujra eloallitani a rendezeshez (merve 100 000 elemnel
    # 0,65 mp helyett 0,02 mp).
    out: list[tuple[str, Candidate]] = []
    kis_nagy = terv.beallitas.ignore_case
    gyoker = Path(target)
    varolista = [gyoker]
    atnezett = 0
    while varolista:
        path = varolista.pop()
        try:
            bejegyzesek = scandir_sorted(path)
        except QbtError as exc:
            if path == gyoker:
                raise
            terv.figyelo.figyelmeztet(str(exc))
            continue
        for entry in bejegyzesek:
            atnezett += 1
            if atnezett % JELZES_ELEMENKENT == 0:
                terv.figyelo.ellenoriz()
                terv.figyelo.jelez(
                    f"{target}: {atnezett} elem atnezve, "
                    f"{len(out)} felesleges...")
            full = path / entry.name
            key = path_key(full, kis_nagy)
            if terv.bekenhagy(key, norm_key(entry.name, kis_nagy)):
                continue
            if kesz_kulcs(key, kis_nagy) in roots:
                continue  # a torrente: se o, se ami alatta van
            if entry.is_symlink():
                if key not in dirs:
                    out.append((key, Candidate(
                        full, False, 0, "nem tartozik torrenthez (link)")))
                continue
            is_dir = entry.is_dir(follow_symlinks=False)
            if is_dir and key in dirs:
                varolista.append(full)  # van alatta megtartando elem
                continue
            if too_young(full, terv.beallitas.min_age_days):
                continue
            out.append((key, Candidate(full, is_dir, entry_size(full, is_dir),
                                       "nem tartozik torrenthez")))
    out.sort(key=lambda parost: parost[0])
    return [jelolt for _, jelolt in out]


def erintett_torrentek(
    torrents: Sequence[Torrent],
    targets: Sequence[Path],
    beallitas: Beallitas,
) -> list[str]:
    """Azoknak a torrenteknek az azonositoja, amik a vizsgalt konyvtarakba
    esnek.

    Csak ezeknek kell fajlonkent lekerni a tartalmat (--pontos). Egy nagy
    qBittorrentben a torrentek tobbsege tipikusan mas konyvtarban lakik: az o
    fajllistajuk lekerese torrentenkent egy felesleges halozati fordulo lenne,
    az eredmenyt pedig ugyis eldobnank."""
    kis_nagy = beallitas.ignore_case
    cel_kulcsok = [path_key(t, kis_nagy) for t in targets]
    kellenek: list[str] = []
    for torrent in torrents:
        thash = torrent.get("hash") or ""
        if not thash:
            continue
        for nyers in (torrent.get("save_path"), torrent.get("download_path"),
                      torrent.get("content_path")):
            helyi = apply_maps(normalize_remote(nyers or ""), beallitas.maps,
                               kis_nagy)
            if not helyi:
                continue
            kulcs = path_key(helyi, kis_nagy)
            # Az is szamit, ha a torrent a vizsgalt konyvtar FOLOTT van: a
            # fajljai akkor is beleeshetnek (pl. save_path=/downloads, a
            # vizsgalt konyvtar meg /downloads/rss).
            if any(under(kulcs, cel) or under(cel, kulcs)
                   for cel in cel_kulcsok):
                kellenek.append(thash)
                break
    return kellenek


def _gyokertelen_ellenorzes(
    torrents: Sequence[Torrent],
    files_by_hash: Mapping[str, Sequence[str]],
    ignore_case: bool,
) -> None:
    """Biztonsagi fek a gyoker-konyvtar nelkuli torrentekre.

    Az ilyen torrent fajljai kozvetlenul a mentesi konyvtarban vannak, es a
    nevuket CSAK a fajllistabol lehet megtudni. Ha az hianyzik, a program nem
    latna, hogy azok a fajlok egy torrenthez tartoznak - es letorolne oket.
    Inkabb leallunk: a hivo dolga lekerni a fajllistat (lasd
    gyokertelen_torrentek)."""
    hianyzik = [thash for thash in gyokertelen_torrentek(torrents, ignore_case)
                if not files_by_hash.get(thash)]
    if hianyzik:
        raise SafetyStop(
            f"{len(hianyzik)} torrentnek nincs gyoker-konyvtara (a fajljai "
            "kozvetlenul a mentesi konyvtarban vannak), es a fajllistajuk "
            "hianyzik. Enelkul a sajat fajljaikat is feleslegesnek latnam, "
            "ezert leallok.")


def plan_all(
    torrents: Sequence[Torrent],
    files_by_hash: Mapping[str, Sequence[str]],
    targets: Sequence[Path],
    beallitas: Beallitas | None = None,
    figyelo: Figyelo | None = None,
) -> list[Candidate]:
    """A teljes terv: mely elemekhez nem tartozik mar torrent.

    A vizsgalt konyvtarak vedik egymast: ha az egyik a masik alkonyvtara (pl.
    downloads es downloads/rss), akkor a szulo takaritasakor nem esik aldozatul.

    SafetyStop-ot dob, ha a beallitasokbol az kovetkezne, hogy szinte mindent
    torolne - ilyenkor sokkal valoszinubb, hogy a beallitas rossz, mint hogy
    tenyleg minden felesleges.
    """
    beallitas = beallitas or Beallitas()
    figyelo = figyelo or Figyelo()
    if not torrents and not beallitas.allow_empty:
        raise SafetyStop("A qBittorrentben egyetlen torrent sincs, igy MINDENT "
                         "torolne.")
    kis_nagy = beallitas.ignore_case
    _gyokertelen_ellenorzes(torrents, files_by_hash, kis_nagy)
    names = (owned_names(torrents, files_by_hash, kis_nagy)
             if beallitas.mode == Mod.FELSO else set())
    candidates: list[Candidate] = []
    for target in targets:
        figyelo.ellenoriz()
        vedett = [t for t in targets if t != target]
        vedett += list(beallitas.extra_protected)
        terv = _Terv.keszit(beallitas, vedett, figyelo)
        if beallitas.mode == Mod.FELSO:
            candidates += plan_toplevel(target, names, terv)
            continue
        roots, dirs = owned_paths(torrents, files_by_hash, beallitas.maps,
                                  target, kis_nagy)
        figyelo.jegyzet(target, len(roots))
        if not roots and not beallitas.allow_empty:
            raise SafetyStop(
                f"Egyetlen torrent-elem sem esik a(z) {target} konyvtarba. "
                "Valoszinuleg utvonal-megfeleltetes kell (TAVOLI=HELYI). "
                "Igy MINDENT torolne, ezert leallok.")
        candidates += plan_tree(target, roots, dirs, terv)
    return candidates


# ------------------------------------------------------------------ torles

def human(size: float) -> str:
    """Ember szamara olvashato meret."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < EGYSEG or unit == "PB":
            return f"{int(size)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= EGYSEG
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


def csere_ujraprobalva(forras: Path, cel: Path, probak: int = 5) -> None:
    """Fajl vegleges helyre mozgatasa (a beallitasok mentesehez).

    Eloszor ideiglenes fajlba irunk, es csak keszen cserelunk - igy egy
    felbeszakadt mentes nem teszi tonkre a meglevo fajlt. A cserenel viszont
    Windowson a viruskereso, a keresoindexelo vagy egy megnyitott elonezet
    atmenetileg fogva tarthatja a celt, es a csere PermissionError-ral
    elszallna: ilyenkor rovid varakozas utan ujraprobaljuk. Linuxon es
    macOS-en ez az ag gyakorlatilag sosem fut le."""
    for proba in range(max(1, probak)):
        try:
            os.replace(forras, cel)
            return
        except PermissionError:
            if proba == probak - 1:
                raise
            time.sleep(0.15 * 2 ** proba)


@functools.lru_cache(maxsize=8)
def _gazdak(celok: tuple[str, ...]) -> tuple[tuple[str, Path], ...]:
    """A vizsgalt konyvtarak osszehasonlitasra elokeszitve, a legkulsotol.

    Elemenkent ujra rendezni es Path-ot epiteni feleslegesen draga: tizezer
    torolt elemnel merve ez volt a torlesi ciklus legdragabb resze."""
    return tuple((path_key(cel), Path(cel))
                 for cel in sorted(celok, key=len))


def owner_target(
    path: str | os.PathLike[str],
    targets: Sequence[str | os.PathLike[str]],
) -> Path:
    """Melyik vizsgalt konyvtarhoz kepest szamoljuk az elem utvonalat (a
    kukaban ez alapjan jon letre a konyvtar-szerkezet). Egymasba agyazott
    konyvtaraknal a legkulsot valasztjuk, igy nem utik egymast az azonos nevu
    fajlok (pl. rss\\film.mkv es film.mkv)."""
    gazdak = _gazdak(tuple(str(t) for t in targets))
    if not gazdak:
        return Path(path).parent
    kulcs = path_key(path)
    return next((cel for gazda_kulcs, cel in gazdak
                 if kulcs != gazda_kulcs and under(kulcs, gazda_kulcs)),
                gazdak[0][1])


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


def pozitiv_egesz(szoveg: str) -> int:
    ertek = int(szoveg)
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
    parser.add_argument("--probak", type=pozitiv_egesz, default=ALAP_PROBAK,
                        metavar="DB",
                        help="egy WebUI hivas ennyiszer probalkozzon atmeneti "
                             "hiba eseten (alap: %(default)s; 1 = ne probaljon "
                             "ujra)")
    parser.add_argument("--szalak", type=pozitiv_egesz, default=ALAP_SZALAK,
                        metavar="DB",
                        help=f"a --pontos fajllista-lekeres parhuzamossaga "
                             f"(alap: %(default)s, legfeljebb {MAX_SZALAK})")
    parser.add_argument("--verzio", "--version", action="version",
                        version=f"qbt_cleanup.py {__version__}",
                        help="a verzio kiirasa")
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
            raise BeallitasHiba(f"Nincs ilyen konyvtar: {target}")
        if not target.is_dir():
            raise BeallitasHiba(f"Nem konyvtar: {target}")
        if is_root_like(target):
            raise BeallitasHiba(
                f"Biztonsagi okbol a gyoker konyvtarat nem takaritom: {target}")
        # Ugyanaz a konyvtar ketszer megadva ketszer is torolne (masodszor mar
        # hibaval), ezert csak egyszer vesszuk fel.
        kulcs = path_key(target, ignore_case)
        if kulcs not in latott:
            latott.add(kulcs)
            targets.append(target)
    return targets


@dataclass(slots=True)
class _Futas:
    """A parancssorbol osszeallitott, mar ellenorzott futas.

    Azert kulon, mert az elokeszites (kapcsolok ertelmezese, konyvtarak
    ellenorzese) es a vegrehajtas ket kulon dolog: igy mindketto onmagaban
    olvashato es tesztelheto marad."""

    targets: list[Path]
    beallitas: Beallitas
    halozat: Halozat
    trash_dir: Path | None = None


def _kuka_elokeszites(args: argparse.Namespace, targets: Sequence[Path],
                      ignore_case: bool) -> Path | None:
    """A kuka konyvtar letrehozasa es ellenorzese. Hiba eseten QbtError."""
    if not args.kuka:
        return None
    trash_dir = normalize_target(args.kuka)
    try:
        trash_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BeallitasHiba(
            f"Nem tudom letrehozni a kukat ({trash_dir}): {exc}") from exc
    kuka_kulcs = path_key(trash_dir, ignore_case)
    if any(kuka_kulcs == path_key(t, ignore_case) for t in targets):
        raise BeallitasHiba("A kuka nem lehet maga a vizsgalt konyvtar.")
    return trash_dir


def _elokeszites(args: argparse.Namespace) -> _Futas:
    """A kapcsolokbol ellenorzott futas. Hiba eseten QbtError vagy ValueError."""
    ignore_case = not args.case_sensitive
    targets = _celkonyvtarak(args.konyvtarak, ignore_case)
    maps = tuple(parse_map(entry) for entry in args.utvonal)
    trash_dir = _kuka_elokeszites(args, targets, ignore_case)

    excludes = tuple(args.kivetel)
    if not args.no_default_excludes:
        excludes += DEFAULT_EXCLUDES

    beallitas = Beallitas(
        mode=Mod(args.mod),
        maps=maps,
        excludes=excludes,
        ignore_case=ignore_case,
        min_age_days=args.min_age,
        extra_protected=(trash_dir,) if trash_dir else (),
        allow_empty=args.allow_empty,
    )
    halozat = Halozat(timeout=args.timeout, probak=args.probak,
                      insecure=args.insecure, szalak=args.szalak)
    return _Futas(targets, beallitas, halozat, trash_dir)


def _jelszo(args: argparse.Namespace) -> str | None:
    """A jelszo a parancssorbol, a kornyezetbol, vagy bekerve. Ha kellene, de
    nincs honnan venni: QbtError."""
    password = args.password
    if password is None:
        password = os.environ.get("QBT_PASSWORD")
    if args.user and password is None:
        if not sys.stdin.isatty():
            raise BeallitasHiba("Nincs jelszo (--password vagy QBT_PASSWORD).")
        password = getpass.getpass(f"qBittorrent jelszo ({args.user}): ")
    return password


def kell_fajllista(torrents: Sequence[Torrent], targets: Sequence[Path],
                   beallitas: Beallitas, pontos: bool) -> list[str]:
    """Mely torrentekhez kell a fajllista.

    Ket okbol kell: a --pontos modhoz (ott fajlonkent hasonlitunk), illetve a
    gyoker-konyvtar nelkuli torrentekhez - azoknal CSAK igy tudjuk meg, mi
    tartozik hozzajuk a mentesi konyvtarban. Ez utobbi az uzemmodtol fuggetlen,
    kulonben a sajat fajljaikat torolnenk."""
    kellenek = gyokertelen_torrentek(torrents, beallitas.ignore_case)
    if pontos:
        kellenek += erintett_torrentek(torrents, targets, beallitas)
    return list(dict.fromkeys(kellenek))


def _lekerdezes(
    client: QbtClient, futas: _Futas, pontos: bool,
) -> tuple[str, list[dict[str, Any]], dict[str, list[str]]]:
    """Bejelentkezes, torrentek, es (ha kell) a fajllistak lekerese."""
    client.login()
    version = client.version()
    torrents = client.torrents()
    files_by_hash: dict[str, list[str]] = {}
    kellenek = kell_fajllista(torrents, futas.targets, futas.beallitas, pontos)
    if kellenek:
        print(f"Fajllista lekerese {len(kellenek)} torrenthez "
              f"({len(torrents)} kozul)...")
        files_by_hash = client.files_many(kellenek)
    return version, torrents, files_by_hash


def _torlesek(candidates: Sequence[Candidate], futas: _Futas,
              naplo: qbt_naplo.TorlesNaplo | None) -> tuple[int, int]:
    """A tenyleges torles. Visszaadja: (felszabadult bajt, sikertelen darab)."""
    freed = 0
    failed = 0
    for cand in candidates:
        gazda = owner_target(cand.path, futas.targets)
        ok, message = remove_entry(cand, gazda, futas.trash_dir)
        if ok:
            freed += cand.size
        else:
            failed += 1
        if naplo:
            naplo.rogzit(cand, ok, message, kukaba=bool(futas.trash_dir))
        print(f"  {human(cand.size):>10}  {cand.path}  ({message})")
    return freed, failed


def _figyelmeztetesek(gondok: Sequence[str]) -> None:
    if not gondok:
        return
    print()
    print(f"Figyelem: {len(gondok)} konyvtarat nem tudtam beolvasni - "
          "ezekben nem takaritottam:", file=sys.stderr)
    for gond in gondok[:MUTATOTT_RESZLET]:
        print(f"  {gond}", file=sys.stderr)
    if len(gondok) > MUTATOTT_RESZLET:
        print(f"  ... es meg {len(gondok) - MUTATOTT_RESZLET}.",
              file=sys.stderr)


def _esemenynaplo_indul(args: argparse.Namespace, pontos: bool) -> None:
    """Az esemenynaplo bekapcsolasa a torlesi naplo melle.

    Utemezve futtatva (Feladatutemezo) a kepernyore irt uzenetek elvesznek -
    ez az egyetlen nyom arrol, hogy a takaritas egyaltalan elindult-e, es hol
    allt meg.

    A parancssort SZANDEKOSAN nem irjuk bele, csak a lenyeget: a --password
    ott lehet benne, es a naplo nem valo jelszotarnak."""
    if args.no_naplo:
        return
    hova = (Path(args.naplo).parent / qbt_naplo.ESEMENY_NEV
            if args.naplo else None)
    qbt_naplo.esemenyek_indul(hova)
    qbt_naplo.jegyzet("indul: qbt_cleanup %s (mod: %s%s, %s, %d konyvtar)",
                      __version__, args.mod, ", pontos" if pontos else "",
                      "torol" if args.torol else "proba",
                      len(args.konyvtarak))


def _figyelmeztet_kapcsolokra(args: argparse.Namespace, pontos: bool) -> None:
    """A csendben hatastalan kapcsolokra kulon szolunk: kulonben a felhasznalo
    azt hinne, hogy hatott."""
    if args.pontos and not pontos:
        print("Figyelem: a --pontos csak a 'fa' modban szamit, most nem "
              "hasznalom.", file=sys.stderr)
    if args.utvonal and args.mod != Mod.FA:
        print("Figyelem: az --utvonal csak a 'fa' modban szamit.",
              file=sys.stderr)


def _fejlec(client: QbtClient, version: str, torrents: Sequence[Torrent],
            futas: _Futas, pontos: bool) -> None:
    print(f"qBittorrent {version} ({client.base}) - {len(torrents)} torrent")
    print(f"Uzemmod: {futas.beallitas.mode}{' (pontos)' if pontos else ''}")
    for target in futas.targets:
        print(f"Vizsgalt konyvtar: {target}")


def _atnezes(torrents: Sequence[Torrent],
             files_by_hash: Mapping[str, Sequence[str]],
             futas: _Futas) -> list[Candidate]:
    """A konyvtarak atnezese, a menet kozbeni gondok kiirasaval."""
    gondok: list[str] = []
    figyelo = Figyelo(
        on_note=lambda cel, db: print(
            f"A(z) {cel} alatt talalt torrent-elemek: {db}"),
        on_warn=gondok.append,
    )
    candidates = plan_all(torrents, files_by_hash, futas.targets,
                          futas.beallitas, figyelo)
    _figyelmeztetesek(gondok)
    return candidates


def _lista_kiirasa(candidates: Sequence[Candidate], total: int) -> None:
    print(f"Felesleges elemek ({len(candidates)} db, {human(total)}):")
    for cand in candidates:
        print(f"  [{'D' if cand.is_dir else 'F'}] {human(cand.size):>10}  "
              f"{cand.path}")


def _torles_szakasz(args: argparse.Namespace, futas: _Futas,
                    candidates: Sequence[Candidate], total: int) -> int:
    """A tenyleges torles: fekek, megerosites, naplo, vegrehajtas."""
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
        if not confirm(len(candidates), total, futas.trash_dir):
            print("Megsem toroltem semmit.")
            return 0

    naplo = None
    if not args.no_naplo:
        naplo = qbt_naplo.nyitas(args.naplo,
                                 int(args.naplo_meret * 1024 * 1024),
                                 args.naplo_tartas)
    print()
    try:
        freed, failed = _torlesek(candidates, futas, naplo)
    finally:
        if naplo:
            naplo.close()

    print()
    qbt_naplo.jegyzet("kesz: %d elem torolve, %s felszabadulva, %d sikertelen",
                      len(candidates) - failed, human(freed), failed)
    maradt = f"  {failed} elem sikertelen!" if failed else ""
    print(f"Kesz: {len(candidates) - failed} elem, {human(freed)} "
          f"felszabadulva.{maradt}")
    if naplo:
        print(f"A torlesek naploja: {naplo.path}")
    return 1 if failed else 0


def _main(argv: Sequence[str] | None) -> int:
    _utf8_kimenet()

    args = build_parser().parse_args(argv)
    pontos = args.pontos and args.mod == Mod.FA
    _esemenynaplo_indul(args, pontos)
    _figyelmeztet_kapcsolokra(args, pontos)

    try:
        futas = _elokeszites(args)
        client = QbtClient(args.url, args.user, _jelszo(args), futas.halozat)
        version, torrents, files_by_hash = _lekerdezes(client, futas, pontos)
        _fejlec(client, version, torrents, futas, pontos)
        candidates = _atnezes(torrents, files_by_hash, futas)
    except (BeallitasHiba, ValueError) as exc:   # a keressel van baj
        print(str(exc), file=sys.stderr)
        return 2
    except SafetyStop as exc:                    # a biztonsagi fek fogott
        qbt_naplo.jegyzet("biztonsagi fek: %s", exc)
        print()
        print(f"{exc} Ha tenyleg ezt akarod: --ures-lista-ok", file=sys.stderr)
        return 2
    except QbtError as exc:                      # halozat vagy fajlrendszer
        qbt_naplo.jegyzet("a takaritas megallt: %s", exc)
        print(f"Hiba: {exc}", file=sys.stderr)
        print("Semmit nem toroltem.", file=sys.stderr)
        return 1

    total = sum(c.size for c in candidates)
    qbt_naplo.jegyzet("atnezve: %d torrent, %d felesleges elem (%s)",
                      len(torrents), len(candidates), human(total))
    print()
    if not candidates:
        print("Nincs felesleges elem - nincs mit tenni.")
        return 0

    _lista_kiirasa(candidates, total)
    if not args.torol:
        print()
        print("Ez csak proba volt, semmit nem toroltem. "
              "Tenyleges torleshez tedd hozza: --torol")
        return 0

    return _torles_szakasz(args, futas, candidates, total)


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < MIN_PYTHON:
        kell = ".".join(str(x) for x in MIN_PYTHON)
        print(f"Tul regi Python: {sys.version.split()[0]} (legalabb {kell} kell).",
              file=sys.stderr)
        return 2
    try:
        return _main(argv)
    except (KeyboardInterrupt, Megszakitva):  # pragma: no cover - kezi leallitas
        qbt_naplo.jegyzet("megszakitva")
        print("\nMegszakitva. A hatralevo elemekhez nem nyultam.",
              file=sys.stderr)
        return 130
    finally:
        qbt_naplo.esemenyek_lezar()


if __name__ == "__main__":
    sys.exit(main())
