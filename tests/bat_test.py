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
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        print("ok    %-46s %r" % (name, got))
    else:
        fail = 1
        print("HIBA  %-46s kapott=%r  vart=%r" % (name, got, want))


batok = sorted(REPO.glob("*.bat"))
check("van parancsfajl", bool(batok), True)

for bat in batok:
    adat = bat.read_bytes()
    maganyos_lf = adat.count(b"\n") - adat.count(b"\r\n")
    check("%s: minden sorveg CRLF" % bat.name, maganyos_lf, 0)
    check("%s: nincs ekezetes karakter" % bat.name,
          [b for b in adat if b > 127], [])
    check("%s: nincs BOM" % bat.name, adat[:3] == b"\xef\xbb\xbf", False)

    szoveg = adat.decode("ascii", "replace")
    # A hivatkozott programfajlok tenyleg letezzenek.
    for nev in ("qbt_gui.py", "qbt_cleanup.py", "requirements.txt"):
        if nev in szoveg:
            check("%s: hivatkozik ra, es megvan (%s)" % (bat.name, nev),
                  (REPO / nev).is_file(), True)
    # Minden goto-nak legyen cimkeje.
    cimkek = {sor.strip().lstrip(":").lower()
              for sor in szoveg.splitlines() if sor.strip().startswith(":")}
    ugrasok = {sor.split("goto", 1)[1].strip().lstrip(":").lower()
               for sor in szoveg.splitlines() if "goto" in sor.lower()
               and not sor.strip().lower().startswith("rem")}
    check("%s: minden ugrasnak van cimkeje" % bat.name,
          sorted(ugrasok - cimkek), [])

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
