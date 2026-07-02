---
name: debt-collection
version: 0.1.0
owner: yuya_tokuda@trees-catering.com
last_reviewed: 2026-07-02
status: draft
---

# Skill: debt-collection（未収入金回収）

## 役割

未収リストを入力として、段階別督促文（丁寧→期限明示→最終）を生成し、
回収追跡シート（DEBT_COLLECTION_LOG）の記録内容を出力する。

**AIが行うのは文章生成と記録内容の作成のみ。**
**送信・Sheets書き込み・金額変更は人間が行う。**

---

## 依存

- Agent: CFO Agent（`core/cash_flow.py` / `core/profit_leak.py`）
- Templates: `templates/debt-collection/lv1_polite.md` / `lv2_deadline.md` / `lv3_final.md`
- Sheet: `DEBT_COLLECTION_LOG`（Google Sheets）※書き込みは人間

---

## 入力スキーマ

```json
{
  "customer_name": "string（顧客名・必須）",
  "contact": "string（LINE/電話/メール・必須）",
  "amount": "integer（未収金額・円・必須）",
  "due_date": "YYYY-MM-DD（支払期日・必須）",
  "elapsed_days": "integer（経過日数・必須）",
  "contact_history": ["string（過去連絡履歴のリスト・任意）"],
  "next_payment_plan": "string（顧客が提示した次回支払予定日・任意）",
  "priority": "S|A|B（S=即日/A=3日以内/B=今週中・必須）",
  "owner": "string（担当者名・必須）",
  "send_approved": "boolean（送信可否。false=DRY_RUNのみ・必須）"
}
```

---

## 出力スキーマ

```json
{
  "level": "1|2|3（生成した督促レベル）",
  "message": "string（送信テキスト本文）",
  "send_channel": "LINE|email|phone（推奨送信手段）",
  "dry_run": "boolean（send_approved=falseの場合は常にtrue）",
  "log_entry": {
    "案件ID": "DC-{YYYYMMDD}-{連番}",
    "顧客名": "string",
    "未収金額": "integer",
    "Lv送信日": "YYYY-MM-DD",
    "状態": "Lv1送信|Lv2送信|Lv3送信"
  }
}
```

---

## 督促レベル判定ロジック（ルールベース）

| 条件 | レベル | 使用テンプレ |
|--|--|--|
| `elapsed_days < 7` | Lv1 | `lv1_polite.md` |
| `7 <= elapsed_days <= 14` | Lv2 | `lv2_deadline.md` |
| `elapsed_days > 14` または `priority == "S"` | Lv3 | `lv3_final.md` |
| `contact_history` に「Lv3送信済み」が含まれる | **エスカレーション** | 人間判断必須・AI出力停止 |

---

## 禁止事項（永久固定）

- `send_approved: false` の場合、外部への送信は絶対禁止
- AIが金額・期日を自動変更することは禁止（人間が入力した値をそのまま使う）
- 顧客の連絡先情報（電話番号・LINE ID等）をログに平文保存することは禁止（マスク処理必須）
- OpenAI API の使用禁止（ルールベース生成のみ）
- Lv3の送信をAIが自動実行することは禁止

---

## 人間確認ポイント（永久固定・省略不可）

1. **送信前**: 生成された全文・宛先・金額・期日を目視確認
2. **Lv3送信前**: 必ずオーナー（徳田）が承認してから送信
3. **回収記録時**: 入金額の確定はオーナーまたは担当者が確認・記録

---

## 改善方法

実行ログに「採用 / 修正 / 却下」をオーナーが1タップ記録する。
`weekly-review` Skill が修正パターンを集計し、`SKILL.md` の更新提案をPRとして生成する。
マージはオーナーが判断する。

---

## 再利用先

- 全事業の売掛管理（Catering / TACHINOMIYA / Tree Beauty / 琉球火鍋）
- 将来的にコンサル事業の回収管理にも横展開可能

---

## テストケース（最低3件・`tests/debt_collection/` に配置予定）

| ケース | elapsed_days | priority | 期待レベル |
|--|--|--|--|
| 通常入金遅れ | 3 | B | Lv1 |
| 週超え未入金 | 10 | A | Lv2 |
| 2週超え未入金 | 18 | A | Lv3 |
| Sリード未収（即日） | 5 | S | Lv3（優先度Sで上書き）|
| Lv3送信済みの再依頼 | 25 | S | エスカレーション（AI出力停止）|
