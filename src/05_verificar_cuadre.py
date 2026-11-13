"""05 — Verifica que CSV limpio, Excel y PDF cuadren al centavo.

Fuentes comparadas:
  CSV   data/flotilla_auditada_limpia.csv + data/rechazados_auditoria.csv (verdad de origen)
  Excel output/control_flotilla_firmacar.xlsx (suma de la hoja Flotilla_Limpia + KPIs del resumen)
  PDF   output/reporte_direccion_firmacar.pdf (texto extraído con pypdf, tal como lo lee una persona)

Sale con código 1 si hay cualquier diferencia.
Uso: .venv/bin/python src/05_verificar_cuadre.py
"""

from __future__ import annotations

import csv
import re
import sys
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from pypdf import PdfReader

RAIZ = Path(__file__).resolve().parent.parent
LIMPIA_CSV = RAIZ / "data" / "flotilla_auditada_limpia.csv"
RECHAZADOS_CSV = RAIZ / "data" / "rechazados_auditoria.csv"
EXCEL = RAIZ / "output" / "control_flotilla_firmacar.xlsx"
PDF = RAIZ / "output" / "reporte_direccion_firmacar.pdf"

CENTAVO = Decimal("0.01")
# concepto -> (columna CSV/Excel, etiqueta en el PDF, signo con que aparece en el PDF, KPI del Resumen Excel)
CONCEPTOS = {
    "Renta base": ("renta_mensual_mxn", "Ingreso por Rentas Base", 1, None),
    "Cobro km excedente": ("cobro_km_excedente_mxn", "Ingreso por Km Excedentes", 1, None),
    "Ingreso bruto": ("ingreso_bruto_mxn", "Ingreso Bruto Total", 1, "Ingreso Bruto Total"),
    "Costo taller": ("costo_taller_mxn", "Costos de Taller", -1, "Costo Total de Taller"),
    "Seguro": ("seguro_mensual_mxn", "Seguros", -1, None),
    "Reserva depreciación": ("reserva_depreciacion_mxn", "Reservas de Depreciación", -1, None),
    "Utilidad neta": ("utilidad_neta_mxn", "Utilidad Operativa Neta", 1, "Utilidad Neta Total"),
}


def dec(v) -> Decimal:
    return Decimal(str(v)).quantize(CENTAVO)


def leer_csv(ruta: Path) -> list[dict]:
    with ruta.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    limpias, rechazados = leer_csv(LIMPIA_CSV), leer_csv(RECHAZADOS_CSV)

    wb = load_workbook(EXCEL, read_only=True)
    filas_xl = list(wb["Flotilla_Limpia"].iter_rows(values_only=True))
    enc_xl, datos_xl = list(filas_xl[0]), filas_xl[1:]
    n_rech_xl = sum(1 for _ in wb["Rechazados_Revision"].iter_rows(min_row=2))
    kpis_xl = {r[0]: r[1] for r in wb["Resumen_Direccion"].iter_rows(min_row=4, max_col=2, values_only=True)
               if r[0] and r[1] is not None}

    texto = "\n".join(p.extract_text() for p in PdfReader(PDF).pages)

    def monto_pdf(etiqueta: str) -> Decimal | None:
        m = re.search(re.escape(etiqueta) + r"\s*\n\s*(-?)\$([\d,]+\.\d{2})", texto)
        return None if not m else Decimal(m.group(1) + m.group(2).replace(",", ""))

    ok = True
    print(f"{'Concepto':<22}{'CSV':>16}{'Excel':>16}{'Excel KPI':>16}{'PDF':>16}  Resultado")
    for nombre, (col, etiqueta, signo, kpi) in CONCEPTOS.items():
        v_csv = sum((Decimal(r[col]) for r in limpias), Decimal("0.00"))
        i = enc_xl.index(col)
        v_xl = sum((dec(r[i]) for r in datos_xl), Decimal("0.00"))
        v_kpi = dec(kpis_xl[kpi]) if kpi else None
        v_pdf = monto_pdf(etiqueta)
        v_pdf = None if v_pdf is None else v_pdf * signo
        valores = [v for v in (v_csv, v_xl, v_kpi, v_pdf) if v is not None]
        cuadra = v_pdf is not None and len(set(valores)) == 1
        ok &= cuadra
        f = lambda v: "—" if v is None else f"{v:,.2f}"  # noqa: E731
        print(f"{nombre:<22}{f(v_csv):>16}{f(v_xl):>16}{f(v_kpi):>16}{f(v_pdf):>16}  "
              f"{'OK' if cuadra else 'DIFERENCIA'}")

    m = re.search(r"(\d+) procesadas = (\d+) limpias \+ (\d+) rechazadas", texto)
    pdf_cnt = tuple(map(int, m.groups())) if m else None
    csv_cnt = (len(limpias) + len(rechazados), len(limpias), len(rechazados))
    xl_cnt = (len(datos_xl) + n_rech_xl, len(datos_xl), n_rech_xl)
    cnt_ok = pdf_cnt == csv_cnt == xl_cnt and kpis_xl.get("Unidades Activas") == len(limpias)
    ok &= cnt_ok
    print(f"\nFilas (entradas, limpias, rechazadas): CSV={csv_cnt} Excel={xl_cnt} PDF={pdf_cnt}  "
          f"{'OK' if cnt_ok else 'DIFERENCIA'}")
    print(f"\nVEREDICTO: {'CUADRA' if ok else 'NO CUADRA'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
