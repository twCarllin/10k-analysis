# 10-K Multi-Agent Investment Research Pipeline

從 SEC EDGAR 10-K/10-Q 文件自動萃取投資 insight，使用 multi-agent + skill 架構。

輸入 ticker + 年份，輸出繁體中文 Markdown + PDF 報告，包含 Bull/Bear case、關鍵追蹤指標、財務數據表格與季度趨勢圖。

輸出結果請參考 INTC_20260425_183226_report.pdf

## 最新變更（2026-04-28）

### 供應鏈分析（supply_chain_analysis）
新增獨立 skill，從多個 section 系統性萃取供應鏈資訊：
- 來源：Item 1 Business（原物料、單一來源風險）+ Item 1A Risk Factors（地緣 / 集中風險）+ Item 7 MD&A（實際財務影響）+ Item 8 Footnotes（採購承諾）
- 分類六大類別：concentration / geopolitical / price / shortage / logistics / regulatory
- 跨年比較產出 improvements / deteriorations 訊號
- 10-K + 10-Q Q1 跑、Q2/Q3 skip（Q2/Q3 通常只一句「No material changes」）
- 獨立模組，**不接** rerate / cross_year / insight_synthesis，只在 report 自有「## 供應鏈分析」段落呈現

### 競爭對手識別（competitor_mapping）
新增獨立 skill，從 Item 1 Business 抽取結構化競爭資訊：
- named_competitors（清單 + ticker + 受競爭市場）
- market_position（leader / challenger / niche / follower）+ evidence quote
- disclosure_quality（high / medium / low + rationale）
- yoy 變化標記（new / removed / unchanged）
- Q1 baseline 模式：Q1 10-Q 沿用去年 10-K 為基準（標題顯示「（基準：YYYY 10-K）」）；Q2/Q3 skip

## 最新變更（2025-04-25）

### CLI 自動推算前期
- 不再需要手動輸入 `prior_year`，系統自動推算：
  - 10-K → 自動比對前一年 10-K
  - 10-Q Q1 → 自動比對前一年 10-K（看年度承諾是否開始兌現）
  - 10-Q Q2/Q3 → 自動比對前一季（追蹤敘事演進）
- 新增 `--prior-year` flag 可手動覆蓋

### 評價趨勢判斷（3 條件獨立判斷）
新增「評價趨勢判斷」區塊，以紅綠燈號呈現三個維度：

| 燈號 | 意義 |
|------|------|
| 🟢 | 條件成立 |
| 🟡 | 尚未成立但趨勢正在成長（emerging） |
| 🔴 | 條件不成立 |

三個維度：
- **營收結構在變**：高毛利部門營收佔比是否持續上升（來源：segment_trend）
- **營收品質在變**：利潤率與現金流趨勢是否向好（來源：three_statement_cross）
- **敘事在變**：管理層語言是否從計畫期轉向成果期（來源：mdna_analysis）

每個條件由獨立 agent 判斷，互不影響，避免模型因整體面好壞而產生一致性偏差。各條件附帶繁體中文論述，引用具體數字佐證。

### 敘事動能追蹤（Narrative Momentum）
mdna_analysis 新增 `momentum` 欄位，追蹤前後期敘事語言的變化軌跡：
- `early_delta` / `mature_delta`：早期/成熟語言數量的前後期差異
- `direction`：accelerating（成長）/ stable / decelerating（退縮）
- Q1 與 10-K 比、Q2+ 與前一季比，quarter-over-quarter 追蹤敘事演進

## To Do
- 利用程式和 eval 降低對模型的依賴程度

## Quick Start

```bash
# 1. 建立環境
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install pango  # PDF 生成需要

# 2. 設定 API Key
cp config.example.json config.json
# 編輯 config.json 填入 anthropic_api_key

# 3. 執行（10-K 年報，自動比對前一年）
python main.py HWM 2025

# 執行（10-Q 季報，自動比對前期）
python main.py HWM 2025 --filing-type 10-Q --quarter Q1
```

## 設定檔

```json
{
  "anthropic_api_key": "sk-ant-...",
  "llama_cloud_api_key": "",
  "model": "claude-sonnet-4-5",
  "max_tokens": 4096,
  "max_tokens_by_skill": {
    "risk_analysis": 8192,
    "mdna_analysis": 8192,
    "cross_year_compare": 8192,
    "insight_synthesis": 8192
  }
}
```

