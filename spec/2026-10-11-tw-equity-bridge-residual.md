# Spec：tw-equity 淨利／營業利益變動歸因的殘差收斂

- run_id：`2026-10-11-tw-equity-bridge-residual`
- 日期：2026-10-11
- 前一個 run：`spec/2026-10-11-tw-equity-sign-fix.md`（commit d30fd34）。符號修正後，85 家工業公司中，淨利 bridge 殘差超過目標變動 5% 的仍有 23 家，營業利益 bridge 有 8 家。
- 殘差來源的逐家診斷（2026-10-11，主 flow 用 `<scratch>/resid.py` 逐列對帳）：殘差都不是符號問題，而是有明細列沒有算進歸因。

## 1. 問題（逐家對帳結果）

殘差單位：億元。

| 類 | 原因 | 公司（殘差） |
|---|---|---|
| R1 | 營業利益 bridge 的組成項只有 revenue、cogs、total_opex，漏了 `other_operating_net`（其他收益及費損淨額）與 `ecl_operating` | 6770（134.20，等於其他收益及費損的變動）、2368（3.19）、2615（−2.17）、4904（0.66） |
| R2 | 預期信用減損：淨利 bridge 沒有列入 `ecl_operating`；而且標題變體沒對到：「預期信用減損迴轉利益」「預期信用減損利益(損失)」「預期信用(迴轉利益)減損損失」「預期信用減損損失(迴轉利益)」「預期信用減損損失(回升利益)」「預期信用減損(迴轉利益)損失」「預期信用減損(損失)利益」「非投資之預期信用減損損失」 | 2357（−54.70）、2376（−4.17）、3661（−2.13）、3443（−1.46）、2327、2412、2926、3045、4904、3533、6415、8299 |
| R3 | 權益法損益的標題變體沒對到：「採用權益法之關聯企業及合資損益份額」「採用權益法認列關聯企業及合資損益之份額」「採用權益法認列之關聯企業損益之份額」「…利益(損失)之份額」「…(損)益之份額」「…損失份額」「採用權益法之關聯企業損益份額」「採用權益法認列關聯企業損益之份額」 | 8299（66.83，等於全部殘差）、2327、2412、2492、2618、3045、3661、6415、2207、2357、3008、5347 |
| R4 | 業外明細沒有 key，各家名稱不同：金融資產評價損益（2207 36.95、6415 14.83、2327 7.77、2492 4.80、1101）、處分利益／損失、股利收入、租金收入、補償及理賠收入、什項支出（1519、2492、4904、5347）、「外幣兌換損失」（3533 11.12） | 同左 |
| R5 | 損益表只有「營業費用」一列（對到 `total_opex`），沒有推銷／管理／研發明細。淨利 bridge 的三費都是 None，整段營業費用漏掉 | 2615（−6.24）、2618（−4.18）、5871 |
| R6 | 成本應優先用 `cogs_total`（營業成本合計），bridge 目前用 `cogs`（銷貨成本）；另外幾個別名：「研發費用」→ rd_expenses（3008）、「管理及總務費用」→ admin_expenses（2207） | 1519（工程成本漏掉）、5871、3008、2207 |
| R7 | 停業單位：淨利 bridge 沒有「停業單位損益」組成項 | 2449（−30.53，等於去年同期停業單位利益 30.53） |
| R8 | 單步式損益表（2207）：收入與支出各只有合計，沒有 revenue／cogs／三費結構 | 2207（21.33） |
| 已知限制 | OCR 誤讀：1101 印章蓋住（本期營業成本讀成 30,477 仟元）；6223「推銷費用」讀成「匯銷費用」、小計列名不同 | 1101、6223 |

## 2. 修法

### 2.1 bridge 組成項（`metrics.py`）

- 營業利益 bridge：組成項加 `other_operating_net`、`ecl_operating`（R1）。
- 淨利 bridge：
  - 加 `ecl_operating`、`discontinued_ops`（新 key，「停業單位損益」「停業單位利益」「停業單位損失」「停業單位淨利」等）（R2、R7）。
  - `cogs` 改為候選：有 `cogs_total` 用它，否則用 `cogs`（R6）。
  - 三費（selling／admin／rd）全部缺值時，改用 `total_opex` 當一個組成項（R5）。
  - 加兩個合成組成項（R4）：
    - **其他營業費用** ＝ (operating_income − gross_profit) − Σ(selling、admin、rd、ecl_operating、other_operating_net 的已對到值)。
    - **其他營業外收支** ＝ (pretax_income − operating_income) − Σ(interest_income、other_income、other_gains_losses、finance_costs、equity_method_share、fx_gain_loss 的已對到值)。
    - 需要的小計缺值時，合成項為 None，不影響其他項。
    - 合成項要標記 `synthetic: true`，答案呈現時用這兩個名稱。
    - 單步式（R8）：有 `income_total` 與 `expense_total`、而且沒有 gross_profit／operating_income 時，淨利 bridge 改用 `income_total`、`expense_total`、`income_tax`、`discontinued_ops` 當組成項。
