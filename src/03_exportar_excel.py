"""03 — Exporta el control de flotilla a Excel.

Entrada:  data/flotilla_auditada_limpia.csv, data/rechazados_auditoria.csv (salidas de 02)
Salida:   output/control_flotilla_firmacar.xlsx con 3 hojas:
  1. Resumen_Direccion   KPIs globales + tabla por segmento (Sedán, Pickup, Van, SUV)
  2. Flotilla_Limpia     unidades válidas, de menor a mayor utilidad_neta_mxn
  3. Rechazados_Revision filas apartadas con motivo_rechazo y área responsable

Los totales se calculan con Decimal y se escriben como valores (no fórmulas) para que
el CSV, el Excel y el PDF cuadren al centavo. Al final se relee el archivo y se verifica.

Uso: .venv/bin/python src/03_exportar_excel.py
"""

from __future__ import annotations

import csv
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

RAIZ = Path(__file__).resolve().parent.parent
LIMPIA_CSV = RAIZ / "data" / "flotilla_auditada_limpia.csv"
RECHAZADOS_CSV = RAIZ / "data" / "rechazados_auditoria.csv"
SALIDA = RAIZ / "output" / "control_flotilla_firmacar.xlsx"

CENTAVO = Decimal("0.01")
FMT_MXN = '"$"#,##0.00'
FMT_PCT = '0.00"%"'
FMT_INT = "#,##0"

# Segmento de la fuente -> segmento de reporte. SUV no existe hoy en la flotilla.
SEGMENTO_REPORTE = {"Compacto": "Sedán", "Pickup": "Pickup", "Van": "Van"}
ORDEN_SEGMENTOS = ["Sedán", "Pickup", "Van", "SUV"]

ENTEROS = {"odometro_inicial_km", "odometro_final_km", "unidad_odometro_corregida", "km_contrato",
           "dias_taller", "km_recorridos", "km_excedentes", "linea_origen"}

AZUL = PatternFill("solid", fgColor="1F3864")
GRIS = PatternFill("solid", fgColor="F2F2F2")
VERDE = PatternFill("solid", fgColor="E2EFDA")
ROJO = PatternFill("solid", fgColor="FCE4D6")
AMARILLO = PatternFill("solid", fgColor="FFF2CC")
BLANCO_NEGRITA = Font(bold=True, color="FFFFFF")
NEGRITA = Font(bold=True)
BORDE = Border(bottom=Side(style="thin", color="BFBFBF"))


