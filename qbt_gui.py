#!/usr/bin/env python3
"""qBittorrent takarító – grafikus felület.

A tényleges munkát a `qbt_cleanup.py` végzi (ugyanaz a kód, amit a parancssoros
használat is hív), ez a fájl csak a kezelőfelület: beállítások, a felesleges
elemek listája kipipálható tételekkel, és a törlés.

Indítás Windows alatt: kattints duplán a `qbittorrent_clean.bat` fájlra.
Máshol:

    python3 qbt_gui.py
"""

import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

# A motor a program mellett van, akkor is, ha máshonnan indítják.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import qbt_cleanup as engine  # noqa: E402

CIM = "qBittorrent takarító"


def beallitas_fajl():
    """A beállítások helye: Windowson az AppData, máshol a home könyvtár."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "qbittorrent_clean" / "beallitasok.json"
    return Path.home() / ".qbittorrent_clean.json"


class TakaritoApp:
    """A teljes kezelőfelület. A hálózati és fájlrendszeri munka külön szálon
    fut, hogy az ablak ne fagyjon le; az eredmény egy sorba (queue) kerül, amit
    az ablak 100 ezredmásodpercenként néz meg."""

    def __init__(self, root):
        self.root = root
        self.uzenetek = queue.Queue()
        self.elemek = []          # engine.Candidate lista
        self.pipaltak = set()     # a bepipált elemek indexei
        self.sor_index = {}       # Treeview sor -> index
        self.dolgozik = False

        root.title(CIM)
        root.minsize(880, 620)
        self._epit()
        self.beallitasok_betoltese()
        root.protocol("WM_DELETE_WINDOW", self.kilepes)
        root.after(100, self._sor_figyelese)

    # ------------------------------------------------------------ felület

    def _epit(self):
        fo = ttk.Frame(self.root, padding=8)
        fo.pack(fill="both", expand=True)
        fo.columnconfigure(0, weight=1)
        fo.rowconfigure(4, weight=1)

        # --- kapcsolat ---
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

        ttk.Button(kap, text="Kapcsolat próba", command=self.kapcsolat_proba).grid(
            row=0, column=4, rowspan=2, sticky="ns", padx=(8, 0))

        # --- vizsgált könyvtárak ---
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

        # --- beállítások ---
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

        # útvonal-megfeleltetés (csak a "fa" módhoz)
        self.ut_keret = ttk.LabelFrame(
            beall, text="Útvonal-megfeleltetés (qBittorrent útvonala = helyi "
                        "útvonal)", padding=6)
        self.ut_keret.grid(row=0, column=5, rowspan=6, sticky="nsew", padx=(12, 0))
        self.ut_keret.columnconfigure(0, weight=1)
        self.lista_ut = tk.Listbox(self.ut_keret, height=5, exportselection=False)
        self.lista_ut.grid(row=0, column=0, rowspan=2, sticky="nsew")
        ttk.Button(self.ut_keret, text="Hozzáad…", command=self.utvonal_hozzaad).grid(
            row=0, column=1, sticky="ew", padx=(6, 0))
        ttk.Button(self.ut_keret, text="Kivesz", command=self.utvonal_kivesz).grid(
            row=1, column=1, sticky="new", padx=(6, 0), pady=2)

        # --- gombok ---
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
        ttk.Button(gombok, text="Beállítások mentése",
                   command=self.beallitasok_mentese).pack(side="right")

        # --- találatok ---
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
        self.fa.column("pipa", width=34, anchor="center", stretch=False)
        self.fa.column("tipus", width=76, anchor="center", stretch=False)
        self.fa.column("meret", width=90, anchor="e", stretch=False)
        self.fa.column("ut", width=560, anchor="w")
        self.fa.grid(row=0, column=0, sticky="nsew")
        fg = ttk.Scrollbar(lista, orient="vertical", command=self.fa.yview)
        fg.grid(row=0, column=1, sticky="ns")
        self.fa.configure(yscrollcommand=fg.set)
        self.fa.bind("<Button-1>", self.sor_kattintas)

        # --- állapotsor ---
        also = ttk.Frame(fo)
        also.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        also.columnconfigure(0, weight=1)
        self.v_allapot = tk.StringVar(value="Készen állok.")
        ttk.Label(also, textvariable=self.v_allapot).grid(row=0, column=0, sticky="w")
        self.halado = ttk.Progressbar(also, mode="indeterminate", length=160)
        self.halado.grid(row=0, column=1, sticky="e")

        self._mod_valtas()
        self._kuka_valtas()

    def _mod_valtas(self):
        fa_mod = self.v_mod.get() == "fa"
        self.cb_pontos.configure(state="normal" if fa_mod else "disabled")
        # Csak a gombokat tiltjuk: a letiltott Listboxba a Tk nem enged beleirni
        # (a mentett megfeleltetesek betoltese csendben elveszne).
        for gyerek in self.ut_keret.winfo_children():
            if isinstance(gyerek, ttk.Button):
                gyerek.configure(state="normal" if fa_mod else "disabled")

    def _kuka_valtas(self):
        allapot = "normal" if self.v_kuka_be.get() else "disabled"
        self.e_kuka.configure(state=allapot)
        self.b_kuka.configure(state=allapot)

    def allapot(self, szoveg):
        self.v_allapot.set(szoveg)

    # ------------------------------------------------- könyvtárak, útvonalak

    def _konyvtar_felvesz(self, ut):
        if not ut:
            return
        ut = engine.normalize_target(ut)
        if engine.is_root_like(ut):
            messagebox.showerror(CIM, "A gyökérkönyvtárat biztonsági okból nem "
                                      "takarítjuk:\n%s" % ut)
            return
        if not ut.is_dir():
            messagebox.showerror(CIM, "Nincs ilyen könyvtár (vagy nem érhető "
                                      "el):\n%s" % ut)
            return
        meglevo = [engine.norm_key(x) for x in self.lista_kony.get(0, "end")]
        if engine.norm_key(str(ut)) in meglevo:
            return
        self.lista_kony.insert("end", str(ut))

    def konyvtar_tallozas(self):
        self._konyvtar_felvesz(filedialog.askdirectory(title="Vizsgálandó könyvtár"))

    def konyvtar_beiras(self):
        self._konyvtar_felvesz(simpledialog.askstring(
            CIM, "Könyvtár útvonala (hálózati megosztás is lehet):",
            initialvalue="\\\\192.168.1.38\\downloads", parent=self.root))

    def konyvtar_kivesz(self):
        for i in reversed(self.lista_kony.curselection()):
            self.lista_kony.delete(i)

    def kuka_tallozas(self):
        ut = filedialog.askdirectory(title="Kuka könyvtár")
        if ut:
            self.v_kuka.set(str(engine.normalize_target(ut)))

    def utvonal_hozzaad(self):
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
            engine.parse_map("%s=%s" % (tavoli, helyi))
        except ValueError as exc:
            messagebox.showerror(CIM, str(exc))
            return
        self.lista_ut.insert("end", "%s=%s" % (tavoli.strip(), helyi.strip()))

    def utvonal_kivesz(self):
        for i in reversed(self.lista_ut.curselection()):
            self.lista_ut.delete(i)

    # -------------------------------------------------------- beállítás-fájl

    def beallitasok_mentese(self, csendben=False):
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
            "utvonalak": list(self.lista_ut.get(0, "end")),
        }
        fajl = beallitas_fajl()
        try:
            fajl.parent.mkdir(parents=True, exist_ok=True)
            with open(str(fajl), "w", encoding="utf-8") as fh:
                json.dump(adat, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            if not csendben:
                messagebox.showerror(CIM, "Nem sikerült menteni:\n%s" % exc)
            return
        if not csendben:
            self.allapot("Beállítások elmentve: %s" % fajl)

    def beallitasok_betoltese(self):
        fajl = beallitas_fajl()
        try:
            with open(str(fajl), encoding="utf-8") as fh:
                adat = json.load(fh)
        except (OSError, ValueError):
            return
        self.v_url.set(adat.get("url") or self.v_url.get())
        self.v_user.set(adat.get("user", ""))
        self.v_pw_mentes.set(bool(adat.get("jelszo_mentese")))
        self.v_pw.set(adat.get("jelszo", ""))
        self.lista_kony.delete(0, "end")
        for ut in adat.get("konyvtarak", []):
            self.lista_kony.insert("end", ut)
        self.v_mod.set(adat.get("mod", "felso"))
        self.v_pontos.set(bool(adat.get("pontos")))
        self.v_kivetel.set(adat.get("kivetelek", ""))
        self.v_min_kor.set(str(adat.get("min_kor", "0")))
        self.v_kuka_be.set(bool(adat.get("kuka_be")))
        self.v_kuka.set(adat.get("kuka", ""))
        self.lista_ut.delete(0, "end")
        for sor in adat.get("utvonalak", []):
            self.lista_ut.insert("end", sor)
        self._mod_valtas()
        self._kuka_valtas()

    def kilepes(self):
        self.beallitasok_mentese(csendben=True)
        self.root.destroy()

    # ------------------------------------------------------------ vizsgálat

    def _beallitasok_osszeszedese(self):
        """A felületről összeszedett beállítások. Hiba esetén None (és szól)."""
        url = self.v_url.get().strip()
        if not url:
            messagebox.showerror(CIM, "Add meg a qBittorrent WebUI címét.")
            return None

        konyvtarak = []
        for szoveg in self.lista_kony.get(0, "end"):
            ut = engine.normalize_target(szoveg)
            if not ut.is_dir():
                messagebox.showerror(CIM, "Nem érhető el a könyvtár:\n%s" % ut)
                return None
            konyvtarak.append(ut)
        if not konyvtarak:
            messagebox.showerror(CIM, "Adj meg legalább egy vizsgálandó "
                                      "könyvtárat.")
            return None

        try:
            min_kor = float(self.v_min_kor.get() or 0)
        except ValueError:
            messagebox.showerror(CIM, "A „csak ennél régebbi” mező csak szám "
                                      "lehet.")
            return None

        try:
            utvonalak = [engine.parse_map(sor)
                         for sor in self.lista_ut.get(0, "end")]
        except ValueError as exc:
            messagebox.showerror(CIM, str(exc))
            return None

        kuka = None
        if self.v_kuka_be.get():
            if not self.v_kuka.get().strip():
                messagebox.showerror(CIM, "Add meg a kuka könyvtárát.")
                return None
            kuka = engine.normalize_target(self.v_kuka.get().strip())
            try:
                kuka.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(CIM, "Nem tudom létrehozni a kukát:\n%s" % exc)
                return None
            if any(kuka == k for k in konyvtarak):
                messagebox.showerror(CIM, "A kuka nem lehet maga a vizsgált "
                                          "könyvtár.")
                return None

        kivetelek = [x.strip() for x in self.v_kivetel.get().split(",") if x.strip()]
        return {
            "url": url,
            "user": self.v_user.get().strip(),
            "jelszo": self.v_pw.get(),
            "konyvtarak": konyvtarak,
            "mod": self.v_mod.get(),
            "pontos": self.v_pontos.get(),
            "utvonalak": utvonalak,
            "kivetelek": kivetelek + engine.DEFAULT_EXCLUDES,
            "min_kor": min_kor,
            "kuka": kuka,
        }

    def _munka_indul(self, szoveg):
        self.dolgozik = True
        self.b_proba.configure(state="disabled")
        self.b_torles.configure(state="disabled")
        self.halado.start(12)
        self.allapot(szoveg)

    def _munka_vege(self):
        self.dolgozik = False
        self.halado.stop()
        self.b_proba.configure(state="normal")
        self.b_torles.configure(
            state="normal" if self.pipaltak else "disabled")

    def kapcsolat_proba(self):
        if self.dolgozik:
            return
        self._munka_indul("Kapcsolódás…")
        szal = threading.Thread(target=self._kapcsolat_szal, args=(
            self.v_url.get().strip(), self.v_user.get().strip(), self.v_pw.get()),
            daemon=True)
        szal.start()

    def _kapcsolat_szal(self, url, user, jelszo):
        try:
            kliens = engine.QbtClient(url, user, jelszo)
            kliens.login()
            valasz = ("kapcsolat", kliens.version(), len(kliens.torrents()))
        except engine.QbtError as exc:
            valasz = ("hiba", str(exc))
        self.uzenetek.put(valasz)

    def vizsgalat(self):
        if self.dolgozik:
            return
        beall = self._beallitasok_osszeszedese()
        if not beall:
            return
        self.fa.delete(*self.fa.get_children())
        self.elemek = []
        self.pipaltak = set()
        self._munka_indul("Torrentek lekérése, majd a könyvtárak átnézése…")
        threading.Thread(target=self._vizsgalat_szal, args=(beall,),
                         daemon=True).start()

    def _vizsgalat_szal(self, beall):
        """Külön szálon: WebUI lekérdezés + a könyvtárak átnézése. Tkinterhez
        nem nyúlhat, csak üzenetet küld."""
        try:
            kliens = engine.QbtClient(beall["url"], beall["user"], beall["jelszo"])
            kliens.login()
            torrentek = kliens.torrents()
            fajlok = {}
            if beall["mod"] == "fa" and beall["pontos"]:
                for torrent in torrentek:
                    azon = torrent.get("hash") or ""
                    if azon:
                        fajlok[azon] = kliens.files(azon)
            elemek = engine.plan_all(
                torrentek, fajlok, beall["konyvtarak"], beall["mod"],
                beall["utvonalak"], beall["kivetelek"], True, beall["min_kor"],
                extra_protected=[beall["kuka"]] if beall["kuka"] else ())
            self.uzenetek.put(("vizsgalat", len(torrentek), elemek))
        except engine.QbtError as exc:
            self.uzenetek.put(("hiba", str(exc)))
        except OSError as exc:  # pragma: no cover - fájlrendszer hiba
            self.uzenetek.put(("hiba", "Fájlrendszer hiba: %s" % exc))

    def _elemek_kiirasa(self, elemek, pipalva=True):
        self.elemek = elemek
        self.pipaltak = set(range(len(elemek))) if pipalva else set()
        self.sor_index = {}
        self.fa.delete(*self.fa.get_children())
        for i, elem in enumerate(elemek):
            sor = self.fa.insert("", "end", values=(
                "☑" if pipalva else "☐",
                "könyvtár" if elem.is_dir else "fájl",
                engine.human(elem.size), str(elem.path)))
            self.sor_index[sor] = i

    def sor_kattintas(self, esemeny):
        """Az első oszlopra kattintva ki/be pipál egy sort."""
        if self.dolgozik or self.fa.identify_region(esemeny.x, esemeny.y) != "cell":
            return
        if self.fa.identify_column(esemeny.x) != "#1":
            return
        self.pipa_valt(self.fa.identify_row(esemeny.y))

    def pipa_valt(self, sor):
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

    def mindet_valt(self):
        if self.dolgozik or not self.elemek:
            return
        mind = len(self.pipaltak) < len(self.elemek)
        self.pipaltak = set(range(len(self.elemek))) if mind else set()
        for sor, index in self.sor_index.items():
            self.fa.set(sor, "pipa", "☑" if index in self.pipaltak else "☐")
        self._osszegzes()

    def _osszegzes(self):
        meret = sum(self.elemek[i].size for i in self.pipaltak)
        self.b_torles.configure(state="normal" if self.pipaltak else "disabled")
        self.allapot("%d elem kipipálva, összesen %s."
                     % (len(self.pipaltak), engine.human(meret)))

    # --------------------------------------------------------------- törlés

    def torles(self):
        if self.dolgozik or not self.pipaltak:
            return
        beall = self._beallitasok_osszeszedese()
        if not beall:
            return
        valasztott = [self.elemek[i] for i in sorted(self.pipaltak)]
        meret = sum(c.size for c in valasztott)
        if beall["kuka"]:
            kerdes = ("%d elemet mozgatok a kukába (%s):\n%s\n\nMehet?"
                      % (len(valasztott), engine.human(meret), beall["kuka"]))
        else:
            kerdes = ("%d elem VÉGLEGES törlése, összesen %s.\n\n"
                      "Ez nem vonható vissza. Biztos?"
                      % (len(valasztott), engine.human(meret)))
        if not messagebox.askyesno(CIM, kerdes, icon="warning", default="no"):
            return
        self._munka_indul("Törlés…")
        threading.Thread(target=self._torles_szal,
                         args=(valasztott, beall["konyvtarak"], beall["kuka"]),
                         daemon=True).start()

    def _torles_szal(self, elemek, konyvtarak, kuka):
        kesz, hibak, felszabadult = [], [], 0
        for elem in elemek:
            gazda = engine.owner_target(elem.path, konyvtarak)
            siker, uzenet = engine.remove_entry(elem, gazda, kuka)
            if siker:
                kesz.append(elem)
                felszabadult += elem.size
            else:
                hibak.append((elem, uzenet))
        self.uzenetek.put(("torles", kesz, hibak, felszabadult))

    # ----------------------------------------------------- üzenetek kezelése

    def _sor_figyelese(self):
        try:
            while True:
                self._uzenet(self.uzenetek.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._sor_figyelese)

    def _uzenet(self, uzenet):
        fajta = uzenet[0]
        if fajta == "kapcsolat":
            _, verzio, darab = uzenet
            self._munka_vege()
            self.allapot("Kapcsolódva: qBittorrent %s, %d torrent."
                         % (verzio, darab))
        elif fajta == "vizsgalat":
            _, torrentek, elemek = uzenet
            self._elemek_kiirasa(elemek)
            self._munka_vege()
            if not elemek:
                self.allapot("%d torrent – nincs felesleges elem, nincs mit "
                             "tenni." % torrentek)
            else:
                self._osszegzes()
        elif fajta == "torles":
            _, kesz, hibak, felszabadult = uzenet
            toroltek = {id(c) for c in kesz}
            maradek = [c for c in self.elemek if id(c) not in toroltek]
            # A megmaradt sorok kipipálatlanok lesznek: amit a felhasználó most
            # szándékosan kihagyott, azt egy újabb kattintás ne törölje.
            self._elemek_kiirasa(maradek, pipalva=False)
            self._munka_vege()
            self.allapot("Kész: %d elem, %s felszabadulva.%s"
                         % (len(kesz), engine.human(felszabadult),
                            "  %d elemet nem sikerült!" % len(hibak) if hibak else ""))
            if hibak:
                reszletek = "\n".join("%s\n    %s" % (c.path, u)
                                      for c, u in hibak[:10])
                messagebox.showwarning(
                    CIM, "Néhány elemet nem sikerült törölni:\n\n%s" % reszletek)
        elif fajta == "hiba":
            self._munka_vege()
            self.allapot("Hiba – semmit nem töröltem.")
            messagebox.showerror(CIM, uzenet[1])


def main():
    root = tk.Tk()
    try:
        TakaritoApp(root)
    except Exception as exc:  # pragma: no cover - indulási hiba
        messagebox.showerror(CIM, "Nem sikerült elindulni:\n%s" % exc)
        raise
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
