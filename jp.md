# 專案計畫：日股 EDINET 多 Agent 財報分析 Pipeline (v2.2)

> **Status**: Draft v2.2
> **Author**: Carl (林家逸)
> **Target executor**: Claude Code
> **Reviewer**: ChatGPT (cross-check)
> **目標範圍**: 全功能版（有報 + 半期報 + 臨時報 + TDNET + logmi 逐字稿）
> **架構策略**: 漸進式（先複製 SEC 邏輯，暫不抽 core，事後收斂）。`jp/` 與既有 `us/` SEC pipeline 平行，主要架構 pattern（prepare/strategy/orchestrator/eval_loop/llm_judge）跟著既有走。

---

## 1. 日本揭露制度速覽

### 1.1 法律框架

| 項目 | 對應 |
|---|---|
| 主法 | 金融商品取引法（金商法） |
| 主管 | 金融廳 (FSA) |
| 揭露系統 | **EDINET** + **TDNET** (兩套並行) |
| 等同物 | 美國 SEC EDGAR（但日本拆兩套） |

**雙系統的差異**：
- **EDINET**（金融廳）：法定揭露文件，有 API、有 XBRL，但**沒有即時推播**
- **TDNET**（東證）：適時開示（即時事件揭露），**沒有官方 API**，需 scrape

### 1.2 文件類型對照

| SEC | 日本（金商法） | 提交期限 | 本專案範圍 |
|---|---|---|---|
| 10-K | **有価証券報告書** (yūhō) | 會計年度結束後 3 個月內 | Phase 1A ✅ |
| 10-Q | ❌ **已於 2024 年 4 月廢止** | — | — |
| 10-Q (半年) | **半期報告書** | 半期結束後 45 日內 | Phase 1B ✅ |
| 8-K | **臨時報告書** | 事由發生時 | Phase 1B ✅ |
| 8-K (即時公告) | **適時開示** (TDNET) | 即時 | Phase 1C ✅ |
| 法說會 | **決算説明会** | 季度結束後 4–6 週 | Phase 1C ✅ |
| S-1 | **有価証券届出書** | 發行前 | ❌ |
| 13D/13G | **大量保有報告書** (5%) | 5 營業日內 | ❌ |

**重要**：日本季報於 2024/4 廢止，取而代之的是交易所層級的「四半期決算短信」（非金商法法定文件，內容較簡略）。本專案不直接處理短信，但 TDNET 監控會撈到。

### 1.3 EDINET API 的關鍵限制

EDINET v2 API 只有兩個 endpoint：

```
GET /documents.json?date=YYYY-MM-DD  → 列出某日全市場所有提報
GET /documents/{docID}               → 下載特定文件 ZIP
```

**沒有「按公司查歷史 filings」的 endpoint**。要拿到某公司歷史文件，必須按日期掃描，再用 `edinetCode` 過濾。

含意：必須暴力日期掃描 + 本地索引表 + 選擇性下載。一次掃描覆蓋全市場，未來擴展 watchlist 零邊際成本；EDINET rate limit 1 req/sec，5 年歷史一次性投入。本地用 DuckDB 存索引表，後續查詢全部走本地。

### 1.4 iXBRL 結構

EDINET 提交的有報為 **iXBRL (Inline XBRL)** 格式：

- 同一份 `.htm` 檔同時可給人讀（HTML）跟機器讀（XBRL）
- 章節以 `<ix:nonNumeric name="...">` 包覆，數字以 `<ix:nonFraction name="...">` 包覆
- Element name 來自 **jpcrp (企業内容開示府令) taxonomy**，FSA 強制標準化
- 全市場所有公司用同一套 element name → 跨公司分析友好

含意：本專案章節切割一律以 iXBRL element name 為 anchor，不用 regex。

### 1.5 TDNET 的特殊性（Phase 1C 才碰）

- 沒有官方 API，但網頁結構穩定：`https://www.release.tdnet.info/inbs/I_list_{NNN}_{YYYYMMDD}.html`
- 每天集中在 15:00–17:00 JST 大量湧入（業績發表集中日 5/10–15、11/10–15 更誇張）
- 同一家公司可能 5 分鐘內連發訂正版，需要去重邏輯
- 跟 EDINET 的「臨時報告書」**有部分重疊但不完全**：TDNET 範圍更廣（含業績速報、月次營收），臨時報告書範圍更窄（金商法強制揭露事項）

### 1.6 logmi Finance 的角色（Phase 1C）

- 日本最大免費決算説明会逐字稿媒體，掲載實績 1,700+ 家公司
- 含 Q&A 部分（這是法說會最值錢的內容）
- 沒有官方 API，需 scrape
- **版權考量**：自用、研究用 OK，商用需授權
- 對信用研究的最高價值：管理層對 outlook 的承諾強度評估（敬語層次）

