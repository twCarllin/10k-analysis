# 產業地圖：關係強度、歷史趨勢及研究提示
## 授權與分級
使用者同意執行營收占比＋趨勢＋重點提示。沿用黑底已交付2檔76行（未提交），纳入本run；docs/research與產業檢核表_架構.md擱置。2tasks/4items，Tier2，complexity_reasons=[公開介面／落地資料契約]：既有relation.disclosures增加 sales_share/purchase_share 類型（沿用payload/store），來源與分母契約變動。預估90分鐘。無開放問題。
## 已查現況
pilot_candidates.py _t8_candidates 目前保存amount但沒保存entry.pct；來源 raw JSON的customers_sales是客戶銷貨占比、customers_purchase是進貨占比（tables.py CustomerEntry.pct）。現有app financialSummary/analysisComparison已可算四率與同比；TW資料多為兩個H1期別（snapshot查2360 H1 2025/2026），不能宣稱連續四季。現有模型、sourceproof、snapshotmerge/SQLite保留disclosures（model.py、store.py）。
## 契約
B1 T8 sales entry.pct→sales_share：分母為披露供應商同期總銷貨／營收；purchase entry.pct→purchase_share：分母為披露買方同期總進貨，不可稱營收占比。value有限0..100，unit%，currency null，period完整，evidence指向實際entry.pct。沒pct/不合法，不造數值；沿用匿名owner+period身份，不把不同期同名匿名客戶合併。merge/store不丟來源，矛盾揭露不擇一。
B2 financialTrend(index,id,metric,{period,basis,scope})回傳截至所選期別最多8個已匯入的同basis/scope/相同期間長度（差<=7日）的完整期別，按日期排序，每點含value/reason/formula/inputs/evidenceIds。同H1僅比較H1、US YTD與singlequarter不同長度不可連。不同公司各自有缺值仍共用頁面選期。沒有或僅1期明示，null/缺資料點斷線，不填補季度，不把只有2個H1稱四季。不顯示所選期別之後資料。
B3 researchSignals以已核對四率/同比/占比生成事實提示，每条含company/metric/period/evidenceIds/current&prior資料；描述升/降pp與可追查項目，不宣稱因果/預測/投資排序。例毛利delta<0且營益delta>0→『毛利率下降、營業利益率上升；可追查費用率或業務組合』；net_margin delta>0且abs(fcf_delta)<0.1pp→『稅後淨利率上升、自由現金流營收率大致持平；可追查營運資金與資本支出』。缺值/矛盾不能生成相應數字結論；0.1pp持平門檻要明示。占比明示實際分母/期間，不能自動判單一依賴/關係終止，沒資料提示補資料。
B4 供應線標營收占比或進貨占比+期間，線寬只依合法有證據的單筆同期間share決定（0也是已揭露、unknown非0）；多期展示各期不可加總/揉成一個分母，不同kind分開。圖只用該關係最新合法share（須單一期且唯一無矛盾；若最新披露矛盾/缺資料則不回退舊值）。如果sales/purchase同時有合法share，sales優先作線寬但圖例明示。原訂單量/金額/待查核標示及來源保留；標籤compact避免亂，右側完整來源。
B5 四率旁有可見sparkline/歷史入口及期別數，點趨勢點可看期別/值/來源；『研究重點』區常可見，最多3條首屏提示，可選其他公司查看，不隱藏data gaps。中心+下游/同業/產業群組與同一期選單同步；tips非任意同業排名。所有字串安全textContent，手機內部滾動無外溢，黑底對比清楚，不新增外部fetch/CDN。
## 驗收
真producer normalize/pilot→merge→store pct指標；Node三層函式邊界、中文提示不越界；真Chrome線寬/0未知/提示可見/趨勢點source/切期別/匿名/手機。主flow獨立2點mutation fail restorepass，21公司CLI重建與真2360圖：2025/2026H1兩期、客戶占比有年份、提示兩项可查證。最後全套無新增穩定失敗。
