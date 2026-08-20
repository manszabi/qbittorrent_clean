#!/usr/bin/env python3
"""Naplok: mi tunt el (torlesi naplo), es mi tortent (esemenynaplo).

Minden torolt (vagy kukaba mozgatott) elemrol egy sor kerul a naploba: a
pontos ido, a muvelet, a meret, es kulon oszlopban a konyvtar es a fajlnev.
A sorok tabulatorral vannak elvalasztva, igy a fajl szovegszerkesztoben is
olvashato, tablazatkezeloben pedig egybol oszlopokra bomlik.

A naplo magatol rotalodik: uj fajlt kezd, ha
  * uj het kezdodott (hetfo 00:00), vagy
  * a mostani fajl elerte a merethatart (alap: 5 MB).
A lezart fajlt gzip-pel tomoriti (torlesek-2026-08-14.log.gz), es a
megadott darabszamnal regebbieket eldobja.

A masodik naplo (esemenyek.log) nem konyveles, hanem hibakereses: mikor
indult a program, mit nem ert el, hol allt le. Ez a grafikus felulet - es az
utemezett futas - egyetlen nyoma egy baj utan, mert ott nincs konzol, ami
megorizne a kepernyore irt uzeneteket.

A naplozas SOHA nem allithatja meg a takaritast: ha barmi gond van vele,
csak jelzunk rola, es a torles megy tovabb.
"""

from __future__ import annotations

import contextlib
import gzip
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timedelta
from io import TextIOWrapper
from logging.handlers import BaseRotatingHandler, RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # csak a tipusokhoz kell, korkoros importot nem okoz
    from qbt_cleanup import Candidate

# Alapertelmezesek. A merethatar es a megtartott fajlok szama a hivo oldalrol
# is allithato (--naplo-meret, --naplo-tartas).
ALAP_MERET: Final = 5 * 1024 * 1024   # 5 MB
ALAP_TARTAS: Final = 12               # kb. negyedevnyi heti fajl
NAPLO_NEV: Final = "torlesek.log"

# Az esemenynaplo (mi tortent a program koruli) kisebb es rovidebb ideig kell:
# nem konyveles, hanem hibakereses.
ESEMENY_NEV: Final = "esemenyek.log"
ESEMENY_MERET: Final = 512 * 1024
ESEMENY_TARTAS: Final = 3

OSZLOPOK: Final = ("ido", "muvelet", "tipus", "meret_bajt", "konyvtar", "nev",
                   "reszletek")
FEJLEC: Final = "\t".join(OSZLOPOK)
IDO_ALAK: Final = "%Y-%m-%d %H:%M:%S"


def naplo_konyvtar() -> Path:
    """A naplo helye: Windowson az AppData, maskepp az XDG szerinti allapot-
    konyvtar (ide valok a naplok, nem a beallitasok melle)."""
    appdata = os.environ.get("APPDATA")
    if sys.platform == "win32" and appdata:
        return Path(appdata) / "qbittorrent_clean" / "naplo"
    allapot = os.environ.get("XDG_STATE_HOME")
    alap = Path(allapot) if allapot else Path.home() / ".local" / "state"
    return alap / "qbittorrent_clean" / "naplo"


def alap_naplo_fajl() -> Path:
    return naplo_konyvtar() / NAPLO_NEV


def esemeny_naplo_fajl() -> Path:
    return naplo_konyvtar() / ESEMENY_NEV


def _kovetkezo_hetfo(mikor: datetime) -> float:
    """A `mikor` utani elso hetfo 00:00 idobelyege. Ekkor kezdunk uj fajlt."""
    hetfo = mikor.date() + timedelta(days=7 - mikor.weekday())
    return datetime.combine(hetfo, datetime.min.time()).timestamp()


def _mezo(ertek: object) -> str:
    """Egy oszlop tartalma. A tabulatort es a sortorest ki kell szurni, mert
    azok szetvagnak a sort - fajlnevben (Linuxon) barmi elofordulhat."""
    szoveg = str(ertek)
    for jel in ("\t", "\r", "\n"):
        szoveg = szoveg.replace(jel, " ")
    return szoveg