---

## 2. 範圍切分：四個內部里程碑

### 2.1 切分原則

每個 Phase 都符合**獨立可驗收**：跑得起來、跑得完、有 demo 價值。任何 Phase 結束都不是「半成品」狀態。

**Phase 是決策邊界，不是時間估算**。Claude Code 的執行速度與人類工時不同 scale，本計畫不設「幾週完成」這類日曆估算。每個 Phase 結束點的意義是：

- **review 觸發點**：人類回來判斷成果品質、決定要不要進下一 Phase
- **scope creep 防火牆**：避免 Claude Code 在中段順手擴範圍
- **drift log review 時機**：重複代碼治理（§4.0）需要定期 review
- **可中斷點**：隨時可在 milestone 邊界停下不損失進度

### 2.2 Phase 1A：有報基礎 pipeline

#### In Scope
- EDINET 抓取層（日期掃描、本地索引、選擇性下載）
- Ticker ↔ EDINET code ↔ J-Quants code 對照表
- iXBRL 章節 splitter（基於 jpcrp element name）
- J-Quants 整合（財務數字）
- 五個核心 narrative skill：
  - `jp-risk-skill` (事業等のリスク)
  - `jp-mda-skill` (経営者による財政状態...分析)
  - `jp-business-skill` (事業の内容)
  - `jp-going-concern-skill` (継続企業の前提)
  - `jp-strategy-skill` (経営方針)
- `jp-financial-skill`
- Phase 1 平行執行 + Phase 2 sequential 整合
- Eval loop（從 us/ 複製，加日文 rubric）
- 繁中報告輸出
- TOWA (6315) 過去 3 年有報 end-to-end 驗證

#### Out of Scope
- 半期報、臨時報（Phase 1B）
- TDNET、logmi（Phase 1C）
- 跨年度 narrative diff（Phase 1D）
- Watchlist 多公司（單一公司驗收即可）

驗收標準：§7.1。

### 2.3 Phase 1B：半期報與臨時報擴充

#### In Scope
- EDINET doc_type=160 (半期報) 接入
- EDINET doc_type=180 (臨時報) 接入
- 半期報 iXBRL element name mapping（與有報不同）
- 臨時報事件分類器（M&A / 增資 / 重大契約 / 訴訟 / 災害...）
- 半期報 vs 有報的時間軸整合（避免重複算同一期）
- 報告輸出新增「近期事件」章節

#### Out of Scope
- 即時推播（Phase 1C 的 TDNET）
- 半期報跟前期有報的數字 reconciliation（Phase 1D）

驗收標準：§7.2。

### 2.4 Phase 1C：TDNET 與法說會逐字稿

#### In Scope
- TDNET 適時開示 scraper（含去重、訂正偵測）
- TDNET 公告分類（業績速報 / M&A / 業績修正 / 月次營收...）
- logmi Finance scraper（含 Q&A 段落辨識）
- `jp-earnings-call-skill`（Q&A 訊號分析、敬語強度評估）
- `jp-tdnet-event-skill`（即時事件影響評估）
- Event 模式 CLI: `jp.run watch`

#### Out of Scope
- 法說會投影片 PDF 分析（Phase 1D 可選）
- Whisper 音檔轉錄（不在本專案範圍）
- 真正即時推播（cron 模式即可，間隔 15 分鐘）

驗收標準：§7.3。

### 2.5 Phase 1D：品質提升與整合

#### In Scope
- 跨年度 narrative diff (risk section YoY)
- 半期報 vs 前期有報數字 reconciliation
- Eval rubric 精修（基於 Phase 1A–1C 的觀察）
- 報告品質提升（人工 review feedback loop）
- 完整文件：架構圖、SKILL.md 規格、troubleshooting
- Drift log review（決定要不要進 Phase 2 抽 core）

#### Out of Scope
- Phase 2 抽 core 動作本身（獨立 milestone）
- nanobot / Telegram 整合（Phase 2+）

驗收標準：§7.4。

### 2.6 永遠 Out of Scope

整個 Phase 1 都不會做：

- **對 us/ (現有 SEC pipeline) 的任何修改**
- 抽 core / 重構（保留給 Phase 2）
- 韓股接入（保留給 Phase 3）
- nanobot / autoresearch / Telegram 整合
- Watchlist 大規模平行（> 5 家公司）
- 即時推播（push notification）
- Whisper 音檔轉錄
- 投影片 PDF 圖表辨識

---

## 3. JP 特有契約（給 Claude Code 的明確介面）

> 本章只列**日股特有、不能從 us/ 推導的**契約。架構 pattern（檔案分層、orchestrator 平行/sequential、eval loop retry）一律跟著既有 us/ 既有實作走。

### 3.1 `jp/prepare.py` 主要 Functions

