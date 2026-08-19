"""Hamis qBittorrent WebUI es proba-konyvtarfa - a tesztek kozos kelleke.

Igy a motor (qbt_test.py) es a felulet (gui_test.py) ugyanazt a kiszolgalot es
ugyanazt a konyvtarfat hasznalja.

A kiszolgalo szandekosan tud rosszul is viselkedni (atmeneti hiba, lejart
munkamenet, lassu valasz): a hibaturest csak igy lehet merni."""

import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

USER, PASSWORD = "admin", "titok123"

# Ket torrent a downloads, egy a downloads/rss konyvtarban.
TORRENTS = [
    {"hash": "aaa", "name": "Film.Egy.2024",
     "save_path": "/downloads", "download_path": "",
     "content_path": "/downloads/Film.Egy.2024"},
    {"hash": "bbb", "name": "Sorozat S01",
     "save_path": "/downloads", "download_path": "",
     "content_path": "/downloads/Sorozat S01"},
    {"hash": "ccc", "name": "hetivideo.mkv",
     "save_path": "/downloads/rss", "download_path": "",
     "content_path": "/downloads/rss/hetivideo.mkv"},
]

FILES = {
    "aaa": [{"name": "Film.Egy.2024/film.mkv"}, {"name": "Film.Egy.2024/film.srt"}],
    "bbb": [{"name": "Sorozat S01/e01.mkv"}, {"name": "Sorozat S01/e02.mkv"}],
    "ccc": [{"name": "hetivideo.mkv"}],
}


class Viselkedes:
    """A hamis kiszolgalo szeszelyei.

    A teszt beallitja, mi tortenjen a kovetkezo hivasoknal (atmeneti hiba,
    lejart munkamenet, lassu valasz), a szamlalokbol pedig utana leolvashato,
    mi tortent valojaban."""

    def __init__(self):
        self.atmeneti_hibak = 0     # ennyi kovetkezo GET-re 503 a valasz
        self.retry_after = None     # a 503 melle kuldott Retry-After fejlec
        self.lejart_munkamenet = 0  # ennyi kovetkezo GET-re 403, es kilep
        self.keses = 0.0            # a fajllista-lekeres ennyit varjon (mp)
        self.fajl_hivasok = 0
        self.belepesek = 0
        self.egyszerre = 0          # eppen hany fajllista-lekeres fut
        self.egyszerre_csucs = 0    # ebbol latszik, hogy tenyleg parhuzamos
        self.zar = threading.Lock()


def start_server(torrents=None, files=None, user=USER, password=PASSWORD,
                 viselkedes=None):
    """Elindit egy hamis WebUI-t a helyi gepen. Visszaadja: (url, kiszolgalo).
    A vegen kiszolgalo.shutdown() illik.

    Szalankent kulon szolgalja ki a kereseket, kulonben a parhuzamos
    lekerdezes merese ertelmetlen lenne: a sorbaallas maga tuntetne el a
    kulonbseget."""
    torrents = TORRENTS if torrents is None else torrents
    files = FILES if files is None else files
    allapot = viselkedes or Viselkedes()

    class Handler(BaseHTTPRequestHandler):
        logged_in = False

        def log_message(self, *a):  # csendben
            pass

        def _send(self, code, body, ctype="text/plain; charset=UTF-8",
                  fejlecek=()):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for nev, ertek in fejlecek:
                self.send_header(nev, ertek)
            self.end_headers()
            self.wfile.write(data)

        def _szandekos_hiba(self):
            """Ha ez a keres szandekosan elszall, kikuldi a valaszt, es igazat
            ad vissza."""
            with allapot.zar:
                if allapot.lejart_munkamenet > 0:
                    allapot.lejart_munkamenet -= 1
                    Handler.logged_in = False  # ujra be kell jelentkezni
                    self._send(403, "Forbidden")
                    return True
                if allapot.atmeneti_hibak > 0:
                    allapot.atmeneti_hibak -= 1
                    fejlecek = ([("Retry-After", str(allapot.retry_after))]
                                if allapot.retry_after is not None else ())
                    self._send(503, "Service Unavailable", fejlecek=fejlecek)
                    return True
            return False

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode())
            if self.path == "/api/v2/auth/login":
                ok = (form.get("username", [""])[0] == user
                      and form.get("password", [""])[0] == password)
                with allapot.zar:
                    allapot.belepesek += 1
                if ok:
                    Handler.logged_in = True
                    self.send_response(200)
                    self.send_header("Set-Cookie", "SID=teszt; path=/")
                    self.send_header("Content-Length", "3")
                    self.end_headers()
                    self.wfile.write(b"Ok.")
                else:
                    self._send(200, "Fails.")
                return
            self._send(404, "nincs ilyen")

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if self._szandekos_hiba():
                return
            if not Handler.logged_in:
                self._send(403, "Forbidden")
                return
            if parsed.path == "/api/v2/app/version":
                self._send(200, "v4.6.5")
            elif parsed.path == "/api/v2/torrents/info":
                self._send(200, json.dumps(torrents), "application/json")
            elif parsed.path == "/api/v2/torrents/files":
                self._fajllista(parsed)
            else:
                self._send(404, "nincs ilyen")

        def _fajllista(self, parsed):
            with allapot.zar:
                allapot.fajl_hivasok += 1
                allapot.egyszerre += 1
                allapot.egyszerre_csucs = max(allapot.egyszerre_csucs,
                                              allapot.egyszerre)
            try:
                if allapot.keses:
                    time.sleep(allapot.keses)
                qs = urllib.parse.parse_qs(parsed.query)
                self._send(200,
                           json.dumps(files.get(qs.get("hash", [""])[0], [])),
                           "application/json")
            finally:
                with allapot.zar:
                    allapot.egyszerre -= 1

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server


def build_tree(base):
    """A megosztas utanzata: qBittorrent szerint /downloads es /downloads/rss.

    Ami a torrentekhez tartozik: Film.Egy.2024, Sorozat S01, rss/hetivideo.mkv.
    Ami felesleges: Regi.Film.2011, arvalt.mkv, rss/tavalyi.mkv (es a torrent
    konyvtaraban a mintakep.jpg, ha fajlonkent nezzuk).
    """
    share = Path(base) / "downloads"
    rss = share / "rss"
    (share / "Film.Egy.2024").mkdir(parents=True)
    (share / "Film.Egy.2024" / "film.mkv").write_bytes(b"x" * 2048)
    (share / "Film.Egy.2024" / "film.srt").write_bytes(b"y" * 10)
    (share / "Film.Egy.2024" / "mintakep.jpg").write_bytes(b"z" * 100)  # idegen
    (share / "Sorozat S01").mkdir()
    (share / "Sorozat S01" / "e01.mkv").write_bytes(b"a" * 1024)
    (share / "Sorozat S01" / "e02.mkv").write_bytes(b"b" * 1024)
    (share / "Regi.Film.2011").mkdir()  # ehhez mar nincs torrent
    (share / "Regi.Film.2011" / "regi.mkv").write_bytes(b"c" * 4096)
    (share / "arvalt.mkv").write_bytes(b"d" * 64)  # ehhez sincs
    (share / "@eaDir").mkdir()  # NAS mappa, nem bantjuk
    (share / "@eaDir" / "ize").write_bytes(b"e")
    rss.mkdir()
    (rss / "hetivideo.mkv").write_bytes(b"f" * 512)
    (rss / "tavalyi.mkv").write_bytes(b"g" * 256)  # ehhez nincs torrent
    return share, rss