def leer_csv(ruta: Path) -> tuple[list[str], list[dict]]:
    with ruta.open(newline="", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        return list(lector.fieldnames or []), list(lector)


def d(valor: str) -> Decimal:
    return Decimal(valor)


def q(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, ROUND_HALF_UP)


def area_responsable(motivo: str) -> str:
    areas = []
    if "DUPLICADO" in motivo:
        areas.append("Captura")
    if "odometro" in motivo:
        areas.append("Operaciones")
    if "renta_mensual" in motivo or "tarifa" in motivo or "seguro" in motivo:
        areas.append("Facturación")
    if "costo_taller" in motivo or "dias_taller" in motivo:
        areas.append("Taller / Facturación")
    return ", ".join(dict.fromkeys(areas)) or "Operaciones"


# --------------------------------------------------------------------------- estilos
def encabezado(ws, fila: int, columnas: list[str]) -> None:
    for j, nombre in enumerate(columnas, 1):
        c = ws.cell(row=fila, column=j, value=nombre)
        c.font, c.fill = BLANCO_NEGRITA, AZUL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[fila].height = 32


def formato_columna(nombre: str) -> str | None:
    if nombre.endswith("_mxn"):
        return FMT_MXN
    if nombre.endswith("_pct"):
        return FMT_PCT
    if nombre in ENTEROS:
        return FMT_INT
    return None


def ajustar_anchos(ws, minimo: int = 10, maximo: int = 60) -> None:
    for col in ws.columns:
        largo = max((len(str(c.value)) for c in col if c.value is not None), default=0)
        ws.column_dimensions[get_column_letter(col[0].column)].width = max(minimo, min(maximo, largo + 3))


# --------------------------------------------------------------------------- hojas
def hoja_resumen(ws, limpias: list[dict]) -> None:
    ingreso = sum((d(r["ingreso_bruto_mxn"]) for r in limpias), Decimal(0))
    taller = sum((d(r["costo_taller_mxn"]) for r in limpias), Decimal(0))
    utilidad = sum((d(r["utilidad_neta_mxn"]) for r in limpias), Decimal(0))
    margen_prom = q(sum((d(r["margen_operativo_pct"]) for r in limpias), Decimal(0)) / len(limpias))
    margen_global = q(utilidad / ingreso * 100)

    ws["A1"] = "FirmaCar — Control de Flotilla (cifras en MXN)"
    ws["A1"].font = Font(bold=True, size=14, color="1F3864")

    encabezado(ws, 3, ["KPI", "Valor"])
    kpis = [
        ("Unidades Activas", len(limpias), FMT_INT),
        ("Ingreso Bruto Total", ingreso, FMT_MXN),
        ("Costo Total de Taller", taller, FMT_MXN),
        ("Utilidad Neta Total", utilidad, FMT_MXN),
        ("Margen Promedio % (promedio simple por unidad)", margen_prom, FMT_PCT),
        ("Margen Global % (Utilidad Total / Ingreso Total)", margen_global, FMT_PCT),
    ]
    for i, (nombre, valor, fmt) in enumerate(kpis, 4):
        ws.cell(row=i, column=1, value=nombre).font = NEGRITA
        c = ws.cell(row=i, column=2, value=float(valor) if isinstance(valor, Decimal) else valor)
        c.number_format = fmt
        for col in (1, 2):
            ws.cell(row=i, column=col).border = BORDE

    # ---- tabla por segmento
    fila0 = 4 + len(kpis) + 2
    ws.cell(row=fila0 - 1, column=1, value="Rentabilidad por segmento vehicular").font = Font(bold=True, size=12)
    cols = ["Segmento", "Unidades", "Ingreso Bruto", "Costo Taller", "Utilidad Neta",
            "Utilidad Neta por Unidad", "Margen Promedio %", "Margen Global %", "Ranking (utilidad/unidad)"]
    encabezado(ws, fila0, cols)

    filas_seg = []
    for seg in ORDEN_SEGMENTOS:
        sub = [r for r in limpias if SEGMENTO_REPORTE.get(r["segmento"], r["segmento"]) == seg]
        if not sub:
            filas_seg.append({"seg": seg, "n": 0})
            continue
        ing = sum((d(r["ingreso_bruto_mxn"]) for r in sub), Decimal(0))
        util = sum((d(r["utilidad_neta_mxn"]) for r in sub), Decimal(0))
        filas_seg.append({
            "seg": seg, "n": len(sub), "ing": ing,
            "taller": sum((d(r["costo_taller_mxn"]) for r in sub), Decimal(0)),
            "util": util, "util_u": q(util / len(sub)),
            "m_prom": q(sum((d(r["margen_operativo_pct"]) for r in sub), Decimal(0)) / len(sub)),
            "m_glob": q(util / ing * 100),
        })
    con_datos = sorted((s for s in filas_seg if s["n"]), key=lambda s: s["util_u"], reverse=True)
    for rank, s in enumerate(con_datos, 1):
        s["rank"] = rank

    for i, s in enumerate(filas_seg, fila0 + 1):
        ws.cell(row=i, column=1, value=s["seg"]).font = NEGRITA
        if not s["n"]:
            ws.cell(row=i, column=2, value=0).number_format = FMT_INT
            ws.cell(row=i, column=3, value="Sin unidades en la flotilla")
            for col in range(1, len(cols) + 1):
                ws.cell(row=i, column=col).fill = GRIS
            continue
        valores = [s["n"], s["ing"], s["taller"], s["util"], s["util_u"], s["m_prom"], s["m_glob"], s["rank"]]
        formatos = [FMT_INT, FMT_MXN, FMT_MXN, FMT_MXN, FMT_MXN, FMT_PCT, FMT_PCT, FMT_INT]
        for j, (v, fmt) in enumerate(zip(valores, formatos), 2):
            c = ws.cell(row=i, column=j, value=float(v) if isinstance(v, Decimal) else v)
            c.number_format = fmt
        if s["rank"] == 1:
            for col in range(1, len(cols) + 1):
                ws.cell(row=i, column=col).fill = VERDE

    mejor = con_datos[0]
    nota = fila0 + len(filas_seg) + 2
    ws.cell(row=nota, column=1,
            value=f"Segmento con mayor utilidad neta por unidad: {mejor['seg']} "
                  f"(${mejor['util_u']:,.2f} MXN por unidad, margen global {mejor['m_glob']}%).").font = NEGRITA
    ws.cell(row=nota + 1, column=1,
            value="Sedán = segmento 'Compacto' de la fuente (Nissan Versa, KIA Rio). "
                  "SUV: sin unidades en la flotilla actual.").font = Font(italic=True, color="7F7F7F")

    ws.column_dimensions["A"].width = 48
    for col in "BCDEFGHI":
        ws.column_dimensions[col].width = 18
    ws.freeze_panes = "A4"


def hoja_tabla(ws, columnas: list[str], filas: list[dict], colorear_bandera: bool = False,
               texto_crudo: bool = False) -> None:
    """texto_crudo=True deja los valores tal cual vienen de la fuente (salvo linea_origen)."""
    encabezado(ws, 1, columnas)
    formatos = [FMT_INT if c == "linea_origen" else (None if texto_crudo else formato_columna(c))
                for c in columnas]
    for i, r in enumerate(filas, 2):
        for j, (col, fmt) in enumerate(zip(columnas, formatos), 1):
            v = r.get(col, "")
            if fmt and v not in ("", None):
                v = int(v) if fmt == FMT_INT else float(Decimal(v))
            c = ws.cell(row=i, column=j, value=v)
            if fmt:
                c.number_format = fmt
        if colorear_bandera:
            relleno = {"CRITICA_PERDIDA": ROJO, "ALERTA_TALLER": AMARILLO}.get(r.get("bandera_alerta"))
            if relleno:
                for j in range(1, len(columnas) + 1):
                    ws.cell(row=i, column=j).fill = relleno
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columnas))}{len(filas) + 1}"
    ajustar_anchos(ws)