```python
# Phase 1A
def ensure_ticker_map_fresh(max_age_days: int = 30) -> None
def ticker_to_edinet(ticker: str) -> str
def fetch_edinet_index(d: date, api_key: str) -> list[dict]
def scan_date_range(start: date, end: date) -> None
def find_filings_local(edinet_code: str, doc_types: set[str], since: date | None) -> list[dict]
def download_filing(doc_id: str, out_dir: Path) -> Path
def fetch_jquants_statements(jquants_code: str) -> dict

# Phase 1B 沿用上述（doc_type=160/180 透過參數）

# Phase 1C
def scrape_tdnet(d: date) -> list[dict]
def scrape_logmi_for_ticker(ticker: str, since: date) -> list[dict]
def fetch_logmi_transcript(url: str) -> dict
```

關鍵設計：純 I/O 無 LLM 呼叫；Idempotent；checkpoint 機制（`shared_data/_scanned_dates.json`）；rate limit EDINET 1 req/sec。

### 3.2 `jp/strategy.py` 主要 Functions

```python
def find_ixbrl_main(zip_path: Path) -> Path | None
def split_filing_by_ixbrl(htm_path: Path) -> dict[str, str]
def split_risk_section(text: str) -> list[dict]
def extract_numeric_facts(htm_path: Path) -> list[dict]
def normalize_jp(text: str) -> str

# Phase 1B
def detect_filing_type(htm_path: Path) -> Literal["yuho", "hanki", "rinji"]
def classify_extraordinary_event(text: str) -> str  # M&A / 增資 / ...

# Phase 1C
def parse_logmi_transcript(html: str) -> dict  # 含 Q&A 段落辨識
def parse_tdnet_announcement(html: str) -> dict
```

### 3.3 Report Writer 輸出格式

讀 `jp/program.md` 生成繁中 markdown 報告。

**Batch 模式（Phase 1A）報告結構**：

```markdown
# {公司名稱} ({ticker}) 財報分析報告

> 期間: {period_start} - {period_end}
> 提報日: {submitted_at}
> 文件: {doc_type_name} (docID: {doc_id})

## 1. 公司概況
## 2. 財務時序（5 年表）
## 3. 風險敘事重點
## 4. 管理層分析 (MD&A) 摘要
## 5. 研發與策略
## 6. 信用觀察點
## 附錄：原文引用對照
```

**Phase 1B 新增 §7**：近期重大事件（半期報 + 臨時報）
**Phase 1C 新增 §8 §9**：近期適時開示（TDNET 30 天） / 最新法說會 Q&A 重點（logmi）

**Event 模式報告結構**：

```markdown
# {公司名稱} ({ticker}) 事件分析

> 事件: {event_title}
> 揭露: {disclosure_time} via {tdnet / extraordinary / logmi}

## 摘要（200 字內）
## 影響評估
## 信用面 read-through
## 原文引用
```

### 3.4 LLM 處理原則：直接餵日文，不翻譯

**所有日文 narrative 直接送進 Claude，不經翻譯層**。理由：敬語強度（「達成すべく取り組んでまいります」vs「達成に向けて努力してまいります」）是 guidance 訊號，翻譯會被壓平；漢字壓縮密度高，日文 token 數約英文翻譯版 60–70%；FSS 明示英文版不具法律效力，以日文為準。

含意：不需要日文分詞器；不需要術語對照表；報告**輸出層**用繁中（讀者是台灣使用者）；Prompt 設計需明確要求 Claude 用「日本 IR 文化」視角閱讀。

---

## 4. iXBRL Element → Skill Mapping（全功能版）

### 4.1 Phase 1A（有報核心章節）

| jpcrp Element Name | 章節中文 | Skill |
|---|---|---|
| `OverviewOfBusinessTextBlock` | 事業の内容 | `jp-business-skill` |
| `BusinessRisksTextBlock` | 事業等のリスク | `jp-risk-skill` |
| `ManagementAnalysisOfFinancialPositionOperatingResultsAndCashFlowsTextBlock` | 経営者による財政状態... | `jp-mda-skill` |
| `MattersRelatedToGoingConcernAssumptionTextBlock` | 継続企業の前提 | `jp-going-concern-skill` |
| `BusinessPolicyBusinessEnvironmentIssuesToAddressEtcTextBlock` | 経営方針 | `jp-strategy-skill` |
| `ResearchAndDevelopmentActivitiesTextBlock` | 研究開発活動 | `jp-rd-skill` |
| (財務數字 via iXBRL + J-Quants) | 経理の状況 | `jp-financial-skill` |

### 4.2 Phase 1B（治理、股東、半期報、臨時報）

