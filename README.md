# FirmaCar — Auditoría de rentabilidad de flotilla

Pipeline reproducible que convierte la captura mensual (sucia) de una flotilla en arrendamiento
en un control auditado: CSV limpio, Excel para operación y un PDF de 2 páginas para Dirección,
con cuadre al centavo entre los tres.

## El problema de negocio

Una arrendadora cobra a cada cliente una **renta mensual** con un **límite de kilómetros**; lo que
se pasa se cobra por km excedente. Contra ese ingreso pesan el **taller**, el **seguro** y la
**depreciación** (reserva de 1.20 MXN por km). Con cientos de unidades el cierre de mes falla por
la calidad de la captura, no por las fórmulas:

| Problema real de captura | Efecto si no se detecta | Qué hace el pipeline |
|---|---|---|
| Filas duplicadas | Ingreso inflado | Las aparta como `DUPLICADO` |
| Odómetro en millas en vez de km | Km excedentes no cobrados, reserva subestimada | Convierte a km (heurística + correcciones manuales) |
| Odómetro final < inicial | Km negativos, cobro imposible | Rechaza con motivo para Operaciones |
| Renta negativa, taller `PENDIENTE_FACTURA` | Utilidad falsa | Rechaza con motivo para Facturación/Taller |
| Fechas, montos y nombres en formatos mezclados | Totales que no cuadran entre áreas | Normaliza todo (AAAA-MM-DD, MXN numérico) |

Resultado: Dirección ve qué unidades pierden dinero y por qué (auditar factura de taller,
reducir días en taller, renovar unidad), y ninguna fila se pierde en el camino:
**entradas = limpias + rechazadas**.

## Correr todo desde cero

```bash
./correr_todo.sh
```

Crea `.venv`, instala `requirements.txt` y ejecuta 01 → 05 más `pytest`. Requiere Python 3 e internet
la primera vez (descarga el catálogo EPA; después usa la caché `data/raw/vehicles.csv.zip`).
`./correr_todo.sh --refrescar` vuelve a descargarlo (EPA lo actualiza, por lo que las cifras pueden cambiar).

## Pipeline

| Paso | Script | Salida |
|---|---|---|
| 01 | `src/01_ingesta_flotilla.py` | `data/catalogo_epa_vehiculos.csv` (EPA, km/L), `data/operacion_mensual_sucia.csv` (240 filas, semilla 42) |
| 02 | `src/02_auditoria_operativa.py` | `data/flotilla_auditada_limpia.csv`, `data/rechazados_auditoria.csv` |
| 03 | `src/03_exportar_excel.py` | `output/control_flotilla_firmacar.xlsx` (Resumen_Direccion, Flotilla_Limpia, Rechazados_Revision) |
| 04 | `src/04_reporte_director_pdf.py` | `output/reporte_direccion_firmacar.pdf`, `output/rentabilidad_segmento.png` |
| 05 | `src/05_verificar_cuadre.py` | Cuadre CSV = Excel = PDF de 7 conceptos y conteos (código 1 si no cuadra) |
| — | `tests/test_firmacar.py` | Pruebas pytest de cuadre, odómetros, fórmulas y entregables |

Entradas manuales: `data/correcciones_manuales.csv` (odómetros en millas confirmados que la
heurística no detecta). `data/_control_inyeccion.csv` es la clave de respuestas de los datos
sintéticos; el pipeline **no** la lee.

## Reglas del proyecto (`CLAUDE.md`)

MXN, kilómetros, `random_state=42` y fórmulas exactas:

```
Km_Excedentes = max(0, Km_Recorridos - Km_Contrato)
Ingreso_Bruto = Renta_Base + Km_Excedentes * Tarifa_Km_Excedente
Utilidad_Neta = Ingreso_Bruto - Costo_Taller - Seguro_Mensual - Reserva_Depreciacion
Margen_Pct    = (Utilidad_Neta / Ingreso_Bruto) * 100
```

## Claude Code: Skill y Subagente

### Skill `/auditar-flotilla` — `.claude/commands/auditar-flotilla.md`

Comando que se invoca escribiendo `/auditar-flotilla` en Claude Code. Estructura:

- **Frontmatter** `description:` — texto que aparece en el autocompletado.
- **Pasos** — 1) correr `./correr_todo.sh`; 2) confirmar entradas = limpias + rechazadas;
  3) cuadrar CSV/Excel/PDF con `05_verificar_cuadre.py` (diferencia 0.00 MXN);
  4) recalcular fórmulas; 5) listar las 5 unidades menos rentables.
- **Formato del reporte** — tablas de conteo, cuadre y top 5, con veredicto **CUADRA / NO CUADRA**.
- Delega la revisión de contratos al subagente `auditor-financiero`.

### Subagente `auditor-financiero` — `.claude/agents/auditor-financiero.md`

Agente especializado con contexto propio. Estructura:

- **Frontmatter YAML** — `name: auditor-financiero`, `description:` (Claude lo usa para decidir
  cuándo delegarle) y `tools: Read, Grep, Glob, Bash`.
- **Validaciones** — ningún contrato aprobado con `odometro_final_km < odometro_inicial_km`,
  ningún monto negativo, renta > 0, km consistentes y cierre contable recalculado.
- **Reglas** — solo lectura: reporta, no corrige.
- **Salida** — hallazgo por unidad y veredicto **APROBADO / RECHAZADO**.

Se invoca pidiéndolo en lenguaje natural ("usa el auditor-financiero para revisar los contratos
aprobados") o desde la Skill.

## Limitaciones conocidas

- Los datos de operación son **sintéticos** (generados con semilla 42 sobre el catálogo real de EPA).
- EPA no publica Chevrolet Aveo, VW Virtus ni Renault Kangoo; NP300 y Hilux usan como proxy
  Frontier y Tacoma (columna `tipo_coincidencia = proxy_epa`).
- La detección de millas es heurística (umbrales de km/año y km/mes por segmento); los casos que
  no detecta se corrigen en `data/correcciones_manuales.csv`. Con datos reales conviene que la
  fuente traiga la unidad del odómetro.
- Segmento "Compacto" se reporta como "Sedán"; no hay SUV en la flotilla actual.
