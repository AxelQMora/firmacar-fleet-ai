"""02 — Auditoría operativa de la flotilla FirmaCar.

Lee data/operacion_mensual_sucia.csv y aplica las reglas de CLAUDE.md:
  1. Elimina duplicados exactos (se registran como rechazados con su motivo).
  2. Normaliza clientes, fechas (AAAA-MM-DD) y montos (sin "$" ni comas).
  3. Detecta odómetros capturados en millas y los convierte a km (* 1.60934):
     por heurística o por data/correcciones_manuales.csv (casos confirmados).
  4. Aparta filas con errores críticos en data/rechazados_auditoria.csv.
  5. Calcula métricas financieras -> data/flotilla_auditada_limpia.csv.

Regla estricta: entradas = limpias + rechazadas; si no cuadra, no se escribe nada.
Aritmética monetaria con Decimal, redondeo a centavos (ROUND_HALF_UP).

Uso: python src/02_auditoria_operativa.py
"""

from __future__ import annotations

import csv
import datetime as dt
import re
import sys
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "data" / "operacion_mensual_sucia.csv"
SALIDA_LIMPIA = RAIZ / "data" / "flotilla_auditada_limpia.csv"
SALIDA_RECHAZADOS = RAIZ / "data" / "rechazados_auditoria.csv"
# Correcciones confirmadas por Operaciones para casos que la heurística no detecta.
CORRECCIONES_CSV = RAIZ / "data" / "correcciones_manuales.csv"
CORRECCIONES_VALIDAS = {"odometro_en_millas"}

KM_POR_MILLA = Decimal("1.60934")
RESERVA_POR_KM = Decimal("1.20")
CENTAVO = Decimal("0.01")
UMBRAL_MARGEN_PCT = Decimal("12")
UMBRAL_DIAS_TALLER = 5

# Heurística de millas (no hay bandera en la fuente). Una unidad comercial en
# arrendamiento recorre >= 25,000 km/año y un mínimo mensual por segmento.
# Un odómetro por debajo de cualquiera de los dos umbrales se interpreta como millas.
KM_ANUAL_MIN = Decimal("25000")
KM_MES_MIN_SEGMENTO = {"Compacto": 1_500, "Pickup": 2_000, "Van": 2_500}

MONTOS = ["renta_mensual_mxn", "tarifa_km_extra_mxn", "costo_taller_mxn", "seguro_mensual_mxn"]
ENTEROS = ["odometro_inicial_km", "odometro_final_km", "km_contrato", "dias_taller"]
MESES_ES = {m: i for i, m in enumerate(
    ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"], 1)}
PARTICULAS_SIEMPRE = {"de", "del", "y", "e"}   # siempre en minúscula (salvo al inicio)
ARTICULOS = {"la", "las", "los", "el"}          # minúscula solo tras "de" (Alimentos La Huerta)
SIGLAS = {"mx", "sa", "cv"}

COLUMNAS_LIMPIAS = [
    "id_unidad", "cliente", "modelo", "segmento", "fecha_corte",
    "odometro_inicial_km", "odometro_final_km", "unidad_odometro_corregida",
    "metodo_correccion_odometro", "km_contrato",
    "renta_mensual_mxn", "tarifa_km_extra_mxn", "costo_taller_mxn", "dias_taller",
    "seguro_mensual_mxn", "estatus_pago",
    "km_recorridos", "km_excedentes", "cobro_km_excedente_mxn", "ingreso_bruto_mxn",
    "reserva_depreciacion_mxn", "costo_total_mxn", "utilidad_neta_mxn",
    "margen_operativo_pct", "bandera_alerta",
]


class ErrorFila(Exception):
    pass


# --------------------------------------------------------------------------- normalización
def normalizar_cliente(valor: str) -> str:
    palabras = valor.strip().lower().split()
    salida = []
    for i, p in enumerate(palabras):
        if p in SIGLAS:
            salida.append(p.upper())
        elif i > 0 and (p in PARTICULAS_SIEMPRE or (p in ARTICULOS and palabras[i - 1] == "de")):
            salida.append(p)
        else:
            salida.append(p[:1].upper() + p[1:])
    return " ".join(salida)


def normalizar_fecha(valor: str) -> str:
    v = valor.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})-([a-zA-Z]{3})-(\d{4})", v)
    if m and m.group(2).lower() in MESES_ES:
        try:
            return dt.date(int(m.group(3)), MESES_ES[m.group(2).lower()], int(m.group(1))).isoformat()
        except ValueError:
            pass
    raise ErrorFila(f"fecha_corte con formato no reconocido: '{valor}'")


def parsear_monto(campo: str, valor: str) -> Decimal:
    limpio = valor.strip().replace("$", "").replace(",", "")
    try:
        d = Decimal(limpio)
    except InvalidOperation:
        d = None
    if d is None or not d.is_finite():
        raise ErrorFila(f"{campo} no numérico: '{valor.strip()}'")
    return d.quantize(CENTAVO, ROUND_HALF_UP)