| jpcrp Element Name | 章節中文 | Skill |
|---|---|---|
| `CorporateGovernanceTextBlock` | コーポレート・ガバナンス | `jp-governance-skill` |
| `InformationAboutOfficersTextBlock` | 役員の状況 | `jp-officers-skill` |
| `InformationAboutMajorShareholdersTextBlock` | 大株主の状況 | `jp-shareholders-skill` |
| (半期報用 jpcrp_sr 對應 element) | 半期報書き起こし | `jp-semi-annual-skill` |
| (臨時報內文) | 臨時報告書 | `jp-extraordinary-skill` |

### 4.3 Phase 1C（事件、法說會）

| 來源 | Skill |
|---|---|
| TDNET 公告分類後 | `jp-tdnet-event-skill` |
| logmi 法說會逐字稿（含 Q&A） | `jp-earnings-call-skill` |

### 4.4 Phase 1D（跨年度比較）

| 觸發 | Skill |
|---|---|
| YoY risk diff | `jp-risk-diff-skill` |
| 半期 vs 前期有報 reconciliation | `jp-reconciliation-skill` |

### 4.5 永遠不做的（範圍外）

- `OverviewOfAccountingEstimatesTextBlock` 等 IFRS 細項揭露 → Phase 2+ 再評估
- 子公司各別揭露
- 大量保有報告書（5% rule）

---

## 5. 任務拆解（給 Claude Code 的執行清單）

### 5.0 治理規則（執行任務前先讀）

採用漸進式策略意味著短期會有 jp/ 跟 us/ 的代碼重複。為避免長期 drift，本專案立下以下規則：

**規則 1：明確標註複製來源**

任何從 us/ 複製到 jp/ 的檔案，檔頭必須有：

```python
# COPIED FROM us/eval_loop.py at commit <hash> on <date>
# This duplication is intentional. See project plan §5.0.
# Do not refactor to import from us/.
# Future state: both us/ and jp/ will import from core/ in Phase 2.
```

**規則 2：建立 drift log**

`docs/jp/duplication_drift.md` 追蹤每個複製檔案：

```markdown
| File | Original | Last Synced | Status |
|---|---|---|---|
| jp/eval_loop.py | us/eval_loop.py | 2026-05-15 | matches |
| jp/llm_judge.py | us/llm_judge.py | 2026-05-15 | jp added 日文 rubric |
```

每完成一個 Phase milestone 時 review 這份表。

**規則 3：禁止反向 import**

`jp/` 不可以 `from us.eval_loop import ...`，反之亦然。如果發現需要 import，**那就是 Phase 2 抽 core 的訊號**。

**規則 4：不為未來韓股預留抽象**

`jp/` 就好好做日股，不為「未來會接 kr/」寫過度抽象的 code。Phase 2 才是抽象的時間。

---

任務按 Phase 1A → 1B → 1C → 1D 分組。每組內以 T{phase letter}.{number} 編號。

### 5.1 Phase 0：環境準備（跨 Phase 共用）

- [ ] **T0.1** 確認 EDINET API key 已申請，存到 `.env` 為 `EDINET_API_KEY`
- [ ] **T0.2** 確認 J-Quants 帳號已申請，refresh token 存到 `.env` 為 `JQUANTS_REFRESH_TOKEN`
- [ ] **T0.3** 建立 `research_pipeline/jp/` 目錄（與既有 `research_pipeline/us/` 平行），內部子目錄由後續任務逐步建立
- [ ] **T0.4** 在 `pyproject.toml` 加 dependencies：
  - 基礎：`httpx`, `beautifulsoup4`, `lxml`, `duckdb`, `pandas`, `pyarrow`, `tenacity`, `python-dotenv`
  - Phase 1C 加：`feedparser`（如 TDNET 有 RSS）、`playwright`（如 logmi 需要 JS render）
- [ ] **T0.5** 建立 `docs/jp/duplication_drift.md` 空表（§5.0 規則 2）

### 5.2 Phase 1A：有報基礎 pipeline

#### A1. Master data
- [ ] **TA1.1** 寫 `jp/scripts/build_ticker_map.py`：
  - 下載 JPX 上場銘柄一覧 Excel
  - 下載 EDINET CorpCode (API `/EdinetCode`)
  - Join 建立 `shared_data/master.duckdb` 的 `ticker_map`
  - Schema: `(jpx_code, edinet_code, jquants_code, company_name_ja, company_name_en, sector_code, market_segment, updated_at)`
- [ ] **TA1.2** 跑 TA1.1，確認 TOWA (6315 → E01708) 出現
- [ ] **TA1.3** `tests/jp/test_ticker_map.py`：驗證 TOWA、豐田 (7203)、軟銀 G (9984)、瑞穗 FG (8411)

