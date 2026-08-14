"""A Windows parancsfajlok ellenorzese.

Nem futtatja oket (ahhoz Windows kellene), hanem azokat a hibakat keresi,
amiktol a cmd.exe hasznalhatatlanna valik - es amik Linuxon / a GitHub ZIP-ben
eszrevetlenul keletkeznek:

  * LF sorveg: a cmd.exe bajt-eltolas alapjan olvassa tovabb a fajlt, es
    LF-nel elcsuszik, majd egy sor kozepen folytatja ("... was unexpected at
    this time"),
  * ekezetes karakter: a cmd a rendszer kodlapjaval olvas, nem UTF-8-cal,
  * hianyzo .gitattributes szabaly: e nelkul a git a klonozasnal / ZIP-ben
    visszaalakitana a sorvegeket.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        print(f"ok    {name:<46} {got!r}")
    else:
        fail = 1
        print(f"HIBA  {name:<46} kapott={got!r}  vart={want!r}")


batok = sorted(REPO.glob("*.bat"))
check("van parancsfajl", bool(batok), True)

for bat in batok:
    adat = bat.read_bytes()
    maganyos_lf = adat.count(b"\n") - adat.count(b"\r\n")
    check(f"{bat.name}: minden sorveg CRLF", maganyos_lf, 0)
    check(f"{bat.name}: nincs ekezetes karakter",
          [b for b in adat if b > 127], [])
    check(f"{bat.name}: nincs BOM", adat[:3] == b"\xef\xbb\xbf", False)

    szoveg = adat.decode("ascii", "replace")
    # A hivatkozott programfajlok tenyleg letezzenek.
    for nev in ("indit.py", "qbt_gui.py", "qbt_cleanup.py"):
        if nev in szoveg:
            check(f"{bat.name}: hivatkozik ra, es megvan ({nev})",
                  (REPO / nev).is_file(), True)
    # Tobbsoros zarojeles blokk: pont ezeken csuszik el a cmd, ha a sorveg
    # valahogy megis LF lenne. Ezert egyetlen sor sem vegzodhet nyito
    # zarojelre.
    check(f"{bat.name}: nincs tobbsoros zarojeles blokk",
          [sor for sor in szoveg.splitlines() if sor.rstrip().endswith("(")], [])
    # Verziojelzo: a kimenetbol latszik, melyik valtozat futott.
    check(f"{bat.name}: kiirja az indito verziojat",
          "[indito v" in szoveg, True)

    # Minden goto-nak legyen cimkeje.
    cimkek = {sor.strip().lstrip(":").lower()
              for sor in szoveg.splitlines() if sor.strip().startswith(":")}
    ugrasok = {sor.split("goto", 1)[1].strip().lstrip(":").lower()
               for sor in szoveg.splitlines() if "goto" in sor.lower()
               and not sor.strip().lower().startswith("rem")}
    check(f"{bat.name}: minden ugrasnak van cimkeje",
          sorted(ugrasok - cimkek), [])

    # Elgepelt valtozonev: a cmd a parancsfajlban NEM ures szoveggel
    # helyettesiti az ismeretlen %VALAMI%-t, hanem valtozatlanul hagyja - igy a
    # "%HATAR%" szoveg jutna el a programig argumentumkent. Ezert minden
    # hivatkozott valtozot vagy a fajl allit be, vagy a Windows adja.
    WINDOWSTOL = {"cd", "appdata", "localappdata", "userprofile", "path",
                  "temp", "tmp", "errorlevel", "username", "computername"}
    beallitott = {m.lower() for m in re.findall(
        r'(?im)^\s*set\s+"?([A-Za-z_][A-Za-z0-9_]*)=', szoveg)}
    # A %% a cmd-ben egyetlen szazalekjelet jelent, azt nem hivatkozasnak
    # szanjuk; a %~dp0 es a %0..%9 pedig a parancsfajl sajat adata.
    hivatkozott = {m.lower() for m in re.findall(
        r'(?<!%)%([A-Za-z_][A-Za-z0-9_]*)%', szoveg.replace("%%", ""))}
    check(f"{bat.name}: minden hasznalt valtozo letezik",
          sorted(hivatkozott - beallitott - WINDOWSTOL), [])
    # Forditva is: amit beallitunk, azt hasznaljuk is (elfelejtett kapcsolo).
    check(f"{bat.name}: minden beallitott valtozot hasznal is",
          sorted(beallitott - hivatkozott - {"py"}), [])

attrib = REPO / ".gitattributes"
check("van .gitattributes", attrib.is_file(), True)
if attrib.is_file():
    sorok = [s.strip() for s in attrib.read_text(encoding="utf-8").splitlines()]
    check("a .bat sorvegeit rogziti",
          any(s.startswith("*.bat") and ("-text" in s or "eol=crlf" in s)
              for s in sorok), True)

print()
print("MINDEN BAT TESZT SIKERES" if not fail else "VOLT HIBA")
sys.exit(fail)