- 殘差的定義不變：目標變動 − Σ組成項變動。修完後殘差只剩四捨五入與 OCR 誤讀。

### 2.2 別名（`statements.py`）

- `ecl_operating`：補 §1 R2 所列的全部變體。
- `equity_method_share`：補 §1 R3 所列的全部變體。要附相近但不該對到的反例：OCI 區段的「採用權益法認列之關聯企業之其他綜合損益之份額」。
- `fx_gain_loss`：補「外幣兌換損失」「外幣兌換利益」。
- `rd_expenses`：補「研發費用」。`admin_expenses`：補「管理及總務費用」。
- `discontinued_ops`：新 key。

### 2.3 答案呈現（`qa.py`）

- 合成組成項在 bridge 答案中照一般項目寫，名稱用「其他營業費用」「其他營業外收支」。「其他營業費用」屬費用類，用費用句型。
- 停業單位損益用一般「變動」句型，名稱照帳本。

### 2.4 驗收輸出（`fs_acceptance.py`）

- `--all70` 的輸出加 bridge 殘差統計：對每家工業公司算淨利與營業利益 bridge 的殘差，SUMMARY 行加 `bridge_residual_gt5pct=<淨利家數>/<營業利益家數>`，並在每家的 JSON 記錄加 `bridge_residual`（兩個 bridge 的殘差與目標變動）。這是 RETRO 2026-10-11 約束的要求。

## 3. DoD

- 修完後，85 家工業公司中，淨利與營業利益 bridge 殘差超過 5% 的公司，只剩 1101 與 6223。要附全量前後比對。
- 2449 的淨利 bridge 出現「停業單位利益」組成項，變動 −30.53 億。
- 合成項測試：fixture 中有未對到 key 的業外列時，「其他營業外收支」等於這些列的合計；小計缺值時為 None。
- 新別名各有測試，含反例。
- 原本殘差已小於 5% 的公司，bridge 結果不變；或只多出合成項，而且合成項為 0。
- 回歸：101 家勾稽不變（`fs_acceptance --all70` 仍是 98/101）；FCF 與現金淨變動 bridge 不變；`fy_acceptance` 輸出不變；測試快照依 Spec 更新並逐項說明差異。

## 4. 不做

- CFO bridge 的組成項覆蓋率。
- 金控 bridge。
- 1101、6223 的 OCR。

## 5. 使用者裁示（2026-10-11）

- 使用者裁示處理這批殘差，並把 2449 的停業單位加進淨利 bridge 的組成項（只是歸因，勾稽仍不處理停業單位）。

## 6. 收尾結果（2026-10-11）

- 85 家工業公司：淨利與營業利益 bridge 殘差超過 5% 的公司，由 23／8 家降到只剩 1101、6223（OCR 已知限制）。殘差變大的只有這 2 家；既有組成項的變動只有 1519、5871（成本改用營業成本合計，R6）與 2207（單步式，R8）。
- 2449 的淨利 bridge 出現「停業單位利益」−30.53 億，殘差 0。
- 新對到 key 的列：ecl_operating 30 家、equity_method_share 19 家、fx_gain_loss 2 家、discontinued_ops 2 家、rd_expenses 2 家、admin_expenses 1 家。101 家勾稽不變（98/101）。`fy_acceptance` 輸出不變。
- 驗收 SUMMARY：`conform=98/101 known_limitations=3 exceptions=2 bridge_residual_gt5pct=2/2`。統計失敗時該家 `bridge_residual` 為 None，不影響 conform。
- 契約 1.3 仲裁：原文與 §2.1 衝突（新組成項本來就會吸收原本小於 5% 的殘差），Spec 優先，改為「既有組成項 delta 不變、殘差不可變大」。
- DoD 1.3 ③ 釐清：batch 的 bridge 只輸出 top_drivers 的 key，不帶 synthetic。
- 留作後續：目標變動極小時「占 X%」會很大（2618：−0.68 億的目標變動，占比 28032%），屬呈現問題；「其他營業費用」只在進入前 5 項時才出現在答案中。