#### A2. EDINET 抓取層
- [ ] **TA2.1** `jp/data_sources/edinet_client.py`：
  - `fetch_index(date, api_key)`：含 retry + rate limit
  - `download_doc(doc_id, api_key, out_dir)`：type=1
- [ ] **TA2.2** `jp/prepare.py` 的 `scan_date_range()`：
  - 寫入 `filings_index` 表
  - Schema: `(doc_id PK, edinet_code, doc_type_code, period_start, period_end, submitted_at, filer_name)`
  - Checkpoint 機制
- [ ] **TA2.3** `find_filings_local(edinet_code, doc_types, since)`
- [ ] **TA2.4** `download_for_watchlist(watchlist, doc_types)`
- [ ] **TA2.5** Backfill TOWA 過去 3 年：執行 `scan_date_range(2022-01-01, today)` 並下載 doc_type=120
- [ ] **TA2.6** 驗收：`data/raw/E01708/` 底下有至少 3 份有報 ZIP

#### A3. J-Quants
- [ ] **TA3.1** `jp/data_sources/jquants_client.py`：
  - `refresh_id_token(refresh_token)`
  - `fetch_statements(jquants_code, id_token)`
- [ ] **TA3.2** 整合進 prepare.py
- [ ] **TA3.3** 驗收：TOWA 的 J-Quants statements 抓下來，肉眼確認數字合理

#### A4. iXBRL 解析
- [ ] **TA4.1** `jp/ixbrl_parser.py`：
  - `find_ixbrl_main(zip_path)`
  - `parse_filing(zip_path)` 回傳 `{"facts": [...], "narratives": [...]}`
- [ ] **TA4.2** `jp/chapter_splitter.py`：
  - 定義 `JPCRP_CHAPTER_MAP_YUHO`（§4.1 七個 element）
  - `split_filing_by_ixbrl(htm_path) -> dict[chapter_key, text]`
- [ ] **TA4.3** `jp/strategy.py` 的 `split_risk_section(text)`：條目級拆解
- [ ] **TA4.4** `jp/normalizers.py`：NFKC + 全形/半形 + whitespace
- [ ] **TA4.5** Smoke test on TOWA 第 47 期，列印 element + 前 200 字確認
- [ ] **TA4.6** `jp/strategy.py` 整合，輸出到 `data/processed/{edinet_code}/{doc_id}/`

#### A5. Skill 文件
- [ ] **TA5.1** `jp/skills/jp-risk-skill/SKILL.md`
- [ ] **TA5.2** `jp/skills/jp-mda-skill/SKILL.md`
- [ ] **TA5.3** `jp/skills/jp-business-skill/SKILL.md`
- [ ] **TA5.4** `jp/skills/jp-going-concern-skill/SKILL.md`
- [ ] **TA5.5** `jp/skills/jp-strategy-skill/SKILL.md`
- [ ] **TA5.6** `jp/skills/jp-rd-skill/SKILL.md`
- [ ] **TA5.7** `jp/skills/jp-financial-skill/SKILL.md`

#### A6. Orchestrator（複製 + 改寫）
- [ ] **TA6.1** 複製 `us/orchestrator.py` → `jp/orchestrator.py`，**檔頭加 §5.0 規則 1 標註**
- [ ] **TA6.2** 複製 `us/eval_loop.py` → `jp/eval_loop.py`，同上
- [ ] **TA6.3** 複製 `us/llm_judge.py` → `jp/llm_judge.py`，同上 + 加日文 rubric 項目
- [ ] **TA6.4** 更新 `docs/jp/duplication_drift.md`（§5.0 規則 2）
- [ ] **TA6.5** 在 `jp/orchestrator.py` 改寫 chunk → skill mapping 為日文版
- [ ] **TA6.6** `jp/program.md`：報告生成指令（依 §3.3 輸出格式）

#### A7. CLI 與驗收
- [ ] **TA7.1** `jp/run.py` CLI entry：`report` 子命令
- [ ] **TA7.2** 跑 `python -m jp.run report --ticker 6315 --years 3`，產出報告
- [ ] **TA7.3** 人工 review，記錄問題到 `docs/jp/findings_1a.md`
- [ ] **TA7.4** 驗收（§7.1）

### 5.3 Phase 1B：半期報與臨時報

#### B1. 半期報擴充
- [ ] **TB1.1** `JPCRP_CHAPTER_MAP_HANKI`：半期報專用 element name（jpcrp_sr 前綴）
- [ ] **TB1.2** `detect_filing_type(htm_path)`：自動分辨 yuho / hanki / rinji
- [ ] **TB1.3** `jp/skills/jp-semi-annual-skill/SKILL.md`：半期報專用 skill（章節較少、聚焦變化）
- [ ] **TB1.4** Backfill TOWA 半期報 ZIP
- [ ] **TB1.5** 驗收：跑半期報能產出簡化版報告

