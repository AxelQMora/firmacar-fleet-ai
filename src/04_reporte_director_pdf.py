"""04 — Reporte de Dirección en PDF (1-2 páginas).

Todo se calcula desde data/flotilla_auditada_limpia.csv y data/rechazados_auditoria.csv
(salidas de 02); no hay cifras escritas a mano.

Salidas:
  output/rentabilidad_segmento.png   gráfica matplotlib Ingreso vs Costo Total por segmento
  output/reporte_direccion_firmacar.pdf

Librerías: matplotlib (gráfica) + reportlab (PDF).
Uso: .venv/bin/python src/04_reporte_director_pdf.py
"""

from __future__ import annotations

import csv
import datetime as dt
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MultipleLocator  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_RIGHT  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import inch  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

RAIZ = Path(__file__).resolve().parent.parent
LIMPIA_CSV = RAIZ / "data" / "flotilla_auditada_limpia.csv"
RECHAZADOS_CSV = RAIZ / "data" / "rechazados_auditoria.csv"
GRAFICA_PNG = RAIZ / "output" / "rentabilidad_segmento.png"
SALIDA_PDF = RAIZ / "output" / "reporte_direccion_firmacar.pdf"

CENTAVO = Decimal("0.01")
# Mismo mapeo que src/03_exportar_excel.py (Compacto de la fuente = Sedán en reportes).
SEGMENTO_REPORTE = {"Compacto": "Sedán", "Pickup": "Pickup", "Van": "Van"}
ORDEN_SEGMENTOS = ["Sedán", "Pickup", "Van", "SUV"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

# Reglas de recomendación automática (umbrales de negocio).
TALLER_SOBRE_INGRESO_MAX = Decimal("0.40")  # taller > 40 % del ingreso -> auditar factura
DIAS_TALLER_MAX = 5
ODOMETRO_RENOVACION_KM = 150_000
ANTIGUEDAD_RENOVACION = 4  # años

# Paleta validada (dataviz: categórica slot 1 y 2, superficie y tintas).
AZUL, NARANJA = "#2a78d6", "#eb6834"
SUPERFICIE, TINTA, TINTA_2 = "#fcfcfb", "#0b0b0b", "#52514e"
CORP = colors.HexColor("#1F3864")
GRIS_CLARO = colors.HexColor("#F2F2F2")
LINEA = colors.HexColor("#BFBFBF")


def leer_csv(ruta: Path) -> list[dict]:
    with ruta.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sumar(filas: list[dict], col: str) -> Decimal:
    return sum((Decimal(r[col]) for r in filas), Decimal("0.00"))


def mxn(v: Decimal) -> str:
    return f"-${-v:,.2f}" if v < 0 else f"${v:,.2f}"


def pct(parte: Decimal, total: Decimal) -> Decimal:
    return (parte / total * 100).quantize(CENTAVO, ROUND_HALF_UP)


# --------------------------------------------------------------------------- cálculos
def estado_resultados(limpias: list[dict]) -> list[tuple[str, Decimal, str]]:
    """(concepto, monto, tipo) con tipo en {linea, subtotal, total}."""
    renta = sumar(limpias, "renta_mensual_mxn")
    exced = sumar(limpias, "cobro_km_excedente_mxn")
    ingreso = sumar(limpias, "ingreso_bruto_mxn")
    taller = sumar(limpias, "costo_taller_mxn")
    seguro = sumar(limpias, "seguro_mensual_mxn")
    reserva = sumar(limpias, "reserva_depreciacion_mxn")
    utilidad = sumar(limpias, "utilidad_neta_mxn")
    # Controles internos: las piezas deben reconstruir los totales al centavo.
    assert renta + exced == ingreso, "Rentas + excedentes != ingreso bruto"
    assert ingreso - taller - seguro - reserva == utilidad, "Estado de resultados no cuadra"
    return [
        ("Ingreso por Rentas Base", renta, "linea"),
        ("Ingreso por Km Excedentes", exced, "linea"),
        ("Ingreso Bruto Total", ingreso, "subtotal"),
        ("Costos de Taller", -taller, "linea"),
        ("Seguros", -seguro, "linea"),
        ("Reservas de Depreciación", -reserva, "linea"),
        ("Utilidad Operativa Neta", utilidad, "total"),
    ]


def por_segmento(limpias: list[dict]) -> list[dict]:
    salida = []
    for seg in ORDEN_SEGMENTOS:
        sub = [r for r in limpias if SEGMENTO_REPORTE.get(r["segmento"], r["segmento"]) == seg]
        salida.append({
            "segmento": seg, "unidades": len(sub),
            "ingreso": sumar(sub, "ingreso_bruto_mxn"),
            "costo": sumar(sub, "costo_total_mxn"),
            "utilidad": sumar(sub, "utilidad_neta_mxn"),
        })
    return salida


def recomendacion(r: dict, anio_corte: int) -> str:
    ingreso = Decimal(r["ingreso_bruto_mxn"])
    taller = Decimal(r["costo_taller_mxn"])
    anio_modelo = int(r["modelo"][-4:])
    recs = []
    if ingreso > 0 and taller / ingreso > TALLER_SOBRE_INGRESO_MAX:
        recs.append("Auditar factura de taller")
    if int(r["dias_taller"]) > DIAS_TALLER_MAX:
        recs.append("Reducir días en taller / asignar unidad sustituta")
    if int(r["odometro_final_km"]) >= ODOMETRO_RENOVACION_KM or anio_corte - anio_modelo >= ANTIGUEDAD_RENOVACION:
        recs.append("Renovar unidad")
    if Decimal(r["utilidad_neta_mxn"]) < 0 and not recs:
        recs.append("Revisar tarifa de renta del contrato")
    return "; ".join(recs) or "Monitorear"


def top5_alerta(limpias: list[dict]) -> tuple[list[dict], int]:
    """Unidades que pierden dinero o pasan > 5 días en taller.
    Orden: primero las de mayor pérdida (utilidad asc), desempate por más días en taller."""
    candidatas = [r for r in limpias
                  if Decimal(r["utilidad_neta_mxn"]) < 0 or int(r["dias_taller"]) > DIAS_TALLER_MAX]
    candidatas.sort(key=lambda r: (Decimal(r["utilidad_neta_mxn"]), -int(r["dias_taller"]), r["id_unidad"]))
    return candidatas[:5], len(candidatas)


# --------------------------------------------------------------------------- gráfica
def generar_grafica(segmentos: list[dict]) -> None:
    datos = [s for s in segmentos if s["unidades"]]
    etiquetas = [f"{s['segmento']}\n({s['unidades']} unidades)" for s in datos]
    ingreso = [float(s["ingreso"]) for s in datos]
    costo = [float(s["costo"]) for s in datos]

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
    fig, ax = plt.subplots(figsize=(7.2, 3.3), dpi=200)
    fig.patch.set_facecolor(SUPERFICIE)
    ax.set_facecolor(SUPERFICIE)

    x = range(len(datos))
    ancho, hueco = 0.34, 0.02  # hueco = separación visual entre barras adyacentes
    b1 = ax.bar([i - ancho / 2 - hueco / 2 for i in x], ingreso, ancho, color=AZUL, label="Ingreso Bruto", zorder=3)
    b2 = ax.bar([i + ancho / 2 + hueco / 2 for i in x], costo, ancho, color=NARANJA, label="Costo Total", zorder=3)
    for barras in (b1, b2):
        for b in barras:
            ax.annotate(f"${b.get_height() / 1e6:,.2f} M", (b.get_x() + b.get_width() / 2, b.get_height()),
                        xytext=(0, 3), textcoords="offset points", ha="center", va="bottom",
                        fontsize=8, color=TINTA)

    ax.set_xticks(list(x), etiquetas, color=TINTA)
    ax.yaxis.set_major_locator(MultipleLocator(500_000))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v / 1e6:,.1f} M"))
    ax.tick_params(axis="y", colors=TINTA_2, length=0)
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color="#e4e3df", linewidth=0.8, zorder=0)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color("#bdbcb6")
    ax.set_ylabel("MXN", color=TINTA_2)
    ax.set_ylim(0, max(ingreso + costo) * 1.15)
    ax.legend(loc="upper left", frameon=False, ncols=2, labelcolor=TINTA)
    ax.set_title("Ingreso Bruto vs Costo Total por segmento vehicular", loc="left",
                 fontsize=10.5, fontweight="bold", color=TINTA)
    fig.tight_layout()
    GRAFICA_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(GRAFICA_PNG, facecolor=SUPERFICIE)
    plt.close(fig)


