---
description: Corre el pipeline de limpieza, cuadra CSV/Excel/PDF y reporta las 5 unidades menos rentables
---

Audita la flotilla de FirmaCar siguiendo las reglas de `CLAUDE.md`.

## Pasos
1. **Ejecutar el pipeline completo** con `./correr_todo.sh` (01 ingesta → 02 auditoría →
   03 Excel → 04 PDF → 05 cuadre → pytest). Si algo falla, detente y reporta el error.
   No inventes resultados.
2. **Conteo de registros:** confirma que `entradas = limpias + rechazadas`.
   Muestra los tres números.
3. **Cuadre entre fuentes:** usa la salida de `.venv/bin/python src/05_verificar_cuadre.py`,
   que suma `ingreso_bruto_mxn`, `costo_taller_mxn`, `seguro_mensual_mxn`,
   `reserva_depreciacion_mxn` y `utilidad_neta_mxn` (y rentas/excedentes) en:
   - el CSV limpio `data/flotilla_auditada_limpia.csv`,
   - el Excel `output/control_flotilla_firmacar.xlsx`,
   - el PDF `output/reporte_direccion_firmacar.pdf` (texto extraído).
   La diferencia debe ser **0.00 MXN** en cada concepto. Cualquier diferencia es un fallo.
4. **Recalcular fórmulas:** verifica fila por fila con las fórmulas exactas de `CLAUDE.md`.
5. **Top 5 menos rentables:** desde el CSV limpio, ordena por `utilidad_neta_mxn` ascendente
   (empate: `margen_operativo_pct`).

## Formato del reporte
- Tabla de conteo (entradas / limpias / rechazadas / ✅ o ❌).
- Tabla de cuadre: concepto × CSV × Excel × PDF × diferencia.
- Tabla de las 5 unidades: id_unidad, ingreso_bruto_mxn, utilidad_neta_mxn, margen_operativo_pct,
  km_excedentes, bandera_alerta.
- Veredicto final: **CUADRA** o **NO CUADRA** con la lista de discrepancias.

Para revisar odómetros y montos de contratos, delega en el subagente `auditor-financiero`.