class HetiMeretRotalo(BaseRotatingHandler):
    """Naplofajl, ami hetente ES merethatarnal is uj fajlt kezd.

    A szabvany konyvtarban a ketto kulon-kulon letezik (TimedRotatingFile-
    Handler, illetve RotatingFileHandler), egyszerre viszont nem - ezert
    ez a kis osztaly. A lezart fajlt gzip-pel tomoriti."""

    def __init__(self, filename: str | os.PathLike[str],
                 max_bytes: int = ALAP_MERET, backup_count: int = ALAP_TARTAS,
                 encoding: str = "utf-8") -> None:
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        super().__init__(str(filename), "a", encoding=encoding, delay=False)
        self.hatarido = _kovetkezo_hetfo(datetime.fromtimestamp(self._kezdet()))

    def _kezdet(self) -> float:
        """A mostani fajl kora. Ha mar letezik, a modositasi idejebol indulunk
        ki (ugyanugy, ahogy a szabvany idozitett kezelo teszi)."""
        try:
            return os.stat(self.baseFilename).st_mtime
        except OSError:
            return time.time()

    def _open(self) -> TextIOWrapper:
        ures = (not os.path.exists(self.baseFilename)
                or os.path.getsize(self.baseFilename) == 0)
        stream = super()._open()
        if ures:  # minden uj fajl a fejleccel kezdodik
            stream.write(FEJLEC + self.terminator)
            stream.flush()
        return stream

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        if time.time() >= self.hatarido:
            return True
        if self.max_bytes <= 0:
            return False
        if self.stream is None:  # pragma: no cover - csak delay=True eseten
            self.stream = self._open()
        uzenet = self.format(record) + self.terminator
        self.stream.seek(0, os.SEEK_END)
        return self.stream.tell() + len(uzenet.encode("utf-8")) > self.max_bytes

    def _rotalt_nev(self) -> Path:
        """Szabad nev a lezart fajlnak:
        torlesek-2026-08-14_142530_871204.log.gz

        A mikromasodperc mindig benne van. Ez ket dolgot ad: a fajlok neve
        szerint is pontosan idorendben allnak, es egy korabbi nev sosem
        hasznalodik ujra - kulonben egy mar eldobott (regi) nev egy friss
        fajlra kerulne, es a sorrend osszekeveredne."""
        alap = Path(self.baseFilename)
        most = datetime.now()
        for lepes in range(1000):
            mikor = (most + timedelta(microseconds=lepes)).strftime(
                "%Y-%m-%d_%H%M%S_%f")
            jelolt = alap.with_name(f"{alap.stem}-{mikor}{alap.suffix}.gz")
            if not jelolt.exists():
                return jelolt
        return alap.with_name(  # pragma: no cover - gyakorlatilag elerhetetlen
            f"{alap.stem}-{mikor}-{time.time_ns()}{alap.suffix}.gz")

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None  # type: ignore[assignment]
        forras = Path(self.baseFilename)
        if forras.exists() and forras.stat().st_size:
            cel = self._rotalt_nev()
            with forras.open("rb") as be, gzip.open(cel, "wb") as ki:
                shutil.copyfileobj(be, ki)
            forras.unlink()
        self._regieket_eldob()
        self.hatarido = _kovetkezo_hetfo(datetime.now())
        if not self.delay:
            self.stream = self._open()

    def _regieket_eldob(self) -> None:
        if self.backup_count <= 0:
            return
        alap = Path(self.baseFilename)
        # A modositasi ido szerint rendezunk, nem nev szerint: a nevben a
        # kotojel korabbra rendezodne, mint a pont, igy egy sorszam nelkuli
        # (regi) fajl a lista vegere kerulne, es a legfrissebbet dobnank el.
        regiek = sorted(alap.parent.glob(f"{alap.stem}-*{alap.suffix}.gz"),
                        key=lambda f: (f.stat().st_mtime, f.name))
        for fajl in regiek[:max(0, len(regiek) - self.backup_count)]:
            # Ha epp mas fogja a fajlt, majd a kovetkezo rotalas eldobja.
            with contextlib.suppress(OSError):
                fajl.unlink()


