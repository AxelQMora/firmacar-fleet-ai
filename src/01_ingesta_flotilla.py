"""01 — Ingesta de flotilla FirmaCar (100 % reproducible, semilla 42).

Paso 1. Descarga el catálogo oficial de EPA FuelEconomy.gov, lo guarda en
        data/raw/vehicles.csv.zip (caché) y extrae los modelos de flotilla
        2021-2025 -> data/catalogo_epa_vehiculos.csv (rendimiento en km/L).
Paso 2. Con ese catálogo genera data/operacion_mensual_sucia.csv
        (240 registros del mes de corte, deliberadamente sucios).

Reproducibilidad:
- Toda la aleatoriedad sale de random.Random(42).
- EPA actualiza su archivo; por eso se usa la copia en caché si existe.
  Usa --refrescar para volver a descargarlo. El SHA-256 se imprime siempre.

Suciedad inyectada (sobre 230 registros únicos + 10 duplicados = 240):
- clientes con espacios y mayúsculas mezcladas
- fecha_corte en 3 formatos: AAAA-MM-DD, DD/MM/AAAA, DD-mmm-AAAA (español)
- montos con "$" y comas, p. ej. "$14,500.00"
- 12 filas con odómetros capturados en millas
- 10 filas duplicadas exactas
- 18 filas con errores críticos irrecuperables (6 de cada tipo):
  odómetro final < inicial, renta negativa, costo_taller "PENDIENTE_FACTURA"

data/_control_inyeccion.csv es la clave de respuestas para validar la limpieza.
El pipeline de limpieza NO debe leerlo; solo sirve para auditar.

Uso: python src/01_ingesta_flotilla.py [--refrescar]
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import random
import sys
import urllib.request
import zipfile
from pathlib import Path

SEMILLA = 42
RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
RAW_ZIP = DATA / "raw" / "vehicles.csv.zip"
CATALOGO_CSV = DATA / "catalogo_epa_vehiculos.csv"
OPERACION_CSV = DATA / "operacion_mensual_sucia.csv"
CONTROL_CSV = DATA / "_control_inyeccion.csv"

EPA_URL = "https://www.fueleconomy.gov/feg/epadata/vehicles.csv.zip"
MPG_A_KM_L = 1.609344 / 3.785411784  # 0.425144
KM_POR_MILLA = 1.609344
ANIOS = range(2021, 2026)
MES_CORTE = (2026, 10)  # octubre 2026

N_UNICOS = 230
N_DUPLICADOS = 10
N_MILLAS = 12
N_CRITICOS = 18  # 6 + 6 + 6

# (marca EPA, prefijo de modelo EPA, modelo de referencia MX, tipo de coincidencia, segmento)
MODELOS_FLOTILLA = [
    ("Nissan", "Versa", "Nissan Versa", "exacto", "Compacto"),
    ("Kia", "Rio", "KIA Rio", "exacto", "Compacto"),
    ("Ford", "Transit T150 Wagon", "Ford Transit", "exacto", "Van"),
    ("Nissan", "Frontier", "Nissan NP300", "proxy_epa", "Pickup"),
    ("Toyota", "Tacoma", "Toyota Hilux", "proxy_epa", "Pickup"),
]
# Variantes que no representan una unidad de flotilla típica.
EXCLUIR_SI_CONTIENE = ("PRO4X", "TRD", "Hybrid")
SIN_DATOS_EPA = ["Chevrolet Aveo", "VW Virtus", "Renault Kangoo"]

# Parámetros operativos por segmento (MXN y km).
PARAMS = {
    "Compacto": dict(renta=(9_500, 14_500), tarifa=(2.5, 4.0), seguro=(1_800, 2_800),
                     km_contrato=(2_000, 2_500, 3_000), km_mes=(1_500, 4_500)),
    "Pickup": dict(renta=(16_000, 24_000), tarifa=(3.5, 5.5), seguro=(2_800, 4_200),
                   km_contrato=(3_000, 4_000, 5_000), km_mes=(2_000, 6_000)),
    "Van": dict(renta=(22_000, 32_000), tarifa=(4.5, 6.5), seguro=(3_500, 5_500),
                km_contrato=(4_000, 5_000, 6_000), km_mes=(2_500, 7_000)),
}

CLIENTES = [
    "Logística del Bajío", "Distribuidora Norteña", "Farmacias Santa Clara",
    "Grupo Constructor Atlas", "Mensajería Express MX", "Alimentos La Huerta",
    "Servicios Médicos Integra", "Telecom Pacífico", "Agroinsumos del Valle",
    "Seguridad Privada Centinela", "Paquetería Rápida Sur", "Inmobiliaria Torres",
]
MESES_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

COLUMNAS = [
    "id_unidad", "cliente", "modelo", "segmento", "fecha_corte",
    "odometro_inicial_km", "odometro_final_km", "km_contrato", "renta_mensual_mxn",
    "tarifa_km_extra_mxn", "costo_taller_mxn", "dias_taller", "seguro_mensual_mxn",
    "estatus_pago",
]


# --------------------------------------------------------------------------- paso 1
def obtener_zip_epa(refrescar: bool) -> bytes:
    if refrescar or not RAW_ZIP.exists():
        print(f"Descargando {EPA_URL} ...")
        with urllib.request.urlopen(EPA_URL, timeout=60) as resp:
            contenido = resp.read()
        RAW_ZIP.parent.mkdir(parents=True, exist_ok=True)
        RAW_ZIP.write_bytes(contenido)
    else:
        print(f"Usando caché local {RAW_ZIP.relative_to(RAIZ)}")
    contenido = RAW_ZIP.read_bytes()
    print(f"SHA-256 catálogo EPA: {hashlib.sha256(contenido).hexdigest()}")
    return contenido


def construir_catalogo(zip_bytes: bytes) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        with zf.open("vehicles.csv") as f:
            lector = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
            filas = []
            for r in lector:
                anio = int(r["year"])
                if anio not in ANIOS:
                    continue
                if any(x in r["model"] for x in EXCLUIR_SI_CONTIENE):
                    continue
                for marca, prefijo, modelo_mx, tipo, segmento in MODELOS_FLOTILLA:
                    if r["make"] == marca and r["model"].startswith(prefijo):
                        mpg_c, mpg_ciu, mpg_car = (float(r[k]) for k in ("comb08", "city08", "highway08"))
                        filas.append({
                            "epa_id": int(r["id"]),
                            "anio": anio,
                            "marca": marca,
                            "modelo_epa": r["model"],
                            "modelo_mx_referencia": modelo_mx,
                            "tipo_coincidencia": tipo,
                            "segmento": segmento,
                            "clase_epa": r["VClass"],
                            "combustible": r["fuelType"],
                            "transmision": r["trany"],
                            "cilindrada_l": r["displ"],
                            "mpg_combinado": mpg_c,
                            "rend_ciudad_km_l": round(mpg_ciu * MPG_A_KM_L, 2),
                            "rend_carretera_km_l": round(mpg_car * MPG_A_KM_L, 2),
                            "rend_combinado_km_l": round(mpg_c * MPG_A_KM_L, 2),
                        })
                        break
    filas.sort(key=lambda x: (x["modelo_mx_referencia"], x["anio"], x["epa_id"]))
    return filas


def escribir_csv(ruta: Path, filas: list[dict], columnas: list[str]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas, lineterminator="\n")
        w.writeheader()
        w.writerows(filas)


# --------------------------------------------------------------------------- paso 2
def ensuciar_cliente(rng: random.Random, nombre: str) -> str:
    estilo = rng.choice(["original", "upper", "lower", "title", "aleatorio"])
    if estilo == "upper":
        nombre = nombre.upper()
    elif estilo == "lower":
        nombre = nombre.lower()
    elif estilo == "title":
        nombre = nombre.title()
    elif estilo == "aleatorio":
        nombre = "".join(c.upper() if rng.random() < 0.5 else c.lower() for c in nombre)
    if rng.random() < 0.4:
        nombre = nombre.replace(" ", "  ", 1)
    return " " * rng.randint(0, 2) + nombre + " " * rng.randint(0, 3)


def formatear_fecha(rng: random.Random, f: dt.date) -> str:
    formato = rng.randrange(3)
    if formato == 0:
        return f.isoformat()
    if formato == 1:
        return f.strftime("%d/%m/%Y")
    return f"{f.day:02d}-{MESES_ES[f.month - 1]}-{f.year}"


def formatear_monto(rng: random.Random, valor: float) -> str:
    estilo = rng.randrange(4)
    if estilo == 0:
        return f"{valor:.2f}"            # 14500.00
    if estilo == 1:
        return f"${valor:,.2f}"          # $14,500.00
    if estilo == 2:
        return f"{valor:,.2f}"           # 14,500.00
    return f"${valor:.2f}"               # $14500.00


def generar_operacion(rng: random.Random, catalogo: list[dict]) -> tuple[list[dict], list[dict]]:
    # Se elige primero el modelo de referencia (peso uniforme) y luego una versión EPA,
    # para que los modelos con muchas variantes EPA no dominen la flotilla.
    por_modelo: dict[str, list[dict]] = {}
    for c in catalogo:
        por_modelo.setdefault(c["modelo_mx_referencia"], []).append(c)
    modelos = sorted(por_modelo)

    anio_c, mes_c = MES_CORTE
    dias_mes = (dt.date(anio_c + (mes_c == 12), mes_c % 12 + 1, 1) - dt.timedelta(days=1)).day

    registros = []
    for i in range(1, N_UNICOS + 1):
        v = rng.choice(por_modelo[rng.choice(modelos)])
        p = PARAMS[v["segmento"]]
        antiguedad = anio_c - v["anio"]
        odo_ini = int(max(antiguedad, 0.3) * rng.uniform(25_000, 45_000) + rng.uniform(500, 8_000))
        odo_fin = odo_ini + rng.randint(*p["km_mes"])
        costo_taller = 0.0 if rng.random() < 0.65 else round(rng.uniform(800, 25_000), 2)
        dias_taller = 0 if costo_taller == 0 else rng.randint(1, 10)
        registros.append({
            "id_unidad": f"FC-{i:04d}",
            "cliente": ensuciar_cliente(rng, rng.choice(CLIENTES)),
            "modelo": f"{v['modelo_mx_referencia']} {v['anio']}",
            "segmento": v["segmento"],
            "fecha_corte": formatear_fecha(rng, dt.date(anio_c, mes_c, rng.randint(1, dias_mes))),
            "odometro_inicial_km": odo_ini,
            "odometro_final_km": odo_fin,
            "km_contrato": rng.choice(p["km_contrato"]),
            "renta_mensual_mxn": formatear_monto(rng, round(rng.uniform(*p["renta"]) / 50) * 50),
            "tarifa_km_extra_mxn": formatear_monto(rng, round(rng.uniform(*p["tarifa"]), 2)),
            "costo_taller_mxn": formatear_monto(rng, costo_taller),
            "dias_taller": dias_taller,
            "seguro_mensual_mxn": formatear_monto(rng, round(rng.uniform(*p["seguro"]) / 10) * 10),
            "estatus_pago": rng.choices(["PAGADO", "PENDIENTE", "VENCIDO"], weights=[70, 20, 10])[0],
        })

    # Conjuntos disjuntos: críticos, millas y origen de duplicados.
    indices = list(range(N_UNICOS))
    rng.shuffle(indices)
    criticos = indices[:N_CRITICOS]
    millas = indices[N_CRITICOS:N_CRITICOS + N_MILLAS]
    origen_dup = indices[N_CRITICOS + N_MILLAS:N_CRITICOS + N_MILLAS + N_DUPLICADOS]

    control = []
    tipos_criticos = ["odometro_final_menor"] * 6 + ["renta_negativa"] * 6 + ["taller_pendiente_factura"] * 6
    for idx, tipo in zip(criticos, tipos_criticos):
        r = registros[idx]
        if tipo == "odometro_final_menor":
            r["odometro_final_km"] = r["odometro_inicial_km"] - rng.randint(500, 15_000)
        elif tipo == "renta_negativa":
            r["renta_mensual_mxn"] = "-" + r["renta_mensual_mxn"]
        else:
            r["costo_taller_mxn"] = "PENDIENTE_FACTURA"
            r["dias_taller"] = rng.randint(1, 10)
        control.append({"id_unidad": r["id_unidad"], "tipo_inyeccion": tipo})

    for idx in millas:
        r = registros[idx]
        r["odometro_inicial_km"] = round(r["odometro_inicial_km"] / KM_POR_MILLA)
        r["odometro_final_km"] = round(r["odometro_final_km"] / KM_POR_MILLA)
        control.append({"id_unidad": r["id_unidad"], "tipo_inyeccion": "odometro_en_millas"})

    for idx in origen_dup:
        registros.append(dict(registros[idx]))
        control.append({"id_unidad": registros[idx]["id_unidad"], "tipo_inyeccion": "duplicado_exacto"})

    rng.shuffle(registros)
    control.sort(key=lambda x: (x["tipo_inyeccion"], x["id_unidad"]))
    return registros, control


# --------------------------------------------------------------------------- main
def main() -> None:
    rng = random.Random(SEMILLA)
    refrescar = "--refrescar" in sys.argv[1:]

    catalogo = construir_catalogo(obtener_zip_epa(refrescar))
    escribir_csv(CATALOGO_CSV, catalogo, list(catalogo[0].keys()))

    registros, control = generar_operacion(rng, catalogo)
    escribir_csv(OPERACION_CSV, registros, COLUMNAS)
    escribir_csv(CONTROL_CSV, control, ["id_unidad", "tipo_inyeccion"])

    # ---- Conteo inicial
    print("\n=== Catálogo EPA ===")
    print(f"Versiones extraídas: {len(catalogo)}  -> {CATALOGO_CSV.relative_to(RAIZ)}")
    for m in sorted({c["modelo_mx_referencia"] for c in catalogo}):
        sub = [c for c in catalogo if c["modelo_mx_referencia"] == m]
        anios = sorted({c["anio"] for c in sub})
        rend = [c["rend_combinado_km_l"] for c in sub]
        print(f"  {m:<14} {sub[0]['tipo_coincidencia']:<10} versiones={len(sub):>2}  "
              f"años={anios[0]}-{anios[-1]}  km/L comb={min(rend):.2f}-{max(rend):.2f}")
    print(f"  Sin datos en EPA (no incluidos): {', '.join(SIN_DATOS_EPA)}")

    n_total = len(registros)
    n_dup = sum(c["tipo_inyeccion"] == "duplicado_exacto" for c in control)
    n_mi = sum(c["tipo_inyeccion"] == "odometro_en_millas" for c in control)
    n_crit = sum(c["tipo_inyeccion"] not in ("duplicado_exacto", "odometro_en_millas") for c in control)
    print("\n=== Operación mensual sucia ===")
    print(f"Registros totales (entradas):     {n_total}  -> {OPERACION_CSV.relative_to(RAIZ)}")
    print(f"  Unidades únicas:                {N_UNICOS}")
    print(f"  Duplicados exactos:             {n_dup}")
    print(f"  Odómetro en millas (recuperable): {n_mi}")
    print(f"  Errores críticos irrecuperables:  {n_crit}")
    print(f"Esperado tras limpieza: limpias={n_total - n_dup - n_crit}  "
          f"rechazadas={n_dup + n_crit}  (suma={n_total})")


if __name__ == "__main__":
    main()