## CLI 用法

```bash
# 完整分析（前期自動推算）
python main.py <TICKER> <YEAR>

# 10-Q 季報（Q1 比對 10-K，Q2+ 比對前一季）
python main.py <TICKER> <YEAR> --filing-type 10-Q --quarter Q1

# 手動覆蓋前期年份
python main.py HWM 2025 --prior-year 2022

# 指定本地檔案
python main.py HWM 2025 --file ./data/cache/htm/HWM_2025_10K.htm

# 只重跑特定 agent（其餘從快取載入）
python main.py HWM 2025 --only business,risk

# 清除 checkpoint 重新開始
python main.py HWM 2025 --clean

# 不發 API，用 mock 結果測試流程
python main.py HWM 2025 --dry-run
```

## Pipeline 架構

```
                         main.py
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         data_fetcher  doc_converter  section_splitter
         (EDGAR API)   (markitdown)   (TOC-guided + LLM fallback)
              │            │            │
              └────────────┼────────────┘
                           ▼
                     orchestrator.py
                           │
     ┌─────── Phase 1 (平行) ───────────────────────────┐
     │ business │ competitor_mapping │ risk │ mdna       │
     │ governance │ fn_* x8 │ terms_glossary             │
     │ supply_chain（10-K + Q1）                         │
     └───────────────────────────────────────────────────┘
                           │
     ┌─────── Phase 2 (序列) ─────────────────────┐
     │ 2a: financial (XBRL+FS+fn)               │
     │ 2b: segment_trend (XBRL+biz+mdna)        │
     │ 2c: three_statement_cross (financial+XBRL)│
     └──────────────────────────────────────────┘
                           │
     ┌─────── Phase 3 ────────────────────────────┐
     │ 3a: unusual_operations                     │
     │ 3b: rerate（3 條件平行）                     │
     │     ├── rerate_structure (segment_trend)   │
     │     ├── rerate_quality (3_statement_cross) │
     │     └── rerate_narrative (mdna)            │
     └────────────────────────────────────────────┘
                           │
     ┌─────── Phase 4 (Eval Loop) ─────┐
     │ hard_rule → schema → LLM eval   │
     │ FAIL → retry with hint (max 2)  │
     └─────────────────────────────────┘
                           │
     ┌─────── Prior Year (同 Phase 1+2) ┐
     └──────────────────────────────────┘
                           │
     ┌─────── Synthesis ───────────────┐
     │ cross_year_compare              │
     │ insight_synthesis               │
     └─────────────────────────────────┘
                           │
     ┌─────── Phase 5 ────────────────┐
     │ completeness_check (Grade A-D) │
     └────────────────────────────────┘
                           │
                     report_writer.py
                     ├── report.md
                     ├── report.pdf
                     └── raw.json
```

## Agent / Skill 清單

