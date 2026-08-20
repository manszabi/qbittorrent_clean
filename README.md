# 🧹 qBittorrent takarító

> A megosztásodon maradt szemét kitakarítása: ami már nincs a qBittorrentben,
> az mehet.

Megnézi, hogy egy qBittorrent (WebUI) éppen milyen torrenteket futtat, majd a
megadott könyvtárban – például egy Samba megosztáson – megkeresi azokat a
fájlokat és könyvtárakat, **amikhez már nem tartozik torrent**, és törli őket.

- **grafikus felület** és parancssoros használat is,
- csak `python3` kell hozzá (3.10+), **külső csomag nélkül**,
- a saját **`.venv`** környezetében fut (Windowson és Linuxon egyaránt), amit
  az első indításkor magának készít el,
- **alapból semmit nem töröl**, csak kiírja, mit törölne,
- a tényleges törléshez `--torol` kell, és megerősítést kér (`--igen` kihagyja),
- törlés helyett tud **kukába** is mozgatni (`--kuka`),
- ha nem éri el a WebUI-t, vagy rossz a jelszó, **egyetlen fájlhoz sem nyúl**,
- minden törlésről **naplót** vezet (mit, mikor, honnan).

## Gyors indítás Windows alatt

Kattints duplán a **`qbittorrent_clean.bat`** fájlra. Az indítás mindent
elintéz:

- megkeresi a Pythont (`py` launcher, majd `python`),
- ellenőrzi a verziót (3.10 vagy újabb kell),
- **elkészíti a saját `.venv` környezetet** a program mappájában (egyszeri,
  pár másodperc), és onnantól mindig abban fut,
- ellenőrzi a szükséges modulokat (`tkinter` és a szabvány könyvtár),
- ha a `requirements.txt`-ben van külső csomag, **telepíti** – a saját
  környezetbe, tehát a rendszer Pythonjához nem nyúl,
- majd elindítja a grafikus felületet.

Maga a `.bat` szándékosan csak a Pythont keresi meg, minden ellenőrzés az
`indit.py`-ban van – így tesztelhető. (A `cmd.exe` nem az: többsoros zárójeles
blokk és LF sorvég együtt menet közbeni, félrevezető hibákat okoz, ezért a
parancsfájlban egyik sincs.)

### A saját környezet (`.venv`)

A program a saját mappájában készít egy `.venv` könyvtárat, és **mindig abban
fut** – mindegy, hogy Windowson a `.bat`-ról, vagy Linuxon a
`python3 qbt_gui.py` paranccsal indítod. A belépési pontok (`indit.py`,
`qbt_gui.py`, `qbt_cleanup.py`) első dolga megnézni, hogy a `.venv`
értelmezőjével futnak-e; ha nem, ugyanazt a fájlt újraindítják onnan,
változatlan kapcsolókkal. A kimenet és a kilépési kód a hívóé marad, tehát az
ütemezett futtatás számára sem változik semmi.

Miért jó ez: a takarító mindenhol ugyanazzal a Pythonnal és ugyanazokkal a
csomagokkal fut, és nem tud elromlani attól, hogy valaki a rendszer Pythonjában
telepít vagy töröl valamit. Cserébe egy mappával több van (`.venv`, kb. 30 MB), az első indítás pedig
pár másodperccel hosszabb; a későbbi indítások költsége mérve 0,1 mp.

Ha nem hozható létre (nincs írási jog a mappára, vagy a disztribúció külön
csomagba tette a `venv`-et: `sudo apt install python3-venv`), a program **nem
áll le**: figyelmeztet, és a rendszer Pythonjával megy tovább.

Kikapcsolás – fejlesztéshez, CI-hez, vagy ha magad kezeled a környezetet:

```bash
QBT_VENV_KIHAGY=1 python3 qbt_gui.py
```

## A grafikus felület

Fentről lefelé:

1. **qBittorrent WebUI** – cím, felhasználó, jelszó. A *Kapcsolat próba* gomb
   megmondja, hány torrentet lát. A jelszó csak akkor mentődik el (sima
   szövegként), ha külön bepipálod.
2. **Vizsgált könyvtárak** – *Tallózás…* vagy *Beírom…* (hálózati útvonalhoz ez
   utóbbi a kényelmesebb: `\\192.168.1.38\downloads`). Sorolj fel minden
   letöltési könyvtárat, az egymásba ágyazottakat is – **védik egymást**.
3. **Beállítások** – üzemmód, kivételek, „csak ennél régebbi”, kuka, és a
   `fa` módhoz az útvonal-megfeleltetések.
