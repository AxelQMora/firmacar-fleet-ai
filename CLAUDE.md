# FirmaCar — Reglas permanentes del proyecto

Análisis de rentabilidad de una flotilla de autos en arrendamiento.

## Unidades y reproducibilidad
- Moneda: **MXN** en todos los montos (2 decimales en reportes).
- Distancias: **kilómetros (km)**. Nunca millas.
- Aleatoriedad: semilla fija **`random_state=42`** (numpy, pandas, sklearn, muestreos).

## Fórmulas financieras (exactas, no modificar)
```
Km_Excedentes   = max(0, Km_Recorridos - Km_Contrato)
Ingreso_Bruto   = Renta_Base + Km_Excedentes * Tarifa_Km_Excedente
Utilidad_Neta   = Ingreso_Bruto - Costo_Taller - Seguro_Mensual - Reserva_Depreciacion
Margen_Pct      = (Utilidad_Neta / Ingreso_Bruto) * 100
```
- Si `Ingreso_Bruto == 0`, `Margen_Pct` no se calcula: la fila se rechaza con motivo explícito.

## Verificación estricta (obligatoria en cada corrida)
- **Registros de entrada = registros limpios + registros rechazados.** Sin excepciones.
- Toda fila rechazada se guarda con su motivo; nunca se descarta en silencio.
- Si la igualdad no se cumple, el proceso falla y no se generan reportes.

## Estructura
- `data/` — datos crudos (solo lectura).
- `output/` — CSV limpio, CSV de rechazados, Excel y PDF.
