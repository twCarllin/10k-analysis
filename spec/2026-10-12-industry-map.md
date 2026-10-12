# 產業地圖第一版

## 目標與授權

使用者於 2026-10-12 指示「按照計畫執行吧」，授權建立資料盤點、共用格式、既有流程轉接、三個畫面及試點驗收。實作使用本地資料，不呼叫付費 API，不部署或 push。新建專用 SQLite，不變更既有資料庫。計畫確認沿用本次明確授權。

## 已核對的現況

- `data/output/**/*raw.json` 盤點指令得到 89 份、5 家（HWM、INTC、6315、3653、GEV）；`tw_equity_inputs/*.json` 有 101 家（本次 Python Path 盤點輸出）。
- 台股 raw 的 `bundle.statements` 有來源頁、科目、期間、單位及勾稽結果（`runtime/tw_equity/statements.py:32`、`:74`）。`bundle.metrics.metrics` 帶公式、輸入值及期間（`runtime/tw_equity/metrics.py:42`）。
- 台股批次 JSON 包含公司、來源文件路徑與雜湊、財務數值及期間，但不保留逐列頁碼（`runtime/tw_equity/batch.py:52`、`:84`、`:137`）。因此批次檔只能顯示數據出處，不能捏造原文定位。
- 年報/財報 PDF 可由 `load_pdf` 取得逐頁文字與來源頁碼（`runtime/tw_equity/pdf_doc.py:24`、`:34`）。
- 舊 US raw 的 `results.supply_chain.named_suppliers` 有未附引用的輸出，已見 `Mock Titanium Co.`；不得當成實際供應關係（檢查 `data/output/HWM/HWM_20260517_1712_raw.json`）。

## 情境

S1：研究者盤點本地資料，取得公司、資料類型、期間、來源與缺漏清單。
S2：研究者將台股 raw、台股 batch 或 US raw 轉為統一資料，保存關係、觀測值與證據，重跑無重複。
S3：研究者在產業環節瀏覽公司，搜尋產品/技術，選公司查看關係與財務，再選證據回查來源。
S4：研究者更新資料，保留歷史揭露，區分新增揭露、本期未揭露與已確認終止。
S5：研究者以本地 PDF 完成 15–20 家試點；無法證實的角色留待查核，缺漏不補猜。

## 資料契約 v1

Snapshot：schema_version=1，entities、roles、relations、observations、evidence、coverage、changes。
Entity：id、kind(company/product/technology/material/application)、name、aliases、market、ticker、owner_id；上市公司 ID 為 `company:{market}:{ticker}`；匿名交易對象 ID 必須含 owner_id，不合併跨公司或跨年度的匿名代碼。
Role：id、company_id、theme、stage、product、evidence_ids、status(confirmed/pending)。同公司可以有多角色。stage 用具體環節名稱。
Relation：id、source_id、predicate(supplies_to/competes_with/produces/uses/applies_to)、target_id、product、period、status(confirmed/pending/terminated)、evidence_ids。正式關係需原始文件的定位與支持該關係的摘錄；分析 JSON 的列路徑只能建立 pending。Mock/placeholder 結果不建立實際公司/關係。
Evidence：id、document、document_hash、locator、quote、period、source_type、checked_at。PDF 支持 1-based page，JSON 支持 pointer；來源類型分 primary 與 analysis。時間未知用 null。quote 必須來自對應來源，不能把 AI 分析當成原始披露。
Observation：id、company_id、metric、value、currency、unit、period、basis、scope(company/segment/unknown)、formula、inputs、evidence_ids、quality。財務單位與期間未知保留 unknown/null；缺值保留 null。觀測值使用既有帳本/指標，不重算未定義數字。
Coverage：每家公司列 sources、available、missing、warnings、excluded；來源混有模擬資料須明示。
Change：同具名關係在可比較兩期記 newly_disclosed/not_disclosed_this_period/unchanged；terminated 只允許明確證据或人工確認。

## 公開介面與演算法骨架

