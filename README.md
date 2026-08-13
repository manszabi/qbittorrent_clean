# 🧹 qBittorrent takarító

> A megosztásodon maradt szemét kitakarítása: ami már nincs a qBittorrentben,
> az mehet.

Megnézi, hogy egy qBittorrent (WebUI) éppen milyen torrenteket futtat, majd a
megadott könyvtárban – például egy Samba megosztáson – megkeresi azokat a
fájlokat és könyvtárakat, **amikhez már nem tartozik torrent**, és törli őket.

- csak `python3` kell hozzá (3.7+), **külső csomag nélkül**,
- **alapból semmit nem töröl**, csak kiírja, mit törölne,
- a tényleges törléshez `--torol` kell, és megerősítést kér (`--igen` kihagyja),
- törlés helyett tud **kukába** is mozgatni (`--kuka`),
- ha nem éri el a WebUI-t, vagy rossz a jelszó, **egyetlen fájlhoz sem nyúl**.

## Gyors indítás

Windows alatt a legegyszerűbb a **`qbt_takaritas.bat`**: nyisd meg jegyzettömbbel,
írd át benne a címet, a felhasználónevet és a könyvtárakat, majd kattints rá
duplán. Alapból csak megmutatja, mit törölne.

Parancssorból (Windows):

```bat
python qbt_cleanup.py --url http://192.168.1.38:30024/ --user admin ^
    --konyvtar \\192.168.1.38\downloads ^
    --konyvtar \\192.168.1.38\downloads\rss
```

Linux / macOS, csatolt megosztással:

```bash
python3 qbt_cleanup.py --url http://192.168.1.38:30024/ --user admin \
    --konyvtar /mnt/downloads --konyvtar /mnt/downloads/rss
```

A jelszót nem kell a parancssorba írni: ha nincs megadva, a program bekéri
(vagy a `QBT_PASSWORD` környezeti változóból veszi). Ha jónak találod a listát,
ugyanaz a parancs a végén `--torol`.

## ⚠️ Az egymásba ágyazott könyvtárak

A `\\192.168.1.38\downloads\rss` a `downloads` **alkönyvtára**. Ha csak a
`downloads`-ot vizsgálnád, az `rss` mappa neve nem egyezne egyetlen torrent
nevével sem, ezért a program feleslegesnek látná és **törölné**.

Ezért mindkettőt add meg `--konyvtar`-ral: a vizsgált könyvtárak automatikusan
**védik egymást**, tehát a `downloads` takarításakor az `rss` mappa érintetlen
marad, a tartalmát pedig külön, a saját torrentjeihez mérve nézi meg a program.

## A két üzemmód

| Mód | Mit csinál | Mikor jó |
|-----|------------|----------|
| `--mod felso` (alap) | Csak a megadott könyvtár **legfelső szintjét** nézi, és a **nevek** alapján dönt: a torrentek gyökér-neveivel veti össze. | Szinte mindig. Akkor is működik, ha a qBittorrent NAS-on / konténerben fut, és egészen máshogy látja a könyvtárat (`/downloads`), mint a te géped (`\\192.168.1.38\downloads`). |
| `--mod fa` | A **teljes könyvtárfát** bejárja, és a qBittorrent **útvonalaival** veti össze. | Ha a torrent-könyvtárakon belül is takarítani akarsz, és meg tudod adni az útvonal-megfeleltetést. |

A `fa` módhoz kell az útvonal-megfeleltetés, ha a két gép máshogy látja a
megosztást:

```bat
python qbt_cleanup.py --mod fa ^
    --utvonal /downloads=\\192.168.1.38\downloads ^
    --utvonal /downloads/rss=\\192.168.1.38\downloads\rss ^
    --konyvtar \\192.168.1.38\downloads ^
    --konyvtar \\192.168.1.38\downloads\rss
```

Ha rossz a megfeleltetés, a program **nem talál egyetlen torrent-elemet sem** a
könyvtárban – ilyenkor mindent törölne, ezért inkább leáll és szól.

A `--pontos` kapcsoló (`fa` módban) torrentenként lekéri a fájllistát is, így a
torrent saját könyvtárán belüli idegen fájlok (kézzel bemásolt felirat, minta-
kép, `.nfo`) is feleslegesnek számítanak. Enélkül a torrent könyvtárában semmit
nem bánt.

## Kapcsolók