class TorlesNaplo:
    """A naplo hasznalata: `rogzit()` minden elem utan, a vegen `close()`.

    Szandekosan nem a logging modul globalis nyilvantartasat hasznalja (nincs
    getLogger), hanem kozvetlenul a sajat kezelojenek adja at a sort: igy tobb
    peldany sem zavarja egymast, es a tesztek utan sem marad utana semmi."""

    def __init__(self, path: str | os.PathLike[str],
                 max_bytes: int = ALAP_MERET,
                 backup_count: int = ALAP_TARTAS) -> None:
        self.path = Path(path)
        self.handler = HetiMeretRotalo(self.path, max_bytes, backup_count)
        self.handler.setFormatter(
            logging.Formatter("%(asctime)s\t%(message)s", datefmt=IDO_ALAK))

    def rogzit(self, candidate: Candidate, siker: bool, uzenet: str = "",
               kukaba: bool = False) -> None:
        """Egy elem sorsanak rogzitese. Hibat nem dob: a naplo miatt nem
        allhat meg a takaritas."""
        if siker:
            muvelet = "kukaba" if kukaba else "torolve"
            reszletek = uzenet if kukaba else ""
        else:
            muvelet = "sikertelen"
            reszletek = uzenet
        sor = "\t".join(_mezo(x) for x in (
            muvelet,
            "konyvtar" if candidate.is_dir else "fajl",
            candidate.size,
            candidate.path.parent,
            candidate.path.name,
            reszletek,
        ))
        try:
            self.handler.handle(logging.LogRecord(
                "qbt_naplo", logging.INFO, __file__, 0, sor, (), None))
        except Exception as exc:  # noqa: BLE001 - a torles fontosabb
            print(f"Figyelem: a naploba nem sikerult irni: {exc}",
                  file=sys.stderr)

    def close(self) -> None:
        with contextlib.suppress(Exception):  # pragma: no cover
            self.handler.close()

    def __enter__(self) -> TorlesNaplo:
        return self

    def __exit__(self, *_kivetel: object) -> None:
        self.close()


# --------------------------------------------------------------- esemenyek

# A torlesi naplo azt konyveli, MI tunt el. Az esemenynaplo azt, hogy MI
# TORTENT a program korul: mikor indult, mit nem ert el, hol allt le. A ketto
# szandekosan kulon fajl: a torlesi naplot tablazatkezeloben nezik, es nem
# valo bele hibauzenet.
#
# A grafikus feluletnek ez az egyetlen nyoma egy baj utan (nincs konzolja), az
# utemezett futasnak pedig szinten: a Feladatutemezo elnyeli a kimenetet.
_esemeny_log: Final = logging.getLogger("qbittorrent_clean")
_esemeny_log.propagate = False  # a hivo sajat naplozasat nem zavarjuk


def esemenyek_indul(path: str | os.PathLike[str] | None = None) -> Path | None:
    """Az esemenynaplo bekapcsolasa. Ha nem sikerul, csak None - a program
    naplo nelkul is elmegy. Ketszer hivva nem nyit masodik fajlt."""
    if _esemeny_log.handlers:  # mar be van kapcsolva: a meglevo fajl marad
        meglevo = getattr(_esemeny_log.handlers[0], "baseFilename", "")
        return Path(meglevo) if meglevo else None
    cel = Path(path) if path else esemeny_naplo_fajl()
    try:
        cel.parent.mkdir(parents=True, exist_ok=True)
        kezelo = RotatingFileHandler(
            str(cel), maxBytes=ESEMENY_MERET, backupCount=ESEMENY_TARTAS,
            encoding="utf-8")
    except OSError:
        return None
    kezelo.setFormatter(logging.Formatter("%(asctime)s  %(message)s",
                                          datefmt=IDO_ALAK))
    _esemeny_log.addHandler(kezelo)
    _esemeny_log.setLevel(logging.INFO)
    return cel


def jegyzet(uzenet: str, *args: object) -> None:
    """Egy sor az esemenynaploba. Sosem dob hibat, es ha nincs bekapcsolva
    naplo, akkor sem csinal semmit - a hivo helyen nem kell ellenorizni."""
    if not _esemeny_log.handlers:
        return
    with contextlib.suppress(Exception):  # a naplo miatt semmi nem allhat meg
        _esemeny_log.info(uzenet, *args)


def esemenyek_lezar() -> None:
    """A naplofajl elengedese (a tesztek utan ne maradjon nyitva semmi)."""
    for kezelo in list(_esemeny_log.handlers):
        _esemeny_log.removeHandler(kezelo)
        with contextlib.suppress(Exception):
            kezelo.close()


# ------------------------------------------------------------ torlesi naplo

def nyitas(path: str | os.PathLike[str] | None = None,
           max_bytes: int = ALAP_MERET,
           backup_count: int = ALAP_TARTAS) -> TorlesNaplo | None:
    """Naplo nyitasa. Ha nem sikerul (nincs jog, tele a lemez), csak szolunk,
    es None-t adunk vissza - a takaritas naplo nelkul is elmehet."""
    cel = Path(path) if path else alap_naplo_fajl()
    try:
        return TorlesNaplo(cel, max_bytes, backup_count)
    except OSError as exc:
        print(f"Figyelem: a torlesi naplot nem tudom megnyitni ({cel}): {exc}",
              file=sys.stderr)
        return None
