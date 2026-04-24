# 10-K Multi-Agent Investment Research Pipeline

從 SEC EDGAR 10-K 文件自動萃取投資 insight，使用 multi-agent + skill 架構。

輸入 ticker + 年份，輸出繁體中文 Markdown + PDF 報告，包含 Bull/Bear case、關鍵追蹤指標、財務數據表格與季度趨勢圖。

輸出結果請參考 INTC_20260425_014513_report.pdf

## Quick Start

```bash
# 1. 建立環境
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install pango  # PDF 生成需要

# 2. 設定 API Key
cp config.example.json config.json
# 編輯 config.json 填入 anthropic_api_key

# 3. 執行（10-K 年報）
python main.py HWM 2025 2024

# 執行（10-Q 季報）
python main.py HWM 2024 --filing-type 10-Q --quarter Q3
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
# 完整分析（當年 + 前年比較）
python main.py <TICKER> <YEAR> [PRIOR_YEAR]

# 指定本地檔案
python main.py HWM 2025 --file ./data/cache/htm/HWM_2025_10K.htm

# 只重跑特定 agent（其餘從快取載入）
python main.py HWM 2025 2024 --only business,risk

# 清除 checkpoint 重新開始
python main.py HWM 2025 2024 --clean

# 不發 API，用 mock 結果測試流程
python main.py HWM 2025 2024 --dry-run
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
     │ business │ risk │ mdna │ governance │ fn_* x8     │
     │ terms_glossary                                    │
     └───────────────────────────────────────────────────┘
                           │
     ┌─────── Phase 2 (序列) ───┐
     │ financial (XBRL+FS+fn)   │
     └──────────────────────────┘
                           │
     ┌─────── Phase 3 (序列) ──────────┐
     │ unusual_operations              │
     └─────────────────────────────────┘
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
| unusual_ops | unusual_operations | fn+fin+原文 | 不尋常會計操作識別 |
| cross_year | cross_year_compare | 兩年結果 | 跨年度矛盾與印證 |
| insight | insight_synthesis | 全部結果 | Bull/Bear/追蹤指標 |
| completeness | completeness_check | 全部結果 | 六維度品質評分 |
| eval | eval_analysis | 各 agent 輸出 | LLM-as-Judge 品質評分 |

## 報告結構

1. 公司定位
2. 成長敘事 + 終端市場組合表
3. 整體信心
4. 多頭論點（Bull Case）
5. 空頭論點（Bear Case）
6. 關鍵追蹤指標（未來兩季）
7. 10K 洞察（Information Edge）
8. 財務數據（指標表格 + 季度趨勢折線圖 + 資本配置）
9. 趨勢摘要 + 品質警示 + 異常值
10. 跨年度分析
11. 不尋常操作
12. 交叉驗證
13. 附錄：關鍵術語

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
├── skills/                          # 20 個 skill .md
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