# --------------------------------------------------------------------------- PDF
def estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold", fontSize=18,
                                 textColor=colors.white, alignment=0, spaceAfter=0, leading=22),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=9.5, textColor=colors.HexColor("#D9E1F2")),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12,
                             textColor=CORP, spaceBefore=10, spaceAfter=6),
        "normal": ParagraphStyle("n", parent=base["Normal"], fontSize=9, leading=12),
        "celda": ParagraphStyle("c", parent=base["Normal"], fontSize=8.5, leading=10.5),
        "nota": ParagraphStyle("nota", parent=base["Normal"], fontSize=7.5, leading=9.5,
                               textColor=colors.HexColor("#595959")),
        "der": ParagraphStyle("d", parent=base["Normal"], fontSize=9, alignment=TA_RIGHT),
    }


def construir_pdf(limpias, rechazados, estado, segmentos, top5, n_alerta) -> None:
    e = estilos()
    fechas = sorted(r["fecha_corte"] for r in limpias)
    corte = dt.date.fromisoformat(fechas[-1])
    periodo = f"{MESES[corte.month - 1]} {corte.year}"
    n_dup = sum(r["tipo_rechazo"] == "DUPLICADO" for r in rechazados)
    n_crit = sum(r["tipo_rechazo"] == "CRITICO" for r in rechazados)
    n_entradas = len(limpias) + len(rechazados)
    ingreso = next(m for c, m, _ in estado if c == "Ingreso Bruto Total")

    doc = SimpleDocTemplate(str(SALIDA_PDF), pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.6 * inch,
                            title="Reporte de Dirección FirmaCar", author="FirmaCar — Auditoría de Flotilla")
    ancho = letter[0] - 1.2 * inch
    h: list = []

    # ---- banda de título
    banda = Table([[Paragraph("FirmaCar — Reporte de Dirección", e["titulo"])],
                   [Paragraph(f"Rentabilidad de la flotilla en arrendamiento · Periodo {periodo} · Cifras en MXN",
                              e["sub"])]], colWidths=[ancho])
    banda.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CORP),
                               ("LEFTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, 0), 10),
                               ("BOTTOMPADDING", (0, -1), (-1, -1), 10)]))
    h += [banda, Spacer(1, 10)]

    # ---- bloque superior: corte y conteos
    tiles = [("Fecha de corte", corte.isoformat()), ("Unidades procesadas", f"{n_entradas}"),
             ("Unidades limpias", f"{len(limpias)}"),
             ("Rechazadas", f"{len(rechazados)}")]
    fila_val = [Paragraph(f"<font size=16><b>{v}</b></font>", e["normal"]) for _, v in tiles]
    fila_lab = [Paragraph(f"<font color='#595959'>{k}</font>", e["normal"]) for k, _ in tiles]
    t = Table([fila_lab, fila_val], colWidths=[ancho / 4] * 4)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GRIS_CLARO),
                           ("LINEBEFORE", (1, 0), (-1, -1), 2, colors.white),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
    h.append(t)
    h.append(Paragraph(
        f"Cortes del {fechas[0]} al {fechas[-1]}. Verificación: {n_entradas} procesadas = {len(limpias)} limpias + "
        f"{len(rechazados)} rechazadas ({n_crit} con error crítico, {n_dup} duplicados exactos).", e["nota"]))

    # ---- estado de resultados
    h.append(Paragraph("Estado de resultados de la flotilla", e["h2"]))
    filas = [["Concepto", "MXN", "% del Ingreso Bruto"]]
    estilos_t = [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("BACKGROUND", (0, 0), (-1, 0), CORP), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                 ("FONTSIZE", (0, 0), (-1, -1), 9), ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINEA),
                 ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    for i, (concepto, monto, tipo) in enumerate(estado, 1):
        sangria = "    " if tipo == "linea" else ""
        filas.append([sangria + concepto, mxn(monto), f"{pct(monto, ingreso)}%"])
        if tipo in ("subtotal", "total"):
            estilos_t.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
        if tipo == "total":
            estilos_t += [("BACKGROUND", (0, i), (-1, i), colors.HexColor("#E2EFDA")),
                          ("LINEABOVE", (0, i), (-1, i), 1, CORP)]
    t = Table(filas, colWidths=[ancho * 0.5, ancho * 0.28, ancho * 0.22])
    t.setStyle(TableStyle(estilos_t))
    h.append(t)
    h.append(Paragraph("Fórmulas (CLAUDE.md): Ingreso Bruto = Renta Base + Km Excedentes × Tarifa; "
                       "Utilidad Neta = Ingreso Bruto − Taller − Seguro − Reserva (1.20 MXN/km).", e["nota"]))

    # ---- gráfica
    sin_unidades = [s["segmento"] for s in segmentos if not s["unidades"]]
    nota_graf = (f"Segmento sin unidades en la flotilla: {', '.join(sin_unidades)}. " if sin_unidades else "")
    resumen_seg = " · ".join(f"{s['segmento']}: margen {pct(s['utilidad'], s['ingreso'])}%"
                             for s in segmentos if s["unidades"])
    h.append(KeepTogether([
        Paragraph("Rentabilidad por segmento vehicular", e["h2"]),
        Image(str(GRAFICA_PNG), width=ancho, height=ancho * 3.3 / 7.2),
        Paragraph(f"{resumen_seg}. {nota_graf}Costo Total = Taller + Seguro + Reserva de depreciación.", e["nota"]),
    ]))

    # ---- top 5 alerta crítica
    anio_corte = corte.year
    filas = [["Unidad", "Modelo", "Cliente", "Utilidad Neta", "Margen", "Días\ntaller", "Recomendación operativa"]]
    for r in top5:
        filas.append([
            r["id_unidad"], Paragraph(r["modelo"], e["celda"]), Paragraph(r["cliente"], e["celda"]),
            mxn(Decimal(r["utilidad_neta_mxn"])), f"{Decimal(r['margen_operativo_pct'])}%",
            r["dias_taller"], Paragraph(recomendacion(r, anio_corte), e["celda"]),
        ])
    t = Table(filas, colWidths=[ancho * w for w in (0.09, 0.14, 0.17, 0.14, 0.10, 0.10, 0.26)], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), CORP), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (3, 1), (5, -1), "RIGHT"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINEA),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS_CLARO]),
    ]))
    h.append(KeepTogether([
        Paragraph("Top 5 Unidades con Alerta Crítica", e["h2"]),
        Paragraph(f"{n_alerta} unidades pierden dinero o pasan más de {DIAS_TALLER_MAX} días en taller; "
                  "se muestran las 5 con mayor pérdida.", e["normal"]),
        Spacer(1, 4), t,
        Paragraph(f"Reglas: taller &gt; {int(TALLER_SOBRE_INGRESO_MAX * 100)}% del ingreso → Auditar factura de "
                  f"taller; &gt; {DIAS_TALLER_MAX} días en taller → Reducir días / unidad sustituta; odómetro ≥ "
                  f"{ODOMETRO_RENOVACION_KM:,} km o antigüedad ≥ {ANTIGUEDAD_RENOVACION} años → Renovar unidad; "
                  "pérdida sin otra causa → Revisar tarifa de renta.", e["nota"]),
    ]))

    def pie(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#7F7F7F"))
        canvas.drawString(0.6 * inch, 0.35 * inch,
                          "Generado automáticamente desde data/flotilla_auditada_limpia.csv — FirmaCar")
        canvas.drawRightString(letter[0] - 0.6 * inch, 0.35 * inch, f"Página {doc_.page}")
        canvas.restoreState()

    doc.build(h, onFirstPage=pie, onLaterPages=pie)


# --------------------------------------------------------------------------- main
def main() -> int:
    limpias = leer_csv(LIMPIA_CSV)
    rechazados = leer_csv(RECHAZADOS_CSV)
    estado = estado_resultados(limpias)
    segmentos = por_segmento(limpias)
    top5, n_alerta = top5_alerta(limpias)

    generar_grafica(segmentos)
    construir_pdf(limpias, rechazados, estado, segmentos, top5, n_alerta)

    from pypdf import PdfReader  # solo para informar páginas
    paginas = len(PdfReader(SALIDA_PDF).pages)
    print(f"PDF:     {SALIDA_PDF.relative_to(RAIZ)}  ({paginas} página{'s' if paginas > 1 else ''})")
    print(f"Gráfica: {GRAFICA_PNG.relative_to(RAIZ)}")
    for concepto, monto, _ in estado:
        print(f"  {concepto:<28} {mxn(monto):>16}")
    if not 1 <= paginas <= 2:
        print("ERROR: el reporte debe tener 1 a 2 páginas.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