#### B2. 臨時報接入
- [ ] **TB2.1** `JPCRP_CHAPTER_MAP_RINJI`：臨時報 element name
- [ ] **TB2.2** `classify_extraordinary_event(text)`：分類器（M&A / 增資 / 重大契約 / 訴訟 / 災害 / 役員異動...）
- [ ] **TB2.3** `jp/skills/jp-extraordinary-skill/SKILL.md`
- [ ] **TB2.4** 報告整合：新增「近期事件」章節

#### B3. 報告格式更新
- [ ] **TB3.1** 更新 `jp/program.md`：報告新增 §7（依 §3.3）
- [ ] **TB3.2** 半期報 vs 前期有報的時間軸去重邏輯
- [ ] **TB3.3** 驗收（§7.2）

### 5.4 Phase 1C：TDNET 與法說會

#### C1. TDNET scraper
- [ ] **TC1.1** `jp/data_sources/tdnet_scraper.py`：
  - `scrape_tdnet_index(date)`：解析 `I_list_{NNN}_{YYYYMMDD}.html`
  - 含 pagination、訂正偵測、去重
- [ ] **TC1.2** TDNET 公告分類器（業績速報 / 業績修正 / M&A / 月次營收 / 自家股取得進捗...）
- [ ] **TC1.3** `tdnet_seen.parquet` 本地去重表
- [ ] **TC1.4** `jp/skills/jp-tdnet-event-skill/SKILL.md`

#### C2. logmi scraper
- [ ] **TC2.1** `jp/data_sources/logmi_scraper.py`：
  - `search_for_company(jp_company_name)`：搜尋
  - `fetch_transcript(url)`：抓單篇逐字稿
- [ ] **TC2.2** `parse_logmi_transcript(html)`：辨識 Q&A 段落、講者
- [ ] **TC2.3** `jp/skills/jp-earnings-call-skill/SKILL.md`：
  - 敬語強度分級
  - Q&A 訊號分析（被迴避的問題、答覆強度）
  - 跟前期口徑比較
- [ ] **TC2.4** 版權聲明：`docs/jp/data_usage_terms.md`

#### C3. Event 模式
- [ ] **TC3.1** `jp/run.py` 新增 `watch` 子命令
- [ ] **TC3.2** `jp/run.py` 新增 `analyze-earnings-call` 子命令
- [ ] **TC3.3** Event 模式 report writer：短報告格式（依 §3.3）
- [ ] **TC3.4** 驗收（§7.3）

### 5.5 Phase 1D：品質提升與整合

#### D1. 跨年度 diff
- [ ] **TD1.1** `jp/skills/jp-risk-diff-skill/SKILL.md`：
  - Input: prev_year_chunk + curr_year_chunk
  - Output: 新增 / 削除 / 強化 / 弱化的條目
- [ ] **TD1.2** 整合進 Batch 模式報告（風險章節）

#### D2. Reconciliation
- [ ] **TD2.1** `jp/skills/jp-reconciliation-skill/SKILL.md`：半期報 vs 前期有報數字對帳
- [ ] **TD2.2** 異常 flag 機制

#### D3. 品質提升
- [ ] **TD3.1** 跑 Phase 1A–1C 所有 skill 各 ≥ 5 次，記錄 eval score
- [ ] **TD3.2** Eval rubric 微調（基於觀察的 false positive / negative）
- [ ] **TD3.3** Prompt 精修

#### D4. 文件
- [ ] **TD4.1** `docs/jp/README.md`：架構圖、執行方式、已知限制
- [ ] **TD4.2** `docs/jp/skill_glossary.md`：每個 skill 的職責、I/O contract
- [ ] **TD4.3** `docs/jp/troubleshooting.md`
- [ ] **TD4.4** 在 root README.md 新增日股 section
- [ ] **TD4.5** Review `docs/jp/duplication_drift.md`，決定 Phase 2 是否啟動

#### D5. 驗收
- [ ] **TD5.1** 驗收（§7.4）

---

## 6. Roadmap (Phase 2+)

### Phase 2: Core 重構（獨立 milestone）

**啟動條件**：
1. Phase 1A–1D 全部完成且穩定運作
2. 韓股接入需求出現（避免「兩個市場抽 core 還勉強，第三個進來才發現抽錯」）
3. 找到至少 3 個明確「兩邊 drift 但本質相同」的 module

不滿足以上條件，**Phase 2 不開工**。

**範圍**：
- 從 us/ + jp/ 抽 `core/eval_loop.py`、`core/llm_judge.py`、`core/base_agent.py`、`core/report_writer.py`
- 重新整理 us/ 把美國特有假設參數化（這次就是「重構 SEC」）
- jp/ 對應改 import 路徑
- 完整 regression test 確保兩邊都沒壞

### Phase 3: 韓股接入

