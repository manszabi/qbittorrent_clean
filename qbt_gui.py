#!/usr/bin/env python3
"""qBittorrent takarító – grafikus felület.

A tényleges munkát a `qbt_cleanup.py` végzi (ugyanaz a kód, amit a parancssoros
használat is hív), ez a fájl csak a kezelőfelület: beállítások, a felesleges
elemek listája kipipálható tételekkel, és a törlés.

Indítás Windows alatt: kattints duplán a `qbittorrent_clean.bat` fájlra.
Máshol:

    python3 qbt_gui.py
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Final

# A motor a program mellett van, akkor is, ha máshonnan indítják.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import qbt_cleanup as engine
import qbt_naplo

CIM: Final = "qBittorrent takarító"

# Ennyi ezredmásodpercenként nézi meg az ablak, hogy üzent-e a háttérszál.
FIGYELES_MP: Final = 100

# A találati listát ekkora adagokban töltjük fel. Egy nagy megosztáson a
# vizsgálat sok tízezer sort is adhat, és ezeket egyszerre kitéve az ablak a
# betöltés végéig nem válaszol (mérve: 100 000 sor ≈ 1,05 mp egyben).
# Adagolva egyetlen blokk sem tart 5 ms-nál tovább, a teljes betöltés pedig
# nem lassabb (0,79 mp) – ráadásul közben látszik a haladás.
BETOLTES_ADAG: Final = 400

# A háttérszál állapotüzeneteit legfeljebb ilyen sűrűn engedjük az ablakhoz.
JELZES_SZUNET: Final = 0.1

# A hálózati beállítások gyári értékei (időkorlát, újrapróbálkozás, szálak).
# Egyetlen, meg nem változtatható példány: a Halozat fagyasztott adatosztály.
ALAP_HALOZAT: Final = engine.Halozat()


def dpi_tudatossag() -> None:
    """Windows 11 alatt a Tk alapbol nem DPI-tudatos: 125-150%-os nagyitasnal
    a rendszer nagyitja fel utolag az ablakot, amitol elmosodott lesz minden
    betu. Ezzel jelezzuk, hogy magunk kezeljuk a nagyitast.

    A Tk letrehozasa ELOTT kell meghivni."""
    if sys.platform != "win32":
        return
    import ctypes  # noqa: PLC0415 - csak Windowson kell, es csak indulaskor
    try:
        # 1 = rendszerszintu DPI-tudatossag (Windows 8.1 ota)
        ctypes.OleDLL("shcore").SetProcessDpiAwareness(1)
    except (OSError, AttributeError):  # pragma: no cover - regebbi Windows
        with contextlib.suppress(OSError, AttributeError):
            ctypes.windll.user32.SetProcessDPIAware()


def dpi_szorzo(root: tk.Misc) -> float:
    """A kepernyo nagyitasa (1.0 = 100%, 1.5 = 150%). A képpontban megadott
    meretek ennyivel szorzodnak, hogy nagy felbontason se legyen zsufolt."""
    if sys.platform != "win32":
        return 1.0  # mashol a rendszer maga skalaz
    try:
        return max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except tk.TclError:  # pragma: no cover
        return 1.0


def beallitas_fajl() -> Path:
    """A beállítások helye: Windowson az AppData, máshol a home könyvtár."""
    appdata = os.environ.get("APPDATA")
    if sys.platform == "win32" and appdata:
        return Path(appdata) / "qbittorrent_clean" / "beallitasok.json"
    return Path.home() / ".qbittorrent_clean.json"


def kijelolt_sorok(lista: tk.Listbox) -> list[int]:
    """Egy Listbox kijelölt sorainak indexei, csökkenő sorrendben – így a
    törlés nem csúsztatja el a még hátralévő indexeket.

    A tkinter típusleírásában a `curselection()` visszatérési értéke
    ismeretlen; itt egyszer, központi helyen rögzítjük, hogy egész számok."""
    kijelolt = lista.curselection()  # type: ignore[no-untyped-call]
    return sorted((int(x) for x in kijelolt), reverse=True)


def _szoveglista(adat: Any) -> list[str]:
    """A beállítás-fájlból jövő listák megszűrése. Kézzel is átírható fájl,
    ezért nem bízunk a szerkezetében: egy sima szövegen például végig lehetne
    iterálni betűnként."""
    if not isinstance(adat, list):
        return []
    return [x for x in adat if isinstance(x, str)]


_inditott: list[subprocess.Popen[bytes]] = []


def kulon_inditas(parancs: list[str]) -> None:
    """Külső program (fájlkezelő) indítása úgy, hogy a felület ne várjon rá.

    A korábban indítottak közül a már befejezetteket begyűjtjük: enélkül
    minden megnyitás után zombi folyamat maradna a program végéig. A külön
    munkamenet és az elnyelt kimenet azt szolgálja, hogy a fájlkezelő ne
    írjon a konzolunkra, és ne kapja meg a mi Ctrl+C-nket."""
    _inditott[:] = [p for p in _inditott if p.poll() is None]
    _inditott.append(subprocess.Popen(
        parancs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True))


@dataclass(frozen=True, slots=True)
class Feladat:
    """A felületről összeszedett, már ellenőrzött feladat.

    Korábban ez egy `dict[str, Any]` volt, szöveges kulcsokkal: egy elgépelt
    kulcs csak futás közben, a háttérszálban derült ki. Így a mezőket a
    szerkesztő és a ruff is ellenőrzi."""

    url: str
    user: str
    jelszo: str
    konyvtarak: tuple[Path, ...]
    beallitas: engine.Beallitas
    halozat: engine.Halozat = ALAP_HALOZAT
    pontos: bool = False
    kuka: Path | None = None
    naplo: Path | None = None


@dataclass(frozen=True, slots=True)
class _Mezok:
    """A felület ellenőrzött mezői egyben. Csak azért van, hogy az
    ellenőrzés és a feladat összeállítása két külön, rövid lépés lehessen."""

    konyvtarak: list[Path]
    min_kor: float
    utvonalak: tuple[engine.PathMap, ...]
    halozat: engine.Halozat
    kuka: Path | None


class TakaritoApp:
    """A teljes kezelőfelület. A hálózati és fájlrendszeri munka külön szálon
    fut, hogy az ablak ne fagyjon le; az eredmény egy sorba (queue) kerül, amit
    az ablak 100 ezredmásodpercenként néz meg."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.uzenetek: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.elemek: list[engine.Candidate] = []   # engine.Candidate lista
        self.pipaltak: set[int] = set()            # a bepipált elemek indexei
        self.sor_index: dict[str, int] = {}        # Treeview sor -> index
        self.dolgozik = False
        # A vizsgálatkor érvényes könyvtárlista. A törlésnél ehhez mérjük az
        # elemeket (a kukában ez adja a könyvtár-szerkezetet), különben egy
        # időközbeni átállítás rossz helyre pakolná a fájlokat.
        self.vizsgalt_konyvtarak: list[Path] = []
        # A háttérszál ezt nézi: ha be van állítva, két elem között leáll.
        # Így a megszakítás sosem hagy félig törölt elemet maga után.
        self.megallj = threading.Event()
        self._figyelo: str | None = None
        self._betolto: str | None = None
        self._utolso_jelzes = 0.0
        self.szorzo = dpi_szorzo(root)

        root.title(CIM)
        root.minsize(self.kp(880), self.kp(620))
        with contextlib.suppress(tk.TclError):  # a betuk is kovessek a nagyitast
            root.tk.call("tk", "scaling", self.szorzo * 96.0 / 72.0)
        self._epit()
        self.beallitasok_betoltese()
        root.protocol("WM_DELETE_WINDOW", self.kilepes)
        self._figyelo = root.after(FIGYELES_MP, self._sor_figyelese)

    def kp(self, keppont: int) -> int:
        """Keppontban megadott meret a kepernyo nagyitasahoz igazitva."""
        return round(keppont * self.szorzo)

    # ------------------------------------------------------------ felület

    def _epit(self) -> None:
        """Az ablak felépítése. A szakaszok külön metódusban vannak: együtt
        százsoros függvény lenne, amiben a keresés is nehézkes."""
        fo = ttk.Frame(self.root, padding=8)
        fo.pack(fill="both", expand=True)
        fo.columnconfigure(0, weight=1)
        fo.rowconfigure(4, weight=1)

        self._epit_kapcsolat(fo)
        self._epit_konyvtarak(fo)
        self._epit_beallitasok(fo)
        self._epit_gombok(fo)
        self._epit_lista(fo)
        self._epit_allapotsor(fo)

        self._mod_valtas()
        self._kuka_valtas()
        self._tls_valtas()

    def _epit_kapcsolat(self, fo: ttk.Frame) -> None:
        """A qBittorrent WebUI adatai."""
        kap = ttk.LabelFrame(fo, text="qBittorrent WebUI", padding=8)
        kap.grid(row=0, column=0, sticky="ew")
        kap.columnconfigure(1, weight=1)

        ttk.Label(kap, text="Cím:").grid(row=0, column=0, sticky="w")
        self.v_url = tk.StringVar(value="http://192.168.1.38:30024/")
        ttk.Entry(kap, textvariable=self.v_url).grid(row=0, column=1, columnspan=3,
                                                    sticky="ew", padx=4)

        ttk.Label(kap, text="Felhasználó:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.v_user = tk.StringVar(value="admin")
        ttk.Entry(kap, textvariable=self.v_user, width=18).grid(
            row=1, column=1, sticky="w", padx=4, pady=(4, 0))

        ttk.Label(kap, text="Jelszó:").grid(row=1, column=2, sticky="e", pady=(4, 0))
        self.v_pw = tk.StringVar()
        ttk.Entry(kap, textvariable=self.v_pw, show="•", width=18).grid(
            row=1, column=3, sticky="w", padx=4, pady=(4, 0))

        self.v_pw_mentes = tk.BooleanVar(value=False)
        ttk.Checkbutton(kap, text="jelszó megjegyzése (sima szövegként mentődik)",
                        variable=self.v_pw_mentes).grid(
            row=2, column=1, columnspan=3, sticky="w", padx=4, pady=(4, 0))

        ttk.Label(kap, text="Időkorlát (mp):").grid(
            row=3, column=0, sticky="w", pady=(4, 0))
        self.v_idokorlat = tk.StringVar(value=str(int(ALAP_HALOZAT.timeout)))
        ttk.Spinbox(kap, from_=1, to=600, increment=5, width=6,
                    textvariable=self.v_idokorlat).grid(
            row=3, column=1, sticky="w", padx=4, pady=(4, 0))

        # Ugyanaz, mint a parancssori --nem-biztonsagos-tls. Otthoni NAS-on a
        # WebUI tanusitvanya szinte mindig onalairt; a kockazatot kiirjuk.
        self.v_nem_biztonsagos = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            kap, text="önaláírt tanúsítvány elfogadása (https)",
            variable=self.v_nem_biztonsagos,
            command=self._tls_valtas).grid(
            row=3, column=2, columnspan=2, sticky="w", padx=4, pady=(4, 0))

        self.v_tls_gond = tk.StringVar(value="")
        self.cimke_tls = ttk.Label(kap, textvariable=self.v_tls_gond,
                                   foreground="#a03000")
        self.cimke_tls.grid(row=4, column=0, columnspan=5, sticky="w",
                            pady=(2, 0))

        ttk.Button(kap, text="Kapcsolat próba", command=self.kapcsolat_proba).grid(
            row=0, column=4, rowspan=2, sticky="ns", padx=(8, 0))

    def _epit_konyvtarak(self, fo: ttk.Frame) -> None:
        """A vizsgálandó könyvtárak listája."""
        kony = ttk.LabelFrame(fo, text="Vizsgált könyvtárak", padding=8)
        kony.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        kony.columnconfigure(0, weight=1)

        self.lista_kony = tk.Listbox(kony, height=4, exportselection=False)
        self.lista_kony.grid(row=0, column=0, rowspan=4, sticky="ew")
        gorgeto = ttk.Scrollbar(kony, orient="vertical",
                                command=self.lista_kony.yview)
        gorgeto.grid(row=0, column=1, rowspan=4, sticky="ns")
        self.lista_kony.configure(yscrollcommand=gorgeto.set)

        ttk.Button(kony, text="Tallózás…", command=self.konyvtar_tallozas).grid(
            row=0, column=2, sticky="ew", padx=(8, 0))
        ttk.Button(kony, text="Beírom…", command=self.konyvtar_beiras).grid(
            row=1, column=2, sticky="ew", padx=(8, 0), pady=2)
        ttk.Button(kony, text="Kivesz", command=self.konyvtar_kivesz).grid(
            row=2, column=2, sticky="ew", padx=(8, 0))

        ttk.Label(kony, foreground="#806000",
                  text="Az egymásba ágyazott könyvtárakat is sorold fel (pl. a "
                       "downloads mellett a downloads\\rss mappát): a felsoroltak "
                       "védik egymást.").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def _epit_beallitasok(self, fo: ttk.Frame) -> None:
        """Üzemmód, kivételek, kuka, napló, útvonalak."""
        beall = ttk.LabelFrame(fo, text="Beállítások", padding=8)
        beall.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        beall.columnconfigure(5, weight=1)

        self.v_mod = tk.StringVar(value="felso")
        ttk.Radiobutton(beall, text="Csak a legfelső szint, nevek alapján "
                                    "(ajánlott)", value="felso",
                        variable=self.v_mod, command=self._mod_valtas).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(beall, text="Teljes könyvtárfa, útvonalak alapján",
                        value="fa", variable=self.v_mod,
                        command=self._mod_valtas).grid(
            row=1, column=0, columnspan=3, sticky="w")

        self.v_pontos = tk.BooleanVar(value=False)
        self.cb_pontos = ttk.Checkbutton(
            beall, text="fájlonként (a torrent mappájában lévő idegen fájl is "
                        "felesleges)", variable=self.v_pontos)
        self.cb_pontos.grid(row=2, column=0, columnspan=3, sticky="w", padx=(20, 0))

        ttk.Label(beall, text="Kivételek (vesszővel):").grid(
            row=3, column=0, sticky="w", pady=(6, 0))
        self.v_kivetel = tk.StringVar()
        ttk.Entry(beall, textvariable=self.v_kivetel, width=32).grid(
            row=3, column=1, columnspan=2, sticky="w", padx=4, pady=(6, 0))

        ttk.Label(beall, text="Csak ennél régebbi (nap):").grid(
            row=4, column=0, sticky="w", pady=(4, 0))
        self.v_min_kor = tk.StringVar(value="0")
        ttk.Spinbox(beall, from_=0, to=3650, increment=1, width=6,
                    textvariable=self.v_min_kor).grid(
            row=4, column=1, sticky="w", padx=4, pady=(4, 0))

        self.v_kuka_be = tk.BooleanVar(value=False)
        ttk.Checkbutton(beall, text="Törlés helyett kukába:",
                        variable=self.v_kuka_be, command=self._kuka_valtas).grid(
            row=5, column=0, sticky="w", pady=(4, 0))
        self.v_kuka = tk.StringVar()
        self.e_kuka = ttk.Entry(beall, textvariable=self.v_kuka, width=40)
        self.e_kuka.grid(row=5, column=1, columnspan=2, sticky="ew", padx=4,
                         pady=(4, 0))
        self.b_kuka = ttk.Button(beall, text="…", width=3,
                                 command=self.kuka_tallozas)
        self.b_kuka.grid(row=5, column=3, sticky="w", pady=(4, 0))

        self.v_naplo_be = tk.BooleanVar(value=True)
        ttk.Checkbutton(beall, text="Törlési napló:",
                        variable=self.v_naplo_be).grid(
            row=6, column=0, sticky="w", pady=(4, 0))
        self.v_naplo = tk.StringVar(value=str(qbt_naplo.alap_naplo_fajl()))
        ttk.Entry(beall, textvariable=self.v_naplo, width=40,
                  state="readonly").grid(
            row=6, column=1, columnspan=2, sticky="ew", padx=4, pady=(4, 0))
        ttk.Button(beall, text="Megnyit", width=8,
                   command=self.naplo_megnyitas).grid(
            row=6, column=3, sticky="w", pady=(4, 0))

        # útvonal-megfeleltetés (csak a "fa" módhoz)
        self.ut_keret = ttk.LabelFrame(
            beall, text="Útvonal-megfeleltetés (qBittorrent útvonala = helyi "
                        "útvonal)", padding=6)
        self.ut_keret.grid(row=0, column=5, rowspan=7, sticky="nsew", padx=(12, 0))
        self.ut_keret.columnconfigure(0, weight=1)
        self.lista_ut = tk.Listbox(self.ut_keret, height=5, exportselection=False)
        self.lista_ut.grid(row=0, column=0, rowspan=2, sticky="nsew")
        ttk.Button(self.ut_keret, text="Hozzáad…", command=self.utvonal_hozzaad).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        ttk.Button(self.ut_keret, text="Kivesz", command=self.utvonal_kivesz).grid(
            row=1, column=1, sticky="new", padx=(6, 0), pady=2)

    def _epit_gombok(self, fo: ttk.Frame) -> None:
        """A műveleti gombsor."""
        gombok = ttk.Frame(fo)
        gombok.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.b_proba = ttk.Button(gombok, text="Mit törölne? (próba)",
                                  command=self.vizsgalat)
        self.b_proba.pack(side="left")
        self.b_torles = ttk.Button(gombok, text="Kipipáltak törlése",
                                   command=self.torles, state="disabled")
        self.b_torles.pack(side="left", padx=6)
        ttk.Button(gombok, text="Mindet ki/be", command=self.mindet_valt).pack(
            side="left")
        self.b_megall = ttk.Button(gombok, text="Megszakítás",
                                   command=self.megszakitas, state="disabled")
        self.b_megall.pack(side="left", padx=6)
        ttk.Button(gombok, text="Beállítások mentése",
                   command=self.beallitasok_mentese).pack(side="right")

    def _epit_lista(self, fo: ttk.Frame) -> None:
        """A találati lista (kipipálható sorok)."""
        lista = ttk.Frame(fo)
        lista.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        lista.columnconfigure(0, weight=1)
        lista.rowconfigure(0, weight=1)

        self.fa = ttk.Treeview(lista, columns=("pipa", "tipus", "meret", "ut"),
                               show="headings", selectmode="none")
        self.fa.heading("pipa", text="✓")
        self.fa.heading("tipus", text="Típus")
        self.fa.heading("meret", text="Méret")
        self.fa.heading("ut", text="Útvonal")
        self.fa.column("pipa", width=self.kp(34), anchor="center", stretch=False)
        self.fa.column("tipus", width=self.kp(76), anchor="center",
                       stretch=False)
        self.fa.column("meret", width=self.kp(90), anchor="e", stretch=False)
        self.fa.column("ut", width=self.kp(560), anchor="w")
        self.fa.grid(row=0, column=0, sticky="nsew")
        fg = ttk.Scrollbar(lista, orient="vertical", command=self.fa.yview)
        fg.grid(row=0, column=1, sticky="ns")
        self.fa.configure(yscrollcommand=fg.set)
        self.fa.bind("<Button-1>", self.sor_kattintas)

    def _epit_allapotsor(self, fo: ttk.Frame) -> None:
        """Az alsó állapotsor és a haladásjelző."""
        also = ttk.Frame(fo)
        also.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        also.columnconfigure(0, weight=1)
        self.v_allapot = tk.StringVar(value="Készen állok.")
        ttk.Label(also, textvariable=self.v_allapot).grid(row=0, column=0, sticky="w")
        self.halado = ttk.Progressbar(also, mode="indeterminate",
                                      length=self.kp(160))
        self.halado.grid(row=0, column=1, sticky="e")

    def _mod_valtas(self) -> None:
        fa_mod = self.v_mod.get() == "fa"
        self.cb_pontos.configure(state="normal" if fa_mod else "disabled")
        # Csak a gombokat tiltjuk: a letiltott Listboxba a Tk nem enged beleirni
        # (a mentett megfeleltetesek betoltese csendben elveszne).
        for gyerek in self.ut_keret.winfo_children():
            if isinstance(gyerek, ttk.Button):
                gyerek.configure(state="normal" if fa_mod else "disabled")

    def _tls_valtas(self) -> None:
        """A tanúsítvány-ellenőrzés kikapcsolása igazi kockázat: aki a hálózat
        közepén ül, beleláthat a forgalomba (és a jelszóba). Ezért ki is
        írjuk, ha be van kapcsolva."""
        self.v_tls_gond.set(
            "A tanúsítványt nem ellenőrzöm – csak megbízható (otthoni) "
            "hálózaton használd." if self.v_nem_biztonsagos.get() else "")

    def _kuka_valtas(self) -> None:
        allapot = "normal" if self.v_kuka_be.get() else "disabled"
        self.e_kuka.configure(state=allapot)
        self.b_kuka.configure(state=allapot)

    def allapot(self, szoveg: str) -> None:
        self.v_allapot.set(szoveg)

    # ------------------------------------------------- könyvtárak, útvonalak

    def _konyvtar_felvesz(self, ut: str | os.PathLike[str] | None) -> None:
        if not ut:
            return
        utvonal = engine.normalize_target(ut)
        if engine.is_root_like(utvonal):
            messagebox.showerror(CIM, "A gyökérkönyvtárat biztonsági okból nem "
                                      f"takarítjuk:\n{utvonal}")
            return
        if not utvonal.is_dir():
            messagebox.showerror(CIM, "Nincs ilyen könyvtár (vagy nem érhető "
                                      f"el):\n{utvonal}")
            return
        meglevo = {engine.path_key(x) for x in self.lista_kony.get(0, "end")}
        if engine.path_key(utvonal) in meglevo:
            return
        self.lista_kony.insert("end", str(utvonal))

    def konyvtar_tallozas(self) -> None:
        self._konyvtar_felvesz(filedialog.askdirectory(title="Vizsgálandó könyvtár"))

    def konyvtar_beiras(self) -> None:
        self._konyvtar_felvesz(simpledialog.askstring(
            CIM, "Könyvtár útvonala (hálózati megosztás is lehet):",
            initialvalue="\\\\192.168.1.38\\downloads", parent=self.root))

    def konyvtar_kivesz(self) -> None:
        for i in kijelolt_sorok(self.lista_kony):
            self.lista_kony.delete(i)

    def kuka_tallozas(self) -> None:
        ut = filedialog.askdirectory(title="Kuka könyvtár")
        if ut:
            self.v_kuka.set(str(engine.normalize_target(ut)))

    def naplo_megnyitas(self) -> None:
        """A naplót tartalmazó mappa megnyitása a rendszer fájlkezelőjében."""
        mappa = Path(self.v_naplo.get()).parent
        try:
            mappa.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(mappa)  # csak Windowson létezik
            else:
                kulon_inditas(["open" if sys.platform == "darwin"
                               else "xdg-open", str(mappa)])
        except (OSError, AttributeError) as exc:
            messagebox.showerror(CIM, f"Nem tudom megnyitni:\n{mappa}\n\n{exc}")

    def utvonal_hozzaad(self) -> None:
        tavoli = simpledialog.askstring(
            CIM, "A qBittorrent szerinti útvonal (pl. /downloads):",
            parent=self.root)
        if not tavoli:
            return
        helyi = simpledialog.askstring(
            CIM, "Ugyanez ezen a gépen (pl. \\\\192.168.1.38\\downloads):",
            parent=self.root)
        if not helyi:
            return
        try:
            engine.parse_map(f"{tavoli}={helyi}")
        except ValueError as exc:
            messagebox.showerror(CIM, str(exc))
            return
        self.lista_ut.insert("end", f"{tavoli.strip()}={helyi.strip()}")

    def utvonal_kivesz(self) -> None:
        for i in kijelolt_sorok(self.lista_ut):
            self.lista_ut.delete(i)

    # -------------------------------------------------------- beállítás-fájl

    def beallitasok_mentese(self, csendben: bool = False) -> None:
        adat = {
            "url": self.v_url.get(),
            "user": self.v_user.get(),
            "jelszo_mentese": self.v_pw_mentes.get(),
            "jelszo": self.v_pw.get() if self.v_pw_mentes.get() else "",
            "konyvtarak": list(self.lista_kony.get(0, "end")),
            "mod": self.v_mod.get(),
            "pontos": self.v_pontos.get(),
            "kivetelek": self.v_kivetel.get(),
            "min_kor": self.v_min_kor.get(),
            "kuka_be": self.v_kuka_be.get(),
            "kuka": self.v_kuka.get(),
            "naplo_be": self.v_naplo_be.get(),
            "utvonalak": list(self.lista_ut.get(0, "end")),
            "idokorlat": self.v_idokorlat.get(),
            "nem_biztonsagos_tls": self.v_nem_biztonsagos.get(),
        }
        fajl = beallitas_fajl()
        # Előbb egy ideiglenes fájlba írunk, és csak utána cseréljük le a
        # régit: egy félbeszakadt mentés így nem teszi tönkre a meglévőt.
        ideiglenes = fajl.with_name(fajl.name + ".uj")
        try:
            fajl.parent.mkdir(parents=True, exist_ok=True)
            ideiglenes.write_text(
                json.dumps(adat, ensure_ascii=False, indent=2), encoding="utf-8")
            # A fájlban jelszó is lehet: csak a tulajdonos olvashassa.
            # (Windowson / hálózati meghajtón nincs mit beállítani.)
            with contextlib.suppress(OSError):
                os.chmod(ideiglenes, 0o600)
            # Windowson a víruskereső / keresőindexelő pillanatnyi zárolása
            # miatt a csere elszállhat: ilyenkor újrapróbáljuk.
            engine.csere_ujraprobalva(ideiglenes, fajl)
        except OSError as exc:
            ideiglenes.unlink(missing_ok=True)
            if not csendben:
                messagebox.showerror(CIM, f"Nem sikerült menteni:\n{exc}")
            return
        if not csendben:
            self.allapot(f"Beállítások elmentve: {fajl}")

    def beallitasok_betoltese(self) -> None:
        fajl = beallitas_fajl()
        try:
            adat = json.loads(fajl.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(adat, dict):
            return
        self.v_url.set(adat.get("url") or self.v_url.get())
        self.v_user.set(str(adat.get("user", "")))
        self.v_pw_mentes.set(bool(adat.get("jelszo_mentese")))
        self.v_pw.set(str(adat.get("jelszo", "")))
        self.lista_kony.delete(0, "end")
        for ut in _szoveglista(adat.get("konyvtarak")):
            self.lista_kony.insert("end", ut)
        self.v_mod.set("fa" if adat.get("mod") == "fa" else "felso")
        self.v_pontos.set(bool(adat.get("pontos")))
        self.v_kivetel.set(str(adat.get("kivetelek", "")))
        self.v_min_kor.set(str(adat.get("min_kor", "0")))
        self.v_kuka_be.set(bool(adat.get("kuka_be")))
        self.v_kuka.set(str(adat.get("kuka", "")))
        self.v_naplo_be.set(bool(adat.get("naplo_be", True)))
        self.lista_ut.delete(0, "end")
        for sor in _szoveglista(adat.get("utvonalak")):
            self.lista_ut.insert("end", sor)
        self.v_idokorlat.set(str(adat.get("idokorlat")
                                 or self.v_idokorlat.get()))
        self.v_nem_biztonsagos.set(bool(adat.get("nem_biztonsagos_tls")))
        self._mod_valtas()
        self._kuka_valtas()
        self._tls_valtas()

    def kilepes(self) -> None:
        # Munka kozben a kilepes felbehagyna a torlest (a hattérszal a
        # folyamatban levo elemmel egyutt all le), ezert rakerdezunk.
        if self.dolgozik and not messagebox.askyesno(
                CIM, "Most is dolgozom. Ha kilépsz, a művelet félbemarad.\n\n"
                     "Biztosan bezárod?", icon="warning", default="no"):
            return
        self.megallj.set()  # a háttérszál a következő elemnél leáll
        self.beallitasok_mentese(csendben=True)
        # Az időzítőket le kell mondani: a destroy() után elsülve már nem
        # létező ablakhoz nyúlnának (TclError).
        for azonosito in (self._figyelo, self._betolto):
            if azonosito is not None:
                with contextlib.suppress(tk.TclError):
                    self.root.after_cancel(azonosito)
        self._figyelo = self._betolto = None
        qbt_naplo.jegyzet("a felulet bezarult")
        self.root.destroy()

    # ------------------------------------------------------------ vizsgálat

    def _konyvtarak_ellenorzese(self) -> tuple[bool, list[Path]]:
        """A vizsgálandó könyvtárak listája, ellenőrizve.

        Ugyanaz a könyvtár kétszer felsorolva megvédené önmagát (a felsoroltak
        védik egymást), és a vizsgálat üres eredményt adna. A listára ilyen
        nem kerülhet fel, egy kézzel átírt beállítás-fájlból viszont igen –
        ezért itt is kiszűrjük, ugyanúgy, ahogy a parancssoros változat."""
        konyvtarak: list[Path] = []
        latott: set[str] = set()
        for szoveg in self.lista_kony.get(0, "end"):
            ut = engine.normalize_target(szoveg)
            if not ut.is_dir():
                messagebox.showerror(CIM, f"Nem érhető el a könyvtár:\n{ut}")
                return False, []
            kulcs = engine.path_key(ut)
            if kulcs in latott:
                continue
            latott.add(kulcs)
            konyvtarak.append(ut)
        if not konyvtarak:
            messagebox.showerror(CIM, "Adj meg legalább egy vizsgálandó "
                                      "könyvtárat.")
            return False, []
        return True, konyvtarak

    def _min_kor_ellenorzese(self) -> tuple[bool, float]:
        """A „csak ennél régebbi” mező értéke napokban."""
        try:
            min_kor = float(self.v_min_kor.get() or 0)
        except ValueError:
            messagebox.showerror(CIM, "A „csak ennél régebbi” mező csak szám "
                                      "lehet.")
            return False, 0.0
        if min_kor < 0:
            messagebox.showerror(CIM, "A „csak ennél régebbi” mező nem lehet "
                                      "negatív.")
            return False, 0.0
        return True, min_kor

    def _halozat_ellenorzese(self) -> tuple[bool, engine.Halozat]:
        """A hálózati beállítások: időkorlát és a tanúsítvány-ellenőrzés."""
        try:
            idokorlat = float(self.v_idokorlat.get().replace(",", "."))
        except ValueError:
            messagebox.showerror(CIM, "Az időkorlát csak szám lehet.")
            return False, ALAP_HALOZAT
        if idokorlat <= 0:
            messagebox.showerror(CIM, "Az időkorlát nullánál nagyobb legyen.")
            return False, ALAP_HALOZAT
        return True, engine.Halozat(timeout=idokorlat,
                                    insecure=self.v_nem_biztonsagos.get())

    def _utvonalak_ellenorzese(self) -> tuple[bool, tuple[engine.PathMap, ...]]:
        """Az útvonal-megfeleltetések (TÁVOLI=HELYI) értelmezése."""
        try:
            return True, tuple(engine.parse_map(sor)
                               for sor in self.lista_ut.get(0, "end"))
        except ValueError as exc:
            messagebox.showerror(CIM, str(exc))
            return False, ()

    def _ellenorzott_mezok(self) -> _Mezok | None:
        """A felület mezőinek ellenőrzése. Hiba esetén None (és szól).

        Az egyes mezők ellenőrzése külön metódusban van: mindegyik ugyanazt a
        (rendben van-e, érték) párt adja vissza, így itt egyetlen minta
        ismétlődik, nem ötféle hibakezelés."""
        rendben, konyvtarak = self._konyvtarak_ellenorzese()
        if not rendben:
            return None
        rendben, min_kor = self._min_kor_ellenorzese()
        if not rendben:
            return None
        rendben, utvonalak = self._utvonalak_ellenorzese()
        if not rendben:
            return None
        rendben, halozat = self._halozat_ellenorzese()
        if not rendben:
            return None
        rendben, kuka = self._kuka_ellenorzese(konyvtarak)
        if not rendben:
            return None
        return _Mezok(konyvtarak, min_kor, utvonalak, halozat, kuka)

    def _beallitasok_osszeszedese(self) -> Feladat | None:
        """A felületről összeszedett, már ellenőrzött feladat (vagy None)."""
        url = self.v_url.get().strip()
        if not url:
            messagebox.showerror(CIM, "Add meg a qBittorrent WebUI címét.")
            return None
        mezok = self._ellenorzott_mezok()
        if mezok is None:
            return None
        kivetelek = tuple(x.strip() for x in self.v_kivetel.get().split(",")
                          if x.strip())
        beallitas = engine.Beallitas(
            mode=engine.Mod(self.v_mod.get()),
            maps=mezok.utvonalak,
            excludes=kivetelek + engine.DEFAULT_EXCLUDES,
            min_age_days=mezok.min_kor,
            extra_protected=(mezok.kuka,) if mezok.kuka else (),
        )
        return Feladat(
            url=url,
            user=self.v_user.get().strip(),
            jelszo=self.v_pw.get(),
            konyvtarak=tuple(mezok.konyvtarak),
            beallitas=beallitas,
            halozat=mezok.halozat,
            pontos=self.v_pontos.get(),
            kuka=mezok.kuka,
            naplo=Path(self.v_naplo.get()) if self.v_naplo_be.get() else None,
        )

    def _kuka_ellenorzese(
        self, konyvtarak: Sequence[Path],
    ) -> tuple[bool, Path | None]:
        """A kuka könyvtár előkészítése.

        Vissza: (rendben van-e, az útvonal). A kettő azért kell külön, mert a
        „nincs kuka” és a „hibás kuka” két különböző dolog: az elsővel megy
        tovább a munka, a másodiknál megállunk (a hibaüzenetet már kiírtuk)."""
        if not self.v_kuka_be.get():
            return True, None
        if not self.v_kuka.get().strip():
            messagebox.showerror(CIM, "Add meg a kuka könyvtárát.")
            return False, None
        kuka = engine.normalize_target(self.v_kuka.get().strip())
        try:
            kuka.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(CIM, f"Nem tudom létrehozni a kukát:\n{exc}")
            return False, None
        kuka_kulcs = engine.path_key(kuka)
        if any(kuka_kulcs == engine.path_key(k) for k in konyvtarak):
            messagebox.showerror(CIM, "A kuka nem lehet maga a vizsgált "
                                      "könyvtár.")
            return False, None
        return True, kuka

    def _munka_indul(self, szoveg: str) -> None:
        self.dolgozik = True
        self.megallj.clear()
        self.b_proba.configure(state="disabled")
        self.b_torles.configure(state="disabled")
        self.b_megall.configure(state="normal")
        self.halado.start(12)
        self.allapot(szoveg)

    def _munka_vege(self) -> None:
        self.dolgozik = False
        self.halado.stop()
        self.b_proba.configure(state="normal")
        self.b_megall.configure(state="disabled")
        self.b_torles.configure(
            state="normal" if self.pipaltak else "disabled")

    def megszakitas(self) -> None:
        """A folyamatban lévő munka leállítása. A háttérszál két elem között
        áll meg, tehát félig törölt elem nem maradhat utána."""
        if not self.dolgozik:
            return
        self.megallj.set()
        self.allapot("Megszakítás – az éppen folyó lépés után leállok…")

    def _jelez(self, szoveg: str, azonnal: bool = False) -> None:
        """Állapotüzenet a háttérszálból. Másodpercenként legfeljebb tízszer
        engedjük tovább: e nélkül egy tízezer elemű törlés több tízezer
        üzenettel árasztaná el az ablakot, és pont attól akadna meg."""
        most = time.monotonic()
        if azonnal or most - self._utolso_jelzes >= JELZES_SZUNET:
            self._utolso_jelzes = most
            self.uzenetek.put(("allapot", szoveg))

    def _hatterben(self, munka: Callable[[], tuple[Any, ...]]) -> None:
        """Elindít egy háttérszálat. Bármi is történik odabent, az eredmény (vagy
        a hiba) beérkezik a sorba – enélkül egy váratlan kivétel örökre
        „dolgozik” állapotban hagyná az ablakot."""
        def torzs() -> None:
            try:
                valasz = munka()
            except engine.Megszakitva:
                valasz = ("megszakadt",)
            except engine.QbtError as exc:
                valasz = ("hiba", str(exc))
            except OSError as exc:
                valasz = ("hiba", f"Fájlrendszer hiba: {exc}")
            except Exception as exc:  # noqa: BLE001 - az ablak nem fagyhat le
                valasz = ("hiba", f"Váratlan hiba: {exc!r}")
            self.uzenetek.put(valasz)

        threading.Thread(target=torzs, daemon=True).start()

    def kapcsolat_proba(self) -> None:
        if self.dolgozik:
            return
        url = self.v_url.get().strip()
        if not url:
            messagebox.showerror(CIM, "Add meg a qBittorrent WebUI címét.")
            return
        rendben, halozat = self._halozat_ellenorzese()
        if not rendben:
            return
        user = self.v_user.get().strip()
        jelszo = self.v_pw.get()
        self._munka_indul("Kapcsolódás…")
        self._hatterben(lambda: self._kapcsolat_szal(url, user, jelszo, halozat))

    def _kapcsolat_szal(self, url: str, user: str, jelszo: str,
                        halozat: engine.Halozat) -> tuple[Any, ...]:
        kliens = engine.QbtClient(url, user, jelszo, halozat)
        kliens.megszakitva = self.megallj.is_set
        kliens.login()
        return ("kapcsolat", kliens.version(), len(kliens.torrents()))

    def vizsgalat(self) -> None:
        if self.dolgozik:
            return
        feladat = self._beallitasok_osszeszedese()
        if not feladat:
            return
        self.fa.delete(*self.fa.get_children())
        self.elemek = []
        self.pipaltak = set()
        self.sor_index = {}
        self.vizsgalt_konyvtarak = list(feladat.konyvtarak)
        self._munka_indul("Torrentek lekérése, majd a könyvtárak átnézése…")
        self._hatterben(lambda: self._vizsgalat_szal(feladat))

    def _vizsgalat_szal(self, feladat: Feladat) -> tuple[Any, ...]:
        """Külön szálon: WebUI lekérdezés + a könyvtárak átnézése. Tkinterhez
        nem nyúlhat, csak üzen a sorba, illetve az eredményt adja vissza."""
        kliens = engine.QbtClient(feladat.url, feladat.user, feladat.jelszo,
                                  feladat.halozat)
        # A megszakítás a hálózati várakozás közben is hasson.
        kliens.megszakitva = self.megallj.is_set
        kliens.login()
        torrentek = kliens.torrents()
        fajlok: dict[str, list[str]] = {}
        pontos = feladat.pontos and feladat.beallitas.mode == engine.Mod.FA
        kellenek = engine.kell_fajllista(
            torrentek, feladat.konyvtarak, feladat.beallitas, pontos)
        if kellenek:
            fajlok = kliens.files_many(
                kellenek,
                on_progress=lambda kesz, osszes: self._jelez(
                    f"Torrentek fájllistája: {kesz}/{osszes}…"),
                megszakitva=self.megallj.is_set)
        gondok: list[str] = []
        self._jelez("A könyvtárak átnézése…", azonnal=True)
        elemek = engine.plan_all(
            torrentek, fajlok, feladat.konyvtarak, feladat.beallitas,
            engine.Figyelo(
                on_note=lambda cel, db: self._jelez(f"{cel}: {db} torrent-elem…"),
                on_warn=gondok.append,
                on_progress=self._jelez,
                megszakitva=self.megallj.is_set))
        return ("vizsgalat", len(torrentek), elemek, gondok)

    def _elemek_kiirasa(self, elemek: Sequence[engine.Candidate],
                        pipalva: bool = True,
                        keszen: Callable[[], None] | None = None) -> None:
        """A találati lista feltöltése, adagokban.

        Sok tízezer sort egyszerre kitéve az ablak a betöltés végéig nem
        válaszolna, ezért adagonként rakjuk ki őket, két adag között
        visszaadva a vezérlést a Tk-nak. A `keszen` akkor fut le, amikor az
        utolsó sor is a helyén van – innentől biztonságos a listára
        támaszkodni."""
        if self._betolto is not None:  # egy korábbi betöltés még futhat
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(self._betolto)
            self._betolto = None
        self.elemek = list(elemek)
        self.pipaltak = set(range(len(elemek))) if pipalva else set()
        self.sor_index = {}
        self.fa.delete(*self.fa.get_children())
        self._kiir_adag(0, pipalva, keszen)

    def _kiir_adag(self, honnan: int, pipalva: bool,
                   keszen: Callable[[], None] | None) -> None:
        jel = "☑" if pipalva else "☐"
        for i in range(honnan, min(honnan + BETOLTES_ADAG, len(self.elemek))):
            elem = self.elemek[i]
            sor = self.fa.insert("", "end", values=(
                jel,
                "könyvtár" if elem.is_dir else "fájl",
                engine.human(elem.size), str(elem.path)))
            self.sor_index[sor] = i
        kovetkezo = honnan + BETOLTES_ADAG
        if kovetkezo < len(self.elemek):
            self.allapot(f"Lista feltöltése: {kovetkezo}/{len(self.elemek)}…")
            self._betolto = self.root.after(
                1, self._kiir_adag, kovetkezo, pipalva, keszen)
            return
        self._betolto = None
        if keszen:
            keszen()

    def sor_kattintas(self, esemeny: tk.Event[Any]) -> None:
        """Az első oszlopra kattintva ki/be pipál egy sort."""
        if self.dolgozik or self.fa.identify_region(esemeny.x, esemeny.y) != "cell":
            return
        if self.fa.identify_column(esemeny.x) != "#1":
            return
        self.pipa_valt(self.fa.identify_row(esemeny.y))

    def pipa_valt(self, sor: str) -> None:
        """Egy sor ki/be pipálása."""
        index = self.sor_index.get(sor)
        if index is None:
            return
        if index in self.pipaltak:
            self.pipaltak.discard(index)
            self.fa.set(sor, "pipa", "☐")
        else:
            self.pipaltak.add(index)
            self.fa.set(sor, "pipa", "☑")
        self._osszegzes()

    def mindet_valt(self) -> None:
        if self.dolgozik or not self.elemek:
            return
        mind = len(self.pipaltak) < len(self.elemek)
        self.pipaltak = set(range(len(self.elemek))) if mind else set()
        for sor, index in self.sor_index.items():
            self.fa.set(sor, "pipa", "☑" if index in self.pipaltak else "☐")
        self._osszegzes()

    def _osszegzes(self) -> None:
        meret = sum(self.elemek[i].size for i in self.pipaltak)
        self.b_torles.configure(state="normal" if self.pipaltak else "disabled")
        self.allapot(f"{len(self.pipaltak)} elem kipipálva, összesen "
                     f"{engine.human(meret)}.")

    # --------------------------------------------------------------- törlés

    def torles(self) -> None:
        if self.dolgozik or not self.pipaltak:
            return
        feladat = self._beallitasok_osszeszedese()
        if not feladat:
            return
        indexek = sorted(self.pipaltak)
        valasztott = [self.elemek[i] for i in indexek]
        meret = sum(c.size for c in valasztott)
        if feladat.kuka:
            kerdes = (f"{len(valasztott)} elemet mozgatok a kukába "
                      f"({engine.human(meret)}):\n{feladat.kuka}\n\nMehet?")
        else:
            kerdes = (f"{len(valasztott)} elem VÉGLEGES törlése, összesen "
                      f"{engine.human(meret)}.\n\n"
                      "Ez nem vonható vissza. Biztos?")
        if not messagebox.askyesno(CIM, kerdes, icon="warning", default="no"):
            return
        # A vizsgálatkor érvényes könyvtárlistához mérünk, nem a mostanihoz.
        konyvtarak = self.vizsgalt_konyvtarak or list(feladat.konyvtarak)
        qbt_naplo.jegyzet("torles indul: %d elem, %s%s", len(valasztott),
                          engine.human(meret),
                          f", kukaba: {feladat.kuka}" if feladat.kuka else "")
        self._munka_indul("Törlés…")
        self._hatterben(lambda: self._torles_szal(
            indexek, valasztott, konyvtarak, feladat.kuka, feladat.naplo))

    def _torles_szal(
        self,
        indexek: Sequence[int],
        elemek: Sequence[engine.Candidate],
        konyvtarak: Sequence[Path],
        kuka: Path | None,
        naplo_ut: Path | None = None,
    ) -> tuple[Any, ...]:
        kesz: set[int] = set()
        hibak: list[tuple[engine.Candidate, str]] = []
        felszabadult = 0
        megszakadt = False
        osszes = len(elemek)
        naplo = qbt_naplo.nyitas(naplo_ut) if naplo_ut else None
        # A könyvtárlistát egyszer alakítjuk át, nem elemenként.
        gazdak = tuple(str(k) for k in konyvtarak)
        try:
            for sorszam, (index, elem) in enumerate(
                    zip(indexek, elemek, strict=True), 1):
                if self.megallj.is_set():
                    # Két elem között állunk meg: a most törölt elem már kész,
                    # a következőhöz nem nyúlunk. Ami elkészült, az érvényes.
                    megszakadt = True
                    break
                gazda = engine.owner_target(elem.path, gazdak)
                siker, uzenet = engine.remove_entry(elem, gazda, kuka)
                if siker:
                    kesz.add(index)
                    felszabadult += elem.size
                else:
                    hibak.append((elem, uzenet))
                if naplo:
                    naplo.rogzit(elem, siker, uzenet, kukaba=bool(kuka))
                self._jelez(f"Törlés: {sorszam}/{osszes} – {elem.path.name}")
        finally:
            if naplo:
                naplo.close()
        qbt_naplo.jegyzet("torles kesz: %d elem, %s felszabadulva, %d "
                          "sikertelen%s", len(kesz), engine.human(felszabadult),
                          len(hibak), ", megszakitva" if megszakadt else "")
        return ("torles", kesz, hibak, felszabadult, megszakadt)

    # ----------------------------------------------------- üzenetek kezelése

    def _sor_figyelese(self) -> None:
        try:
            while True:
                self._uzenet(self.uzenetek.get_nowait())
        except queue.Empty:
            pass
        self._figyelo = self.root.after(FIGYELES_MP, self._sor_figyelese)

    def _uzenet(self, uzenet: tuple[Any, ...]) -> None:
        """Egy háttérszáltól érkezett üzenet feldolgozása. A válasz első eleme
        mondja meg, miről van szó; a többi az adott üzenet tartalma."""
        fajta, *tartalom = uzenet
        # A kezelok mas-mas parametereket varnak (az uzenet fajtaja mondja
        # meg, mit): a kozos tipusuk igy csak "valamit csinal, nem ad vissza
        # semmit". A tartalom a kuldes helyen es itt is egyutt valtozik.
        kezelok: dict[str, Callable[..., None]] = {
            "allapot": self._uzenet_allapot,
            "kapcsolat": self._uzenet_kapcsolat,
            "vizsgalat": self._uzenet_vizsgalat,
            "torles": self._uzenet_torles,
            "megszakadt": self._uzenet_megszakadt,
            "hiba": self._uzenet_hiba,
        }
        kezelo = kezelok.get(fajta)
        if kezelo:
            kezelo(*tartalom)

    def _uzenet_allapot(self, szoveg: str) -> None:
        if self.dolgozik:  # egy kesve erkezo jelzes ne irja felul a vegso
            self.allapot(szoveg)

    def _uzenet_kapcsolat(self, verzio: str, darab: int) -> None:
        self._munka_vege()
        self.allapot(f"Kapcsolódva: qBittorrent {verzio}, {darab} torrent.")

    def _uzenet_vizsgalat(self, torrentek: int,
                          elemek: Sequence[engine.Candidate],
                          gondok: Sequence[str]) -> None:
        qbt_naplo.jegyzet("atnezve: %d torrent, %d felesleges elem, "
                          "%d olvashatatlan konyvtar", torrentek, len(elemek),
                          len(gondok))

        def keszen() -> None:
            self._munka_vege()
            if not elemek:
                self.allapot(f"{torrentek} torrent – nincs felesleges elem, "
                             "nincs mit tenni.")
            else:
                self._osszegzes()
            self._gondok_jelzese(gondok)

        self._elemek_kiirasa(elemek, keszen=keszen)

    def _gondok_jelzese(self, gondok: Sequence[str]) -> None:
        if not gondok:
            return
        mutat = engine.MUTATOTT_RESZLET
        reszletek = "\n".join(gondok[:mutat])
        tobbi = f"\n… és még {len(gondok) - mutat}." if len(gondok) > mutat else ""
        messagebox.showwarning(
            CIM, f"{len(gondok)} könyvtárat nem tudtam beolvasni, ezekben nem "
                 f"takarítottam:\n\n{reszletek}{tobbi}")

    def _uzenet_torles(self, kesz: set[int],
                       hibak: Sequence[tuple[engine.Candidate, str]],
                       felszabadult: int, megszakadt: bool = False) -> None:
        # A megmaradt sorok kipipálatlanok lesznek: amit a felhasználó most
        # szándékosan kihagyott, azt egy újabb kattintás ne törölje.
        maradek = [c for i, c in enumerate(self.elemek) if i not in kesz]

        def keszen() -> None:
            self._munka_vege()
            baj = f"  {len(hibak)} elemet nem sikerült!" if hibak else ""
            vege = "  Megszakítva." if megszakadt else ""
            self.allapot(f"Kész: {len(kesz)} elem, "
                         f"{engine.human(felszabadult)} felszabadulva."
                         f"{baj}{vege}")
            if hibak:
                reszletek = "\n".join(
                    f"{c.path}\n    {u}"
                    for c, u in hibak[:engine.MUTATOTT_RESZLET])
                messagebox.showwarning(
                    CIM, f"Néhány elemet nem sikerült törölni:\n\n{reszletek}")

        self._elemek_kiirasa(maradek, pipalva=False, keszen=keszen)

    def _uzenet_megszakadt(self) -> None:
        qbt_naplo.jegyzet("a munkat megszakitottak")
        self._munka_vege()
        self.allapot("Megszakítva – semmit nem töröltem.")

    def _uzenet_hiba(self, szoveg: str) -> None:
        qbt_naplo.jegyzet("hiba: %s", szoveg)
        self._munka_vege()
        self.allapot("Hiba – semmit nem töröltem.")
        messagebox.showerror(CIM, szoveg)


def main() -> int:
    if sys.version_info < engine.MIN_PYTHON:
        kell = ".".join(str(x) for x in engine.MIN_PYTHON)
        print(f"Tul regi Python: {sys.version.split()[0]} (legalabb {kell} kell).",
              file=sys.stderr)
        return 2
    # A felületnek nincs konzolja: egy baj után az eseménynapló az egyetlen
    # nyom arról, hogy mi történt.
    qbt_naplo.esemenyek_indul()
    qbt_naplo.jegyzet("indul: felulet %s", engine.__version__)
    dpi_tudatossag()
    root = tk.Tk()
    try:
        TakaritoApp(root)
    except Exception as exc:  # pragma: no cover - indulási hiba
        qbt_naplo.jegyzet("nem sikerult elindulni: %r", exc)
        messagebox.showerror(CIM, f"Nem sikerült elindulni:\n{exc}")
        raise
    try:
        root.mainloop()
    finally:
        qbt_naplo.esemenyek_lezar()
    return 0


if __name__ == "__main__":
    # A program a saját környezetéből (.venv) fut: ha még nem abból indultunk,
    # ez újraindítja ugyanezt a fájlt. Csak közvetlen indításkor: importáláskor
    # (tesztek) nem történik semmi.
    import qbt_kornyezet

    _kod = qbt_kornyezet.belepes(__file__)
    sys.exit(main() if _kod is None else _kod)