4. **Mit törölne? (próba)** – ez még nem töröl semmit, csak listáz.
5. A találati lista minden sora **kipipálható**: kattints a bal szélső ✓
   oszlopra, vagy használd a *Mindet ki/be* gombot. A **Kipipáltak törlése**
   csak a bepipált sorokra vonatkozik, és külön rákérdez.

A beállítások kilépéskor automatikusan elmentődnek (Windowson az
`%APPDATA%\qbittorrent_clean\beallitasok.json` fájlba), és induláskor
visszatöltődnek. A mentés előbb ideiglenes fájlba ír, és csak utána cseréli le
a régit – egy félbeszakadt mentés így nem teszi tönkre a meglévő beállításokat.
A fájlt (mert jelszó is lehet benne) csak a tulajdonos olvashatja.

A hálózati lekérdezés és a könyvtárak átnézése külön szálon fut, így az ablak
nem fagy le a nagy megosztásokon sem. A **Megszakítás** gombbal bármikor le
lehet állítani a munkát: a program két elem között áll meg, tehát félig törölt
elem nem maradhat utána. A találati listát adagokban tölti fel, így sok tízezer
soros eredménynél sem „fagy be” az ablak, és közben látszik a haladás.

## Parancssoros használat

Ütemezett futtatáshoz (Feladatütemező) vagy ha nincs kedved kattintgatni. A
`qbt_takaritas.bat` ezt indítja; közvetlenül így néz ki (Windows):

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
| `--naplo FAJL` | A törlési napló helye (alap: lásd lent). |
| `--nincs-naplo` | Ne vezessen törlési naplót. |
| `--naplo-meret MB` | Ekkora naplófájl után kezdjen újat (alap: 5 MB). |
| `--naplo-tartas DB` | Ennyi lezárt (tömörített) naplófájlt tartson meg (alap: 12). |
| `--max-torles DB` | Ha ennél többet törölne, inkább leáll. |
| `--torol` | Tényleges törlés (enélkül csak lista). |
| `--igen` | Ne kérdezzen rá. Ütemezett futtatáshoz kell. |
| `--ures-lista-ok` | Akkor is dolgozzon, ha egy torrent sincs (⚠️ ilyenkor mindent törölne). |
| `--kis-nagy-betu` | Számítson a kis- és nagybetű a nevek összevetésénél (alapból nem számít – így inkább megtart valamit, mint hogy tévedésből töröljön). |
| `--nem-biztonsagos-tls` | HTTPS-nél ne ellenőrizze a tanúsítványt. |
| `--idokorlat MP` | Hálózati időkorlát (alap: 30 mp). |
| `--probak DB` | Egy WebUI-hívás ennyiszer próbálkozzon átmeneti hiba esetén (alap: 3; `1` = ne próbálja újra). |
| `--szalak DB` | A `--pontos` fájllista-lekérés párhuzamossága (alap: 8, legfeljebb 16). |
| `--verzio` | A verzió kiírása. |

Gyárilag védett nevek (a NAS és az operációs rendszer mappái):
`.recycle`, `#recycle`, `@Recycle`, `@eaDir`, `.@__thumb`, `lost+found`,
`.Trash-*`, `$RECYCLE.BIN`, `System Volume Information`, `.unwanted`.

## Törlési napló

Minden törölt (vagy kukába mozgatott) elemről bejegyzés készül. A napló helye
alapból:

| | |
|---|---|
| Windows | `%APPDATA%\qbittorrent_clean\naplo\torlesek.log` |
| Linux / macOS | `~/.local/state/qbittorrent_clean/naplo/torlesek.log` |

(Az eseménynapló ugyanitt, `esemenyek.log` néven – lásd lentebb.)

A sorok tabulatorral vannak elválasztva, így szövegszerkesztőben olvasható,
táblázatkezelőben pedig egyből oszlopokra bomlik:

```
ido                  muvelet   tipus     meret_bajt  konyvtar                    nev                reszletek
2026-08-14 17:23:45  torolve   konyvtar  4294967296  \\192.168.1.38\downloads    Regi.Film.2011
2026-08-14 17:23:47  kukaba    fajl      104857600   \\192.168.1.38\downloads    arva.mkv           kukaba: …\.kuka\arva.mkv
2026-08-14 17:23:48  sikertelen fajl     512         \\192.168.1.38\downloads    zart.mkv           SIKERTELEN: [WinError 32] …
```

A napló **magától rotálódik**: új fájlt kezd hétfőnként, illetve ha a mostani
elérte az 5 MB-ot (`--naplo-meret`). A lezárt fájlt gzip-pel tömöríti
(`torlesek-2026-08-14_172345_871204.log.gz`), és a 12 legfrissebbnél
régebbieket eldobja (`--naplo-tartas`).

