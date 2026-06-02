# Theory Y Memo — Mandarin (zh) Localization Glossary

Portable translation core for Mandarin investment memos. Loaded by
`theory-y-localize` (and reusable by any future service worker). Use the
**Target term** for every listed concept so translations are consistent and
market-standard, not literal.

## Conventions
- **Acronym in parentheses on first use.** Keep the English acronym so chart/table
  cross-references stay legible: e.g. `企业价值/EBITDA 倍数 (EV/EBITDA)`. After first
  use within a section you may use the Chinese term alone.
- **Numbers:** keep Western numerals and the source's compact scale notation
  (`$5,114B`, `85.2%`, `16.68x`) verbatim — do **not** convert to 亿/万. The "x"
  multiple suffix stays as-is (e.g. `30.6x` → `30.6 倍` is acceptable in prose, but
  keep `30.6x` inside tables to preserve column alignment).
- **Do not translate:** tickers (NVDA, AMD, TSM…), company legal names
  (NVIDIA Corporation), the `$` symbol, `N/M` / `N/A` flags, and any `[[chart:…]]`
  token. Translate the human caption text inside `[[table:…]]` tokens.
- **Rating labels** are institutional standards — translate per the table below and
  keep them crisp.

## Term map

| EN term | Target term (zh) | Note |
|---|---|---|
| Investment Memo | 投资备忘录 | title line |
| One-Line Thesis | 一句话投资论点 | |
| Valuation Snapshot | 估值快照 | |
| Business Overview & Operations | 业务概览与运营 | |
| Alternative Data & Macro Signals | 另类数据与宏观信号 | |
| Consumer & Public Opinion | 消费者与公众舆论 | |
| Key Risks & Structural Barriers | 关键风险与结构性壁垒 | |
| Investment Recommendation | 投资建议 | |
| thesis | 投资论点 | |
| valuation | 估值 | |
| valuation bridge | 估值桥接分析 | the implied-earnings derivation |
| Market Cap | 市值 | |
| Enterprise Value (EV) | 企业价值 (EV) | |
| Trailing Revenue (TTM) | 过去十二个月营收 (TTM) | |
| Trailing EBITDA (TTM) | 过去十二个月 EBITDA (TTM) | keep EBITDA in Latin |
| EBITDA Margin | EBITDA 利润率 | |
| gross margin | 毛利率 | |
| operating margin | 营业利润率 | |
| net income | 净利润 | |
| free cash flow (FCF) | 自由现金流 (FCF) | |
| YoY (year-over-year) | 同比 | |
| QoQ (quarter-over-quarter) | 环比 | |
| revenue growth | 营收增速 | |
| operating leverage | 经营杠杆 | core analytical term |
| forward P/E | 前瞻市盈率 (forward P/E) | |
| trailing P/E | 历史市盈率 | |
| NTM (next-twelve-months) | 未来十二个月 (NTM) | |
| out-year | 远期年度 | |
| EV/Revenue | 企业价值/营收倍数 (EV/Revenue) | |
| EV/EBITDA | 企业价值/EBITDA 倍数 (EV/EBITDA) | |
| PEG | 市盈率相对盈利增长比率 (PEG) | |
| multiple (valuation) | 估值倍数 | |
| basis points (bps) | 个基点 | |
| peer / comps / peer set | 可比公司 | |
| cross-sectional comparison | 横向比较 | |
| discount (to peers) | 折让 | "31% discount" → "31% 折让" |
| premium | 溢价 | |
| moat | 护城河 | |
| structural barrier | 结构性壁垒 | |
| switching cost | 转换成本 | |
| pricing power | 定价权 | |
| bull case | 看多情形 | |
| bear case | 看空情形 | |
| conviction | 信心 / 确信度 | "High conviction" → "高确信度" |
| Rating | 评级 | |
| Buy | 买入 | rating label |
| Overweight | 增持 | |
| Neutral / Hold | 中性 / 持有 | |
| Underweight | 减持 | |
| Sell | 卖出 | |
| downgrade trigger | 下调评级触发条件 | |
| upgrade trigger | 上调评级触发条件 | |
| catalyst | 催化剂 | |
| guidance | 业绩指引 | |
| consensus | 市场一致预期 | |
| hyperscaler | 超大规模云厂商 | |
| capex | 资本开支 | |
| TAM (total addressable market) | 潜在市场总规模 (TAM) | |
| segment mix | 业务板块构成 | |
| sentiment | 情绪 | |
| signal count | 信号计数 | sentiment methodology |
| confidence (data) | 置信度 | "high/medium/low confidence" → 高/中/低置信度 |
| 52-week range | 52 周区间 | |
| price target | 目标价 | |
| margin of safety | 安全边际 | |
| export control | 出口管制 | |
| data gap | 数据缺口 | |
| Sourcing note | 数据来源说明 | end-of-memo footnote |
| INSTITUTIONAL USE ONLY | 仅供机构使用 | PDF header chrome |
| Equity Research | 股票研究 | PDF header chrome |
