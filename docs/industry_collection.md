# 台股資料抓取

使用專案 Python。結果寫至獨立目錄，既有 PDF 僅供盤點。

```sh
.venv/bin/python -m runtime.industry_collection inventory
.venv/bin/python -m runtime.industry_collection plan
.venv/bin/python -m runtime.industry_collection discover --tickers 2360 2404 6139 6223 6515
.venv/bin/python -m runtime.industry_collection collect
```

不指定 `--tickers` 時，使用核心 20 家。`discover` 保存官方目錄 HTML 與
`source-manifest.json`。年報以財務年度後一年查詢股東會資料；財報以民國年度與季別查詢。
PDF 檔名只從官方目錄取得。下載頁先回傳連結，再下載及檢查 PDF 頁面。
原檔以 SHA256 保存。`index.json` 保存來源、期別、雜湊、UTC 抓取時間與修訂關係。
公告時間未知時為 null。月營收 API 只有最新月；程式核對公司與月份，歷史月份保留缺件。
法說、重大訊息與產品頁尚未自動支援。缺件狀態不表示公司未披露。

補件時，使用可追查的官方 URL 建立 JSON 清單，並以 `--manifest PATH` 載入。
每筆需有 `ticker`、`market`、`doc_type`、`period`、`basis`、`currency`、`unit`、
`announced_at`、`url`、`format`（pdf/json/html）。市場與單位未知可填 null。
保留官方查詢目錄 URL 與文件名稱，不能猜下載檔名。

續跑會先驗證快取雜湊及內容。損毀快取標記 failed，使用 `--refresh` 重抓。
修訂資料保存新版本，不覆寫舊原檔。個別文件失敗不停止其他文件。
每個請求間隔 0.5 秒，timeout 20 秒，最多 3 次。429 或伺服器錯誤可重試。
stdout 為 JSON；stderr 為診斷。可使用 `--log-level` 與 `--log-format text|json`。
診斷欄位包含 UTC timestamp、level、logger、event、message。

每日增量命令：先執行 discover，再執行 collect --refresh。此命令保存修訂版本，
不安裝排程。歷史目標固定截至 2026-10-13；新期間須先更新目標並核對公告狀態。

官方舊站的歷史月營收可使用共享查詢。每月查上市與上櫃表各一次，核對表頭月份與公司代號。

```sh
.venv/bin/python -m runtime.industry_collection discover-monthly --tickers 2360 2404 6139 6223 6515 --interval 1
.venv/bin/python -m runtime.industry_collection collect --manifest data/industry_collection/monthly-source-manifest.json
```

月營收原 HTML 在 discovery 時保存並校驗雜湊；collect 讀取該原檔，不按公司重抓整表。
`revenue_cells` 保存官方表格的當月、去年同月與累計欄位原文。不要把累計欄位當當月收入。
`--timeout` 預設 20 秒，`--attempts` 預設 3 次（最多5次），`--interval` 最少0.5秒。
`--max-downloads` 預設300筆；超出上限時命令停止，須明確指定新上限。
官方上傳時間另存 `uploaded_at` 與 `date_type=uploaded_at`，不當作首次公告時間。
正常下載為 INFO，重試為 WARNING，最終失敗為 ERROR。下載紀錄另存 downloads.jsonl。
命令完成診斷包含失敗筆數；JSON每筆狀態可供操作程式判定部分失敗。

`current.json` 保存各來源目前有效的版本；`index.json` 保存不同內容與來源。
若來源由 A 改為 B，再改回 A，續跑使用 A；原檔仍只保存兩個內容。
快取損毀時，普通續跑列 failed。`--refresh` 取得並驗證內容後，把損毀檔移至
`quarantine`，恢復原檔，並在 downloads.jsonl 記錄隔離檔路徑。
`validate --tickers` 只查核指定公司。

本輪試跑結果見 [industry_collection_acceptance.md](industry_collection_acceptance.md)。
驗證使用既有PDF parser，不呼叫付費OCR或模型。年報及財報的查核結果、缺口、完整來源組合與input_files會保存在validation/report.json。輸入按財報及年報的完整雜湊版本保存，不能手動覆寫。

```sh
.venv/bin/python -m runtime.industry_collection validate --root data/industry_collection/core --tickers 2360 2404 6139 6223 6515
```

此validate命令只解析年報及財報PDF。月營收、法說、產品及公告原檔保留，未提供相應parser時明示unsupported_local_parser。使用CLI的--tickers限制公司。資料有缺口時，先讀來源紀錄及review queue，再補件。