# --------------------------------------------------------------------------- main
def main() -> int:
    cols_limpias, limpias = leer_csv(LIMPIA_CSV)
    cols_rech, rechazados = leer_csv(RECHAZADOS_CSV)

    limpias_orden = sorted(limpias, key=lambda r: (d(r["utilidad_neta_mxn"]), r["id_unidad"]))

    # Rechazados: motivo y responsable al frente; los montos se dejan como texto original
    # (son los valores sin corregir que Operaciones debe revisar).
    for r in rechazados:
        r["area_responsable"] = area_responsable(r["motivo_rechazo"])
    cols_rev = ["linea_origen", "id_unidad", "tipo_rechazo", "motivo_rechazo", "area_responsable"] + [
        c for c in cols_rech if c not in ("linea_origen", "id_unidad", "tipo_rechazo", "motivo_rechazo")]
    rechazados.sort(key=lambda r: (r["tipo_rechazo"] != "CRITICO", int(r["linea_origen"])))

    wb = Workbook()
    hoja_resumen(wb.active, limpias)
    wb.active.title = "Resumen_Direccion"
    hoja_tabla(wb.create_sheet("Flotilla_Limpia"), cols_limpias, limpias_orden, colorear_bandera=True)
    ws_r = wb.create_sheet("Rechazados_Revision")
    hoja_tabla(ws_r, cols_rev, rechazados, texto_crudo=True)
    for c in ws_r[1]:
        if c.column > 5:
            ws_r.column_dimensions[c.column_letter].width = 18
    ws_r.column_dimensions["D"].width = 70

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    wb.save(SALIDA)

    # ---- verificación releyendo el archivo
    wb2 = load_workbook(SALIDA)
    ws_l = wb2["Flotilla_Limpia"]
    idx_u = [c.value for c in ws_l[1]].index("utilidad_neta_mxn") + 1
    util_excel = sum(q(Decimal(str(ws_l.cell(row=i, column=idx_u).value))) for i in range(2, ws_l.max_row + 1))
    util_csv = sum((d(r["utilidad_neta_mxn"]) for r in limpias), Decimal(0))
    kpi_util = q(Decimal(str(wb2["Resumen_Direccion"]["B7"].value)))  # fila 7 = Utilidad Neta Total

    print(f"Archivo: {SALIDA.relative_to(RAIZ)}")
    print("Filas de datos por hoja (sin encabezado):")
    print(f"  Resumen_Direccion:   6 KPIs + {len(ORDEN_SEGMENTOS)} segmentos")
    print(f"  Flotilla_Limpia:     {ws_l.max_row - 1}")
    print(f"  Rechazados_Revision: {wb2['Rechazados_Revision'].max_row - 1}")
    print("\nCuadre utilidad_neta_mxn (MXN):")
    print(f"  CSV limpio:               {util_csv:>16,.2f}")
    print(f"  Excel Flotilla_Limpia:    {util_excel:>16,.2f}")
    print(f"  Excel KPI Resumen:        {kpi_util:>16,.2f}")
    ok = util_csv == util_excel == kpi_util
    filas_ok = ws_l.max_row - 1 == len(limpias) and wb2["Rechazados_Revision"].max_row - 1 == len(rechazados)
    print(f"  Diferencia: {util_csv - util_excel:.2f}  ->  {'CUADRA' if ok and filas_ok else 'NO CUADRA'}")
    return 0 if ok and filas_ok else 1


if __name__ == "__main__":
    sys.exit(main())
