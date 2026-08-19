# Felülvizsgálat, javítások és mérési jegyzőkönyv

Környezet: Python 3.10 / 3.11 / 3.12 / 3.13, Ubuntu 24.04, Xvfb.
Minden mérés a repó saját teszt-eszközeivel készült: a `fake_qbt.py` hamis
qBittorrent WebUI-t ad (lassítható, hibázó és munkamenetet vesztő végpontokkal),
a `terheles_test.py` pedig valódi, ideiglenes könyvtárfán mér.

A felülvizsgálat szempontja: ugyanaz, amivel a `web_downloader` készült –
*mit csinál a program akkor, amikor valami rosszul megy?*

---

## 1. A felülvizsgálatban talált hiányosságok

| # | Hiányosság | Következmény | Bizonyíték / javítás |
|---|-----------|--------------|----------------------|
| 1 | A WebUI-hívások **egyszer** próbálkoztak | Egyetlen átmeneti hiba (a NAS épp ébred, a WebUI újraindul, torlódás) elbuktatta az egész takarítást – akkor is, ha a következő pillanatban minden működött | teszt: két egymás utáni `503` után a válasz megjön (`--probak`, duplázódó várakozás, `Retry-After` 30 mp-re vágva) |
| 2 | **Lejárt munkamenet** kezelése hiányzott | Egy több ezer torrentes, fájlonkénti lekérdezés túllépi a qBittorrent munkamenet-határidejét: a program a felénél `403`-mal leállt | teszt: a kiszolgáló egy hívásra 403-at ad és kilépteti a klienst – a program újra bejelentkezik, és folytatja |
| 3 | A `--pontos` mód **minden** torrenthez lekérte a fájllistát, **egyesével** | 2000 torrentnél 2000 egymás utáni hálózati forduló, a többségük fölösleges (más könyvtárban lakó torrent) | mérés lent: 7,3× gyorsulás a párhuzamos lekéréstől, és 1980 elmaradó hívás a szűréstől |
| 4 | A munkát **nem lehetett megszakítani** | Egy nagy megosztás átnézése közben csak az ablak bezárása maradt – ami törlés közben félbehagyta volna a munkát | *Megszakítás* gomb; a háttérszál két elem között áll meg, félig törölt elem nem maradhat |
| 5 | A találati lista **egyben** került a felületre | A betöltés végéig az ablak nem válaszol, és nincs visszajelzés | mérés: 100 000 sor egyben 1,05 mp néma megállás; 400-as adagokban egyetlen blokk sem hosszabb 5 ms-nál (és összesen sem lassabb) |
| 6 | A felület és a motor **`dict[str, Any]`-vel**, a tervezés pedig **12 különálló paraméterrel** kommunikált | Az elgépelt kulcs csak futás közben, a háttérszálban derült ki; egy új kapcsoló minden hívást átírt, és könnyű volt elcsúszni a sorrendben | `Halozat`, `Beallitas`, `Figyelo`, `Feladat` adatosztályok; a `ruff` pylint-szabályai (PL) bekapcsolva |
| 7 | A beállítások mentése `os.replace`-szel, újrapróbálkozás nélkül | Windowson a víruskereső / keresőindexelő pillanatnyi zárolása `PermissionError`-ral eldobta a mentést – a beállítások elvesztek | teszt: két „zárolt” próbálkozás után is sikerül a csere (`csere_ujraprobalva`) |
| 8 | A napló mappáját megnyitó `subprocess.Popen` nem gyűjtötte be a gyereket | Minden megnyitás után zombi folyamat maradt a program végéig, a fájlkezelő pedig a mi konzolunkra írt és megkapta a Ctrl+C-nket | külön munkamenet, elnyelt kimenet, a befejezettek begyűjtése |
| 9 | **Nem volt eseménynapló** | A felületnek nincs konzolja, az ütemezett futás kimenetét elnyeli a Feladatütemező: egy sikertelen futás után semmi nyom nem maradt arról, hogy mi történt | `esemenyek.log`, rotálva (512 KB, 3 példány). A parancssor **szándékosan** nem kerül bele: a `--password` ott lehetne benne – erre külön teszt is figyel |
| 10 | A napló és a beállítások helye csak az `APPDATA` **meglétét** nézte | Nem Windowson (Wine, MSYS, kézzel beállított környezet) a Windows-os elrendezést használta volna | `sys.platform == "win32"` feltétel is kell hozzá |
| 11 | Az indító tesztje a futtató gép `tkinter`-jétől függött | Ahol nincs `python3-tk`, a teszt a **programot** minősítette hibásnak (ebben a konténerben 3 ellenőrzés bukott emiatt) | a modul-ellenőrzés kicserélhető; a hiányzó `tkinter` üzenete külön teszttel |
| 12 | Az indító modul-listája elavult | A program azóta használ `threading`, `concurrent.futures` és `enum` modult; ezek hiányát az indító nem vette volna észre, a felület pedig érthetetlen hibával állt volna meg | a lista kiegészítve |
| 13 | `_main` 102, `_epit` 102 utasítás | Egy százsoros függvényben a hiba is jól elfér | mindkettő lépésekre bontva; a `ruff` PL-szabályai őrzik |
| 14 | A tesztek a valódi felhasználói állapot-könyvtárba írhattak | A tesztfuttatás nyomot hagyott a fejlesztő gépén | a tesztek `XDG_STATE_HOME`-ot állítanak maguknak |

