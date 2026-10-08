---
skill_version: 1.0
last_modified: 2025-04-23
---

# three_statement_cross

## Purpose
在損益表、資產負債表、現金流量表之間找「對不起來」的地方。
機會和風險都藏在三表的矛盾裡，這是機構分析師的核心方法。

## Input
- financial_summary（必填）：financial_agent 輸出的 JSON 字串
- xbrl_json（必填）：完整 XBRL 數據，用於取細項（AR、Inventory、CapEx）
- retry_hint（選填）

## Instructions

### Step 1：建立四個核心追蹤指標的季度走勢
從 XBRL 取以下數據（季度，至少 4 季）：
- 營收（Revenue）
- 應收帳款（Accounts Receivable, AR）
- 存貨（Inventory）
- 資本支出（CapEx）
- 營業現金流（CFO）
- 自由現金流（FCF）

### Step 2：執行三表矛盾檢查

#### 矛盾檢查 A：營收 ↑ 但現金流 ↓
計算：AR / Revenue 比率的變化
- AR 成長速度 > 營收成長速度 → 收款出現問題
  - 若是新業務初期（SaaS 起步）→ 可接受（標記 watch）
  - 若持續惡化超過 2 季 → 危險（標記 warning）
- 存貨成長速度 > 營收成長速度 → 備貨 or 賣不掉
  - 若同時有新產品發布 → 可能是備貨（標記 watch）
  - 若營收沒有加速 → 需求錯判（標記 warning）

#### 矛盾檢查 B：營業利益 ↓ 但營收 ↑
判斷是「投資期」還是「惡化期」：
- 投資期（Bull）：R&D ↑ + SG&A ↑ + 毛利未崩 + 新業務佔比上升
- 惡化期（Bear）：費用 ↑ + 毛利 ↓ + 新業務沒有成長

#### 矛盾檢查 C：CapEx 有效性
- CapEx ↑ → 後續 1~2 年營收 ↑ + 毛利 ↑ → 有效投資（Bullish）
- CapEx ↑ → 營收持平 + 毛利 ↓ → 資本配置失敗（Bearish）

#### 矛盾檢查 D：庫存預測現金流
- 庫存 ↑ 超過 2 季 → 預警下季 CFO 將下滑
  （現金拿去做貨，還沒變收入）

### Step 3：使用機構判斷表輸出每個矛盾的判定結果

每個矛盾點輸出：
- signal_type：bullish / bearish / watch / neutral
- evidence：具體數字（e.g. AR +60%, Revenue +20%）
- interpretation：一句話解讀
- timeframe：短期現象 / 持續趨勢

## Output Format
```json
{
  "checks": {
    "revenue_vs_cashflow": {
      "ar_revenue_ratio_trend": "AR 成長 60%，Revenue 成長 20%，比率惡化",
      "inventory_trend": "存貨 +30%，與營收成長相符，備貨可能性高",
      "signal": "watch|bullish|bearish|neutral",
      "note": ""
    },
    "profit_vs_revenue": {
      "classification": "investing|deteriorating|unclear",
      "evidence": "R&D +40%，毛利率維持 45%，SaaS 佔比從 35% 升至 42%",
      "signal": "bullish|bearish|watch|neutral",
      "note": ""
    },
    "capex_effectiveness": {
      "capex_trend": "CapEx +50% YoY",
      "return_visible": true,
      "signal": "bullish|bearish|watch|neutral",
      "note": ""
    },
    "inventory_cashflow_predictor": {
      "inventory_buildup": false,
      "next_quarter_cfo_risk": "low|medium|high",
      "note": ""
    }
  },
  "overall_signals": [
    {
      "signal_type": "bullish|bearish|watch|neutral",
      "dimension": "profit_vs_revenue",
      "evidence": "具體數字",
      "interpretation": "短期壓利潤、投資新業務，毛利未崩，為 re-rate 鋪路"
    }
  ],
  "insufficient_data": false
}
```
