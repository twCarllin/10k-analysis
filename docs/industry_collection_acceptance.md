# 台股資料抓取：2026-10-13試跑

本輪完成抓取工具及核心20家公司試跑。資料仍有缺口。已有原檔、解析通過、視覺查核及使用者人工確認是不同狀態。

## 取得結果

|資料|目標|已有原檔|缺件|
|---|---:|---:|---:|
|2023–2025年報|60份公司年度|30|30|
|2024Q3–2026Q2財報|160份公司季度|64|96|
|2023-10–2026-09月營收|720筆公司月份|711|9|
|法說會季度資料|160份公司季度|14|146|
|24個月重大訊息|20家公司完整區間|0|20|
|產品／服務頁|20家公司|2|18|

年報及財報數包含45份本地原檔；新下載為15個年報年度及44個財報季度，共59份PDF。法說會實際保存21份PDF，含同一期不同版本及依會議日期標記的補件，不能把21份全部當成21個財務季度。月營收保存72份官方整批原表；711筆是去除重複来源後的公司月份。缺9個月份的是7769，原因是兩個官方市場表未找到該公司；不能因此判為營收零或未披露。

已取得2360及6139產品／服務頁。6223投資人訊息索引另存一份快照；此快照不代表24個月完整公告。各類資料的完整來源目錄仍有未取得項目。

依據：`data/industry_collection/core/summary.json`、`target-coverage.json`、`coverage-summary.md`、`index.json`。原檔在core/raw及pilot/raw；部分索引保留pilot的絕對原檔路徑。

## 來源失敗與解析缺口

22筆PDF請求失敗，原因為來源拒絕連線或下載頁未提供PDF連結。每個HTTP請求最多2次，未繞過來源保護。原始結果與重試清單保留。3個年報年度及3個財報季度雖有本地原檔，但本輪官方更新請求失敗；已有原檔不代表已取得最新版本。

PDF查核共126筆：45本地、59下載、22下載失敗。58筆為程式查核通過且人工待確認；68筆阻擋，含22筆下載失敗。未通過者保留期間、頁碼、單位、欄位、勾稽或解析缺口。新取得Q1/Q3等文件可保存原檔，但既有parser的期間模型不能支援所有格式；不直接產生可比較數字。

依據：`core/validation/report.json`、`review-queue.json`、`gap-queue.json/md`、`retry-manifest.json`。初次合併資料漏了目前版本索引，造成部分文件重抓；已合併current.json並續跑，原檔及中止／續跑紀錄保留。

## 來源查核

程式核對6945筆財務值的原頁、期間、欄位、數字及單位。這是來源匹配，不是使用者人工核准。

主flow另對照12個原始PDF頁面，視覺核對20筆財務值，分布於2360、2404、6139、6515的BS／IS／CF。第五家6223當期財報解析未通過，未補假數字。紀錄：`pilot/visual-check/checked.json`及四張原頁截圖。

核心20家公司只取得4筆可具名的T8關係：8046對南亞塑膠公司、南亞電子材料（昆山）公司，分別揭露2024及2025進貨。4筆已全數對照年報PDF第109頁（印刷頁103），仍保持pending。少於10筆，缺口6筆。匿名對象、合計、其他及純標點不當作公司。紀錄：`core/visual-check/relationships-checked.json`及原頁截圖。

合法來源組合已產生14個輸入版本，版本ID含年報與財報完整SHA256。可用於現有本地pipeline；同一期間不同版本保持分開。索引：`core/validation/report.json`的input_files及input_sources。

## 操作與重跑

```sh
.venv/bin/python -m runtime.industry_collection inventory
.venv/bin/python -m runtime.industry_collection plan
.venv/bin/python -m runtime.industry_collection discover --root data/industry_collection/core --interval 1
.venv/bin/python -m runtime.industry_collection collect --root data/industry_collection/core --interval 1
.venv/bin/python -m runtime.industry_collection discover-monthly --root data/industry_collection/core --interval 1
.venv/bin/python -m runtime.industry_collection collect --root data/industry_collection/core --manifest data/industry_collection/core/monthly-source-manifest.json --max-downloads 1000
```

先確認來源恢復，才用retry-manifest.json重跑失敗請求。補法說、公告及產品資料時使用官方source manifest，原文與來源必須可追查。validate只支援年報及財報PDF；其他格式的解析缺口會明示。更正版另存。每日更新命令見industry_collection.md；本輪未安裝排程。目標期間固定截至2026-10-13，新期間須先更新並核對公告狀態。

現有地圖程式及使用者原有修改保留。資料未自動匯入現有地圖或變更關係狀態。

## 流程與驗證紀錄（收尾驗證前快照）

- [x] step 1：兩個code-writer交付；知識與契約前置已附派工。
- [x] step 2：只stage本次程式、測試、文件及Spec。
- [x] step 3：公開資料契約直接交獨立code-reviewer審完整staged diff。
- [x] step 4：原4項重大問題已修正；具體引文經cite_check核對；最新程式審查零重大問題。
- [ ] step 5：本地測試與格式檢查；收尾全套結果由run_verify留痕。
- [ ] step 6：prepare、含Run-Id的commit、finalize。
- [x] step 7：retro已追加R-007至R-009。

收尾測試、提交及完成狀態以本地run manifest和Git的Run-Id紀錄為準，不以本文收尾前的待辦欄位判定。

原始證據在`run/2026-10-13-industry-data-collection-*`。資料完成度為partial；不能把工具驗收當作全數資料已取得。