A felületen a *Beállítások* alatt ki-be kapcsolható, és a **Megnyit** gombbal
a napló mappája megnyitható. A próba (nem törlő) futás nem ír a naplóba, és a
naplózás soha nem állítja meg a takarítást: ha nem írható a fájl, csak szól
róla.

## Eseménynapló

A törlési napló mellett készül egy `esemenyek.log` is, ugyanabban a mappában.
Ez nem könyvelés, hanem **hibakeresés**: mikor indult a program, mit nem ért
el, hány elemet talált, hol állt le.

```
2026-08-19 05:41:02  indul: felulet 2.1
2026-08-19 05:41:20  a WebUI nem elerheto: Nem sikerult elerni a qBittorrent WebUI-t …
2026-08-19 05:42:11  atnezve: 148 torrent, 6 felesleges elem (12.4 GB)
2026-08-19 05:42:19  kesz: 6 elem torolve, 12.4 GB felszabadulva, 0 sikertelen
```

Erre azért van szükség, mert a **grafikus felületnek nincs konzolja**, az
**ütemezett futásnak** pedig elnyeli a kimenetét a Feladatütemező: baj esetén
másképp semmi nyom nem maradna. A **parancssor nem kerül bele**: a
`--password` ott lehetne benne, és a napló nem való jelszótárnak. A fájl
legfeljebb 512 KB, és három korábbi példányt tart meg – magától nem nő el. Parancssorból a `--nincs-naplo`
kapcsolja ki (a törlési naplóval együtt).

## Amire figyel

- A **gyökérmappa nélküli** torrenteket is felismeri. Ha a torrentet a
  qBittorrent „ne hozzon létre almappát" tartalom-elrendezésével adták hozzá,
  a fájljai közvetlenül a letöltési könyvtárban vannak, és a WebUI a
  `content_path` mezőben **magát a mentési könyvtárat** küldi. Ilyenkor a
  program – mindkét üzemmódban – lekéri a torrent fájllistáját, hogy tudja,
  mi tartozik hozzá; ha az nem érhető el, inkább leáll, semhogy a seedelt
  fájlokat feleslegesnek lássa.
- A **félkész** letöltéseket megtartja: a `.!qB` végződésű fájlokat és a
  torrent ideiglenes (`download_path`) könyvtárát is a torrenthez tartozónak
  veszi – mindkét üzemmódban.
- Az **ékezetes neveket** egységesíti (a Samba és a macOS másképp kódolhatja
  ugyanazt a nevet), és alapból a kis/nagybetűt sem nézi.
