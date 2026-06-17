# DataSpider連携仕様

## 接続設定

| 設定項目 | 値 |
|---|---|
| アダプタ名 | SAP_RFC_ADAPTER |
| ホスト | sap-prod.hulft.co.jp |
| クライアント | 800 |
| 言語 | JA |

## スクリプト一覧

- `DS_001_Order_Extract.dss` — 発注データ抽出
- `DS_002_Order_Transform.dss` — データ変換・マッピング
- `DS_003_Order_Load.dss` — ANDPAD API送信

## 変換ルール

1. 日付変換: SAP内部日付(YYYYMMDD) → ISO8601(YYYY-MM-DD)
2. 金額変換: SAP通貨単位(1/100) → 実数
3. コード変換: SAPステータス → ANDPADステータス(マスタ参照)