def parsear_entero(campo: str, valor: str) -> int:
    try:
        return int(valor.strip())
    except ValueError:
        raise ErrorFila(f"{campo} no es entero: '{valor.strip()}'") from None


def parece_millas(odo_ini: int, odo_fin: int, anio_modelo: int, anio_corte: int, segmento: str) -> bool:
    antiguedad = max(anio_corte - anio_modelo, 1)
    km_anual = Decimal(odo_ini) / antiguedad
    minimo_mes = KM_MES_MIN_SEGMENTO.get(segmento, 0)
    return km_anual < KM_ANUAL_MIN or (odo_fin - odo_ini) < minimo_mes


def millas_a_km(valor: int) -> int:
    return int((Decimal(valor) * KM_POR_MILLA).quantize(Decimal("1"), ROUND_HALF_UP))


# --------------------------------------------------------------------------- auditoría por fila
def auditar_fila(r: dict, correcciones: dict[str, str]) -> dict:
    """Devuelve la fila limpia con métricas o lanza ErrorFila con todos los motivos."""
    motivos: list[str] = []
    out: dict = {"id_unidad": r["id_unidad"].strip()}

    def intentar(fn, *args):
        try:
            return fn(*args)
        except ErrorFila as e:
            motivos.append(str(e))
            return None

    out["cliente"] = normalizar_cliente(r["cliente"])
    out["modelo"] = " ".join(r["modelo"].split())
    out["segmento"] = r["segmento"].strip()
    out["estatus_pago"] = r["estatus_pago"].strip().upper()
    out["fecha_corte"] = intentar(normalizar_fecha, r["fecha_corte"])

    for c in ENTEROS:
        out[c] = intentar(parsear_entero, c, r[c])
    for c in MONTOS:
        out[c] = intentar(parsear_monto, c, r[c])

    oi, of = out["odometro_inicial_km"], out["odometro_final_km"]
    if oi is not None and of is not None and of < oi:
        motivos.append(f"odometro_final_km ({of}) menor que odometro_inicial_km ({oi})")
    if out["renta_mensual_mxn"] is not None and out["renta_mensual_mxn"] <= 0:
        motivos.append(f"renta_mensual_mxn <= 0: {out['renta_mensual_mxn']}")
    for c in ("tarifa_km_extra_mxn", "costo_taller_mxn", "seguro_mensual_mxn"):
        if out[c] is not None and out[c] < 0:
            motivos.append(f"{c} negativo: {out[c]}")
    for c in ("km_contrato", "dias_taller"):
        if out[c] is not None and out[c] < 0:
            motivos.append(f"{c} negativo: {out[c]}")
    m_anio = re.search(r"(\d{4})$", out["modelo"])
    if not m_anio:
        motivos.append(f"modelo sin año identificable: '{out['modelo']}'")

    if motivos:
        raise ErrorFila(" | ".join(motivos))

    # ---- corrección de millas
    anio_corte = int(out["fecha_corte"][:4])
    if correcciones.get(out["id_unidad"]) == "odometro_en_millas":
        metodo = "manual"
    elif parece_millas(oi, of, int(m_anio.group(1)), anio_corte, out["segmento"]):
        metodo = "heuristica"
    else:
        metodo = ""
    corregida = bool(metodo)
    out["metodo_correccion_odometro"] = metodo
    if corregida:
        oi, of = millas_a_km(oi), millas_a_km(of)
        out["odometro_inicial_km"], out["odometro_final_km"] = oi, of
    out["unidad_odometro_corregida"] = int(corregida)

    # ---- métricas (fórmulas de CLAUDE.md)
    km_rec = of - oi
    km_exc = max(0, km_rec - out["km_contrato"])
    cobro_exc = (km_exc * out["tarifa_km_extra_mxn"]).quantize(CENTAVO, ROUND_HALF_UP)
    ingreso = out["renta_mensual_mxn"] + cobro_exc
    reserva = (km_rec * RESERVA_POR_KM).quantize(CENTAVO, ROUND_HALF_UP)
    costo_total = out["costo_taller_mxn"] + out["seguro_mensual_mxn"] + reserva
    utilidad = ingreso - out["costo_taller_mxn"] - out["seguro_mensual_mxn"] - reserva
    if ingreso == 0:
        raise ErrorFila("ingreso_bruto_mxn = 0: margen no calculable")
    margen = (utilidad / ingreso * 100).quantize(CENTAVO, ROUND_HALF_UP)

    if utilidad < 0:
        bandera = "CRITICA_PERDIDA"
    elif margen < UMBRAL_MARGEN_PCT or out["dias_taller"] > UMBRAL_DIAS_TALLER:
        bandera = "ALERTA_TALLER"
    else:
        bandera = "RENTABLE"

    out.update({
        "km_recorridos": km_rec,
        "km_excedentes": km_exc,
        "cobro_km_excedente_mxn": cobro_exc,
        "ingreso_bruto_mxn": ingreso,
        "reserva_depreciacion_mxn": reserva,
        "costo_total_mxn": costo_total,
        "utilidad_neta_mxn": utilidad,
        "margen_operativo_pct": margen,
        "bandera_alerta": bandera,
    })
    return out


