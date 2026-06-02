# Theory Y Memo — Spanish (es) Localization Glossary

Portable translation core for Spanish investment memos. Loaded by
`theory-y-localize` (and reusable by any future service worker). Use the
**Target term** for every listed concept so translations are consistent and
market-standard, not literal.

## Conventions
- **Acronym in parentheses on first use.** Keep the English acronym so chart/table
  cross-references stay legible: e.g. `valor de empresa sobre EBITDA (EV/EBITDA)`.
  After first use within a section you may use the Spanish term alone.
- **Number formatting (es):** decimal comma, thin-space thousands separator
  (`1 234,5`). Keep the source's compact scale notation and the `x` multiple suffix
  inside tables verbatim (`30.6x`, `$5,114B`) to preserve column alignment; in prose
  you may localize decimals (e.g. `16,68x`). Percentages use a comma decimal
  (`85,2 %`) with a thin space before `%`.
- **Do not translate:** tickers (NVDA, AMD, TSM…), company legal names
  (NVIDIA Corporation), the `$` symbol, `N/M` / `N/A` flags, and any `[[chart:…]]`
  token. Translate the human caption text inside `[[table:…]]` tokens.
- **Rating labels** are institutional standards — translate per the table below.

## Term map

| EN term | Target term (es) | Note |
|---|---|---|
| Investment Memo | Memorándum de Inversión | title line |
| One-Line Thesis | Tesis en Una Línea | |
| Valuation Snapshot | Panorámica de Valoración | |
| Business Overview & Operations | Visión General del Negocio y Operaciones | |
| Alternative Data & Macro Signals | Datos Alternativos y Señales Macro | |
| Consumer & Public Opinion | Opinión del Consumidor y Pública | |
| Key Risks & Structural Barriers | Riesgos Clave y Barreras Estructurales | |
| Investment Recommendation | Recomendación de Inversión | |
| thesis | tesis | |
| valuation | valoración | |
| valuation bridge | puente de valoración | implied-earnings derivation |
| Market Cap | Capitalización Bursátil | |
| Enterprise Value (EV) | Valor de Empresa (EV) | |
| Trailing Revenue (TTM) | Ingresos de los Últimos Doce Meses (TTM) | |
| Trailing EBITDA (TTM) | EBITDA de los Últimos Doce Meses (TTM) | keep EBITDA |
| EBITDA Margin | Margen EBITDA | |
| gross margin | margen bruto | |
| operating margin | margen operativo | |
| net income | beneficio neto | |
| free cash flow (FCF) | flujo de caja libre (FCF) | |
| YoY (year-over-year) | interanual | |
| QoQ (quarter-over-quarter) | trimestral (intertrimestral) | |
| revenue growth | crecimiento de ingresos | |
| operating leverage | apalancamiento operativo | core analytical term |
| forward P/E | PER prospectivo (forward P/E) | |
| trailing P/E | PER histórico | |
| NTM (next-twelve-months) | próximos doce meses (NTM) | |
| out-year | ejercicio futuro | |
| EV/Revenue | valor de empresa sobre ingresos (EV/Revenue) | |
| EV/EBITDA | valor de empresa sobre EBITDA (EV/EBITDA) | |
| PEG | ratio PEG | keep PEG |
| multiple (valuation) | múltiplo de valoración | |
| basis points (bps) | puntos básicos (pb) | |
| peer / comps / peer set | comparables | |
| cross-sectional comparison | comparación transversal | |
| discount (to peers) | descuento | "31% discount" → "descuento del 31 %" |
| premium | prima | |
| moat | foso defensivo (moat) | |
| structural barrier | barrera estructural | |
| switching cost | coste de cambio | |
| pricing power | poder de fijación de precios | |
| bull case | escenario alcista | |
| bear case | escenario bajista | |
| conviction | convicción | "High conviction" → "convicción alta" |
| Rating | calificación | |
| Buy | Comprar | rating label |
| Overweight | Sobreponderar | |
| Neutral / Hold | Neutral / Mantener | |
| Underweight | Infraponderar | |
| Sell | Vender | |
| downgrade trigger | desencadenante de rebaja | |
| upgrade trigger | desencadenante de mejora | |
| catalyst | catalizador | |
| guidance | previsiones (guidance) | |
| consensus | consenso de mercado | |
| hyperscaler | hiperescalador | |
| capex | inversión en capital (capex) | |
| TAM (total addressable market) | mercado total direccionable (TAM) | |
| segment mix | mezcla por segmentos | |
| sentiment | sentimiento | |
| signal count | recuento de señales | sentiment methodology |
| confidence (data) | confianza | "high/medium/low" → confianza alta/media/baja |
| 52-week range | rango de 52 semanas | |
| price target | precio objetivo | |
| margin of safety | margen de seguridad | |
| export control | control de exportaciones | |
| data gap | vacío de datos | |
| Sourcing note | Nota sobre fuentes | end-of-memo footnote |
| INSTITUTIONAL USE ONLY | USO INSTITUCIONAL EXCLUSIVO | PDF header chrome |
| Equity Research | Análisis de Renta Variable | PDF header chrome |
