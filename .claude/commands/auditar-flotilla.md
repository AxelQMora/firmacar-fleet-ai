---
description: Corre el pipeline de limpieza, cuadra CSV/Excel/PDF y reporta las 5 unidades menos rentables
---

Audita la flotilla de FirmaCar siguiendo las reglas de `CLAUDE.md`.

## Pasos
1. **Ejecutar el pipeline de limpieza** (`python src/pipeline_limpieza.py`).
   Si el script no existe o falla, detente y reporta el error. No inventes resultados.
2. **Conteo de registros:** confirma que `entradas = limpias + rechazadas`.
   Muestra los tres números.
3. **Cuadre entre fuentes:** calcula la suma de `Ingreso_Bruto`, `Costo_Taller`,
   `Seguro_Mensual`, `Reserva_Depreciacion` y `Utilidad_Neta` en:
   - el CSV limpio de `output/`,
   - el Excel de `output/`,
   - el PDF de `output/` (extrae los totales del texto).
   La diferencia debe ser **0.00 MXN** en cada concepto. Cualquier diferencia es un fallo.
4. **Recalcular fórmulas:** verifica fila por fila con las fórmulas exactas de `CLAUDE.md`.
5. **Top 5 menos rentables:** ordena por `Utilidad_Neta` ascendente (empate: `Margen_Pct`).

## Formato del reporte
- Tabla de conteo (entradas / limpias / rechazadas / ✅ o ❌).
- Tabla de cuadre: concepto × CSV × Excel × PDF × diferencia.
- Tabla de las 5 unidades: unidad, Ingreso_Bruto, Utilidad_Neta, Margen_Pct, Km_Excedentes.
- Veredicto final: **CUADRA** o **NO CUADRA** con la lista de discrepancias.

Para revisar odómetros y montos de contratos, delega en el subagente `auditor-financiero`.
