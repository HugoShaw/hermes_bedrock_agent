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
12. [納品チェックリスト](#12-納品チェックリスト)

---

## 0. Quick Start / 最短手順

以下の 5 ステップでドキュメントアップロードから QA まで完了できます。

```bash
# ① S3 にドキュメントをアップロード
aws s3 sync ./設計書/ s3://s3-hulftchina-rd/サンプル20260529/

# ② VLM で Excel/PDF を解析し Markdown に変換
dualrag parse --s3-prefix "サンプル20260529/" \
  --project-id "sample_20260529" \
  --output-dir outputs/サンプル20260529

# ③ Markdown → ベクトル KB (LanceDB) を構築
dualrag build-kb outputs/サンプル20260529/wb1/vlm_parsed/ \
  --project-id "sample_20260529"

# ④ Markdown → グラフ DB (Neptune) を構築
dualrag graph outputs/サンプル20260529 \
  --project-id "sample_20260529"

# ⑤ 質問応答ターミナルを起動
dualrag qa --project-id "sample_20260529"
```

> 💡 各コマンドの詳細は[パイプラインの実行](#6-パイプラインの実行)を参照してください。  
> ⚠️ ステップ②で LibreOffice が必要です（[環境構築](#5-環境構築)参照）。

---

## 1. プロジェクト概要

### DualRAG とは

DualRAG は、日本企業の設計書（Excel ワークブック、PDF、フローチャート）を AI で解析し、**ベクトル検索 + グラフ検索**の 2 つの検索手法を組み合わせた質問応答ナレッジベースを構築するパイプラインです。

### 対象ドキュメント

| ドキュメント種別 | 具体例 |
|----------------|--------|
| Excel 設計書 | 業務プロセス図、マッピング定義書、API仕様書、IF定義書 |
| PDF 仕様書 | アプリケーション概要書、開発仕様書 |
| Mermaid ファイル (`.mmd`) | フローチャート ground-truth（存在する場合） |

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

1. **S3 アップロード** — プロジェクト単位で Excel/PDF ファイルを S3 にアップロード
2. **`dualrag parse`** — S3 からファイルを取得し、Excel → PDF → PNG → VLM → Markdown に変換
3. **`dualrag build-kb`** — Markdown をチャンク分割して LanceDB（ベクトルDB）に格納
4. **`dualrag graph`** — Markdown からエンティティ/関係を抽出し Neptune（グラフDB）にロード
5. **`dualrag qa`** — 対話ターミナルで質問 → ベクトル検索 + グラフ検索 → マルチモーダル回答生成
6. **エビデンス参照** — 回答の根拠を元の PDF/画像/Markdown まで遡って確認可能

---

## 3. S3 アップロードガイド

### 推奨ディレクトリ構造

```
s3://your-bucket/
├── プロジェクトA/                      # プロジェクト単位でディレクトリを分ける
│   ├── 設計書_マッピング定義.xlsx
│   ├── 仕様書_API概要.xlsx
│   └── フローチャート.mmd            # 存在すればフローチャート ground-truth
├── プロジェクトB/
│   ├── IF定義書_受発注.xlsx
│   └── 概要設計.pdf
└── 14_債務奉行クラウド/
    ├── 債務_APIデータ形式.xlsx
    ├── FY2024_アプリケーション概要.xlsx
    └── ...
```

**重要な原則：**

- プロジェクトごとに**独立した S3 ディレクトリ**を使用する
- 異なるプロジェクトのファイルを同じディレクトリに混在させない
- S3 ディレクトリ名がそのままプロジェクト識別子の基盤となる

### アップロード手順

```bash
# 単一ファイルのアップロード
aws s3 cp /path/to/設計書.xlsx s3://your-bucket/プロジェクト名/

# フォルダ全体を再帰的にアップロード
aws s3 sync /path/to/local_docs/ s3://your-bucket/プロジェクト名/

# アップロード確認
aws s3 ls s3://your-bucket/プロジェクト名/
```

**実例：**

```bash
# プロジェクトのアップロード
aws s3 sync ./設計書/ s3://s3-hulftchina-rd/サンプル20260529/

# アップロード確認
aws s3 ls s3://s3-hulftchina-rd/サンプル20260529/
# 2026-05-29 10:00:00     524288 MW_IFマッピング定義書_205_発注情報.xlsx
# 2026-05-29 10:00:01      45056 M社様_DSSスクリプト改修概要_フローチャート.xlsx
```

### Mermaid ファイル (.mmd) について

プロジェクト内に `.mmd` ファイルが存在する場合、それはフローチャートの **ground-truth**（正解データ）として扱われます。

- VLM がフローチャートを画像から推定するよりも、`.mmd` ファイルの内容を優先する
- `.mmd` は parse ステージでテキストとしてそのまま読み込まれ、Markdown に含まれる
- 他のシートから推定されたフローとの整合性確認にも利用される

---

## 4. Project ID と Project Name

### 概要

DualRAG はマルチプロジェクト対応で、複数プロジェクトのデータを同じ LanceDB / Neptune に格納しながら完全に分離できます。そのため、各プロジェクトに一貫した識別子を付与する必要があります。

| 用語 | 説明 | 使用箇所 |
|------|------|----------|
| `project_id` | 安定した ASCII 識別子 | CLI の `--project-id` 引数、LanceDB フィルタ、Neptune プロパティ |
| `project_name` | 表示用の日本語名 | Neptune の表示ラベル、レポート |

### 推奨命名規則

| 項目 | 推奨フォーマット | 例 |
|------|-----------------|-----|
| `project_id` | ASCII、`_` 区切り | `sample_20260529`, `saimu_bugyo_cloud` |
| `project_name` | 日本語、そのまま | `サンプル20260529`, `14_債務奉行クラウド` |

**重要:**  project_id を全コマンドで統一してください。

```bash
# ✅ 正しい: 全コマンドで同じ project_id を使用
dualrag parse --s3-prefix "サンプル20260529/" --project-id "sample_20260529"
dualrag build-kb outputs/サンプル20260529/wb1/vlm_parsed/ --project-id "sample_20260529"
dualrag graph outputs/サンプル20260529 --project-id "sample_20260529"
dualrag qa --project-id "sample_20260529"

# ❌ 間違い: コマンドごとに project_id が異なる
dualrag build-kb ... --project-id "サンプル20260529"   # ← 日本語
dualrag qa --project-id "sample_20260529"              # ← ASCII
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
| **Amazon Bedrock (Claude Sonnet)** | VLM 視覚解析 + 回答生成 | ✅ 必須 |
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
dualrag --help
```

以下の 4 コマンドが表示されれば成功です：

```
Commands:
  parse     Stage 1: Parse Excel/PDF files from local disk or S3 → VLM markdown.
  build-kb  Stage 2: Parsed markdown → LanceDB vector store + Neptune graph.
  qa        Stage 3: Interactive QA terminal or one-shot query.
  graph     Extract graph from vlm_parsed/ markdown and load into Neptune.
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
S3_BUCKET=your-bucket-name

# VLM モデル ID (視覚解析 + QA 回答生成)
# 重要: ap-northeast-1 では推論プロファイルプレフィックスが必須
# ✅ 正しい: jp.anthropic.claude-sonnet-4-6
# ❌ 間違い: anthropic.claude-sonnet-4-20250514-v1:0 (ValidationException になる)
VISION_LLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6
TEXT_LLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6

# 埋め込みモデル ID
EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0

# ベクトルDB ローカル保存先
VECTOR_LOCAL_STORE_PATH=/home/ubuntu/projects/data/vector_store/lancedb

# ━━━━ オプション設定 ━━━━

# Neptune Analytics グラフ ID (g-xxxxxxxxxx 形式)
# 未設定の場合、QA でグラフコンテキストが使われない
NEPTUNE_GRAPH_ID=g-xxxxxxxxxx
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

S3 から Excel/PDF ファイルをダウンロードし、VLM で解析して Markdown に変換します。

**基本コマンド：**

```bash
dualrag parse --s3-prefix "プロジェクトフォルダ名/"
```

**全オプション指定：**

```bash
dualrag parse \
  --s3-prefix "サンプル20260529/" \
  --project-id "sample_20260529" \
  --output-dir outputs/サンプル20260529
```

**ローカルファイルの直接解析：**

```bash
dualrag parse --file /path/to/設計書.xlsx --output-dir outputs/local_test
```

**主なオプション：**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--s3-prefix` | S3 上のプレフィックス（ディレクトリパス） | なし |
| `--file`, `-f` | ローカルファイルパス | なし |
| `--output-dir`, `-o` | 出力先ディレクトリ | `outputs/` |
| `--project-id` | プロジェクト ID | S3 プレフィックスから自動導出 |
| `--stages` | 実行ステージ: `all\|parse\|ingest\|images\|vlm` | `all` |
| `--mode` | LanceDB 書込モード: `append\|replace\|rebuild` | `append` |
| `--skip-graph` | Neptune グラフをスキップ | なし |

**処理の流れ：**

```
① S3 Discovery    → プレフィックス配下の .xlsx / .pdf 検出
② Download        → ローカルにダウンロード
③ Excel → PDF     → LibreOffice で各シートを個別 PDF に変換
④ PDF → PNG       → pdftoppm で PNG にレンダリング
                     - 小さいシート: 1 枚の画像
                     - 大きいシート: 3000px タイルに分割（300px オーバーラップ）
⑤ VLM Parse       → Claude Sonnet が各画像を「見て」Markdown 生成
                     - シートタイプ自動検出（マッピング/フローチャート/仕様書 等）
                     - タイプ別の専用プロンプト使用
⑥ 出力            → vlm_parsed/ に sheet_NN.md ファイルを生成
```

**所要時間の目安：**

| 対象 | 所要時間 |
|------|---------|
| 1 シート | 40〜120 秒 |
| 27 シートのワークブック | 30〜60 分 |
| 2 ワークブック・29 シート | 約 90 分 |

> ⚠️ VLM 解析を並列実行しないでください。タイムアウトカスケードが発生します。

---

### 6.2 ステージ 2: ベクトル KB 構築 (`dualrag build-kb`)

VLM 解析済み Markdown をチャンク分割し、**LanceDB（ベクトルDB）** に格納します。  
このステップはベクトル検索の基盤を構築します。

**基本コマンド：**

```bash
dualrag build-kb \
  outputs/サンプル20260529/wb1/vlm_parsed/ \
  --project-id "sample_20260529"
```

**ワークブック名を指定（推奨）：**

```bash
dualrag build-kb \
  outputs/サンプル20260529/wb2_mapping/vlm_parsed/ \
  --workbook "MW_IFマッピング定義書_205_発注情報" \
  --project-id "sample_20260529"
```

**主なオプション：**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `PARSED_DIR` (引数) | `vlm_parsed/` ディレクトリパス（必須） | — |
| `--workbook`, `-w` | ワークブック名（メタデータ用） | ディレクトリ名 |
| `--project-id` | プロジェクト ID（**必ず指定**） | 空（警告表示） |
| `--skip-vector` | LanceDB 格納をスキップ | False |
| `--skip-graph` | Neptune グラフをスキップ | False |
| `--use-llm-graph` | Claude Sonnet でグラフ抽出（高品質） | False |
| `--dry-run-graph` | グラフ抽出のみ、Neptune に書き込まない | False |
| `--graph-delay` | LLM 呼び出し間隔（秒） | 3.0 |

**複数ワークブックがある場合：**

ワークブックごとに `build-kb` を実行してください。同じ `project_id` を指定すれば、LanceDB に追記されます：

```bash
# ワークブック 1
dualrag build-kb outputs/サンプル20260529/wb1_flowchart/vlm_parsed/ \
  --workbook "フローチャート設計書" \
  --project-id "sample_20260529"

# ワークブック 2（同じ project_id で追記）
dualrag build-kb outputs/サンプル20260529/wb2_mapping/vlm_parsed/ \
  --workbook "マッピング定義書" \
  --project-id "sample_20260529"
```

---

### 6.3 ステージ 3: グラフ DB 構築 (`dualrag graph`)

プロジェクト全体の VLM 解析結果から、エンティティ（システム、API、テーブル、フィールド等）と関係性を抽出し、**Neptune（グラフDB）** にロードします。  
このステップはグラフ検索の基盤を構築します。

> 📌 **推奨パイプライン**: `dualrag build-kb`（ベクトル KB）→ `dualrag graph`（グラフ DB）の順で実行してください。  
> `build-kb` にも `--use-llm-graph` オプションがありますが、`dualrag graph` はプロジェクト全体を横断的に分析するため、より高品質なグラフが得られます。通常は `dualrag graph` のみでグラフ構築してください。

**基本コマンド：**

```bash
dualrag graph outputs/サンプル20260529 --project-id sample_20260529
```

**Dry-run（Neptune に書き込まず出力ファイルのみ生成）：**

```bash
dualrag graph outputs/サンプル20260529 \
  --project-id sample_20260529 \
  --project-name サンプル20260529 \
  --dry-run
```

**主なオプション：**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `PROJECT_DIR` (引数) | `vlm_parsed/` を含むプロジェクトディレクトリ（必須） | — |
| `--project-id`, `-p` | プロジェクト ID (ASCII) | — |
| `--project-name`, `-n` | 表示用プロジェクト名（日本語可） | — |
| `--dry-run` | Neptune に書き込まず出力のみ | False |
| `--skip-load` | Neptune ロードをスキップ | False |
| `--output-dir`, `-o` | 出力先 | `<project_dir>/graph_output/` |
| `--neptune-graph-id` | Neptune グラフ ID（.env を上書き） | .env の値 |
| `--delay` | LLM 呼出間隔（秒） | 3.0 |

**出力されるファイル：**

```
graph_output/
├── semantic_map_00_markdown_inventory.json     # 入力ファイル一覧
├── semantic_map_01_evidence_units.jsonl         # エビデンスユニット
├── semantic_map_02_id_registry.json            # ノード ID レジストリ
├── semantic_map_03_semantic_nodes.jsonl         # 意味ノード
├── semantic_map_04_semantic_edges.jsonl         # 意味エッジ
├── semantic_map_05_evidence_nodes.jsonl         # エビデンスノード
├── semantic_map_06_evidence_edges.jsonl         # エビデンスエッジ
├── semantic_map_11_candidate_links.jsonl        # 候補リンク（未検証）
├── semantic_map_13_review_tasks.jsonl           # 手動レビュー項目
├── semantic_map_14_full_graph.json              # 完全グラフ統計
├── semantic_map_15_display_graph.json           # 表示グラフ統計
├── semantic_map_nodes_full.jsonl                # 最終ノード全件
├── semantic_map_edges_full.jsonl                # 最終エッジ全件
├── semantic_map_nodes_display.jsonl             # 表示用ノード
├── semantic_map_edges_display.jsonl             # 表示用エッジ
├── semantic_map_import_full.cypher              # Neptune ロード用 Cypher（全件）
├── semantic_map_import_display.cypher           # Neptune ロード用 Cypher（表示）
├── semantic_map_preflight_check.md             # 品質チェックレポート
├── semantic_map_graph_explore_queries.cypher    # 検証用クエリ集
└── semantic_map_extraction_report.md           # 抽出レポート
```

---

### 6.4 ステージ 4: 質問応答 (`dualrag qa`)

構築したナレッジベースに対して質問応答を実行します。

**対話モード（推奨）：**

```bash
dualrag qa --project-id "sample_20260529"
```

**ワンショットクエリ：**

```bash
dualrag qa --project-id "sample_20260529" \
  "発注情報のフィールドマッピングを教えてください"
```

**グラフなしモード（Neptune 未設定時）：**

```bash
dualrag qa --project-id "sample_20260529" --no-graph
```

**主なオプション：**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `[QUERY]` (引数) | ワンショットクエリ（省略で対話モード） | なし |
| `--project-id` | 対象プロジェクト ID | 空（全プロジェクト横断） |
| `--mode`, `-m` | `answer` / `retrieve` / `graph` | `answer` |
| `--top-k`, `-k` | 取得チャンク数 (1–20) | 5 |
| `--no-graph` | グラフコンテキストをスキップ | False |
| `--catalog-dir` | シート閲覧用ディレクトリ | なし |

---

## 7. ローカル出力構造

### `dualrag parse` の出力

```
outputs/サンプル20260529/
├── 01_基本設計/                          # S3 と同じフォルダ構造
│   └── (ソース Excel ファイル)
├── 02_詳細設計/
│   └── (ソース Excel ファイル)
├── wb1_flowchart/                        # ワークブック 1 の処理結果
│   ├── pdf/                             #   シート別 PDF ファイル
│   │   ├── sheet_01.pdf
│   │   └── sheet_02.pdf
│   ├── images/                          #   レンダリング済み PNG 画像
│   │   ├── sheet_01/
│   │   │   └── full.png               #   フルサイズ画像
│   │   └── sheet_02/
│   │       ├── full.png
│   │       └── tiles/                  #   大きいシートはタイル分割
│   │           ├── tile_0_0.png
│   │           └── tile_0_1.png
│   ├── vlm_parsed/                      #   VLM 解析結果（Markdown）
│   │   ├── sheet_01.md
│   │   ├── sheet_01_meta.json          #   メタデータ（タイプ、信頼度等）
│   │   └── sheet_02.md
│   ├── dual_rag/                        #   チャンク JSONL（build-kb 後に生成）
│   │   └── chunks.jsonl
│   └── sheet_name_mapping.csv           #   シート番号 → 実際のシート名
├── wb2_mapping/                          # ワークブック 2 の処理結果
│   ├── pdf/
│   ├── images/
│   ├── vlm_parsed/
│   ├── dual_rag/
│   └── sheet_name_mapping.csv
├── graph_output/                         # グラフ抽出結果（graph コマンド後に生成）
│   ├── semantic_map_*.jsonl
│   ├── semantic_map_*.cypher
│   └── semantic_map_*.md
├── pipeline.log                          # パイプライン実行ログ
└── pipeline_report_*.json                # パイプラインレポート（メトリクス）
```

### 各ディレクトリの役割

| ディレクトリ | 用途 |
|-------------|------|
| `pdf/` | LibreOffice で変換した各シートの PDF。エビデンス画像の元データ |
| `images/` | PDF からレンダリングした PNG。VLM に入力する画像 |
| `vlm_parsed/` | **最重要**: VLM の解析結果 Markdown。後続の全ステージがここを参照 |
| `dual_rag/` | チャンク分割済み JSONL。LanceDB に格納される中間データ |
| `graph_output/` | グラフ抽出の全成果物。Neptune ロード用 Cypher も含む |

### `sheet_name_mapping.csv` の形式

```csv
sheet_index,original_sheet_name,safe_pdf_filename
1,変更履歴,sheet_01
2,API呼出順序,sheet_02
3,DataSpider開発仕様,sheet_03
```

このファイルにより、`sheet_01.md` → 実際のシート名「変更履歴」の対応が追跡できます。

---

## 8. QA 対話ターミナル

### 起動方法

```bash
# 対話モード（推奨）
dualrag qa --project-id "sample_20260529"

# 検索のみモード（回答生成なし、チャンク確認用）
dualrag qa --project-id "sample_20260529" --mode retrieve

# グラフのみモード（Neptune グラフのみ参照）
dualrag qa --project-id "sample_20260529" --mode graph
```

### スラッシュコマンド

対話モード内で以下のコマンドが使用できます：

| コマンド | 機能 |
|---------|------|
| `/mode [retrieve\|answer\|graph]` | クエリモード切り替え |
| `/topk N` | 取得チャンク数を変更 (1–20) |
| `/verbose` | チャンク全文表示の切り替え |
| `/evidence` | PDF/PNG 証拠画像読み込みの切り替え |
| `/history` | 最近のクエリ履歴を表示 |
| `/last` | 最後のクエリを再実行 |
| `/stats` | セッション統計を表示 |
| `/sheets` | 利用可能なシート一覧 |
| `/sheet N` | シート N の内容表示 |
| `/clear` | 画面クリア |
| `/help` | 全コマンド表示 |
| `/quit` or `/exit` | 終了 |

### QA モードの説明

| モード | 動作 | 用途 |
|--------|------|------|
| `answer` | ベクトル検索 + グラフ検索 + マルチモーダル回答生成 | 通常利用 |
| `retrieve` | ベクトル検索のみ、チャンク表示 | 検索品質の確認 |
| `graph` | グラフ検索のみ、関連ノード/エッジ表示 | グラフデータの確認 |

### Vector RAG と Graph RAG の役割

**Vector RAG（ベクトル検索）** は、質問に対して最も類似度の高いドキュメントチャンクを取得します。これが回答の**主要な根拠**です。

- 元の Markdown テキストから直接抽出されたチャンク
- テキスト類似度に基づくため、具体的なキーワードを含む質問に強い
- 各チャンクはソース PDF / 画像まで追跡可能

**Graph RAG（グラフ検索）** は、質問に関連するエンティティ（システム、API、テーブル等）の**構造的な関係情報**を補完コンテキストとして提供します。

- システム間連携、テーブル間マッピング、API 呼出関係など
- ベクトル検索では見つからない横断的な関係を補完
- 回答に構造的な文脈を追加するための参考情報

**重要:** グラフ検索の結果が質問と無関係な場合や、ノイズが多い場合には、システムはベクトル検索で取得したチャンクと元のエビデンス（PDF/画像）を主な根拠として回答を生成します。グラフコンテキストは補足情報であり、回答品質を下げる可能性がある場合は無視されます。

### 質問例

```
「発注情報のフィールドマッピングを教えてください」
「SAP から ANDPAD へのデータフローを説明して」
「リリース前：納品データに対して編集・請負済みキャンセルを行う」
「API呼出順序を教えてください」
「この伝票の必須項目は何ですか？」
「変換ルールの条件分岐を教えて」
「エラー処理のフローを説明してください」
「DataSpider の開発仕様は？」
```

### QA の処理フロー

```
質問入力
  │
  ├── ① LanceDB ベクトル検索 → 類似度の高い Markdown チャンク（テキスト証拠）
  ├── ② Neptune グラフ検索 → 関連ノード・エッジ（構造的コンテキスト）
  │     ├─ Business Semantic Graph（システム、API、データフロー）
  │     └─ Implementation Graph（テーブル、フィールド、マッピングルール）
  ├── ③ 証拠 PDF/PNG 画像ロード（マルチモーダル入力）
  │
  ▼
  全証拠をまとめて Claude Sonnet に送信
  │
  ▼
  根拠付きの回答生成（具体的なシート番号を引用）
```

---

## 9. エビデンストレーシング

### エビデンストレーシングとは

DualRAG の回答は、元のソースドキュメントまで遡って確認できます。これを**エビデンストレーシング**と呼びます。

```
回答テキスト
  │
  ├── 引用チャンク（sheet_13, chunk_005）
  │     │
  │     ├── source_markdown → outputs/.../vlm_parsed/sheet_13.md（VLM 解析結果）
  │     ├── source_pdf      → outputs/.../pdf/sheet_13.pdf（元シート PDF）
  │     └── source_image    → outputs/.../images/sheet_13/full.png（レンダリング画像）
  │
  └── グラフノード（API: 発注キャンセル）
        └── source_file → sheet_13.md (抽出元)
```

### トレーシングチェーン

| レイヤー | ファイル | 説明 |
|---------|---------|------|
| L1: チャンク | `chunks.jsonl` | 分割されたテキスト + メタデータ |
| L2: Markdown | `vlm_parsed/sheet_NN.md` | VLM が生成した構造化テキスト |
| L3: PDF | `pdf/sheet_NN.pdf` | LibreOffice で変換した忠実な PDF |
| L4: 画像 | `images/sheet_NN/full.png` | レンダリング済み PNG 画像 |
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
# vlm_parsed/ に Markdown ファイルが生成されていることを確認
ls outputs/プロジェクト名/ワークブック名/vlm_parsed/

# 生成されたファイル数の確認
find outputs/プロジェクト名/ -name "sheet_*.md" -path "*/vlm_parsed/*" | wc -l

# sheet_name_mapping.csv でシート名の対応を確認
cat outputs/プロジェクト名/ワークブック名/sheet_name_mapping.csv
```

### 10.2 LanceDB チャンク確認

```bash
# Python で直接確認
uv run python -c "
import lancedb
db = lancedb.connect('/home/ubuntu/projects/data/vector_store/lancedb')
tbl = db.open_table('murata_excel_vlm_dual_rag')
print(f'Total records: {tbl.count_rows()}')
import pyarrow.compute as pc
data = tbl.to_arrow()
mask = pc.equal(data.column('project_id'), 'sample_20260529')
print(f'Project records: {data.filter(mask).num_rows}')
"
```

### 10.3 Neptune グラフ確認

```bash
uv run python -c "
import os
os.environ['NEPTUNE_GRAPH_ID'] = 'g-xxxxxxxxxx'
os.environ['AWS_DEFAULT_REGION'] = 'ap-northeast-1'
from hermes_bedrock_agent.clients.neptune import NeptuneClient
c = NeptuneClient()

# ノード数
r = c.execute_query(\"MATCH (n) WHERE n.project_id = 'sample_20260529' RETURN count(n) AS cnt\")
print(f'Nodes: {r[\"results\"][0][\"cnt\"]}')

# エッジ数
r = c.execute_query(\"MATCH ()-[r]->() WHERE r.project_id = 'sample_20260529' RETURN count(r) AS cnt\")
print(f'Edges: {r[\"results\"][0][\"cnt\"]}')
"
```

### 10.4 QA 検索確認

```bash
# ベクトル検索テスト
uv run python -c "
from dotenv import load_dotenv; load_dotenv('.env')
from hermes_bedrock_agent.knowledge_base.vector_store import query_vector_store
results = query_vector_store('発注情報', project_id='sample_20260529', top_k=3)
for r in results:
    print(f'  sheet={r[\"sheet_name\"]} type={r[\"chunk_type\"]} dist={r[\"_distance\"]:.3f}')
"
```

### 10.5 エビデンスパス確認

```bash
# チャンクに記録された PDF パスが実在するか確認
uv run python -c "
import json, os
from pathlib import Path
chunk_file = 'outputs/サンプル20260529/wb2_mapping/dual_rag/chunks.jsonl'
with open(chunk_file) as f:
    chunk = json.loads(f.readline())
pdf_path = chunk['source_pdf_s3_path'].replace('s3://s3-hulftchina-rd/', '')
print(f'PDF path: {pdf_path}')
print(f'Exists: {os.path.exists(pdf_path)}')
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
VISION_LLM_MODEL_ID=anthropic.claude-sonnet-4-20250514-v1:0

# ✅ 正しい（推論プロファイルプレフィックス付き）
VISION_LLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6
```

#### 「VLM call timed out」

boto3 のデフォルトタイムアウトが短すぎます。config で `read_timeout=600` を使用してください。

#### 「LanceDB table not found」

ナレッジベースがまだ構築されていません。`dualrag build-kb` を先に実行してください。

#### 「Neptune: connection error」

Neptune はオプションです。以下で回避可能：
- `dualrag build-kb` → `--skip-graph` を追加
- `dualrag qa` → `--no-graph` を追加

#### 「0 chunks retrieved in QA」

考えられる原因：
1. **project_id 不一致** — `build-kb` 時と `qa` 時で同じ ID を使っていますか？
2. **LanceDB が空** — `tbl.count_rows()` で確認
3. **質問が抽象的すぎる** — より具体的なキーワードで試す

#### 「Evidence images: 0」

チャンクに記録された PDF パスにファイルが存在しないため、マルチモーダル入力用の証拠画像をロードできていません。

> ⚠️ この場合でも QA は回答を生成しますが、**回答品質が低下する可能性があります**。VLM がテキストのみで回答するため、元の設計書の視覚的情報（レイアウト、矢印、色分け等）が参照されません。正確性が重要な回答については、対応する PDF/画像ファイルを手動で確認してください。

原因確認：
```bash
# チャンクの source_pdf_s3_path を確認
head -1 outputs/サンプル20260529/*/dual_rag/chunks.jsonl | python3 -c "
import json, sys
chunk = json.loads(sys.stdin.read())
print(chunk.get('source_pdf_s3_path'))
"
```

#### 日本語パス / Unicode の問題

macOS で作成されたファイル名は NFD 形式（濁点・半濁点が分離した Unicode）になることがあります。Linux 上では NFC を使用するため、ファイルパス解決に失敗することがあります。

対処法：
```bash
# NFD ファイル名の検出
find outputs/ -name "*.xlsx" | uconv -x nfc | diff - <(find outputs/ -name "*.xlsx")
```

---

## 11. 制限事項と注意点

### 既知の制限

| 制限事項 | 説明 | 回避策 |
|---------|------|--------|
| VLM 解析の精度 | 複雑なレイアウトは VLM の解釈が不正確になる場合がある | 出力 Markdown を手動確認。重要な設計書は human-in-the-loop |
| Excel 図形の読取り | LibreOffice の PDF 変換では一部の Excel 図形が正確に描画されない場合がある | PNG レンダリングの品質を確認 |
| 大規模シート | 3000px を超えるシートはタイル分割されるため、タイル境界で情報が断絶する可能性 | 300px のオーバーラップで緩和済みだが、境界部分の確認推奨 |
| 並列実行不可 | VLM 解析は逐次実行のみ | 大量シートの処理には時間がかかる（目安: 29シートで約90分） |
| Neptune オプション | Neptune 未設定時はグラフ検索なし | ベクトル検索のみでも基本的な QA は動作する |

### 人間による確認が推奨されるケース

以下のケースでは、VLM の解析結果を人間が確認することを推奨します：

1. **複雑なフローチャート** — 多数の分岐条件、ループ、並列パスを含むフロー
2. **密集したマッピング表** — 100行以上のフィールドマッピング（タイル分割で一部見落としの可能性）
3. **色だけで区別される情報** — セルの背景色のみで意味を伝えている場合
4. **手書き風の注釈** — Excel のフリーフォームテキストボックスや手書き矢印
5. **複数シートの整合性** — クロスリファレンスが正しく抽出されているか

### Mermaid ファイルの優先利用

プロジェクト内に `.mmd` ファイル（Mermaid フローチャート）が存在する場合：

- VLM が画像から推定したフローよりも `.mmd` ファイルの内容を **ground-truth として優先**
- フローチャートの正確性が求められる場合、元の Excel から Mermaid 記法を人間が作成しておくことを推奨
- `.mmd` ファイルは parse ステージでテキストとして取り込まれ、チャンクに含まれる

### コスト概算

| ステージ | コスト要因 | 目安 |
|---------|-----------|------|
| parse (VLM) | Claude Sonnet 入力: 画像 + 出力: Markdown | 29 シートで約 $20〜$30 |
| build-kb (embedding) | Titan Embed V2 テキスト埋め込み | 数百チャンクで $0.01 未満 |
| graph (LLM extraction) | Claude Sonnet グラフ抽出 | シートあたり約 $0.5 |
| qa (回答生成) | Claude Sonnet マルチモーダル推論 | 1 質問あたり約 $0.05〜$0.10 |

> ⚠️ **注意:** 上記の金額は参考値です。実際のコストは、使用するモデル（Claude Sonnet / Opus）、シート数、画像サイズ、入出力トークン量、および回答の長さによって大きく変動します。最新の Bedrock 料金表を確認してください。

---

## 12. 納品チェックリスト

プロジェクト納品時に以下の項目を順に確認してください。

### 環境準備

- [ ] AWS クレデンシャルが設定されている (`aws sts get-caller-identity` で確認)
- [ ] `.env` ファイルが正しく設定されている（S3 バケット、モデル ID、LanceDB パス）
- [ ] `dualrag --help` で 4 コマンドが表示される
- [ ] LibreOffice が起動している（Excel 解析時のみ: `lsof -i :2002`）

### データ投入

- [ ] S3 にドキュメントがアップロードされている (`aws s3 ls s3://バケット名/サンプル20260529/`)
- [ ] `dualrag parse` が正常完了し、`vlm_parsed/` に Markdown が生成されている
- [ ] `sheet_name_mapping.csv` でシート番号と日本語シート名の対応が確認できる

### ナレッジベース構築

- [ ] LanceDB にプロジェクトのチャンクが格納されている（`project_id = sample_20260529`）
- [ ] Neptune にプロジェクトのノード/エッジが格納されている（`project_id = sample_20260529`）
- [ ] 複数ワークブックがある場合、全ワークブックのチャンクが LanceDB に存在する

### QA 動作確認

- [ ] `dualrag qa --project-id "sample_20260529"` で対話ターミナルが起動する
- [ ] テスト質問に対して回答が生成される（例: 「発注情報のフィールドマッピングを教えてください」）
- [ ] 回答にシート番号やソースの引用が含まれている

### エビデンストレーシング

- [ ] 回答で引用されたチャンクの `source_pdf_s3_path` が実際のファイルを指している
- [ ] ローカルに PDF / 画像ファイルが存在する（`outputs/サンプル20260529/*/pdf/`）
- [ ] `/evidence` コマンドで Evidence images が 1 以上表示される

### 品質確認（推奨）

- [ ] 主要なシートの VLM 解析結果 Markdown を目視確認（フローチャート、マッピング表）
- [ ] 複雑なフローチャートがある場合、`.mmd` ファイルとの整合性を確認
- [ ] グラフ検索で主要システム間の関係が取得できることを確認

---

## 付録: デモスクリプト

開発・検証用のスクリプトが `scripts/` に用意されています：

```bash
# QA 証拠フローのデモ（各ステップを詳細表示）
uv run python scripts/demo_qa_evidence_flow.py \
  --project-id "sample_20260529" \
  "発注情報のフィールドマッピング"

# プロジェクト分離の自動テスト
uv run python scripts/verify_project_isolation.py
```

---

## ライセンス / License

Internal use only.