- DART / OpenDART 接入
- K-XBRL element name mapping
- Chaebol 結構揭露分析（韓國特有）
- 韓文 narrative 直接送 LLM（同 §3.4 邏輯）

### Phase 4: 自動化與整合

- nanobot Telegram 串接
- autoresearch cron daily incremental
- Watchlist 大規模平行（20+ 公司）
- 跨市場 supply chain spillover 分析

### Phase 5: 進階功能

- 法說會音檔 Whisper 轉錄
- 投影片 PDF 圖表辨識（Vision LLM）
- 即時 push notification

---

## 7. 風險與已知問題

### 7.1 技術風險

| 風險 | 影響 | Mitigation |
|---|---|---|
| EDINET API rate limit | 抓取延遲 | tenacity retry、checkpoint、夜間跑 |
| jpcrp taxonomy 年度更新 | element name 微變 | mapping 表設計成可擴充 dict；每年 4 月人工 review |
| TDNET 沒有官方 API，網頁結構變動 | scraper 失效 | 隔離在單一 module；用 schema validation 早期偵測 |
| 公司財報用散文寫風險章節（無條目化） | risk_splitter 失效 | Fallback: 整段送 Claude 自己分 |
| iXBRL htm 內嵌大量圖片導致檔案巨大 | parsing 慢 | 解析時 skip `<img>` |
| LLM 對日文長 context 偶有失準 | 章節分析品質 | eval loop 接 retry；prompt 加強引用要求 |
| logmi 對 scraping 加 anti-bot | scraper 失效 | Playwright fallback；polite delay |
| TDNET 業績集中日（5/10–15）大量湧入 | event 處理延遲 | cron 間隔縮短到 5 分鐘；本地 queue |

### 7.2 資料品質風險

| 風險 | Mitigation |
|---|---|
| 訂正有報出現後舊版資料失效 | 偵測 `doc_type=130` 自動標註並重抓 |
| J-Quants 數字與 iXBRL 對不上 | financial_skill 加 reconciliation check |
| 公司會計年度變更（3 月 → 12 月） | period_end 為主鍵，不假設年度切點 |
| TDNET 同公告多訂正版 | timestamp + content hash 去重 |
| logmi 不同時期排版差異 | parser 寫成 lenient + 加 schema check |

### 7.3 架構風險

| 風險 | 影響 | Mitigation |
|---|---|---|
| **Code duplication drift** | jp/ 跟 us/ 的「複製檔」隨時間分歧，未來抽 core 困難 | §5.0 規則：drift log、檔頭標註、每 Phase milestone review |
| **過早抽象的反向風險** | 為了「準備 Phase 2」在 jp/ 寫過度抽象的 code | §5.0 規則 4：jp/ 就好好做日股，不為未來韓股預留 |
| **永遠不抽 core** | Phase 2 啟動條件太嚴格，core 重構無限延後 | §9 請 ChatGPT 攻擊這個條件；Phase 1D 後條件如已滿足要明確進 Phase 2 |
| **SEC pipeline 被間接影響** | jp/ 開發過程改了 shared_data 結構等共用點 | shared_data/ 只放純資料；任何 us/ 變動需明確 PR review |

### 7.4 範圍蔓延風險

明確排除在 Phase 1 外的項目（§2.6）必須在 Phase 1 結束前不去碰。每個 Phase 結束時 review §2 對應的 In/Out scope，發現偏離立即剎車。

---

## 8. 驗收標準

### 8.1 Phase 1A 驗收

1. `python -m jp.run report --ticker 6315 --years 3` 從零跑到底無錯誤
2. 輸出 `output/6315/{date}_report.md` 結構完整（§3.3 Phase 1A 七個章節都有）
3. 財務數字（營收、營業利益、總資產等）跟 TOWA 公司網站 IR 揭露**完全一致**
4. 風險章節至少抽出 5 個條目，每個都有 title + 分類 + 信用訊號評估
5. MD&A 章節能正確指出至少 3 個業績驅動因素並用日文原文引用佐證
6. Eval loop 至少跑過一次 retry 流程（人為注入錯誤驗證）
7. 重跑（mode=delta 等價）耗時 < 1 分鐘（驗證 cache 有效）
8. `docs/jp/duplication_drift.md` 記錄了所有複製檔案

### 8.2 Phase 1B 驗收

1. 半期報 ZIP 能解析，產出簡化版報告
2. 臨時報能被分類到正確類別（人工 spot check 10 份）
3. TOWA 過去 1 年所有臨時報都能跑出 event 報告
4. 報告 §7「近期重大事件」章節在 TOWA 報告中正確顯示
5. 半期報 vs 前期有報的數字不會重複計入 5 年表

### 8.3 Phase 1C 驗收

