# DualRAG — エンタープライズ設計書ドキュメント解析 & Dual-RAG ナレッジベース

Enterprise Design Document Parsing & Dual-RAG Knowledge Base

---

## 目次

0. [Quick Start / 最短手順](#0-quick-start--最短手順)
1. [プロジェクト概要](#1-プロジェクト概要)
2. [全体ワークフロー](#2-全体ワークフロー)
3. [S3 アップロードガイド](#3-s3-アップロードガイド)
4. [Project ID と Project Name](#4-project-id-と-project-name)
5. [環境構築](#5-環境構築)
6. [パイプラインの実行](#6-パイプラインの実行)
7. [ローカル出力構造](#7-ローカル出力構造)
8. [QA 対話ターミナル](#8-qa-対話ターミナル)
9. [エビデンストレーシング](#9-エビデンストレーシング)
10. [検証とトラブルシューティング](#10-検証とトラブルシューティング)
11. [制限事項と注意点](#11-制限事項と注意点)
12. [パイプライン安全ノート](#12-パイプライン安全ノート)
13. [納品チェックリスト](#13-納品チェックリスト)

---

## 0. Quick Start / 最短手順

以下の 5 ステップでドキュメントアップロードから QA まで完了できます。

```bash
# ① S3 にドキュメントをアップロード
aws s3 sync ./設計書/ s3://s3-hulftchina-rd/14_債務奉行クラウド/

# ② VLM で Excel を解析し Markdown に変換
dualrag parse --s3-prefix s3://s3-hulftchina-rd/14_債務奉行クラウド/ \
  --project-id "14_債務奉行クラウド"

# ③ Markdown → ベクトル KB (LanceDB) を構築
dualrag build-kb \
  outputs/14_債務奉行クラウド/run_20260602_072107/parsed/ \
  --project-id "14_債務奉行クラウド"

# ④ Markdown → グラフ DB (Neptune) を構築
dualrag graph \
  outputs/14_債務奉行クラウド/run_20260602_072107/ \
  --project-id "14_債務奉行クラウド" \
  --dry-run

# ⑤ 質問応答ターミナルを起動
dualrag qa --project-id "14_債務奉行クラウド"
```

> 💡 各コマンドの詳細は[パイプラインの実行](#6-パイプラインの実行)を参照してください。
> ⚠️ ステップ②で LibreOffice が必要です（[環境構築](#5-環境構築)参照）。

**マルチタイプ解析パス（Excel 以外のドキュメントを含むプロジェクト向け）：**

```bash
# ① プロジェクトをスキャン（S3 or ローカル）
dualrag project scan s3://s3-hulftchina-rd/14_債務奉行クラウド/ \
  -p "14_債務奉行クラウド" \
  --output outputs/14_債務奉行クラウド/run_YYYYMMDD_HHMMSS/project_manifest.json

# ② 全ファイルをマルチタイプ解析（PDF, DOCX, CSV, Image 等）
dualrag project parse-all -p "14_債務奉行クラウド"

# ③ 以降は同じ: build-kb → graph → qa
```

---

## 1. プロジェクト概要

### DualRAG とは

DualRAG は、日本企業の設計書（Excel ワークブック、PDF、CSV、フローチャート）を AI で解析し、**ハイブリッド検索（ベクトル + キーワード）+ グラフ検索**の Dual-RAG 手法を組み合わせた質問応答ナレッジベースを構築するパイプラインです。

**v1.0.0** では以下が実装されています：

- プロヴェナンス対応チャンク ID + 完全なグラフリンケージメタデータ
- ハイブリッド検索パイプライン（クエリ正規化 → インテント検出 → マルチクエリリライト → ベクトル+キーワード検索 → マージ）
- オプション Bedrock リランキング（amazon.rerank-v1:0）
- LanceDB ↔ Neptune chunk_id ベースのリンケージ
- QA ターミナルのグラフ表示を業務可読名に改善（4 フォーマット: compact/table/network/raw）
- `/save-graph`, `/save-trace`, `/ask-file`, マルチライン入力
- `project_mapping`, `_safe_str()` 共通化、keyword scan truncation warning

### 対象ドキュメント

| ドキュメント種別 | 具体例 |
|----------------|--------|
| Excel 設計書 | 業務プロセス図、マッピング定義書、API仕様書、IF定義書 |
| PDF 仕様書 | アプリケーション概要書、開発仕様書、API ガイド |
| CSV テストデータ | 入出力テストケース、ユーザー情報 |
| Mermaid ファイル (`.mmd`) | フローチャート ground-truth（存在する場合） |
| DOCX / HTML / 画像 / コード | 各種補足資料（マルチタイプ解析パス経由） |

特に以下のような**複雑な Excel 設計書**の知識抽出に対応しています：

- セル結合・色分け・矢印・図形で意味を伝えるレイアウト
- 複数シートにまたがるシステム間連携マッピング
- Excel 図形で描かれたフローチャート
- テーブル間・フィールド間のデータ変換ルール
- ステータス遷移、分岐条件、エラー処理ロジック

### 使用する AWS サービスとテクノロジー

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  ① S3          ソースドキュメントの保管場所                                  │
│  ② LibreOffice Excel → シート別 PDF 変換                                    │
│  ③ Bedrock     Claude Sonnet (VLM) で画像を視覚的に理解 → Markdown 生成     │
│  ④ Bedrock     Titan Embed V2 でテキスト → ベクトル変換                     │
│  ⑤ LanceDB    ベクトル検索用ローカルデータベース                             │
│  ⑥ Neptune    グラフ検索用グラフデータベース (openCypher)                     │
│  ⑦ Bedrock     Claude Sonnet で最終回答生成（マルチモーダル）               │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### なぜ Dual-RAG か

| RAG 方式 | 得意な質問タイプ | 質問例 |
|---------|----------------|--------|
| **Vector RAG** (テキスト類似度検索) | 「○○について教えて」型 | 「仕入伝票 API のデータ形式は？」 |
| **Graph RAG** (グラフ関係検索) | 「A と B の関係は？」型 | 「SAP から ANDPAD へのデータフローは？」 |

両方を組み合わせることで、テキスト類似度では見つからない構造的な関係も含めて質問に回答できます。

### なぜ VLM（視覚解析）か

日本企業の Excel 設計書は、セル結合・色分け・矢印・図形で意味を伝えます。通常のテキスト抽出ツール（openpyxl、pandas 等）ではレイアウトに含まれる視覚的知識を取得できません。

DualRAG では各シートを画像化し、Claude Sonnet のマルチモーダル機能で**視覚的に理解**することで、従来手法では抽出不可能だった知識を Markdown として構造化します。

---

## 2. 全体ワークフロー

```
 ┌─────────┐     ┌─────────────┐     ┌────────────┐     ┌──────────┐     ┌──────────┐     ┌─────┐
 │ S3 Upload│ ──→ │ dualrag parse│ ──→ │dualrag     │ ──→ │ dualrag  │ ──→ │ dualrag  │ ──→ │ QA  │
 │(ドキュメント)│     │(Excel→VLM)  │     │build-kb    │     │ graph    │     │ qa       │     │回答 │
 └─────────┘     └─────────────┘     │(ベクトルKB) │     │(グラフDB)│     └──────────┘     └─────┘
                                       └────────────┘     └──────────┘
```

**ステップ詳細：**

1. **S3 アップロード** — プロジェクト単位で Excel/PDF/CSV ファイルを S3 にアップロード
2. **`dualrag parse`** — S3 から Excel ファイルを取得し、Excel → PDF → PNG → VLM → Markdown に変換
3. **`dualrag build-kb`** — Markdown をチャンク分割して LanceDB（ベクトルDB）に格納
4. **`dualrag graph`** — Markdown からエンティティ/関係を抽出し Neptune（グラフDB）にロード
5. **`dualrag qa`** — 対話ターミナルで質問 → ベクトル検索 + グラフ検索 → マルチモーダル回答生成
6. **エビデンス参照** — 回答の根拠を元の PDF/画像/Markdown まで遡って確認可能

> 💡 **マルチタイプ解析パス:** Excel 以外のドキュメント（PDF, DOCX, CSV, 画像等）を含むプロジェクトは `dualrag project scan` → `dualrag project parse-all` で一括解析できます。詳細は [6.5 マルチタイプ解析](#65-マルチタイプ解析-dualrag-project-parse-all) を参照。

---

## 3. S3 アップロードガイド

### 推奨ディレクトリ構造

```
s3://s3-hulftchina-rd/
├── 14_債務奉行クラウド/                     # プロジェクト単位でディレクトリを分ける
│   ├── FY2024_HULFT Squareアプリケーション仕様書_債務奉行クラウド.xlsx
│   ├── FY2024_アプリケーション概要_債務奉行クラウド.xlsx
│   ├── FY2024_スクリプト試験票_債務奉行_export_debt_slip.xlsx
│   ├── FY2024_スクリプト試験票_債務奉行_import_buy_slip.xlsx
│   ├── 債務_APIデータ形式.xlsx
│   └── FY2024_レビュー記録表_*.xlsx
└── サンプル20260519/
    ├── MW_IFマッピング定義書_205_発注情報(登録・変更・取消).xlsx
    ├── M社様_DSSスクリプト改修概要_フローチャート.xlsx
    └── *.mmd                                # フローチャート ground-truth
```

**重要な原則：**

- プロジェクトごとに**独立した S3 ディレクトリ**を使用する
- 異なるプロジェクトのファイルを同じディレクトリに混在させない
- S3 ディレクトリ名がそのままプロジェクト識別子の基盤となる

### アップロード手順

```bash
# 単一ファイルのアップロード
aws s3 cp /path/to/設計書.xlsx s3://s3-hulftchina-rd/プロジェクト名/

# フォルダ全体を再帰的にアップロード
aws s3 sync /path/to/local_docs/ s3://s3-hulftchina-rd/プロジェクト名/

# アップロード確認
aws s3 ls s3://s3-hulftchina-rd/プロジェクト名/ --recursive
```

### Mermaid ファイル (.mmd) について

プロジェクト内に `.mmd` ファイルが存在する場合、それはフローチャートの **ground-truth**（正解データ）として扱われます。

- VLM がフローチャートを画像から推定するよりも、`.mmd` ファイルの内容を優先する
- `.mmd` は parse ステージで構造解析（ノード/エッジ抽出）され、`parsed/mermaid/` に出力される
- 他のシートから推定されたフローとの整合性確認にも利用される

---

## 4. Project ID と Project Name

### 概要

DualRAG はマルチプロジェクト対応で、複数プロジェクトのデータを同じ LanceDB / Neptune に格納しながら完全に分離できます。そのため、各プロジェクトに一貫した識別子を付与する必要があります。

| 用語 | 説明 | 使用箇所 |
|------|------|----------|
| `project_id` | 安定した識別子 | CLI の `--project-id` 引数、LanceDB フィルタ、Neptune プロパティ |
| `project_name` | 表示用の日本語名 | Neptune の表示ラベル、レポート |

### 推奨命名規則

| 項目 | 推奨フォーマット | 例 |
|------|-----------------|-----|
| `project_id` | S3 ディレクトリ名と一致させる | `14_債務奉行クラウド`, `サンプル20260519` |
| `project_name` | 人が読みやすい表示名 | `14_債務奉行クラウド`, `サンプル20260519` |

**重要:**  project_id を全コマンドで統一してください。

```bash
# ✅ 正しい: 全コマンドで同じ project_id を使用
dualrag parse --s3-prefix s3://s3-hulftchina-rd/14_債務奉行クラウド/ --project-id "14_債務奉行クラウド"
dualrag build-kb outputs/14_債務奉行クラウド/run_YYYYMMDD_HHMMSS/parsed/ --project-id "14_債務奉行クラウド"
dualrag graph outputs/14_債務奉行クラウド/run_YYYYMMDD_HHMMSS/ --project-id "14_債務奉行クラウド"
dualrag qa --project-id "14_債務奉行クラウド"

# ❌ 間違い: コマンドごとに project_id が異なる
dualrag build-kb ... --project-id "14_saimu_bugyo"    # ← 別の表記
dualrag qa --project-id "14_債務奉行クラウド"           # ← 正式名
# → build-kb のデータが qa で見つからない！
```

### なぜ一貫性が重要か

- **LanceDB**: `project_id` カラムで事前フィルタリング → 不一致だとチャンクが取得できない
- **Neptune**: `project_id` プロパティでノードを絞り込み → 不一致だとグラフが空に見える
- **QA**: ベクトル検索・グラフ検索の両方が project_id を使用 → 0件ヒットの主要原因

---

## 5. 環境構築

### 必要なソフトウェア

| ソフトウェア | 用途 | インストール |
|-------------|------|-------------|
| **Python 3.11+** | 実行環境 | `sudo apt install python3.11` |
| **uv** | パッケージ管理 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **AWS CLI** | AWS 認証・S3 操作 | `sudo apt install awscli` |
| **LibreOffice** | Excel → PDF 変換 | `sudo apt install libreoffice` |
| **poppler-utils** | PDF → PNG 変換 | `sudo apt install poppler-utils` |

### 必要な AWS リソース

| リソース | 用途 | 必須/オプション |
|---------|------|----------------|
| **AWS クレデンシャル** | 全 AWS サービスの認証 | ✅ 必須 |
| **Amazon Bedrock (Claude Sonnet)** | VLM 視覚解析 + 回答生成 + グラフ抽出 | ✅ 必須 |
| **Amazon Bedrock (Titan Embed V2)** | テキスト埋め込み（1024次元） | ✅ 必須 |
| **S3 バケット** | ソースドキュメント保管 | ✅ 必須 |
| **Neptune Analytics** | グラフデータベース | ⚠️ オプション |

> 💡 Neptune なしでも QA は動作します（ベクトル検索のみ）。`--no-graph` オプションで明示的にスキップ可能。

### インストール手順

```bash
# ① プロジェクトディレクトリに移動
cd ~/projects/hermes_bedrock_agent

# ② 依存関係をインストール（.venv/ が自動作成される）
uv sync

# ③ CLI 動作確認
uv run dualrag --help
```

以下の 6 コマンドが表示されれば成功です：

```
Commands:
  parse     Parse Excel/PDF files from S3 or local disk → VLM markdown (PRODUCTION).
  build-kb  Stage 2: Parsed markdown → LanceDB vector store + Neptune graph.
  qa        Stage 3: Interactive QA terminal or one-shot query.
  graph     Extract graph from vlm_parsed/ markdown and load into Neptune.
  project   Project scanning and manifest management.
  prompts   Manage graph extraction prompt versions.
```

### `.env` 設定

```bash
cp .env.example .env
```

以下の設定項目を環境に合わせて編集してください：

```bash
# ━━━━ 必須設定 ━━━━

# AWS リージョン
AWS_REGION=ap-northeast-1

# S3 バケット名
S3_BUCKET=s3-hulftchina-rd

# VLM モデル ID (視覚解析 + QA 回答生成)
# 重要: ap-northeast-1 では推論プロファイルプレフィックスが必須
# ✅ 正しい: jp.anthropic.claude-sonnet-4-6
# ❌ 間違い: anthropic.claude-sonnet-4-20250514-v1:0 (ValidationException になる)
BEDROCK_VLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6

# VLM フォールバックモデル ID (プライマリ失敗時に自動切替)
# 空文字の場合はフォールバックなし（従来と同じ動作）
BEDROCK_VLM_FALLBACK_MODEL_ID=mistral.mistral-large-3-675b-instruct

# 埋め込みモデル ID
BEDROCK_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0

# ベクトルDB ローカル保存先
VECTOR_LOCAL_STORE_PATH=~/projects/data/vector_store/lancedb

# ベクトルDB コレクション名
VECTOR_LOCAL_COLLECTION=dual_rag_default

# ━━━━ オプション設定 ━━━━

# Neptune Analytics グラフ ID (g-xxxxxxxxxx 形式)
# 未設定の場合、QA でグラフコンテキストが使われない
NEPTUNE_GRAPH_ID=g-xxxxxxxxxx

# グラフ抽出プロンプトバージョン (デフォルト: v4.3)
# 選択肢: v4.3, baseline, v4.4
GRAPH_PROMPT_VERSION=v4.3

# グラフ抽出モデル ID（未設定の場合 BEDROCK_TEXT_MODEL_ID → デフォルト jp.anthropic.claude-sonnet-4-6）
BEDROCK_EXTRACTION_MODEL_ID=jp.anthropic.claude-sonnet-4-6
```

**ap-northeast-1 でのモデル ID プレフィックスについて：**

東京リージョンでは Bedrock のモデル ID に**推論プロファイルプレフィックス**が必要です：

| プレフィックス | スコープ | 例 |
|---------------|---------|-----|
| `jp.anthropic.*` | 日本 | `jp.anthropic.claude-sonnet-4-6` |
| `apac.anthropic.*` | アジア太平洋 | `apac.anthropic.claude-sonnet-4-6` |
| `global.anthropic.*` | グローバル | `global.anthropic.claude-sonnet-4-6` |

利用可能なプロファイルの確認：

```bash
aws bedrock list-inference-profiles --region ap-northeast-1 \
  --query "InferenceProfileSummaries[].InferenceProfileId"
```

### LibreOffice の起動

Excel → PDF 変換には LibreOffice がバックグラウンドで動作している必要があります：

```bash
# ヘッドレスモードで起動（ポート 2002）
soffice --headless --accept="socket,host=localhost,port=2002;urp;" --norestore &

# 起動確認（3秒待ち）
sleep 3
lsof -i :2002
```

> ⚠️ LibreOffice は `dualrag parse` 実行時のみ必要です。
> `dualrag build-kb`、`dualrag graph`、`dualrag qa` には不要です。

---

## 6. パイプラインの実行

### 6.1 ステージ 1: ドキュメント解析 (`dualrag parse`)

S3 から Excel ファイルをダウンロードし、VLM で解析して Markdown に変換します。

**出力先:** `outputs/<project-id>/run_<YYYYMMDD_HHMMSS>/`

**基本コマンド：**

```bash
dualrag parse --s3-prefix s3://s3-hulftchina-rd/14_債務奉行クラウド/ \
  --project-id "14_債務奉行クラウド"
```

**ローカルファイルの直接解析：**

```bash
dualrag parse --file /path/to/設計書.xlsx --output-dir outputs/local_test
```

**全オプション：**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--s3-prefix` | S3 URI（`s3://bucket/prefix/` 形式） | なし |
| `--file`, `-f` | ローカルファイルパス | なし |
| `--output-dir`, `-o` | 出力先ディレクトリ（省略時 `outputs/<project-id>/run_<ts>/`） | 自動生成 |
| `--project-id` | プロジェクト ID | S3 プレフィックスから自動導出 |
| `--stages` | 実行ステージ: `all\|parse\|ingest\|images\|vlm` | `all` |
| `--mode` | LanceDB 書込モード: `append\|replace\|rebuild` | `append` |
| `--skip-graph` | Neptune グラフをスキップ | なし |
| `--log-level` | ログレベル | `INFO` |

**処理の流れ：**

```
① S3 Discovery    → プレフィックス配下の .xlsx 検出 + ダウンロード
② Excel → PDF     → LibreOffice (UNO) で各シートを個別 PDF に変換
③ PDF → PNG       → pdftoppm で PNG にレンダリング
                     - 小さいシート: 1 枚の full.png
                     - 大きいシート: 3000px タイルに分割（300px オーバーラップ）
④ VLM Parse       → Claude Sonnet が各画像を「見て」Markdown 生成
                     - シートタイプ自動検出（マッピング/フローチャート/仕様書 等）
                     - タイプ別の専用プロンプト使用
                     - マルチタイル合成（大きいシートは複数画像を統合解析）
⑤ Post-process    → Markdown 整形、YAML frontmatter 付加
⑥ Reorganize      → parsed/excel/<workbook>/ に canonical 構造で配置
                     + evidence/excel/<workbook>/ に PDF/PNG/metadata 保管
                     + legacy_compat/ にシンボリックリンク生成
⑦ Mermaid (任意)  → .mmd ファイル構造解析 → parsed/mermaid/ に出力
```

**所要時間の目安：**

| 対象 | 所要時間 |
|------|---------|
| 1 シート | 40〜120 秒 |
| 11 ワークブック・19 シート | 約 45 分 |
| 27 シートのワークブック | 30〜60 分 |

> ⚠️ VLM 解析を並列実行しないでください。タイムアウトカスケードが発生します。

---

### 6.2 ステージ 2: ベクトル KB 構築 (`dualrag build-kb`)

VLM 解析済み Markdown をチャンク分割し、**LanceDB（ベクトルDB）** に格納します。
このステップはベクトル検索の基盤を構築します。

**Unified ディレクトリ対応（推奨）:**

`dualrag parse` が生成する `parsed/` ディレクトリを直接指定できます：

```bash
dualrag build-kb \
  outputs/14_債務奉行クラウド/run_20260602_072107/parsed/ \
  --project-id "14_債務奉行クラウド"
```

**Legacy ディレクトリ対応:**

従来の `vlm_parsed/` 構造にも対応しています：

```bash
dualrag build-kb \
  outputs/サンプル20260519/run_20260602_074637/MW_IFマッピング定義書_205_発注情報(登録・変更・取消)/vlm_parsed/ \
  --workbook "MW_IFマッピング定義書_205_発注情報" \
  --project-id "サンプル20260519"
```

**全オプション：**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `PARSED_DIR` (引数) | `parsed/` (unified) または `vlm_parsed/` (legacy) ディレクトリ（必須） | — |
| `--workbook`, `-w` | ワークブック名（メタデータ用、legacy 向け） | ディレクトリ名 |
| `--project-id` | プロジェクト ID（**必須** — 省略には `--allow-global` が必要） | — |
| `--replace` | 既存プロジェクトデータを削除してから挿入 | False |
| `--allow-global` | `--project-id` なしでの操作を許可（**危険**: 全データ削除の恐れ）| False |
| `--skip-vector` | LanceDB 格納をスキップ | False |
| `--skip-graph` | Neptune グラフ（keyword）をスキップ | False |
| `--use-llm-graph` | Claude Sonnet でグラフ抽出（高品質、トークン消費） | False |
| `--dry-run-graph` | グラフ抽出のみ、Neptune に書き込まない | False |
| `--graph-delay` | LLM 呼び出し間隔（秒） | 3.0 |
| `--output-dir`, `-o` | chunks.jsonl 出力先 | `<parsed_dir>/../dual_rag/` |
| `--log-level` | ログレベル | `INFO` |

**重要な変更（`--append` 非推奨）:**

- デフォルト動作が **追記（append）** に変更されました
- `--append` は非推奨（no-op）です
- 既存データを置き換えたい場合は `--replace` を使用してください

```bash
# デフォルト: 追記（既存データを保持）
dualrag build-kb outputs/.../parsed/ --project-id "14_債務奉行クラウド"

# 明示的に既存データを削除してから挿入
dualrag build-kb outputs/.../parsed/ --project-id "14_債務奉行クラウド" --replace
```

> ⚠️ `--project-id` なしで `--replace` すると**テーブル全体のデータが削除**される可能性があります。必ず `--project-id` を指定してください。

---

### 6.3 ステージ 3: グラフ DB 構築 (`dualrag graph`)

プロジェクト全体の VLM 解析結果から、エンティティ（システム、API、テーブル、フィールド、ビジネスプロセス、マッピングルール等）と関係性を抽出し、**Neptune（グラフDB）** にロードします。
このステップはグラフ検索の基盤を構築します。

**グラフ抽出プロンプトバージョン:**

| バージョン | スコープ | アダプター | ステータス |
|-----------|---------|-----------|-----------|
| `v4.3` (デフォルト) | chunk | chunk_level | production |
| `baseline` | document | document_to_chunk | experimental |
| `v4.4` | document | document_to_chunk | experimental |

**基本コマンド：**

```bash
dualrag graph outputs/サンプル20260519/run_20260602_074637/ \
  --project-id "サンプル20260519"
```

**Dry-run（Neptune に書き込まず出力ファイルのみ生成）：**

```bash
dualrag graph outputs/サンプル20260519/run_20260602_074637/ \
  --project-id "サンプル20260519" \
  --project-name "サンプル20260519" \
  --dry-run
```

**プロンプトバージョン指定：**

```bash
dualrag graph outputs/14_債務奉行クラウド/run_20260602_072107/ \
  --project-id "14_債務奉行クラウド" \
  --graph-prompt v4.4 \
  --dry-run
```

**全オプション：**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `PROJECT_DIR` (引数) | プロジェクトディレクトリ（`parsed/` や `vlm_parsed/` を含む）（必須） | — |
| `--project-id`, `-p` | プロジェクト ID（**必須**） | — |
| `--project-name`, `-n` | 表示用プロジェクト名（日本語可） | — |
| `--graph-prompt` | プロンプトバージョン (v4.3, baseline, v4.4) | `GRAPH_PROMPT_VERSION` env or `v4.3` |
| `--dry-run` | Neptune に書き込まず出力のみ | False |
| `--skip-load` | Neptune ロードをスキップ | False |
| `--output-dir`, `-o` | 出力先 | `<project_dir>/graph_output/` |
| `--neptune-graph-id` | Neptune グラフ ID（.env を上書き） | .env の値 |
| `--delay` | LLM 呼出間隔（秒） | 3.0 |
| `--verbose`, `-v` | 詳細ログ出力 | False |

**出力されるファイル：**

```
graph_output/
├── <project_id>_nodes.jsonl                    # 全ノード (JSONL)
├── <project_id>_edges.jsonl                    # 全エッジ (JSONL)
├── <project_id>_nodes.cypher                   # ノード用 Cypher (MERGE 文)
├── <project_id>_edges.cypher                   # エッジ用 Cypher (MERGE 文)
├── semantic_map_import_full.cypher             # Neptune ロード用 Cypher（全件）
├── semantic_map_import_display.cypher          # Neptune ロード用 Cypher（表示用）
├── semantic_map_preflight_check.md            # 品質チェックレポート (P0/P1/P2)
├── semantic_map_graph_explore_queries.cypher   # 検証用クエリ集
└── semantic_map_extraction_report.md          # 抽出レポート（検証 Cypher 付き）
```

> 📌 **推奨パイプライン**: `dualrag build-kb`（ベクトル KB）→ `dualrag graph`（グラフ DB）の順で実行してください。
> `build-kb` にも `--use-llm-graph` オプションがありますが、`dualrag graph` はプロジェクト全体を横断的に分析するため、より高品質なグラフが得られます。通常は `dualrag graph` のみでグラフ構築してください。

---

### 6.4 ステージ 4: 質問応答 (`dualrag qa`)

構築したナレッジベースに対して質問応答を実行します。

**対話モード（推奨）：**

```bash
dualrag qa --project-id "サンプル20260519"
```

**ワンショットクエリ：**

```bash
dualrag qa --project-id "14_債務奉行クラウド" \
  "仕入伝票APIのデータ形式を教えてください"
```

**グラフなしモード（Neptune 未設定時）：**

```bash
dualrag qa --project-id "サンプル20260519" --no-graph
```

**全オプション：**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `[QUERY]` (引数) | ワンショットクエリ（省略で対話モード） | なし |
| `--project-id` | 対象プロジェクト ID（**推奨**: 指定しないと全プロジェクト横断） | 空 |
| `--mode`, `-m` | `answer` / `retrieve` / `graph` | `answer` |
| `--top-k`, `-k` | 取得チャンク数 (1–20) | 5 |
| `--no-graph` | グラフコンテキストをスキップ | False |
| `--vector-only` | `--no-graph` のエイリアス | False |
| `--collection` | LanceDB コレクション名を上書き（実験評価用） | なし |
| `--catalog-dir` | シート閲覧用ディレクトリ | なし |
| `--debug-retrieval`, `-d` | 検索の完全トレースを表示 | False |
| `--show-vector-trace` | ベクトル検索詳細を表示 | False |
| `--show-graph-trace` | グラフ検索詳細を表示 | False |
| `--show-context` | LLM 呼び出し前のコンテキスト全文を表示 | False |
| `--strict-project-isolation` | 異プロジェクトデータ混入時にエラー | False |
| `--graph-confidence-threshold` | グラフエッジの信頼度フィルタ | 0.0 |
| `--disable-keyword-boost` | キーワードスコアブーストを無効化 | False |
| `--log-level` | ログレベル | `WARNING` |

---

### 6.5 マルチタイプ解析 (`dualrag project parse-all`)

Excel 以外のドキュメント（PDF, DOCX, CSV, 画像, コード等）を含むプロジェクトに対し、ロール推定 + 戦略選択による一括解析を実行します。

**ワークフロー：**

```bash
# ① プロジェクトスキャン（マニフェスト生成）
dualrag project scan s3://s3-hulftchina-rd/14_債務奉行クラウド/ \
  -p "14_債務奉行クラウド" \
  --output outputs/14_債務奉行クラウド/run_YYYYMMDD_HHMMSS/project_manifest.json

# ② スキャン結果を確認
dualrag project status outputs/14_債務奉行クラウド/run_YYYYMMDD_HHMMSS/

# ③ 全ファイルを一括解析
dualrag project parse-all -p "14_債務奉行クラウド"

# ④ ドライランで分類のみ確認（解析実行なし）
dualrag project parse-all -p "14_債務奉行クラウド" --dry-run
```

**`project scan` オプション：**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `SOURCE` (引数) | S3 URI (`s3://bucket/prefix/`) またはローカルディレクトリ（必須） | — |
| `--project-id`, `-p` | プロジェクト ID | ソースから自動導出 |
| `--name`, `-n` | 表示用プロジェクト名 | なし |
| `--output`, `-o` | マニフェスト JSON 出力パス | `outputs/{project_id}/manifest.json` |
| `--log-level` | ログレベル | `INFO` |

**`project status` オプション：**

| オプション | 説明 |
|-----------|------|
| `PROJECT_DIR` (引数) | `manifest.json` を含むディレクトリ（必須） |

**`project parse-all` オプション：**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--project-id`, `-p` | プロジェクト ID（**必須**） | — |
| `--manifest`, `-m` | マニフェスト JSON パス | `outputs/{project_id}/manifest.json` |
| `--output`, `-o` | 出力ディレクトリ | `outputs/{project_id}` |
| `--dry-run` | 分類のみ実行、解析しない | False |
| `--force` | 既存出力があっても再解析 | False |
| `--skip-vlm` | VLM パーサー（PDF, Image）をスキップ | False |
| `--limit` | 最大解析ファイル数 (0 = 無制限) | 0 |
| `--log-level` | ログレベル | `INFO` |

**処理の流れ：**

```
① マニフェスト読込 → ファイル一覧
② ロール推定 (contract, specification, test_case, data_mapping, ...)
③ 戦略選択 (pdf_vlm, docx, csv, image_vlm, code, ...)
④ パーサーディスパッチ → YAML frontmatter 付き Markdown 生成
⑤ parsing_manifest.json に結果保存
```

**対応パーサー (11 種):** excel_vlm_adapter, pdf_vlm_parser, pdf_text_parser, docx_parser, csv_parser, doc_parser, image_vlm_parser, html_parser, code_parser, markdown_parser, mermaid_parser

> 💡 Excel ファイルは「既存パイプラインで処理済み」としてマーク（`already-handled`）されます。`dualrag parse` で先に Excel を処理してから `parse-all` で残りのファイル（PDF, CSV 等）を追加解析する運用が推奨です。

---

### 6.6 プロンプト管理 (`dualrag prompts`)

グラフ抽出プロンプトのバージョンを管理します。

```bash
# 登録済みバージョン一覧
dualrag prompts list

# 特定バージョンの詳細
dualrag prompts show v4.3

# 現在アクティブなバージョン
dualrag prompts current
```

プロンプトファイルは `prompts/graph_extraction/` に格納されています。バージョンは `prompts/graph_extraction/manifest.yaml` で管理されています。

---

## 7. ローカル出力構造

### `dualrag parse` の出力（Unified 構造）

```
outputs/<project_id>/run_<YYYYMMDD_HHMMSS>/
├── downloads/                                 # S3 からダウンロードした元ファイル
│   ├── *.xlsx                                #   Excel ワークブック
│   ├── csv/                                  #   CSV ファイル（サブフォルダ可）
│   └── *.pdf                                 #   PDF ファイル
├── parsed/                                    # ★ 最重要: canonical 解析結果
│   ├── excel/                                #   Excel 解析結果
│   │   ├── <ワークブック名>/
│   │   │   ├── sheet_01.md                  #   YAML frontmatter 付き Markdown
│   │   │   ├── sheet_02.md
│   │   │   └── sheet_03.md
│   │   └── <別のワークブック>/
│   │       └── sheet_01.md
│   ├── csv/                                  #   CSV 解析結果
│   │   └── <ファイル名>.md
│   ├── pdf/                                  #   PDF 解析結果
│   │   └── <ファイル名>.md
│   └── mermaid/                              #   Mermaid 解析結果（存在する場合）
│       └── mermaid_parsed.md
├── evidence/                                  # エビデンス（VLM 入力画像 + PDF）
│   ├── excel/
│   │   └── <ワークブック名>/
│   │       └── sheet_01/
│   │           ├── sheet_01.pdf             #   LibreOffice 変換 PDF
│   │           ├── full.png                 #   フルサイズ PNG
│   │           ├── vlm_annotated.png        #   VLM アノテーション付き画像
│   │           ├── metadata.json            #   タイル情報等のメタデータ
│   │           └── tiles/                   #   大きいシートの場合
│   │               ├── tile_r00_c00.png
│   │               └── tile_r00_c01.png
│   └── pdf/                                  #   PDF エビデンス画像
│       └── <ファイル名>/
│           ├── page_001.png
│           └── page_002.png
├── intermediates/                             # 中間ファイル（Mermaid 構造解析等）
│   └── mermaid/
│       └── <stem>/
│           ├── mermaid_raw.mmd
│           └── mermaid_structure.json
├── legacy_compat/                             # 後方互換シンボリックリンク
│   └── <ワークブック名>/
│       └── vlm_parsed/ → ../../parsed/excel/<workbook>/
├── parsing_manifest.json                      # ★ canonical 解析マニフェスト
├── parse_summary.json                         # [LEGACY] parse_summary
├── manifest.json                              # 構造マニフェスト
└── project_manifest.json                      # プロジェクトスキャン結果（scan 実行時）
```

### `dualrag project parse-all` の出力

```
outputs/<project_id>/
├── manifest.json                         # プロジェクトマニフェスト（scan で生成）
├── parsed/                               # マルチタイプ解析結果（YAML frontmatter 付き Markdown）
│   ├── excel/                           #   既存パイプラインの Excel 出力
│   ├── docs/                            #   PDF, DOCX 解析結果
│   ├── csv/                             #   CSV 解析結果
│   ├── images/                          #   画像 VLM 解析結果
│   └── code/                            #   コード解析結果
├── evidence/                             # エビデンス画像（VLM 入力に使用した PNG）
│   └── docs/
│       └── <safe_filename>/
│           ├── page_001.png
│           └── page_002.png
├── intermediates/                        # ダウンロード一時保存
│   └── downloads/
└── parsing_manifest.json                 # 解析結果マニフェスト（状態、メトリクス）
```

### 各ディレクトリの役割

| ディレクトリ | 用途 |
|-------------|------|
| `downloads/` | S3 からダウンロードした元ファイル（ソースのローカルコピー） |
| `parsed/` | **最重要**: 全パーサーの解析結果 Markdown。後続の全ステージがここを参照 |
| `evidence/` | VLM に入力した画像・PDF。エビデンストレーシングの中間層 |
| `intermediates/` | 中間処理ファイル（Mermaid 構造、一時ダウンロード等） |
| `legacy_compat/` | 旧構造互換のシンボリックリンク |
| `graph_output/` | グラフ抽出の全成果物（`dualrag graph` 実行後に生成） |

### YAML Frontmatter

`parsed/` 内の全 Markdown ファイルは YAML frontmatter を含みます：

```yaml
---
project_id: "サンプル20260519"
source_file: "s3://s3-hulftchina-rd/サンプル20260519/MW_IFマッピング定義書_205_発注情報(登録・変更・取消).xlsx"
source_type: "excel"
document_type: "excel"
document_role: "data_mapping"
parser_type: "excel_vlm"
document_id: "a1b2c3d4e5f67890"
document_name: "MW_IFマッピング定義書_205_発注情報(登録・変更・取消)"
workbook_name: "MW_IFマッピング定義書_205_発注情報(登録・変更・取消)"
sheet_index: 1
sheet_name: "sheet_01"
display_name: "MW_IFマッピング定義書_205_発注情報(登録・変更・取消) / sheet_01"
unit_type: "sheet"
parsed_at: "2026-06-02T07:46:37.123456"
parser_version: "2.1"
evidence_path: "evidence/excel/MW_IFマッピング定義書_205_発注情報(登録・変更・取消)/sheet_01/"
evidence_paths:
  - "evidence/excel/MW_IFマッピング定義書_205_発注情報(登録・変更・取消)/sheet_01/sheet_01.pdf"
  - "evidence/excel/MW_IFマッピング定義書_205_発注情報(登録・変更・取消)/sheet_01/full.png"
---
```

### 7.5 セマンティック・チャンキング

`dualrag build-kb` は Markdown をチャンク分割する際に、テキストの意味的まとまりを保つセマンティック分割を行います。

**チャンキング設定（`.env`）：**

| 環境変数 | 説明 | デフォルト |
|---------|------|-----------|
| `CHUNK_MODE` | チャンキング方式 (`semantic`) | `semantic` |
| `CHUNK_SEMANTIC_MAX_CHARS` | チャンク最大文字数 | `4000` |
| `CHUNK_SEMANTIC_GROUP_TARGET` | グループ目標文字数 | `2000` |
| `CHUNK_STRATEGY_ENABLED` | タイプ別特殊戦略を有効化 | `false` |

**タイプ別チャンキング戦略 (`CHUNK_STRATEGY_ENABLED=true`)：**

ドキュメントタイプに応じた専用分割ロジックを適用します。

| 戦略 | 対象 | ステータス |
|------|------|-----------|
| `MermaidFlowchartStrategy` | Mermaid フローチャート（ノード/エッジの構造保持） | ✅ 実装済み |
| `DefaultSemanticStrategy` | 一般的な Markdown テキスト（フォールバック） | ✅ 実装済み |
| `SingleChunkStrategy` | 短いドキュメント（分割不要） | ✅ 実装済み |

戦略レジストリ (`chunker_strategies/registry.py`) がドキュメントの `source_type` / `parser_type` を元に適切な戦略を選択します。

### 7.6 プロヴェナンス対応 chunk_id

各チャンクには以下のフォーマットで決定論的な ID が割り当てられます：

```
{source_type}_{document_id}_{unit_label}_c{chunk_index:03d}_{content_hash}
```

**例：**

```
excel_a1b2c3d4e5f67890_sheet_01_c001_f3a1b2c3
```

**特性：**

- **決定論的**: 同じ入力から同じ chunk_id が生成される（再ビルド時の一貫性）
- **プロヴェナンス対応**: chunk_id からソースタイプ、ドキュメント、ユニット、位置が特定可能
- **LanceDB ↔ Neptune リンケージ安全**: chunk_id をキーとして両データベース間の照合が可能

### 7.7 LanceDB メタデータ

LanceDB に格納される各チャンクは、以下のグラフリンケージ用メタデータを保持します：

| フィールド | 説明 | 例 |
|-----------|------|-----|
| `project_id` | プロジェクト識別子 | `サンプル20260519` |
| `chunk_id` | プロヴェナンス対応 ID | `excel_a1b2_sheet_01_c001_f3a1` |
| `document_id` | ドキュメント固有 ID (SHA256 16桁) | `a1b2c3d4e5f67890` |
| `document_name` | ドキュメント表示名 | `MW_IFマッピング定義書_205_発注情報` |
| `document_type` | ドキュメント種別 | `excel` |
| `unit_type` | 分割単位 | `sheet` |
| `source_markdown_file` | 解析結果 Markdown パス | `parsed/excel/.../sheet_01.md` |
| `evidence_path` | エビデンスディレクトリ | `evidence/excel/.../sheet_01/` |
| `evidence_paths` | エビデンスファイル一覧 | `[".../sheet_01.pdf", ".../full.png"]` |
| `content_hash` | コンテンツ SHA256 (短縮) | `f3a1b2c3` |
| `source_file` | S3 ソースファイルパス | `s3://bucket/project/file.xlsx` |
| `source_type` | ソース種別 | `excel` |
| `parser_type` | パーサー種別 | `excel_vlm` |
| `chunk_type` | チャンクの内容分類 | `mapping_table`, `flowchart`, `api_spec` |

これらのメタデータにより：

- **QA 検索結果からソースまで完全に追跡可能**（エビデンストレーシング）
- **Neptune グラフとの chunk_id ベースのリンケージが可能**
- **プロジェクト分離が project_id フィルタで保証される**

---

## 8. QA 対話ターミナル

### 起動方法

```bash
# 対話モード（推奨）
dualrag qa --project-id "サンプル20260519"

# 検索のみモード（回答生成なし、チャンク確認用）
dualrag qa --project-id "サンプル20260519" --mode retrieve

# グラフのみモード（Neptune グラフのみ参照）
dualrag qa --project-id "14_債務奉行クラウド" --mode graph

# デバッグ（検索詳細を表示）
dualrag qa --project-id "14_債務奉行クラウド" -d
# または個別トレース
dualrag qa --project-id "14_債務奉行クラウド" --show-vector-trace --show-graph-trace
```

### スラッシュコマンド

対話モード内で以下のコマンドが使用できます：

| コマンド | 機能 |
|---------|------|
| `/mode [retrieve\|answer\|graph]` | クエリモード切り替え |
| `/topk N` | 取得チャンク数を変更 (1–20) |
| `/verbose` | チャンク全文表示の切り替え |
| `/evidence` | PDF/PNG 証拠画像読み込みの切り替え |
| `/trace` | 検索の完全トレースの切り替え |
| `/rerank [on\|off]` | リランキングの切り替え (Bedrock rerank-v1) |
| `/vector-only` | ベクトル検索のみモード切り替え |
| `/isolation` | 最後のプロジェクト分離チェック状態を表示 |
| `/history` | 最近のクエリ履歴を表示 |
| `/last` | 最後のクエリを再実行 |
| `/stats` | セッション統計を表示 |
| `/sheets` | 利用可能なシート一覧 |
| `/sheet N` | シート N の内容表示 |
| `/help` | 全コマンド表示 |
| `/clear` | 画面クリア |
| `/quit` or `/exit` | 終了 |

### QA モードの説明

| モード | 動作 | 用途 |
|--------|------|------|
| `answer` | ハイブリッド検索 + グラフ検索 + オプション再ランク + マルチモーダル回答生成 | 通常利用 |
| `retrieve` | ハイブリッド検索のみ、チャンク + デバッグトレース表示 | 検索品質の確認 |
| `graph` | グラフ検索のみ、関連ノード/エッジ表示 | グラフデータの確認 |

### 8.1 ハイブリッド検索パイプライン

QA のベクトル検索は v0.3.0 で**ハイブリッド検索パイプライン**に拡張されました。以下の多段パイプラインでリコール（検索漏れの削減）を向上させています：

```
ユーザー質問
  │
  ▼
① クエリ正規化 (normalize)
  │  - 全角/半角統一、余分な空白除去
  │
  ▼
② インテント検出 (intent detection)
  │  - 質問がどのドキュメントタイプに関連するか推定
  │  - キーワードベースの軽量分類（LLM 不使用）
  │
  ▼
③ マルチクエリリライト (multi-query rewrite)
  │  - business_query: ビジネス観点のクエリ
  │  - technical_query: 技術観点のクエリ
  │  - keyword_query: キーワード検索用クエリ
  │
  ▼
④ ハイブリッド検索
  │  ├── ベクトル検索 (LanceDB, 正規化クエリ使用)
  │  └── キーワード検索 (テキストマッチング, keyword_query 使用)
  │
  ▼
⑤ マージ & 重複排除
  │  - chunk_id ベースでユニオン
  │  - スコア = max(vector_score, keyword_score × 0.9)
  │
  ▼
⑥ オプション: リランキング (Bedrock rerank-v1)
  │  - 有効時: 候補から最終 top_k を再順位付け
  │  - 無効時 or エラー時: ハイブリッドスコア順を維持
  │
  ▼
⑦ Neptune グラフ検索（補完コンテキスト）
  │
  ▼
⑧ 証拠 PDF/PNG 画像ロード（マルチモーダル入力）
  │
  ▼
⑨ 全証拠をまとめて Claude Sonnet に送信 → 回答生成
```

### 8.2 インテント検出

質問内のキーワードから検索対象のドキュメントタイプを推定します。LLM を使用せず、キーワードマッチングで軽量に動作します。

| インテント | 検出キーワード (一部) | chunk_type ヒント |
|-----------|---------------------|-------------------|
| `mapping` | マッピング, mapping, 変換, 対応表 | `mapping_table`, `cross_sheet_summary` |
| `flowchart` | フロー, flow, シーケンス, 手順, 処理順序, 呼出順序 | `flowchart`, `overview` |
| `api` | API, endpoint, 呼出, インターフェース, リクエスト | `api_spec`, `mapping_table` |
| `field` | フィールド, field, 項目, カラム, データ項目 | `data_condition`, `mapping_table` |
| `rule` | ルール, rule, 条件, ビジネスルール, 判定, 分岐 | `business_rule`, `data_condition` |
| `overview` | 概要, overview, 全体, summary, 一覧, 構成 | `overview`, `cross_sheet_summary` |

### 8.3 マルチクエリリライト

正規化されたクエリとインテントを組み合わせて、複数のクエリバリアントを生成します：

| クエリ種別 | 用途 | 例 (入力: 「API呼出順序」) |
|-----------|------|--------------------------|
| `business_query` | ビジネス文脈でのリライト | `API呼出順序 処理フロー シーケンス` |
| `technical_query` | 技術文脈でのリライト | `API呼出順序 endpoint interface request` |
| `keyword_query` | キーワード検索用 | `API 呼出 順序` |

### 8.4 ハイブリッド検索の詳細

**ベクトル検索** — LanceDB の埋め込みベクトルに対するコサイン類似度検索：
- 入力: 正規化クエリ（セマンティック類似度に最適化）
- 候補数: `top_k × 2` を取得し、マージプールとして使用
- プロジェクト分離: `project_id` フィルタで事前絞り込み

**キーワード検索** — LanceDB のテキストフィールドに対する語彙ベースマッチング：
- 入力: `keyword_query`（キーワード分割されたクエリ）
- chunk `text` + メタデータフィールドに対する部分一致
- ベクトル検索では埋め込みに含まれにくい固有名詞・専門用語を補完

**マージルール:**
- chunk_id をキーとしてユニオン
- 同一 chunk_id がベクトル・キーワード双方でヒットした場合: `score = max(vector_score, keyword_score × 0.9)`
- キーワードのみヒット: `score = keyword_score × 0.9`（若干ディスカウント）
- 重複排除後、スコア降順でソート

### 8.5 オプション: Bedrock リランキング

ハイブリッド検索の候補に対して、Bedrock の rerank モデルで最終的な関連度スコアを再計算します。

**リランキング設定（`.env`）：**

| 環境変数 | 説明 | デフォルト |
|---------|------|-----------|
| `RERANK_ENABLED` | リランキングを有効化 | `false` |
| `RERANK_MODEL_ID` | Bedrock rerank モデル ID | `amazon.rerank-v1:0` |
| `RERANK_CANDIDATE_K` | リランク対象の候補数 | `30` |
| `RERANK_TOP_K` | リランク後の最終出力数 | `5` |
| `RERANK_FALLBACK_ON_ERROR` | エラー時にハイブリッド順序にフォールバック | `true` |
| `RERANK_TIMEOUT_SECONDS` | リランク API タイムアウト（秒） | `30` |

**利用可能なモデル:**

| モデル ID | ステータス | 備考 |
|----------|-----------|------|
| `amazon.rerank-v1:0` | ✅ 利用可能 | 推奨。relevance_score 0-1 を返す |
| `cohere.rerank-v3-5:0` | ❌ 利用不可 | Marketplace サブスクリプションが必要 |

**動作:**

- 有効時: ハイブリッド検索の候補 (`RERANK_CANDIDATE_K` 件) を Bedrock rerank API に送信し、再順位付け
- 無効時: ハイブリッドスコア順の上位 `top_k` 件をそのまま返す
- エラー時 (`RERANK_FALLBACK_ON_ERROR=true`): 警告ログ + ハイブリッド順序にフォールバック（クラッシュしない）
- 全てのプロヴェナンスメタデータはリランク後も完全に保持される

**対話ターミナルでのトグル:**

```
/rerank on    # リランキングを有効化
/rerank off   # リランキングを無効化
```

### 8.6 デバッグトレース

`-d` (または `--debug-retrieval`) フラグ、もしくは `/trace` コマンドで、検索パイプラインの各ステップを可視化します：

```
── Hybrid Retrieval Trace ──
  Normalized query: API呼出順序
  Intent: flowchart (confidence: 0.75)
  Rewritten queries:
    business: API呼出順序 処理フロー シーケンス
    technical: API呼出順序 endpoint interface request
    keyword: API 呼出 順序
  Vector hits: 10
  Keyword hits: 8
  Merged (deduped): 14 (removed 4 duplicates)
── Rerank Trace ──
  Enabled: true
  Model: amazon.rerank-v1:0
  Candidates: 14 → Final: 5
  Latency: 387ms
  Rank comparison:
    #1 (was hybrid #3) score=0.892 [doc: API仕様書, type: api_spec]
    #2 (was hybrid #1) score=0.841 [doc: フローチャート, type: flowchart]
    ...
```

### 8.7 Vector RAG と Graph RAG の役割

**Vector RAG（ハイブリッド検索）** は、質問に対して最も関連性の高いドキュメントチャンクを取得します。これが回答の**主要な根拠**です。

- ベクトル類似度 + キーワードマッチングの組み合わせでリコール向上
- オプション再ランクによる最終精度の向上
- 各チャンクはソース PDF / 画像まで追跡可能
- 完全なプロヴェナンスメタデータ（12フィールド）を保持

**Graph RAG（グラフ検索）** は、質問に関連するエンティティ（システム、API、テーブル等）の**構造的な関係情報**を補完コンテキストとして提供します。

- システム間連携、テーブル間マッピング、API 呼出関係など
- ベクトル検索では見つからない横断的な関係を補完
- 回答に構造的な文脈を追加するための参考情報

**重要:** グラフ検索の結果が質問と無関係な場合や、ノイズが多い場合には、システムはハイブリッド検索で取得したチャンクと元のエビデンス（PDF/画像）を主な根拠として回答を生成します。グラフコンテキストは補足情報であり、回答品質を下げる可能性がある場合は無視されます。

### 8.8 質問例

```
「仕入伝票APIのデータ形式は？」
「発注情報の登録フローを教えてください」
「SAP から ANDPAD へのデータフローは？」
「債務奉行の仕訳データ出力項目を教えて」
「マッピング定義書のフィールド変換ルールを説明して」
「API呼出順序を教えて」
「N101 トークン分岐のフローは？」
```

### 8.9 QA ターミナル v1.0.0 改善 (Graph Display & Utilities)

v1.0.0 では QA 対話ターミナルのグラフ表示と操作性を大幅に改善しました。

#### グラフ表示の可読性向上

グラフ検索結果のデフォルト表示が、Neptune 内部 ID から**業務可読なノード/エッジ名**に変更されました。

**旧（v0.3.0 以前）:**
```
  → n_abc123 --CALLS_API--> n_def456
```

**新（v1.0.0、compact 形式）:**
```
  [DataField] 顧客コード --CALLS_API--> [API] GetCustomer
```

Raw ID は `raw` フォーマット、または verbose/trace/debug モード有効時のみ表示されます。

#### `/graph-format` コマンド — 4 つの表示形式

| フォーマット | 説明 | 用途 |
|-------------|------|------|
| `compact` | `[Type] Name --REL--> [Type] Name` | **デフォルト**、素早い確認 |
| `table` | カラム整列テーブル（番号付き） | 多数のエッジの一覧比較 |
| `network` | ツリー形式（`├─` / `└─`）ソースノードごとにグルーピング | 構造の視覚的把握 |
| `raw` | ノード ID + プロパティ全表示 | デバッグ、Neptune クエリ確認 |

```
/graph-format table    # テーブル表示に切り替え
/graph-format network  # ネットワークツリー表示
/graph-format compact  # デフォルトに戻す
/graph-format raw      # Raw ID 表示（verbose 同等）
```

#### 新しいスラッシュコマンド

| コマンド | 機能 |
|---------|------|
| `/graph-format [compact\|table\|network\|raw]` | グラフ表示フォーマット切替 |
| `/save-graph [path]` | 最後のグラフ結果を JSON でエクスポート |
| `/save-trace [path]` | 最後の検索トレース + グラフを YAML/JSON でエクスポート |
| `/ask-file <path>` | テキストファイル (.txt/.md) の内容をクエリとして入力 |

#### マルチライン入力

トリプルクォート (`"""`) で囲むことで、複数行のクエリを入力できます：

```
DualRAG> """
発注情報の登録フローについて教えてください。
特に以下の点を詳しく：
- API呼出順序
- エラーハンドリング
"""
```

#### 内部改善

| 改善 | 詳細 |
|------|------|
| **project_mapping 共通化** | `_neptune_pid_map` の重複辞書 (3箇所) を `retrieval/project_mapping.py` に統合 |
| **`_safe_str()` 共通化** | 3 モジュールの重複関数を `retrieval/_utils.py` に統合 |
| **keyword scan truncation warning** | キーワード検索が `KEYWORD_SCAN_LIMIT` (2000件) に到達した場合、`logger.warning` でトランケーション警告を出力。`HybridTrace` に `keyword_scan_truncated` フィールド追加 |

#### 未対応事項 (v1.0.0 スコープ外)

- `project_id` enforcement（全関数への一貫した project_id パラメータ強制）
- Legacy QA terminal test import repair（`test_qa_terminal.py` の 43 件のインポートエラー修正）

---

## 9. エビデンストレーシング

### エビデンストレーシングとは

DualRAG の回答は、元のソースドキュメントまで遡って確認できます。これを**エビデンストレーシング**と呼びます。

```
回答テキスト
  │
  ├── 引用チャンク（sheet_01, chunk_005）
  │     │
  │     ├── source_markdown → parsed/excel/<workbook>/sheet_01.md（VLM 解析結果）
  │     ├── source_pdf      → evidence/excel/<workbook>/sheet_01/sheet_01.pdf（元シート PDF）
  │     └── source_image    → evidence/excel/<workbook>/sheet_01/full.png（レンダリング画像）
  │
  └── グラフノード（API: 発注一覧取得）
        └── source_file → sheet_01.md (抽出元)
```

### トレーシングチェーン

| レイヤー | ファイル | 説明 |
|---------|---------|------|
| L1: チャンク | `dual_rag/chunks.jsonl` | 分割されたテキスト + メタデータ |
| L2: Markdown | `parsed/excel/<wb>/sheet_NN.md` | VLM が生成した構造化テキスト |
| L3: PDF | `evidence/excel/<wb>/sheet_NN/sheet_NN.pdf` | LibreOffice で変換した忠実な PDF |
| L4: 画像 | `evidence/excel/<wb>/sheet_NN/full.png` | レンダリング済み PNG 画像 |
| L5: Excel | S3 上の元ファイル | 最終的なソース |

### なぜエビデンスが重要か

日本企業の Excel 設計書には以下の特徴があり、AI の回答が正しいか人間が確認できることが不可欠です：

- **レイアウトに意味がある**: セルの色、矢印、位置関係がビジネスロジックを表現する
- **暗黙の前提が多い**: Excel シート内の注釈や補足が重要な制約条件を含む
- **複数シートの整合性**: あるシートの情報が他のシートの条件に依存する

エビデンストレーシングにより：
1. AI の回答が正確かどうか、元の PDF/画像で視覚的に確認できる
2. 回答の根拠となったシートとチャンクが明確に特定できる
3. 不明確な場合、元の Excel に戻って手動確認できる

---

## 10. 検証とトラブルシューティング

### 10.1 解析の成否確認

```bash
# ─── dualrag parse（Unified 構造）の検証 ───

# parsed/ に Markdown ファイルが生成されていることを確認
ls outputs/14_債務奉行クラウド/run_20260602_072107/parsed/excel/

# 生成されたファイル数の確認
find outputs/14_債務奉行クラウド/run_20260602_072107/parsed/ -name "*.md" | wc -l

# parsing_manifest.json の確認
cat outputs/14_債務奉行クラウド/run_20260602_072107/parsing_manifest.json | python3 -c "
import json, sys
m = json.load(sys.stdin)
r = m.get('parsing_run', {}).get('result', {})
print(f'Excel files parsed: {r.get(\"files_parsed\", 0)}')
print(f'Files failed: {r.get(\"files_failed\", 0)}')
for wb in r.get('workbooks', []):
    print(f'  {wb[\"workbook\"]}: {wb[\"sheets_parsed\"]} sheets')
"

# ─── マルチタイプ解析パイプライン (project parse-all) の検証 ───

# マニフェストが生成されていることを確認
cat outputs/14_債務奉行クラウド/run_20260602_072107/project_manifest.json | python3 -c "
import json, sys
m = json.load(sys.stdin)
print(f'Project: {m[\"project_id\"]}')
print(f'Files: {m[\"file_count\"]}')
print(f'Types: {m[\"type_counts\"]}')
"

# YAML frontmatter が正しく含まれているか確認
head -10 outputs/14_債務奉行クラウド/run_20260602_072107/parsed/excel/*/sheet_01.md
```

### 10.2 LanceDB チャンク確認

```bash
# Python で直接確認
uv run python -c "
import lancedb
db = lancedb.connect('~/projects/data/vector_store/lancedb')
print('Tables:', db.table_names())
tbl = db.open_table('dual_rag_default')
print(f'Total records: {tbl.count_rows()}')
import pyarrow.compute as pc
data = tbl.to_arrow()
mask = pc.equal(data.column('project_id'), '14_債務奉行クラウド')
print(f'Project records: {data.filter(mask).num_rows}')
"
```

### 10.3 Neptune グラフ確認

```bash
uv run python -c "
import os
os.environ.setdefault('NEPTUNE_GRAPH_ID', 'g-xxxxxxxxxx')
os.environ.setdefault('AWS_DEFAULT_REGION', 'ap-northeast-1')
from hermes_bedrock_agent.clients.neptune import NeptuneClient
c = NeptuneClient()

# ノード数
r = c.execute_query(\"MATCH (n) WHERE n.project_id = 'サンプル20260519' RETURN count(n) AS cnt\")
print(f'Nodes: {r[\"results\"][0][\"cnt\"]}')

# エッジ数
r = c.execute_query(\"MATCH ()-[r]->() WHERE r.project_id = 'サンプル20260519' RETURN count(r) AS cnt\")
print(f'Edges: {r[\"results\"][0][\"cnt\"]}')

# エンティティタイプ別分布
r = c.execute_query(\"MATCH (n) WHERE n.project_id = 'サンプル20260519' RETURN labels(n) AS lbl, count(n) AS cnt ORDER BY cnt DESC LIMIT 10\")
for row in r['results']:
    print(f'  {row[\"lbl\"]}: {row[\"cnt\"]}')
"
```

**Graph Explorer 用検証クエリ：**

```cypher
-- ノードタイプ分布
MATCH (n) WHERE n.project_id = 'サンプル20260519'
RETURN labels(n) AS entity_type, count(n) AS cnt ORDER BY cnt DESC

-- 関係タイプ分布
MATCH (a)-[r]->(b) WHERE a.project_id = 'サンプル20260519'
RETURN type(r) AS relationship, count(r) AS cnt ORDER BY cnt DESC

-- 孤立ノード（エッジなし）
MATCH (n) WHERE n.project_id = '14_債務奉行クラウド' AND NOT (n)--()
RETURN n.id, labels(n), n.name LIMIT 20

-- クロスシートリンク（異なるソースファイル間の関係）
MATCH (a)-[r]->(b)
WHERE a.project_id = '14_債務奉行クラウド' AND a.source_file <> b.source_file
RETURN type(r) AS rel, count(r) AS cnt ORDER BY cnt DESC

-- 低信頼エッジ（レビュー候補）
MATCH (a)-[r]->(b)
WHERE a.project_id = '14_債務奉行クラウド' AND r.confidence < 0.70
RETURN type(r), r.confidence, r.link_method, a.name, b.name
ORDER BY r.confidence ASC LIMIT 30
```

> 💡 これらのクエリは `dualrag graph` 実行後に `graph_output/semantic_map_extraction_report.md` にも自動生成されます。

### 10.4 QA 検索確認

```bash
# ベクトル検索テスト
uv run python -c "
from dotenv import load_dotenv; load_dotenv('.env')
from hermes_bedrock_agent.knowledge_base.vector_store import query_vector_store
results = query_vector_store('仕入伝票APIデータ形式', project_id='14_債務奉行クラウド', top_k=3)
for r in results:
    print(f'  sheet={r[\"sheet_name\"]} type={r[\"chunk_type\"]} dist={r[\"_distance\"]:.3f}')
"
```

### 10.5 エビデンスパス確認

```bash
# チャンクに記録された evidence_path が実在するか確認
uv run python -c "
import json
from pathlib import Path
run_dir = Path('outputs/14_債務奉行クラウド/run_20260602_072107')
chunk_file = run_dir / 'dual_rag' / 'chunks.jsonl'
if chunk_file.exists():
    with open(chunk_file) as f:
        chunk = json.loads(f.readline())
    print(f'Evidence path: {chunk.get(\"evidence_path\", \"N/A\")}')
else:
    print('chunks.jsonl not found — run build-kb first')
"
```

### 10.6 よくある問題と対処法

#### 「LibreOffice connection refused on port 2002」

LibreOffice が起動していません：

```bash
pkill -f soffice
soffice --headless --accept="socket,host=localhost,port=2002;urp;" --norestore &
sleep 3
lsof -i :2002
```

#### 「ValidationException: model ID not found」

モデル ID フォーマットが間違っています：

```bash
# ❌ 間違い
BEDROCK_VLM_MODEL_ID=anthropic.claude-sonnet-4-20250514-v1:0

# ✅ 正しい（推論プロファイルプレフィックス付き）
BEDROCK_VLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6
```

#### 「VLM call timed out / converse() hangs」

Bedrock `converse()` は大きなドキュメントで無期限にハングする場合があります。コード側で `signal.SIGALRM` 180秒タイムアウトが設定されていますが、リトライで解決する場合もあります。

#### 「LanceDB table not found」

ナレッジベースがまだ構築されていません。`dualrag build-kb` を先に実行してください。

#### 「Neptune: connection error」

Neptune はオプションです。以下で回避可能：
- `dualrag build-kb` → `--skip-graph` を追加
- `dualrag graph` → `--dry-run` を追加
- `dualrag qa` → `--no-graph` を追加

#### 「0 chunks retrieved in QA」

考えられる原因：
1. **project_id 不一致** — `build-kb` 時と `qa` 時で同じ ID を使っていますか？
2. **LanceDB が空** — `tbl.count_rows()` で確認
3. **質問が抽象的すぎる** — より具体的なキーワードで試す

#### 「Evidence images: 0」

チャンクに記録されたエビデンスパスにファイルが存在しないため、マルチモーダル入力用の証拠画像をロードできていません。

> ⚠️ この場合でも QA は回答を生成しますが、**回答品質が低下する可能性があります**。VLM がテキストのみで回答するため、元の設計書の視覚的情報（レイアウト、矢印、色分け等）が参照されません。

#### 日本語パス / Unicode の問題

macOS で作成されたファイル名は NFD 形式（濁点・半濁点が分離した Unicode）になることがあります。Linux 上では NFC を使用するため、ファイルパス解決に失敗することがあります。

対処法：
```bash
# NFD ファイル名の検出
find outputs/ -name "*.xlsx" | uconv -x nfc | diff - <(find outputs/ -name "*.xlsx")
```

#### 「--project-id is required」

`build-kb` はデフォルトで `--project-id` を必須にしています。これはデータ分離の安全策です。テスト目的で project_id なしで実行する場合は `--allow-global` を付けてください（**本番環境では非推奨**）。

---

## 11. 制限事項と注意点

### 既知の制限

| 制限事項 | 説明 | 回避策 |
|---------|------|--------|
| VLM 解析の精度 | 複雑なレイアウトは VLM の解釈が不正確になる場合がある | 出力 Markdown を手動確認。重要な設計書は human-in-the-loop |
| Excel 図形の読取り | LibreOffice の PDF 変換では一部の Excel 図形が正確に描画されない場合がある | PNG レンダリングの品質を確認 |
| 大規模シート | 3000px を超えるシートはタイル分割されるため、タイル境界で情報が断絶する可能性 | 300px のオーバーラップで緩和済みだが、境界部分の確認推奨 |
| 並列実行不可 | VLM 解析は逐次実行のみ | 大量シートの処理には時間がかかる |
| Neptune オプション | Neptune 未設定時はグラフ検索なし | ベクトル検索のみでも基本的な QA は動作する |
| Bedrock タイムアウト | `converse()` が大きいドキュメントで無期限ハングする場合がある | 180秒スレッドベースタイムアウト + VLM フォールバックモデルで保護済み |

### 人間による確認が推奨されるケース

以下のケースでは、VLM の解析結果を人間が確認することを推奨します：

1. **複雑なフローチャート** — 多数の分岐条件、ループ、並列パスを含むフロー
2. **密集したマッピング表** — 100行以上のフィールドマッピング（タイル分割で一部見落としの可能性）
3. **色だけで区別される情報** — セルの背景色のみで意味を伝えている場合
4. **手書き風の注釈** — Excel のフリーフォームテキストボックスや手書き矢印
5. **複数シートの整合性** — クロスリファレンスが正しく抽出されているか
6. **2FA / スクリーンショット含むシート** — 画像内画像の解析精度は低下する

### Mermaid ファイルの優先利用

プロジェクト内に `.mmd` ファイル（Mermaid フローチャート）が存在する場合：

- VLM が画像から推定したフローよりも `.mmd` ファイルの内容を **ground-truth として優先**
- フローチャートの正確性が求められる場合、元の Excel から Mermaid 記法を人間が作成しておくことを推奨
- `.mmd` ファイルは parse ステージで構造解析され、`parsed/mermaid/` に出力される

### VLM フォールバック (自動モデル切替)

プライマリ VLM モデル（Claude Sonnet 4.6）が失敗した場合、バックアップモデルに自動切替されます。

| 項目 | 値 |
|------|-----|
| プライマリ | `jp.anthropic.claude-sonnet-4-6` (Claude Sonnet 4.6) |
| フォールバック | `mistral.mistral-large-3-675b-instruct` (Mistral Large 3 675B) |
| 切替トリガー | タイムアウト（180秒×2回試行後）、API エラー、スロットリング、ValidationException |
| 設定 | `.env` の `BEDROCK_VLM_FALLBACK_MODEL_ID` |
| 無効化 | `BEDROCK_VLM_FALLBACK_MODEL_ID=` (空文字) |

**動作フロー:**

```
converse() 呼び出し
  → _converse_with_timeout() [180秒 × 2回リトライ]
    → 成功: 結果を返す
    → 失敗 (タイムアウト/エラー):
      → フォールバック未設定: 例外を上げる
      → フォールバック設定済み:
        → _converse_with_timeout(fallback_model) [180秒 × 2回リトライ]
          → 成功: 結果を返す + WARNING ログ出力
          → 失敗: 例外を上げる
```

**注意:**
- フォールバックはテキスト・マルチモーダル（画像）両方で動作します
- フォールバック使用時はログに WARNING レベルで記録されます
- 両モデルとも Bedrock API (ap-northeast-1) 経由でアクセスします
- Mistral Large 3 は IMAGE 入力に対応しているため VLM 解析もそのまま実行可能です

### コスト概算

| ステージ | コスト要因 | 目安 |
|---------|-----------|------|
| parse (VLM) | Claude Sonnet 入力: 画像 + 出力: Markdown | 19 シートで約 $10〜$20 |
| build-kb (embedding) | Titan Embed V2 テキスト埋め込み | 数百チャンクで $0.01 未満 |
| graph (LLM extraction) | Claude Sonnet 2パス抽出 (v4.3) | 20〜40 シートで約 $15〜$25 |
| qa (回答生成) | Claude Sonnet マルチモーダル推論 | 1 質問あたり約 $0.05〜$0.10 |

> ⚠️ **注意:** 上記の金額は参考値です。実際のコストは、使用するモデル、シート数、画像サイズ、入出力トークン量、および回答の長さによって大きく変動します。最新の Bedrock 料金表を確認してください。

---

## 12. パイプライン安全ノート

### 独立ステージとして実行

DualRAG パイプラインの各ステージは**独立した制御された操作**として実行してください。一つのコマンドで全ステージを連続実行することは推奨しません。

```bash
# ステージ 1: パース（S3 からダウンロード + VLM 解析）
dualrag parse --s3-prefix "s3://..." --project-id "..." --output-dir outputs/.../run_...

# ステージ 2: チャンキング（Markdown → LanceDB）
dualrag build-kb --project-id "..." --run-dir outputs/.../run_...

# ステージ 3: グラフ抽出（チャンク → JSONL ノード/エッジ）
dualrag graph --project-id "..." --run-dir outputs/.../run_...

# ステージ 4: グラフインポート（JSONL → Neptune）
dualrag graph-import --project-id "..."

# ステージ 5: QA 検証
dualrag qa --project-id "..." --mode retrieve
```

### project_id の一貫性

**最重要:** `project_id` はパース、チャンキング、LanceDB、グラフ抽出、Neptune、QA の全ステージで一貫している必要があります。

- 混在すると LanceDB のフィルタが失敗し、検索結果が空になる
- Neptune グラフでプロジェクト間リーケージが発生する
- QA が意図しないプロジェクトのチャンクを返す

**安全ルール:**

- パース時に `--project-id` を明示指定
- 後続ステージは同じ値を使用
- QA は `--project-id` フィルタで分離を保証

### リードオンリー操作

以下は既存データを**変更しない**安全な操作です：

| 操作 | 影響 |
|------|------|
| `dualrag qa --mode retrieve` | LanceDB 読み取りのみ |
| `dualrag qa --mode answer` | LanceDB + Neptune 読み取り + Claude API 呼出 |
| `dualrag qa --mode graph` | Neptune 読み取りのみ |

### 書き込み操作（注意が必要）

| 操作 | 書き込み先 | 注意 |
|------|-----------|------|
| `dualrag parse` | ローカル `outputs/` | S3 読み取り + VLM API コスト |
| `dualrag build-kb` | LanceDB (`~/projects/data/vector_store/lancedb`) | 既存チャンクを上書き可能 |
| `dualrag graph` | ローカル `graph_output/` | LLM API コスト |
| `dualrag graph-import` | Neptune | 既存ノード/エッジを MERGE |

---

## 13. 納品チェックリスト

プロジェクト納品時に以下の項目を順に確認してください。

### 環境準備

- [ ] AWS クレデンシャルが設定されている (`aws sts get-caller-identity` で確認)
- [ ] `.env` ファイルが正しく設定されている（S3 バケット、モデル ID、LanceDB パス）
- [ ] `uv run dualrag --help` で 6 コマンドが表示される (parse, build-kb, qa, graph, project, prompts)
- [ ] LibreOffice が起動している（Excel 解析時のみ: `lsof -i :2002`）

### データ投入

- [ ] S3 にドキュメントがアップロードされている (`aws s3 ls s3://バケット名/プロジェクト名/ --recursive`)
- [ ] `dualrag parse` が正常完了し、`parsed/excel/` に YAML frontmatter 付き Markdown が生成されている
- [ ] `parsing_manifest.json` で files_parsed / files_failed を確認
- [ ] Excel 以外のファイルがある場合: `project scan` + `project parse-all` で CSV/PDF 等が `parsed/` に出力されている

### ナレッジベース構築

- [ ] LanceDB にプロジェクトのチャンクが格納されている（`project_id` でフィルタ確認）
- [ ] Neptune にプロジェクトのノード/エッジが格納されている（`project_id` でフィルタ確認）
- [ ] `graph_output/semantic_map_preflight_check.md` で P0 エラーがないことを確認

### QA 動作確認

- [ ] `dualrag qa --project-id "<your_project>"` で対話ターミナルが起動する
- [ ] テスト質問に対して回答が生成される
- [ ] 回答にシート番号やソースの引用が含まれている
- [ ] `/evidence` コマンドで Evidence images が 1 以上表示される

### エビデンストレーシング

- [ ] 回答で引用されたチャンクのエビデンスパスが実際のファイルを指している
- [ ] `evidence/excel/` に PDF / 画像ファイルが存在する
- [ ] 元の Excel ファイルが `downloads/` に保存されている

### 品質確認（推奨）

- [ ] 主要なシートの VLM 解析結果 Markdown を目視確認（フローチャート、マッピング表）
- [ ] 複雑なフローチャートがある場合、`.mmd` ファイルとの整合性を確認
- [ ] グラフ検索で主要システム間の関係が取得できることを確認
- [ ] `dualrag prompts current` でプロンプトバージョンとコードバージョンを記録

---

## 付録: デモスクリプト

開発・検証用のスクリプトが `scripts/` に用意されています：

```bash
# QA 証拠フローのデモ（各ステップを詳細表示）
uv run python scripts/demo_qa_evidence_flow.py \
  --project-id "14_債務奉行クラウド" \
  "仕入伝票APIのデータ形式は？"

# プロジェクト分離の自動テスト
uv run python scripts/verify_project_isolation.py

# グラフ抽出デモ
uv run python scripts/demo_graph_extraction.py

# build-kb 一括実行
uv run python scripts/run_build_kb.py
```

---

## ライセンス / License

Internal use only.