| Kapcsoló | Jelentés |
|----------|----------|
| `--url` | A WebUI címe (alap: `http://192.168.1.38:30024/`, felülírja a `QBT_URL`). |
| `--user`, `--password` | WebUI belépés. Üres felhasználónévnél nem jelentkezik be (ha a WebUI a helyi hálózatról nem kér azonosítást). Jelszó jöhet a `QBT_PASSWORD`-ből is. |
| `--konyvtar` | A vizsgált könyvtár. **Többször is megadható.** |
| `--mod felso` / `--mod fa` | Lásd fent. |
| `--utvonal TAVOLI=HELYI` | Útvonal-megfeleltetés a `fa` módhoz, többször is. |
| `--pontos` | `fa` módban fájlonkénti összevetés. |
| `--kivetel MINTA` | Amit soha ne bántson (pl. `--kivetel "*.nfo"`), többször is. |
| `--nincs-gyari-kivetel` | A gyári védett lista kikapcsolása (lásd lent). |
| `--min-kor NAP` | Csak az ennél régebben módosított elemeket törli. Hasznos, ha épp most raktál oda valamit. |
| `--kuka KONYVTAR` | Törlés helyett ide mozgat. A kuka önmagát nem eszi meg. |
| `--max-torles DB` | Ha ennél többet törölne, inkább leáll. |
| `--torol` | Tényleges törlés (enélkül csak lista). |
| `--igen` | Ne kérdezzen rá. Ütemezett futtatáshoz kell. |
| `--ures-lista-ok` | Akkor is dolgozzon, ha egy torrent sincs (⚠️ ilyenkor mindent törölne). |
| `--kis-nagy-betu` | Számítson a kis- és nagybetű a nevek összevetésénél (alapból nem számít – így inkább megtart valamit, mint hogy tévedésből töröljön). |
| `--nem-biztonsagos-tls` | HTTPS-nél ne ellenőrizze a tanúsítványt. |
| `--idokorlat MP` | Hálózati időkorlát (alap: 30 mp). |

Gyárilag védett nevek (a NAS és az operációs rendszer mappái):
`.recycle`, `#recycle`, `@Recycle`, `@eaDir`, `.@__thumb`, `lost+found`,
`.Trash-*`, `$RECYCLE.BIN`, `System Volume Information`, `.unwanted`.

## Amire figyel

- A **félkész** letöltéseket megtartja: a `.!qB` végződésű fájlokat és a
  torrent ideiglenes (`download_path`) könyvtárát is a torrenthez tartozónak
  veszi.
- Az **ékezetes neveket** egységesíti (a Samba és a macOS másképp kódolhatja
  ugyanazt a nevet), és alapból a kis/nagybetűt sem nézi.
- **Szimbolikus linkbe nem lép be**, csak magát a linket törli.
- Hiba esetén (nem elérhető WebUI, rossz jelszó, olvashatatlan könyvtár)
  **nem töröl semmit**.
- A gyökérkönyvtárat (`/`, `C:\`) nem hajlandó takarítani; a megosztás gyökere
  (`\\gép\megosztás`) viszont rendben van.

## Ütemezett futtatás

Ehhez `--igen` kell (különben rákérdezne), és a jelszót érdemes környezeti
változóban átadni. Windows Feladatütemezőhöz például:

```bat
set QBT_PASSWORD=titkos
python C:\utvonal\qbt_cleanup.py --user admin --min-kor 1 --max-torles 50 ^
    --konyvtar \\192.168.1.38\downloads ^
    --konyvtar \\192.168.1.38\downloads\rss --torol --igen
```

Visszatérési érték: `0` = rendben, `1` = hiba (vagy nem sikerült minden törlés),
`2` = biztonsági okból leállt.

## A repó tartalma

| Fájl | Mi ez |
|------|-------|
| `qbt_cleanup.py` | Maga a program. Ez az egyetlen fájl, ami a működéshez kell. |
| `qbt_takaritas.bat` | Windows-indító: írd át benne a beállításokat, és kattints rá duplán. |
| `tests/qbt_test.py` | A tesztkészlet (lásd lent). |

## Teszt

```bash
python3 tests/qbt_test.py
```

Hamis qBittorrent WebUI-t indít, valódi ideiglenes könyvtárfát épít, és
ténylegesen töröltet vele – ellenőrizve, hogy a torrentekhez tartozó fájlok
megmaradnak, az `rss` alkönyvtár védve van, hiba esetén pedig semmi nem vész el.