# --------------------------------------------------------------------------- main
def cargar_correcciones() -> dict[str, str]:
    if not CORRECCIONES_CSV.exists():
        return {}
    with CORRECCIONES_CSV.open(newline="", encoding="utf-8") as f:
        corr = {r["id_unidad"].strip(): r["correccion"].strip() for r in csv.DictReader(f)}
    invalidas = {k: v for k, v in corr.items() if v not in CORRECCIONES_VALIDAS}
    if invalidas:
        raise SystemExit(f"ERROR: correcciones no soportadas en {CORRECCIONES_CSV.name}: {invalidas}")
    return corr


def main() -> int:
    with ENTRADA.open(newline="", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        columnas_origen = list(lector.fieldnames or [])
        filas = list(lector)
    n_entradas = len(filas)
    correcciones = cargar_correcciones()

    limpias: list[dict] = []
    rechazados: list[dict] = []
    vistos: dict[tuple, int] = {}
    n_duplicados = n_criticos = 0

    for i, r in enumerate(filas):
        linea = i + 2  # línea en el CSV (1 = encabezado)
        clave = tuple(r[c] for c in columnas_origen)
        base = {"linea_origen": linea, **r}
        if clave in vistos:
            n_duplicados += 1
            rechazados.append({**base, "tipo_rechazo": "DUPLICADO",
                               "motivo_rechazo": f"DUPLICADO_EXACTO: copia idéntica de la línea {vistos[clave]}"})
            continue
        vistos[clave] = linea
        try:
            limpias.append(auditar_fila(r, correcciones))
        except ErrorFila as e:
            n_criticos += 1
            rechazados.append({**base, "tipo_rechazo": "CRITICO", "motivo_rechazo": str(e)})

    # ---- cuadre estricto antes de escribir
    n_limpias, n_rech = len(limpias), len(rechazados)
    print("=== Cuadre de filas ===")
    print(f"Entradas:                    {n_entradas}")
    print(f"  Duplicados exactos:        {n_duplicados}")
    print(f"  Rechazos críticos:         {n_criticos}")
    print(f"  Rechazadas (total):        {n_rech}")
    print(f"  Limpias:                   {n_limpias}")
    cuadra = n_entradas == n_limpias + n_rech
    print(f"Verificación {n_entradas} = {n_limpias} + {n_rech}: {'OK' if cuadra else 'FALLA'}")
    if not cuadra:
        print("ERROR: el cuadre no cumple la regla de CLAUDE.md; no se generan archivos.", file=sys.stderr)
        return 1

    with SALIDA_LIMPIA.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_LIMPIAS, lineterminator="\n")
        w.writeheader()
        w.writerows(limpias)
    with SALIDA_RECHAZADOS.open("w", newline="", encoding="utf-8") as f:
        cols = ["linea_origen", *columnas_origen, "tipo_rechazo", "motivo_rechazo"]
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rechazados)

    # ---- totales
    def suma(c: str) -> Decimal:
        return sum((x[c] for x in limpias), Decimal("0.00"))

    print("\n=== Totales flotilla limpia (MXN) ===")
    for c in ("renta_mensual_mxn", "cobro_km_excedente_mxn", "ingreso_bruto_mxn",
              "costo_taller_mxn", "seguro_mensual_mxn", "reserva_depreciacion_mxn",
              "costo_total_mxn", "utilidad_neta_mxn"):
        print(f"  {c:<26} {suma(c):>16,.2f}")
    ingreso_total, utilidad_total = suma("ingreso_bruto_mxn"), suma("utilidad_neta_mxn")
    print(f"  Margen global              {utilidad_total / ingreso_total * 100:>15.2f}%")

    print("\n=== Detalle ===")
    print(f"  Odómetros corregidos de millas a km: {sum(x['unidad_odometro_corregida'] for x in limpias)}"
          f"  (heurística={sum(x['metodo_correccion_odometro'] == 'heuristica' for x in limpias)}, "
          f"manual={sum(x['metodo_correccion_odometro'] == 'manual' for x in limpias)})")
    for b in ("RENTABLE", "ALERTA_TALLER", "CRITICA_PERDIDA"):
        print(f"  {b:<16} {sum(x['bandera_alerta'] == b for x in limpias)}")
    print(f"\nArchivos: {SALIDA_LIMPIA.relative_to(RAIZ)}, {SALIDA_RECHAZADOS.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