1. TDNET scraper 能穩定抓取單日全市場索引(無漏抓）
2. 業績集中日（取一個過去日期）能在 5 分鐘內處理完
3. TDNET 公告分類準確率 > 85%（人工 audit 50 份）
4. logmi scraper 能抓取 TOWA 最近 4 次法說會逐字稿
5. 法說會 skill 能識別 Q&A 段落並產出敬語強度評估
6. Event 模式 CLI 能對單一 TDNET 公告產出短報告
7. `docs/jp/data_usage_terms.md` 完成（版權聲明）

### 8.4 Phase 1D 驗收

1. 風險章節 YoY diff 能正確標出新增 / 削除 / 強化 / 弱化（人工 review TOWA 三年比較）
2. 半期報 vs 前期有報 reconciliation 能 flag 至少一次合理的差異
3. 所有 skill 的 eval 平均分數 ≥ 7
4. 完整文件齊全（§TD4）
5. Drift log review 完成，明確結論「進 Phase 2 / 暫不進」並有理由

---

## 9. 給 ChatGPT Review 的重點問題

### 9.1 架構策略
1. **§5.0 漸進式策略**：在 SEC 「能跑但結構偏亂 + 不可破」的約束下，選擇「jp/ 與 us/ 完全平行、暫不抽 core」是否合理？有沒有更聰明的做法？
2. **§6 Phase 2 啟動條件**：列出的三條件（Phase 1 穩定 + 韓股需求 + 找到 3 個 drift module）是否會導致「永遠不抽 core」？這個條件設得太嚴還是太寬？
3. **§5.0 重複代碼治理**：4 條規則是否足夠避免長期 drift？檔頭標註 + drift log + 禁止反向 import 這套機制有沒有漏洞？

### 9.2 範圍切分
4. **§2 四個 Phase 切分**：每個 Phase 是否真的「stand-alone 可驗收」？有沒有暗藏的跨 Phase 依賴？
5. **§2.6 永遠 Out of Scope**：把「不動 us/」列為硬性限制是否合理？會不會碰到 jp/ 開發中發現必須改 us/ 的情況？
6. **Phase 1A In Scope 邊界**：7 個 skill + 完整 pipeline 在一個 Phase 內，邊界是否切得太寬，導致 review 點到來時人類看不完？

### 9.3 技術決策
7. **§3.4 不做翻譯預處理**：對 LLM 直接餵日文的論述是否站得住？有沒有忽略的成本（例如 token 計費、特定模型對日文的弱項）？
8. **§1.3 EDINET 抓取策略**：暴力日期掃描 vs 其他方案的取捨是否合理？
9. **§4 章節 mapping**：MVP 選的 element 是否涵蓋足夠？有沒有更關鍵的章節遺漏？

### 9.4 任務拆解
10. **§5 任務粒度**：這個粒度是否適合 Claude Code 執行？哪些應該再拆細、哪些可以合併？
11. **複製動作 TA6.1–6.3 的執行順序**：在沒有 core/ 的情況下複製檔案，有沒有更安全的做法？

### 9.5 風險
12. **§7 風險清單**：有沒有遺漏的重要風險？特別是 §7.3 架構風險部分。
13. **§8 驗收標準**：是否足夠 objective、可驗證？

---

## 附錄 A: 參考資料

- EDINET API 仕様書: https://api.edinet-fsa.go.jp/api/auth/index.aspx
- jpcrp taxonomy: https://disclosure2.edinet-fsa.go.jp/weee0020.aspx
- J-Quants API: https://jpx-jquants.com/
- JPX 上場銘柄一覽: https://www.jpx.co.jp/markets/statistics-equities/misc/01.html
- TDNET: https://www.release.tdnet.info/
- logmi Finance: https://finance.logmi.jp/
- TOWA IR: https://www.towajapan.co.jp/ir/

## 附錄 B: 名詞對照表

| 日文 | 中文 | 英文 |
|---|---|---|
| 有価証券報告書 | 有報 | Annual Securities Report |
| 半期報告書 | 半期報 | Semi-annual Report |
| 臨時報告書 | 臨報 | Extraordinary Report |
| 適時開示 | 即時揭露 | Timely Disclosure |
| 決算短信 | 業績速報 | Earnings Flash |
| 決算説明会 | 法說會 | Earnings Call |
| 事業等のリスク | 事業風險 | Business Risks |
| 経営者による財政状態...分析 | 管理層分析 | MD&A |
| 継続企業の前提 | 持續經營疑義 | Going Concern |
| EDINET | — | Electronic Disclosure for Investors' NETwork |
| TDNET | — | Timely Disclosure Network |
| jpcrp | 企業内容開示府令 | (jp taxonomy prefix) |
| jpcrp_sr | 半期報用 taxonomy | (semi-annual taxonomy) |
