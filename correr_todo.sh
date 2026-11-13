#!/usr/bin/env bash
# Corre todo el pipeline FirmaCar desde cero: entorno, datos, auditoría, Excel, PDF, cuadre y pruebas.
# Uso: ./correr_todo.sh            (usa la caché del catálogo EPA si existe)
#      ./correr_todo.sh --refrescar (vuelve a descargar el catálogo EPA)
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "==> Creando entorno virtual .venv"
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

PY=.venv/bin/python
echo "==> 01 Ingesta (catálogo EPA + operación sucia)";  $PY src/01_ingesta_flotilla.py "$@"
echo; echo "==> 02 Auditoría operativa";                  $PY src/02_auditoria_operativa.py
echo; echo "==> 03 Excel";                                $PY src/03_exportar_excel.py
echo; echo "==> 04 PDF de Dirección";                     $PY src/04_reporte_director_pdf.py
echo; echo "==> 05 Cuadre CSV / Excel / PDF";             $PY src/05_verificar_cuadre.py
echo; echo "==> Pruebas";                                  .venv/bin/pytest -q