獨立套件 `runtime.industry_map`，避免改動 main.py 或既有輸出契約。Python 公開介面由實作者在 docs 定義，CLI：

```
.venv/bin/python -m runtime.industry_map inventory --root data/output --out DIR
.venv/bin/python -m runtime.industry_map build --root data/output --inputs tw_equity_inputs --out DIR [--tickers a,b] [--pilot] [--xbrl-dir DIR]
```

inventory(root) -> 逐檔檢查已知 raw/batch 格式，隔離壞 JSON；合併公司 coverage，寫 inventory.json/md。
normalize(record, metadata) -> Snapshot fragment；US 財務僅允許明確提供 metadata.xbrl_facts（SEC companyfacts）與 metadata.xbrl_source_path，保留原值、unit、start/end、fp/form與原始 pointer；raw 沒有原值時記 missing financial_raw，不使用 LLM 敘述補算。來源缺公司/期間時使用 metadata 或標未知；只引用明確存在的欄位。
merge(fragments) -> 依固定 ID 去重；同實體別名合併；不同期間的證據與關係皆保留；不按 mtime 宣稱財報最新。
persist(snapshot, sqlite) -> 專用資料庫唯一 ID upsert；讀回相同 snapshot，schema 版本不相符停止；禁止覆寫非本功能資料庫。
pilot(inputs, tickers) -> load_pdf 年報 + 合併財報，重用既有章節錨點與 extract_tables，取得帳本/指標/T8；角色由產品/業務章節內明確關鍵詞產生候選，原文查核後才 confirmed；不依公司知名度填關係。
render(snapshot) -> 產生無外部依賴 index.html + app.js + style.css + graph.json，可直接開啟；公司選取/篩選/比較/證據點選皆使用相同 snapshot。

## 試點

主題：半導體設備與材料，保留製造、封裝及測試為相鄰環節。選 20 家本地已有 PDF 的候選：2360、2404、6139、6223、6515、7769、6488、3532、2383、6213、6274、3037、3189、8046、2303、2330、2449、3711、6239、6770。公司是否屬此主題須由其年報產品/業務證據決定；沒有證據的候選可保留在待查核清單。美股轉接介面以實際 producer 形狀的 fixtures 驗收，模擬資料不混入真實試點。另以本地 INTC raw 與 data/cache/xbrl/xbrl_INTC.json（entityName=INTEL CORPORATION、cik=50863，Python讀檔查詢結果）補充跨市場示範；不呼叫API。

畫面：產業總覽（環節列、搜尋）；公司詳情（關係方向/產品/期間/狀態、財務）；證據側欄（原文/定位/日期/來源）。財務比較只允許相同指標、幣別、單位、完整期間、basis、scope；不能比較時說明差異，不隱性換匯或年化。

## 驗收與限制

- 每條 confirmed 關係/角色具有支持其內容的 primary 證據；pending 顯示狀態並可篩除。
- 固定 ID 重跑不重複；新期不覆蓋舊期；匿名不跨公司/年度合併；未再披露不當作終止。
- 每個數值保留來源與完整口徑；JSON-only 的頁碼未知明示；混合口徑不排名。
- 逐類資料契約有單元測試、每 task 有整合測試與 mutation 證據。fixture 各區塊附 producer 路徑與行號。
- 真實 20 家試點輸出 coverage、查核清單、地圖與驗收摘要；抽查至少 3 家 PDF 原文/頁碼及財務數值。
- HTML/JS 無 CDN；所有來源字串以 textContent 等安全方式呈現，嵌入 JSON 需逃逸 `<`，避免文件內容執行。
- 提交前完整 pytest、Black 26.5.1、獨立 code-reviewer 審查、run_verify 與 Run-Id commit/finalize。
- 不新增即時資訊或投資評分；外部資料補取與新產業在後续 run。

## 作廢舊行為清單

無。新增獨立資料層與 CLI；既有市場解析流程與財報輸出不改。

## 開放問題

無。技術細節依上述契約執行。既有未提交檔案歸屬等待使用者回答；本功能只新增自己擁有的檔案。