Amit **nem** kellett javítani (a felülvizsgálat ezeket rendben találta): a
biztonsági fékek (üres torrentlista, rossz útvonal-megfeleltetés, gyökér
könyvtár, `--max-torles`), a nem rekurzív fabejárás, az ékezet- és
perjel-egységesítés, a `.!qB` kezelése egyetlen helyen, az írásvédett fájlok
törlése a belépési jog megtartásával, és a törlési napló rotálása.

## 2. Mérések

### 2.1 Fájllista-lekérés (24 torrent, végpontonként 50 ms)

| Megoldás | Idő |
|---|---|
| egyesével, sorban (az eredeti) | 1,24 mp |
| **8 szálon, párhuzamosan (a választott)** | **0,17 mp** |

A gyorsulás 7,3×. A várakozás nem számítás: a szálak nagy része a válaszra vár,
ezért a párhuzamosság felső határa (16) nem a gépről szól, hanem arról, hogy egy
gyenge NAS-t se terheljünk túl.

### 2.2 A lekérdezendő torrentek szűrése (2000 torrent, 20 érintett)

| | |
|---|---|
| szűrés ideje | 0,01 mp |
| elmaradó WebUI-hívás | **1980 db** |

Egy tipikus qBittorrentben a torrentek többsége nem a takarított könyvtárban
lakik. A fájllistájuk lekérése torrentenként egy hálózati forduló – az
eredményt pedig úgyis eldobnánk.

### 2.3 Nagy megosztás átnézése (8000 bejegyzés)

| Üzemmód | Idő | Többletmemória |
|---|---|---|
| `felso` (8000 elem a legfelső szinten) | 0,44 mp | 3,7 MB |
| `fa` (200 könyvtár × 40 fájl) | 0,16 mp | – |

A méretszámolás `os.scandir()` saját `stat()`-jával dolgozik: hálózati
megosztáson ez könyvtáranként egy forduló, nem fájlonként egy.

### 2.4 A találati lista feltöltése (100 000 sor)

| Megoldás | Teljes idő | Leghosszabb egybefüggő blokk |
|---|---|---|
| egyben (az eredeti) | 1,05 mp | 1,05 mp – addig az ablak nem válaszol |
| **400-as adagokban (a választott)** | **0,79 mp** | **5 ms** |

Az adagolás nem csak érzésre jobb: összességében is gyorsabb, mert a Tk nem
egyetlen óriási újrarajzolással birkózik.

## 3. Második kör: hibakeresés, Windows 11, memória és processzoridő

Ez a kör nem az általános felépítést nézte, hanem azt, hogy **igaz-e, amit a
program feltételez**. Ahol lehetett, a forrás a mérce lett: a qBittorrent
WebUI-jának C++ forrása, a CPython `ntpath` modulja és a Windows-manifestje –
nem az emlékezet.

### 3.1 A legfontosabb: adatvesztés gyökérmappa nélküli torrenteknél

A qBittorrent forrásában (`TorrentImpl::contentPath`) ez áll:

```cpp
if (filesCount() == 1)
    return (actualStorageLocation() / filePath(0));
const Path rootPath = this->rootPath();
return (rootPath.isEmpty() ? actualStorageLocation() : rootPath);
```

Tehát egy **többfájlos, gyökérmappa nélküli** torrentnél – ilyet a „ne hozzon
létre almappát" tartalom-elrendezés készít – a `content_path` **maga a mentési
könyvtár**. A program eddig ebből a *letöltési könyvtár nevét* vette
„gyökér-névnek", a torrent saját fájljait pedig nem ismerte fel.

Próba a javítás előtt (3 fájl, kettő a torrenté):

```
root_name() eredmenye: 'downloads'
FELSO mod - amit torolne:  a.mkv, b.mkv, szemet.mkv
FA mod   - amit torolne:  a.mkv, b.mkv, szemet.mkv
```

Vagyis **a seedelt fájlokat is törölte volna, mindkét üzemmódban**.

Javítás: a `root_name()` ilyenkor üres nevet ad; a program a torrent
fájllistájából veszi a legfelső szintű neveket, és ezt **az üzemmódtól
függetlenül** lekéri (`kell_fajllista`). Ha a lista hiányzik, a `plan_all`
biztonsági fékkel leáll, ahelyett hogy találgatna. Ugyanez a futás a javítás
után:

```
Felesleges elemek (1 db, 32 B):  szemet.mkv
megmaradt: ['elso.mkv', 'masodik.mkv']
```