| Agent | Skill | Input | 說明 |
|-------|-------|-------|------|
| business | business_analysis | Item 1 | 公司定位、成長敘事、業務結構、競爭優勢 |
| competitor_mapping | competitor_mapping | Item 1 | 對手清單、市場定位、揭露品質（Q1 用去年 10-K baseline） |
| supply_chain | supply_chain_analysis | Item 1+1A+7+8 footnotes | 原物料、單一來源風險、地緣 / 集中 / 短缺分類、跨期改善/惡化訊號 |
| risk | risk_analysis | Item 1A | 風險清單、跨年變動、措辭強度 |
| mdna | mdna_analysis | Item 7 | 業績驅動因子、管理層語氣、承諾追蹤 |
| governance | governance_analysis | Item 9A+10+11+13 | 審計意見、薪酬結構、治理品質 |
| fn_revenue | footnotes_revenue | Note A+B | 收入認列政策、會計準則變動 |
| fn_segment | footnotes_segment | Note C+D | 部門結構、重組活動 |
| fn_receivables | footnotes_receivables | Note L+Q | 應收帳款證券化、債務結構 |
| fn_assets | footnotes_assets | Note M+N+O+R | 存貨、商譽、金融工具 |
| fn_risk | footnotes_risk | Note U+V+P | 或有負債、承諾、租賃 |
| fn_pension | footnotes_pension | Note G | 退休金資金缺口、精算假設 |
| fn_compensation | footnotes_compensation | Note I+J+K | 股權薪酬、EPS、AOCI |
| fn_tax | footnotes_tax | Note H | 所得稅、遞延稅、不確定稅務部位 |
| terms_glossary | terms_glossary | 全文摘要 | 術語表（附錄） |
| financial | financial_analysis | XBRL+FS+fn | 財務指標趨勢、交叉驗證 |
| segment_trend | segment_trend | XBRL+biz+mdna | 部門營收佔比趨勢、結構轉型識別 |
| 3_stmt_cross | three_statement_cross | financial+XBRL | 三表矛盾檢查、bullish/bearish 訊號 |
| rerate_structure | rerate_structure | segment_trend | 營收結構是否轉型（獨立判斷） |
| rerate_quality | rerate_quality | 3_stmt_cross | 營收品質是否改善（獨立判斷） |
| rerate_narrative | rerate_narrative | mdna | 敘事是否從計畫轉成果（獨立判斷） |
| unusual_ops | unusual_operations | fn+fin+原文 | 不尋常會計操作識別 |
| cross_year | cross_year_compare | 兩年結果 | 跨年度矛盾與印證 |
| insight | insight_synthesis | 全部結果 | Bull/Bear/追蹤指標 |
| completeness | completeness_check | 全部結果 | 六維度品質評分 |
| eval | eval_analysis | 各 agent 輸出 | LLM-as-Judge 品質評分 |

## 報告結構

1. 公司定位
2. Competitor Landscape（10-K / Q1，Q1 標註 baseline 來源）
3. 成長敘事 + 終端市場組合表
4. 供應鏈分析（10-K + Q1，6 子段：整體 / 原物料 / 主要風險 / 跨期變化 / MD&A 實際影響 / 採購承諾）
5. 整體信心
6. 多頭論點（Bull Case）
7. 空頭論點（Bear Case）
8. **評價趨勢判斷**（🟢🟡🔴 紅綠燈 + 論述）
9. 關鍵追蹤指標（未來兩季）
10. 10K 洞察（Information Edge）
11. 財務數據（指標表格 + 季度趨勢折線圖 + 資本配置）
12. 趨勢摘要 + 品質警示 + 異常值
13. 競爭壓力（即時訊號）（Q2/Q3 10-Q）
14. 跨年度分析
15. 不尋常操作
16. 交叉驗證
17. 附錄：關鍵術語

## Checkpoint / Resume

Pipeline 使用 per-agent checkpoint，支援中斷恢復：

- State 存在 `data/cache/pipeline_{ticker}_{year}.json`
- 每個 agent call 獨立記錄完成狀態
- 中斷後重跑自動跳過已完成步驟
- `--only task1,task2` 只重跑指定 agent，其餘從快取
- `--clean` 清除 checkpoint 重頭開始

## Context Log

每次 API call 自動記錄：

```
data/output/contexts/
  {timestamp}_{task_label}_request.md    ← system prompt + user input
  {timestamp}_{task_label}_response.md   ← raw output
data/output/usage.jsonl                  ← token 用量 + 成本 + skill version
```

## 專案結構

```
tenk/
├── main.py                          # CLI 入口
├── config.json                      # API key + model（.gitignore）
├── config.example.json              # 設定範本
├── requirements.txt
├── agents/
│   └── analyst_agent.md             # 共用 agent 定義
├── skills/                          # 24 個 skill .md
├── runtime/
│   ├── agent_runner.py              # Claude API + context log + dry-run
│   ├── orchestrator.py              # 多階段執行 + eval loop + checkpoint
│   ├── pipeline_state.py            # per-agent checkpoint/resume
│   ├── eval_runner.py               # hard rule + schema + LLM eval
│   ├── data_fetcher.py              # EDGAR HTM + XBRL
│   ├── doc_converter.py             # LlamaParse / markitdown
│   ├── section_splitter.py          # TOC-guided + LLM fallback + footnotes 切割
│   ├── report_writer.py             # 繁中 MD + PDF + 折線圖
│   ├── report.css                   # PDF 樣式
│   └── fonts/                       # Noto Sans TC（PDF 中文字型）
└── data/
    ├── cache/                       # HTM / MD / XBRL / pipeline state
    └── output/                      # 報告 + JSON + context log
```
