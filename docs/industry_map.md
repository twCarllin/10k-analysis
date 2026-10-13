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


## 地圖操作

開啟輸出目錄的 `index.html`。入口先顯示產業及待分類節點。點節點只更新詳情。按詳情的「以此為中心」，才切換中心。每次只顯示新中心與直接鄰居，前一中心的其他分支會移除。產品／服務中心可查看提供公司；共同產品不代表競爭。

每區預設顯示最多 5 個鄰居，採單列或單欄排列。工具區顯示剩餘數量；按「查看更多」每次增加 5 個。未顯示的關係與證據保留，顯示後可查看來源。換中心或返回時，各區恢復最多 5 個。

公司中心置中。上游在左，下游在右，競爭者在下，產品／服務在上。分類與產業導航有獨立標示。同一對象有多種關係時，卡片依上游、下游、競爭、提供、分類的順序選區；所有連線與來源仍保留。

「返回前中心」或中心路徑按鈕可返回。「收合中心一層」保留中心；再次按下可展開。「重置」回到產業入口。中心卡固定在分區原點；其他節點可拖動，拖背景可平移。初始、換中心、返回與「適合畫面」均以中心對稱縮放。縮放保留可讀下限；查看更多後，超出畫面的卡片可用背景平移查看。滾輪或 ＋／− 可縮放。「適合畫面」重新置中並調整縮放。Tab 選取節點或連線，Enter／空白鍵查看詳情。

搜尋包含名稱、代號、別名、產業及產品／服務。點搜尋結果直接設為新中心。方向篩選以中心為準，不隨詳情選取變動。關閉待查核會移除候選連線與僅由候選連線連接的鄰居，仍保留中心。關係數量只代表目前可見紀錄。無記錄或已篩除時會明示。

點節點或連線可查看右側詳情，含角色、關係兩端、期別、狀態及來源按鈕。匿名對象顯示披露公司；未知期別、缺證據與資料警告會明示。INTC 的競爭候選若仍待查核，須保持「顯示待查核」才可見；候選不等於已確認關係。來源原文與定位只呈現為文字，不執行其內容或外連。

公司財務與財務比較預設收合。在公司詳情按「加入財務比較」，會自動展開比較入口。只比較目前可見的公司；指標、完整期間、幣別、單位、basis、scope 必須一致。缺值或口徑不完整時阻擋，不換匯、不年化。地圖沿用現有 snapshot；不自動取得新資料。手機畫布在上，詳情在下。


四率比較區位於地圖上方，預設保持可見。公司中心自動比較中心及可見下游；無下游時比較可見同業。產業或產品中心比較可見公司。所有行使用同一期別、報表口徑與範圍。選單預設最新有可用比率的期別；缺資料的公司仍保留。同比使用去年同期間，單位為百分點。數字與中性色條不代表投資建議。

點四率數字可讀公式、輸入、當期與去年來源。比率是公司整體數值，不代表單筆交易。供應箭頭標示下單量與期間；未揭露時明示。下單金額、在手訂單、已實現銷貨與進貨分開呈現。點連線可讀完整交易及來源。缺單位、期間、幣別或來源時不顯示裸數字；矛盾揭露不選一筆或合計。手機比較表可在區內橫向捲動。

四率定義：毛利率＝毛利／營收 × 100；營業利益率＝營業利益／營收 × 100；稅後淨利率＝整體稅後損益／營收 × 100；自由現金流／營收＝（營業現金流－資本支出支出額）／營收 × 100。台灣現金流帳本的負資本支出轉成正支出額；XBRL 的收購資產支付額採正支出額。優先使用唯一完整的百分比觀測，缺值才用同公司、期別、口徑、範圍、單位及幣別的完整金額推導。未知來源、符號、零營收或矛盾資料不計算；自由現金流可為負值。