### 3.2 További javítások

| # | Hiba | Következmény | Bizonyíték / javítás |
|---|------|--------------|----------------------|
| 15 | Gyökérmappa nélküli torrent (lásd fent) | A seedelt fájlok törlése | reprodukált futás + 12 új teszt |
| 16 | UNC-célra mutató megfeleltetés záró perjellel (`\\gep\share\`) hibás kulcsot adott | A `//gep/share//film` alak **egyetlen** valódi elemmel sem egyezett – a torrent mappáját feleslegesnek látta volna | különbség-teszt a régi és az új megvalósítás között (13 eset) |
| 17 | Lejárt munkamenetnél minden szál külön bejelentkezett | 16 párhuzamos lekérdezésnél 16 egyidejű bejelentkezés ugyanarra a munkamenetre | számlálós dedup; teszt: négy egyszerre érkező szálból egy lép be |
| 18 | Az újrapróbálkozás várakozása nem volt megszakítható | A *Megszakítás* után is végig kellett várni a hátralévő másodperceket | a várakozás 0,2 mp-es szeletekben figyeli a megszakítást; teszt: 0,5 mp alatt leáll |
| 19 | A fájllisták teljes WebUI-válasza a memóriában maradt | 500 torrent × 200 fájl esetén 48 MB, pedig csak a névre van szükség | `QbtClient.fajlnevek`; mérve 8,9 MB → 1,3 MB (100×200-on) |
| 20 | `owned_paths` fájlonként `Path` objektumokat épített | A profilozás szerint a pathlib vitte az idő felét | szöveg-kulcsok; 100 000 fájlra **1,54 mp → 0,26 mp** |
| 21 | `owner_target` elemenként újrarendezte a könyvtárlistát | A törlési ciklus legdrágább része volt | előkészített, gyorsítótárazott lista; 20 000 elemre **0,43 mp → 0,13 mp** |
| 22 | A `plan_tree` a rendezéshez újra előállította az összehasonlítási kulcsokat | Fölösleges NFC + casefold minden találatra | a kulcs a találat mellett utazik; 100 000 elemre **0,65 mp → 0,02 mp** |
| 23 | A `Candidate` akkor is újraépítette a `Path`-ot, ha már az volt | 100 000 elemnél 0,07 mp és fölösleges szemét | típusellenőrzés |

### 3.3 Amit megnéztünk, és **nem** kellett javítani

- **`json.load(stream)` a `read()+decode()+loads()` helyett**: 5000 torrentnél
  mérve **ugyanaz** a 6,8 MB csúcs – a `json` úgyis egyben olvassa be. Az
  „optimalizálás" itt nem hozott volna semmit, ezért elmaradt.
- **A `root_path` mező** (a WebUI küldi): a qBittorrent forrása szerint pontosan
  akkor üres, amikor nincs gyökérmappa – tehát nem ad többletinformációt a
  `content_path`-hoz képest.
- **DPI**: a CPython Windows-manifestje (`PC/python.manifest`) **nem** állít
  `dpiAware`-t (csak `longPathAware`-t), tehát a `SetProcessDpiAwareness(1)`
  hívásra tényleg szükség van. Per-monitoros DPI-t szándékosan nem kérünk: a
  Tk 8.6 nem kezeli a `WM_DPICHANGED` üzenetet, így a másik monitorra húzott
  ablak rossz méretű lenne – a rendszerszintű tudatosságnál viszont csak
  átméretezett (életlen) marad.
- **Hosszú útvonalak**: a manifest `longPathAware=true` beállítása önmagában
  csak akkor elég, ha a `LongPathsEnabled` beállítás is be van kapcsolva a
  rendszerleíró adatbázisban. A `\?\` előtag ettől függetlenül működik, ezért
  maradt.

### 3.4 Mérések (második kör)

| Mérés | Előtte | Utána |
|---|---|---|
| `owned_paths`, 100 000 fájl | 1,54 mp | **0,26 mp** |
| `owner_target`, 20 000 törölt elem | 0,43 mp | **0,13 mp** |
| találatok rendezése, 100 000 elem | 0,65 mp | **0,02 mp** |
| fájllisták a memóriában (100 × 200) | 8,9 MB | **1,3 MB** |
| fájllisták a memóriában (500 × 200) | 48,3 MB | **10,2 MB** |

## 4. Végleges tesztek

```
motor (qbt_test.py)                      155 / 155
felület (gui_test.py, Xvfb)               84 / 84
törlési és eseménynapló (naplo_test.py)   49 / 49
Windows 11 (windows_test.py)              33 / 33
indító (indit_test.py)                    27 / 27
parancsfájlok (bat_test.py)               21 / 21
terhelés és mérések (terheles_test.py)    14 / 14
összesen                                 383 / 383
```

`ruff check .` – tiszta, a pylint-szabályokkal (`PL`) együtt.
A teljes készlet Python 3.10-től 3.14-ig fut (GitHub Actions).
