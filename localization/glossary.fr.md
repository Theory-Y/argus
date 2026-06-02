# Theory Y Memo — French (fr) Localization Glossary

Portable translation core for French investment memos. Loaded by
`theory-y-localize` (and reusable by any future service worker). Use the
**Target term** for every listed concept so translations are consistent and
market-standard, not literal.

## Conventions
- **Acronym in parentheses on first use.** Keep the English acronym so chart/table
  cross-references stay legible: e.g. `valeur d'entreprise sur EBITDA (EV/EBITDA)`.
  After first use within a section you may use the French term alone.
- **Number formatting (fr):** decimal comma, thin-space thousands separator
  (`1 234,5`). Keep the source's compact scale notation and the `x` multiple suffix
  inside tables verbatim (`30.6x`, `$5,114B`) to preserve column alignment; in prose
  you may localize decimals (e.g. `16,68x`). Percentages: comma decimal with a thin
  space before `%` (`85,2 %`).
- **Do not translate:** tickers (NVDA, AMD, TSM…), company legal names
  (NVIDIA Corporation), the `$` symbol, `N/M` / `N/A` flags, and any `[[chart:…]]`
  token. Translate the human caption text inside `[[table:…]]` tokens.
- **Rating labels** are institutional standards — translate per the table below.

## Term map

| EN term | Target term (fr) | Note |
|---|---|---|
| Investment Memo | Note d'Investissement | title line |
| One-Line Thesis | Thèse en Une Ligne | |
| Valuation Snapshot | Aperçu de Valorisation | |
| Business Overview & Operations | Présentation de l'Activité et Opérations | |
| Alternative Data & Macro Signals | Données Alternatives et Signaux Macro | |
| Consumer & Public Opinion | Opinion des Consommateurs et du Public | |
| Key Risks & Structural Barriers | Risques Clés et Barrières Structurelles | |
| Investment Recommendation | Recommandation d'Investissement | |
| thesis | thèse | |
| valuation | valorisation | |
| valuation bridge | passerelle de valorisation | implied-earnings derivation |
| Market Cap | Capitalisation Boursière | |
| Enterprise Value (EV) | Valeur d'Entreprise (EV) | |
| Trailing Revenue (TTM) | Chiffre d'Affaires sur Douze Mois Glissants (TTM) | |
| Trailing EBITDA (TTM) | EBITDA sur Douze Mois Glissants (TTM) | keep EBITDA |
| EBITDA Margin | Marge d'EBITDA | |
| gross margin | marge brute | |
| operating margin | marge opérationnelle | |
| net income | résultat net | |
| free cash flow (FCF) | flux de trésorerie disponible (FCF) | |
| YoY (year-over-year) | en glissement annuel | |
| QoQ (quarter-over-quarter) | en glissement trimestriel | |
| revenue growth | croissance du chiffre d'affaires | |
| operating leverage | levier opérationnel | core analytical term |
| forward P/E | PER prospectif (forward P/E) | |
| trailing P/E | PER historique | |
| NTM (next-twelve-months) | douze prochains mois (NTM) | |
| out-year | exercice futur | |
| EV/Revenue | valeur d'entreprise sur chiffre d'affaires (EV/Revenue) | |
| EV/EBITDA | valeur d'entreprise sur EBITDA (EV/EBITDA) | |
| PEG | ratio PEG | keep PEG |
| multiple (valuation) | multiple de valorisation | |
| basis points (bps) | points de base (pb) | |
| peer / comps / peer set | comparables | |
| cross-sectional comparison | comparaison transversale | |
| discount (to peers) | décote | "31% discount" → "décote de 31 %" |
| premium | prime | |
| moat | avantage concurrentiel durable (moat) | |
| structural barrier | barrière structurelle | |
| switching cost | coût de changement | |
| pricing power | pouvoir de fixation des prix | |
| bull case | scénario haussier | |
| bear case | scénario baissier | |
| conviction | conviction | "High conviction" → "conviction élevée" |
| Rating | recommandation | |
| Buy | Achat | rating label |
| Overweight | Surpondérer | |
| Neutral / Hold | Neutre / Conserver | |
| Underweight | Sous-pondérer | |
| Sell | Vente | |
| downgrade trigger | facteur de dégradation | |
| upgrade trigger | facteur de relèvement | |
| catalyst | catalyseur | |
| guidance | prévisions (guidance) | |
| consensus | consensus de marché | |
| hyperscaler | hyperscaler | kept (industry standard in FR press) |
| capex | dépenses d'investissement (capex) | |
| TAM (total addressable market) | marché total adressable (TAM) | |
| segment mix | répartition par segment | |
| sentiment | sentiment | |
| signal count | nombre de signaux | sentiment methodology |
| confidence (data) | confiance | "high/medium/low" → confiance élevée/moyenne/faible |
| 52-week range | fourchette sur 52 semaines | |
| price target | objectif de cours | |
| margin of safety | marge de sécurité | |
| export control | contrôle des exportations | |
| data gap | lacune de données | |
| Sourcing note | Note sur les sources | end-of-memo footnote |
| INSTITUTIONAL USE ONLY | USAGE INSTITUTIONNEL EXCLUSIVEMENT | PDF header chrome |
| Equity Research | Recherche Actions | PDF header chrome |
