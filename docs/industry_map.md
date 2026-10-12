# 本地產業地圖

所有操作使用本地資料。核心試點為 Spec 的 20 家台股。INTC 是美股補充，不計入核心 20 家。不呼叫網路或 API。

## CLI

```sh
.venv/bin/python -m runtime.industry_map inventory --root data/output --out data/industry_map
.venv/bin/python -m runtime.industry_map build --root data/output --inputs tw_equity_inputs --out data/industry_map --tickers 2360,2404 --pilot
```

inventory/build 都接受 --root、--out、--inputs。build 可加 --tickers 逗號清單、--pilot、--xbrl-dir。未指定 tickers 的 pilot 使用 20 家台股。US ticker 不送台股 PDF 解析。--xbrl-dir 讀取 xbrl_TICKER.json。facts 每個 ticker 只讀一次，先保存內容雜湊版本，再建立原始 pointer。

--log-level DEBUG|INFO|WARNING|ERROR|CRITICAL 預設 INFO。--log-format text|json 預設 text。命令結果是 stdout JSON；診斷在 stderr，含 UTC timestamp、level、logger、event、message。輸入失敗退出 1；成功退出 0。

輸出：industry_map.sqlite、snapshot.json、graph.json、index.html、app.js、style.css、inventory.json/md、review_queue.json/md、coverage.json，以及 sources/。直接開啟 index.html。無 CDN。輸出目錄可以保留無關檔案；同名輸出檔需符合 .industry-map-ownership.json 雜湊，否則停止。已標記的 SQLite 允許透過公開 store API 寫入人工查核；重跑先驗證專用資料庫 schema。不要手動修改受管輸出檔。手工查核透過 Python API 保存狀態與真實 primary 來源，再由 CLI 重跑驗證來源。

當次資料先合併，歷史後合併；同 ID 更新當次值，不同舊期保留。未再披露不表示終止。confirmed/terminated 需要原始來源與支持摘錄；重跑重新載入來源查核。無法裁決的 XBRL 衝突值保留 null 與候選證據，不排名。

## Python 公開介面

- runtime.industry_map：snapshot、entity、role、relation、observation、evidence、coverage、stable_id 工廠；merge(fragments, sources=None, previous_period=None, current_period=None)；validate_snapshot；disclosure_changes。
- inventory.inventory(root, inputs='tw_equity_inputs', exclude=())：回傳 records/coverage/warnings；write_inventory(result,out)。
- adapters.normalize(record,metadata=None,source_path='')：產生快照片段。US 原值需 metadata.xbrl_facts 與 xbrl_source_path。
- store.save(snapshot,sqlite)、load(sqlite)：只接受本功能 SQLite v1。
- pilot.build_pilot(inputs_dir,tickers,out_dir,cache_dir=None)：本地 PDF 候選快照。
- render.query_map、company_detail、compare_financials：使用同一快照；render(snapshot,out) 產生離線畫面。
- __main__.main(argv=None)：CLI 入口，回傳退出碼。

匿名交易對象不跨公司或年度合併。分析 JSON 只能建立 pending；缺漏不猜。JSON-only 資料不提供虛構 PDF 頁碼。比較需同指標、幣別、單位、完整期間、basis、scope；不換匯、不年化。試點命令及人工查核欄位見 industry_map_acceptance.md。
