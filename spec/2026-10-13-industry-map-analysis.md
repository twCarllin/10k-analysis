# 產業地圖：交易資訊與四率比較

## 需求與授權
使用者要求在線上註明已揭露下單量；下游展開時直接比較毛利率、營業利益率、稅後淨利率、自由現金流／營收，並同意訂單資訊在線、比率在公司卡片或並列比較區、同期間同口徑、呈現年增百分點與可查看計算來源。
2 tasks / 4 items。Tier 2，complexity_reasons=[公開介面／落地資料契約]：relation 增加可選交易揭露欄位及 model 工廠参数，儲存與舊快照相容。

## 已查事實與範圍
- 現有 observation 有 formula/inputs/evidence_ids/quality（runtime/industry_map/model.py observation）；TW原始資料提供 % 比率，TW batch 同指標unit未知，兩者在snapshot共存（查詢 data/industry_map/snapshot.json：2360 毛利率61.48004374155741，%與unknown兩筆）。
- 資本支出 TW ledger 是負的現金流；現有 fcf formula=cfo+capex（runtime/tw_equity/metrics.py METRIC_SPECS）。US XBRL PaymentsToAcquirePropertyPlantAndEquipment 為支出額；公式需 cfo-支出，不可同用 cfo+capex。
- T8表抽取是歷史銷貨／進貨額，不是訂單（runtime/industry_map/pilot_candidates.py _t8_candidates）。可保留「已實現銷貨／進貨」及來源，不能宣稱下單。
- 既有四率觀測不能因未知單位重複列就全部擋住：可採唯一有完整 % 單位/period/basis/scope/finite值/evidence 的有效比率；相同有效觀測矛盾時標示衝突，不能猜值。

## 行為契約
A1 relation 可選 disclosures=[]。每筆含 kind(order_quantity/order_amount/backlog_amount/sales_amount/purchase_amount)、value、unit、currency、period、evidence_ids；無值或缺必要期間／單位顯示未揭露或資料不完整，不製造數字。已有factory/store/save/load/merge保持兼容，不改頂層schema_version。
A2 T8如有可驗證的數值及明確單位，保存原交易數值及其JSONpointer/PDF來源；無明確單位不猜，不用佔比計算訂單。
A3 毛利率=gross_profit/revenue*100；營益率=operating_income/revenue*100；稅後淨利率=net_income/revenue*100（整體稅後損益非歸母）；FCF營收率=(cfo-資本支出支出額)/revenue*100。優先採唯一完整 % 原比率，缺原比率可由同公司/完整期別/basis/scope/currency/unit的唯一已知金額推導，零營收/缺值/矛盾/不相容不得計算。保留 inputs/formula/evidence。
A4 TW ledger capex負→支出=-capex，XBRL acquisition-payment正→支出=capex；沒有可辨來源或矛盾符號則缺資料。FCF可負，不標好壞。
A5 期別正確處理ROC與西元；期間選單只來自目前中心+比較公司的相關資料、預設最新有可用比率的期別且明示（僅金額但四率全缺的更新期間不作預設；若全無比率，保留缺資料原因），不混季/H1/FY/TTM。所有並列共用相同期別、basis、scope，缺公司保留未匯入，不自動改該公司期別。同比只用去年同起迄/相同basis/scope，無則—，單位為百分點。
A6 公司中心及可見下游（沒有下游時可見同業、產業時可見公司）自動列出4率，不需加入。比較在主畫面保持可見，按數值看來源/公式，明示公司整體數值不代表單笔交易。無財務公司仍顯示行與缺資料原因。
A7 供應連線標示訂單量與期別；無訂單=下單量未揭露，已有其他交易金額獨立標籤，不混currency或訂單量；點線所有來源可讀，長字串安全textContent。多線標籤不能重新讓地圖滿版混亂，可用選取強調及compact badge/交易清單補足。
A8 公司卡片或緊鄰地圖的並列區一眼看到四率及同比變化，數值有中性bar/負值標示；點選、換中心、篩選、查看更多同步。保留現有比對防呆、圖狀態和來源。納入上次9行結果區可見性修正，其他 dirty tree 不動。

## 驗收
模型+存儲roundtrip、normalize/merge生產路徑、Node計算邊界、真Chrome自動表格/連線/期別切換/證據、手機無水平溢出。真21公司輸出重建，至少有台灣公司完整4率實例，所有真實訂單缺漏明示。所有資料本地，不新增外部fetch或CDN。主flow mutation FAIL→restore PASS。
