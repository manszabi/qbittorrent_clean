#!/usr/bin/env bash
# A teljes tesztkeszlet lefuttatasa. Hasznalat: tests/run_all.sh
#
# Szukseges: python3; a felulet teszteleshez tkinter, fejnelkuli gepen
# xvfb-run (Debian/Ubuntu: sudo apt install python3-tk xvfb).
set -u
cd "$(dirname "$0")"

# A tesztek a futtato kornyezetben dolgoznak: egyik se keszitsen maganak
# .venv-et. (A kornyezet-tesztje ezt maga allitja at, ideiglenes mappaban.)
export QBT_VENV_KIHAGY=1

# A GUI-teszthez tkinter kell. Ha a PYTHON nincs megadva, megkeressuk az elso
# olyan python3-at, amiben van tkinter (tobb gepen ez nem az alapertelmezett).
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for cand in python3 python3.13 python3.12 python3.11 python3.10 python; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import tkinter" >/dev/null 2>&1; then
      PY="$cand"; break
    fi
  done
fi
if [ -z "$PY" ]; then
  echo "Nem talaltam tkinter-es python3-at (Debian/Ubuntu: sudo apt install python3-tk)."
  echo "A motor tesztje tkinter nelkul is fut:  python3 qbt_test.py"
  exit 1
fi
if command -v xvfb-run >/dev/null 2>&1; then GUI="xvfb-run -a $PY"; else GUI="$PY"; fi
echo "python: $($PY -V 2>&1)  ($PY)"

fail=0
run() {  # run <nev> <parancs...>
  printf '%-30s' "$1"
  shift
  if out=$("$@" 2>&1); then echo "OK"; else echo "HIBA"; echo "$out" | tail -25; fail=1; fi
}

run "parancsfajlok (*.bat)"  $PY bat_test.py
run "indito (indit.py)"      $PY indit_test.py
run "sajat kornyezet (.venv)" $PY kornyezet_test.py
run "motor (qbt_cleanup.py)" $PY qbt_test.py
run "torlesi naplo (qbt_naplo.py)" $PY naplo_test.py
run "felulet (qbt_gui.py)"   $GUI gui_test.py
run "windows-specifikus"     $PY windows_test.py
run "terheles es meresek"    $PY terheles_test.py

echo
if [ "$fail" -eq 0 ]; then echo "MINDEN TESZT SIKERES"; else echo "VOLT HIBA"; fi
exit $fail
