# 互動產業關係地圖

## 使用者目標與授權

使用者指示：希望像map，點產業/公司/服務後分散，連到上下游、競爭者。本session已授權改版；本次將主畫面換成節點及連線探索，不改資料層與市場解析，也不呼叫API、不push。UI收合審查出現1紅，依Router由Tier1升為Tier2，產品範圍與原2tasks/4items維持。

## 現有來源

snapshot工廠及ID在runtime/industry_map/model.py:29；roles保存company/theme/stage/product/evidence，relations保存source/predicate/target/period/status。原離線render(snapshot,out)與HTML嵌入在runtime/industry_map/render.py:196；CLI負責受管輸出（runtime/industry_map/__main__.py:52）。原JS createIndex/filter/select/compare由runtime/industry_map/assets/app.js提供，舊Node與CLI測試保留。

## 新行為

瀏覽器從同一snapshot建立內部圖，不更改snapshot檔案格式。導航根→產業與待分類；產業→有role的公司；公司→原product字串的共用產品/服務；原relations→原供貨方向/競爭線。共同產品不是競爭證據。匿名實體按原ID區分，不跨owner合併。

普通點選只展開及選取節點，不建立獨立入口。搜尋結果可成獨立入口，以探索未在初始圖的公司。收合父節點須移除只由該分支可達的子節點；其他展開分支可達的共用節點保留。關係篩選及詳情採同一方向/pending規則，選中公司在空關係時仍可讀。

SVG主畫布支持節點/背景拖动、縮放按鈕與滾輪、適合畫面、收合/重置、鍵盤選取。節點/連線中文類型、箭頭、競爭線型、待查核虛線及圖例。右側顯示選取詳情與真實證據；財務/比較收合為次要。長名稱及來源皆用安全textContent/createElementNS，HTML嵌入<仍逃逸，沒有CDN/fetch。

## 驗收

各task契約由task/2026-10-12-industry-map-graph.md單一維護。Node黑箱測試涵蓋資料、圖狀態、方向與來源。真實Chrome整合測試驗證點產業→公司→服務→收合父層；主flow另用21家快照驗搜尋INTC競爭者、供貨箭頭、點邊來源、pan/zoom/drag及手機寬度。保留口徑比較防呆與既有CLI輸出保護。獨立審查、Black、lint、完整pytest gate與Run-Id提交收尾。

## 作廢行為

主畫面不再以公司清單和巨量財務列表為中心。舊JS純API與legacy DOM只保留既有測試兼容性，新頁面由SVG UI啟動。

## 開放問題

無。原孤兒docs/research及產業檢核表_架構.md保留，不納入此run。
