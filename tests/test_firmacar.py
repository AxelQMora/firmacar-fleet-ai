"""Pruebas de integridad del pipeline FirmaCar.

Validan las salidas ya generadas (correr antes ./correr_todo.sh o los scripts 01-04).
Uso: .venv/bin/pytest -v
"""

from __future__ import annotations

import csv
import importlib.util
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

RAIZ = Path(__file__).resolve().parent.parent
SUCIA = RAIZ / "data" / "operacion_mensual_sucia.csv"
LIMPIA = RAIZ / "data" / "flotilla_auditada_limpia.csv"
RECHAZADOS = RAIZ / "data" / "rechazados_auditoria.csv"
EXCEL = RAIZ / "output" / "control_flotilla_firmacar.xlsx"
PDF = RAIZ / "output" / "reporte_direccion_firmacar.pdf"


def leer(ruta: Path) -> list[dict]:
    if not ruta.exists():
        pytest.fail(f"Falta {ruta.relative_to(RAIZ)}: corre ./correr_todo.sh primero")
    with ruta.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def sucia():
    return leer(SUCIA)


@pytest.fixture(scope="module")
def limpias():
    return leer(LIMPIA)


@pytest.fixture(scope="module")
def rechazados():
    return leer(RECHAZADOS)


# 1) Cuadre de filas sin pérdidas ---------------------------------------------------
def test_cuadre_filas_entradas_igual_limpias_mas_rechazadas(sucia, limpias, rechazados):
    assert len(sucia) == len(limpias) + len(rechazados), (
        f"{len(sucia)} entradas != {len(limpias)} limpias + {len(rechazados)} rechazadas")


def test_cuadre_sin_perdidas_por_unidad(sucia, limpias, rechazados):
    """Cada id_unidad de la entrada aparece exactamente las mismas veces en la salida."""
    entrada = Counter(r["id_unidad"] for r in sucia)
    salida = Counter(r["id_unidad"] for r in limpias) + Counter(r["id_unidad"] for r in rechazados)
    assert entrada == salida, f"Diferencias: perdidas={entrada - salida}, sobrantes={salida - entrada}"


def test_rechazados_tienen_motivo(rechazados):
    sin_motivo = [r["linea_origen"] for r in rechazados if not r["motivo_rechazo"].strip()]
    assert not sin_motivo, f"Rechazados sin motivo_rechazo en líneas {sin_motivo}"


# 2) Odómetros --------------------------------------------------------------------------
def test_ninguna_fila_limpia_con_odometro_final_menor(limpias):
    malas = [r["id_unidad"] for r in limpias
             if int(r["odometro_final_km"]) < int(r["odometro_inicial_km"])]
    assert not malas, f"Odómetro final < inicial en filas limpias: {malas}"


# 3) Fórmulas financieras ---------------------------------------------------------------
def test_utilidad_neta_igual_ingreso_menos_costo_total(limpias):
    malas = [
        (r["id_unidad"], r["utilidad_neta_mxn"], r["ingreso_bruto_mxn"], r["costo_total_mxn"])
        for r in limpias
        if Decimal(r["utilidad_neta_mxn"]) != Decimal(r["ingreso_bruto_mxn"]) - Decimal(r["costo_total_mxn"])
    ]
    assert not malas, f"Utilidad != Ingreso - Costo Total: {malas[:5]}"


def test_formulas_claude_md(limpias):
    """Recalcula las fórmulas exactas de CLAUDE.md fila por fila."""
    c = Decimal("0.01")
    for r in limpias:
        km_rec = int(r["odometro_final_km"]) - int(r["odometro_inicial_km"])
        km_exc = max(0, km_rec - int(r["km_contrato"]))
        ingreso = Decimal(r["renta_mensual_mxn"]) + (km_exc * Decimal(r["tarifa_km_extra_mxn"])).quantize(c)
        reserva = (km_rec * Decimal("1.20")).quantize(c)
        costo = Decimal(r["costo_taller_mxn"]) + Decimal(r["seguro_mensual_mxn"]) + reserva
        assert int(r["km_recorridos"]) == km_rec, r["id_unidad"]
        assert int(r["km_excedentes"]) == km_exc, r["id_unidad"]
        assert Decimal(r["ingreso_bruto_mxn"]) == ingreso, r["id_unidad"]
        assert Decimal(r["costo_total_mxn"]) == costo, r["id_unidad"]


def test_sin_montos_negativos_ni_renta_cero(limpias):
    cols = ["renta_mensual_mxn", "tarifa_km_extra_mxn", "costo_taller_mxn", "seguro_mensual_mxn"]
    malas = [(r["id_unidad"], c) for r in limpias for c in cols if Decimal(r[c]) < 0]
    malas += [(r["id_unidad"], "renta<=0") for r in limpias if Decimal(r["renta_mensual_mxn"]) <= 0]
    assert not malas, f"Montos inválidos en filas limpias: {malas}"


# 4) Entregables ------------------------------------------------------------------------
def test_excel_existe_con_tres_hojas():
    assert EXCEL.exists() and EXCEL.stat().st_size > 0, f"No existe {EXCEL.relative_to(RAIZ)}"
    hojas = load_workbook(EXCEL, read_only=True).sheetnames
    assert hojas == ["Resumen_Direccion", "Flotilla_Limpia", "Rechazados_Revision"]


def test_pdf_existe_de_una_a_dos_paginas():
    assert PDF.exists() and PDF.stat().st_size > 0, f"No existe {PDF.relative_to(RAIZ)}"
    assert 1 <= len(PdfReader(PDF).pages) <= 2


def test_totales_csv_excel_pdf_cuadran(capsys):
    """Reutiliza src/05_verificar_cuadre.py: los 7 conceptos y los conteos deben coincidir."""
    spec = importlib.util.spec_from_file_location("verificar", RAIZ / "src" / "05_verificar_cuadre.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    codigo = modulo.main()
    salida = capsys.readouterr().out
    assert codigo == 0, f"CSV / Excel / PDF no cuadran:\n{salida}"
