#!/bin/zsh
# Gate de paridad R6 (antes/después). Uso:
#   BASE_TREE=<árbol base, p.ej. `git archive <commit> | tar -x -C DIR`> AFTER_TREE=<árbol a validar> PY=<python> OUT=<dir de salidas> ./run_gate.sh [casos...]
# Casos por defecto: BK68 BK46 SJ87 SJ97. Cada caso corre en 2 procesos (base y después) en paralelo; sin envoltorios de CPU extra más allá de --dfs.
# BK35/BK46 requieren R6_PILOT_XLSX (archivo confidencial local; NO se versiona). SJ87/SJ97/BK68/BK43 usan Cubicaje18.07.2026.xlsx del repo.
HERE="${0:A:h}"; OUT="${OUT:?}"; PY="${PY:-python}"; BASE_TREE="${BASE_TREE:?}"; AFTER_TREE="${AFTER_TREE:?}"
CASOS=(${@:-BK68 BK46 SJ87 SJ97}); mkdir -p "$OUT"
for c in $CASOS; do
  for t in before:$BASE_TREE after:$AFTER_TREE; do
    R6_ROOT="${t#*:}" "$PY" "$HERE/harness.py" --case $c --tag w_${t%%:*} --out "$OUT" --dfs 2>&1 | tail -1 | cut -c1-220 &
  done
done
wait
"$PY" "$HERE/compare_parity.py" "$OUT" w_before w_after $CASOS