- A **kétféle perjelet** (`\` és `/`) ugyanannak veszi, így a `fa` mód akkor is
  egyezteti az útvonalakat, ha a qBittorrent Windowson fut.
- **Szimbolikus linkbe nem lép be**, csak magát a linket törli.
- Egy **átmeneti hálózati hiba** (a NAS épp ébred, a WebUI újraindul, torlódás)
  nem buktatja el a takarítást: a program duplázódó várakozással újrapróbálja
  (`--probak`), és a kiszolgáló `Retry-After` kérését is figyeli – legfeljebb
  30 másodpercig, hogy egy elgépelt fejléc ne állítsa meg órákra.
- A **lejárt WebUI-munkamenetbe** magától újra bejelentkezik. Egy több ezer
  torrentes, fájlonkénti lekérdezés simán túléli a qBittorrent munkamenet-
  határidejét; enélkül a felénél állna le.
- A `--pontos` módhoz **csak a vizsgált könyvtárba eső torrentek** fájllistáját
  kéri le, és azt is **párhuzamosan** (`--szalak`). Kétezer torrentből tipikusan
  néhány tucat esik ide: a többi lekérdezése fölösleges hálózati forduló lenne.
- Hiba esetén (nem elérhető WebUI, rossz jelszó, olvashatatlan könyvtár)
  **nem töröl semmit**.
- A gyökérkönyvtárat (`/`, `C:\`) nem hajlandó takarítani; a megosztás gyökere
  (`\\gép\megosztás`) viszont rendben van.
- A **260 karakternél hosszabb** útvonalakat is kezeli Windowson (a hosszú
  kiadási nevek egy `Subs` almappával könnyen átlépik ezt a határt).
- Ha egy **alkönyvtárat nem tud beolvasni** (jogosultság, hálózati akadás),
  azt az ágat kihagyja és szól róla – a takarítás többi része lefut.
- A grafikus felület **DPI-tudatos**: Windows 11 alatt 125–150%-os nagyítás
  mellett sem lesz elmosódott.

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
`2` = biztonsági okból leállt (rossz kapcsoló is), `130` = megszakítottad
(Ctrl+C).

## A repó tartalma

| Fájl | Mi ez |
|------|-------|
| `qbittorrent_clean.bat` | **Windows-indító**: megkeresi a Pythont, és átadja a vezérlést az `indit.py`-nak. Ezt kattintsd. |
| `indit.py` | A függőség-ellenőrzés: verzió, saját környezet, modulok, `tkinter`, csomagok telepítése – majd indítja a felületet. |
| `qbt_kornyezet.py` | A saját `.venv` környezet: létrehozás, és a belépési pontok átváltása rá. |
| `qbt_gui.py` | A grafikus felület (Tkinter). |
| `qbt_cleanup.py` | A motor: ez végzi a tényleges munkát, és önmagában, parancssorból is használható (a `qbt_naplo.py` legyen mellette). |
| `qbt_naplo.py` | A törlési napló: sorok írása, heti / méret szerinti rotálás, tömörítés. |
| `qbt_takaritas.bat` | Parancssoros indító ütemezett futtatáshoz. |
| `requirements.txt` | Külső csomag nincs – az indító ezt ellenőrzi. |
| `pyproject.toml` | A fejlesztői eszközök (ruff) beállítása; a program telepítés nélkül fut. |
| `tests/` | Tesztkészlet (lásd lent) és a felülvizsgálati jegyzőkönyv. |

## Teszt

```bash
tests/run_all.sh          # az egész készlet
python3 tests/qbt_test.py # csak a motor (tkinter nélkül is megy)
ruff check .              # stílus- és hibaellenőrzés
```

Ugyanez fut a GitHubon is minden feltöltésnél
(`.github/workflows/tesztek.yml`), a 3.10-től a 3.14-ig minden Python
verzióval.

A felülvizsgálat során talált hiányosságok, a javításuk és a mérések
(párhuzamos lekérdezés, nagy megosztás átnézése, listafeltöltés) a
[`tests/FELULVIZSGALAT.md`](tests/FELULVIZSGALAT.md) fájlban vannak.

Hamis qBittorrent WebUI-t indít, valódi ideiglenes könyvtárfát épít, és
ténylegesen töröltet vele – ellenőrizve, hogy a torrentekhez tartozó fájlok
megmaradnak, az `rss` alkönyvtár védve van, hiba esetén pedig semmi nem vész el.

| Teszt | Mit vizsgál |
|-------|-------------|
| `bat_test.py` | A Windows parancsfájlok: CRLF sorvég, ékezetmentesség, nincs többsoros zárójeles blokk, minden `goto`-nak van címkéje, minden `%VÁLTOZÓ%` létezik, a hivatkozott fájlok léteznek. (Ezek nélkül a `cmd.exe` menet közben, félrevezető helyen száll el.) |
| `indit_test.py` | Az indító függőség-ellenőrzései: verzió, hiányzó modul, `requirements.txt` értelmezése, `pip` újrapróbálkozás (`--user`, illetve `ensurepip` a saját környezetben), hiányos mappa, átváltás a `.venv`-re. |
| `kornyezet_test.py` | A saját `.venv`: útvonalak mindkét rendszerre, mikor kell átváltani, valódi környezet létrehozása és az, hogy a gyerekfolyamat tényleg abból indul. |
| `qbt_test.py` | A motor: útvonal-kezelés (kétféle ékezet-kódolás, kétféle perjel), a két üzemmód, kuka, biztonsági fékek, valódi törlés, naplózás. |
| `naplo_test.py` | A törlési napló: oszlopok, rotálás méretre és hétfőnként, tömörítés, régi fájlok eldobása, hibatűrés. |
| `windows_test.py` | Windows 11 specifikus szabályok Linuxon szimulálva: hosszú útvonalak (`\\?\`, UNC), meghajtó-gyökér, kis-nagybetű, kuka-nevek, `%APPDATA%`, DPI-tudatosság, cp852 konzolkódlap, a napló mappájának megnyitása. Ahol lehet, a CPython saját `ntpath` modulja a mérce. |
| `terheles_test.py` | Terhelés és mérés: 8000 bejegyzésű megosztás mindkét módban, memóriacsúcs, párhuzamos fájllista-lekérés, a lekérdezendő torrentek szűrése,
a fájllisták memóriaigénye, a törlési ciklus költsége. A határok bőségesek, de a nagyságrendi elcsúszást elkapják. |
| `gui_test.py` | A valódi Tkinter ablak végigkattintgatása: kapcsolódás, vizsgálat, pipálgatás, törlés kukába és véglegesen, beállítások mentése és elrontott beállítás-fájl, háttérszálban keletkező hiba, megszakítás, a lista adagolt feltöltése. Fejnélküli gépen `xvfb-run` kell hozzá. |
