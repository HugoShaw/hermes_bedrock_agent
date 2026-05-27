# DualRAG — エンタープライズ設計書ドキュメント解析 & Dual-RAG ナレッジベース

# DualRAG — Enterprise Design Document Parsing & Dual-RAG Knowledge Base

---

## このプロジェクトについて / What This Project Does

**DualRAG** は、日本企業の設計書（Excelワークブック、PDF）をAIで解析し、検索可能なナレッジベースと質問応答ターミナルを構築する完全なパイプラインです。

**DualRAG** is a complete pipeline that parses Japanese enterprise design documents (Excel workbooks, PDFs) using AI, builds a searchable knowledge base, and provides a question-answering terminal.

### 解決する課題 / The Problem

日本企業では、Excelファイルがソフトウェア設計書として広く使用されています。これらのExcelファイルには以下の情報が含まれます：

- 業務プロセス図、システムフロー図
- データ変換ルール、インターフェース定義
- データベーステーブルマッピング、フィールドレベルのマッピング
- 複数システム間の連携仕様

これらの知識は視覚的なスプレッドシートレイアウトに閉じ込められており、検索やクエリ、他システムとの連携が極めて困難です。

### DualRAGの解決方法 / How DualRAG Solves It

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  S3 (Excel/PDF)  ──→  画像化  ──→  AI解析  ──→  ナレッジベース  ──→  QA │
│                                                                         │
│  ① parse:  Excel各シートをPDF/PNG画像に変換し、Claude Sonnetで          │
│            視覚的に理解してMarkdownを生成                                 │
│                                                                         │
│  ② build-kb: Markdownをチャンク分割→ベクトルDB (LanceDB) に格納         │
│              + エンティティ/関係を抽出→グラフDB (Neptune) に格納          │
│                                                                         │
│  ③ qa: 質問に対して、テキスト検索+グラフ検索+元画像をAIに渡して回答      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### なぜ「Dual-RAG」？ / Why "Dual-RAG"?

| RAG方式 | 得意な質問 | 例 |
|---------|-----------|-----|
| **Vector RAG** (テキスト検索) | 「〇〇について教えて」 | 「仕入伝票APIのデータ形式は？」 |
| **Graph RAG** (関係検索) | 「AとBの関連は？」 | 「SAPからANDPADへのデータフローは？」 |

両方を組み合わせることで、どちらか単独では回答できない質問にも対応できます。

### なぜVLM（視覚解析）？ / Why Visual Parsing?

日本企業のExcel設計書は：
- セル結合、色分け、矢印、図形で意味を伝える
- 通常のテキスト抽出（openpyxl、pandas）では理解不可能な複雑なレイアウト
- Excel図形で描かれたフローチャートにはテキスト表現がない

画像に変換してVision-Language Model (VLM) を使うことで、従来のパーサーが見逃す**視覚的な知識**を捕捉します。

---

## 目次 / Table of Contents

1. [クイックスタート / Quick Start](#1-クイックスタート--quick-start)
2. [前提条件 / Prerequisites](#2-前提条件--prerequisites)
3. [インストール / Installation](#3-インストール--installation)
4. [設定 / Configuration](#4-設定--configuration)
5. [使い方ガイド / Usage Guide](#5-使い方ガイド--usage-guide)
6. [自分のドキュメントで試す / Try With Your Own Documents](#6-自分のドキュメントで試す--try-with-your-own-documents)
7. [マルチプロジェクト対応 / Multi-Project Isolation](#7-マルチプロジェクト対応--multi-project-isolation)
8. [技術詳細 / Technical Details](#8-技術詳細--technical-details)
9. [トラブルシューティング / Troubleshooting](#9-トラブルシューティング--troubleshooting)
10. [開発者向け / Development](#10-開発者向け--development)

---

## 1. クイックスタート / Quick Start

**最速で動かすための3ステップ：**

```bash
# ① インストール（初回のみ）
cd ~/projects/hermes_bedrock_agent
uv sync

# ② 設定（初回のみ）
cp .env.example .env
# .env を編集して AWS_REGION, S3_BUCKET, BEDROCK_VLM_MODEL_ID を設定

# ③ 実行（S3上のドキュメントを解析→ナレッジベース構築→質問応答）
soffice --headless --accept="socket,host=localhost,port=2002;urp;" --norestore &

dualrag parse --s3-prefix "あなたのフォルダ名/"
dualrag build-kb outputs/あなたのフォルダ名/run_YYYYMMDD_HHMMSS/ワークブック名/vlm_parsed/ \
  --project-id "あなたのフォルダ名" --use-llm-graph
dualrag qa --project-id "あなたのフォルダ名"
```

> 💡 `project_id` は必ずS3ディレクトリ名と完全一致させてください。
> 例: `s3://bucket/14_債務奉行クラウド/` → `--project-id "14_債務奉行クラウド"`

---

## 2. 前提条件 / Prerequisites

### 必要なソフトウェア / Required Software

| ソフトウェア | 用途 | インストール方法 |
|-------------|------|----------------|
| **Python 3.11+** | 実行環境 | `sudo apt install python3.11` |
| **uv** | パッケージマネージャー | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **AWS CLI** | AWS認証 | `sudo apt install awscli` |
| **LibreOffice** | Excel→PDF変換 | `sudo apt install libreoffice` |
| **poppler-utils** | PDF→PNG変換 | `sudo apt install poppler-utils` |

### 必要なAWSリソース / Required AWS Resources

| リソース | 用途 | 必須？ |
|---------|------|--------|
| **AWSクレデンシャル** | 全AWSサービスの認証 | ✅ 必須 |
| **Amazon Bedrock (Claude Sonnet)** | AI視覚解析+回答生成 | ✅ 必須 |
| **Amazon Bedrock (Titan Embed V2)** | テキスト埋め込み（検索用） | ✅ 必須 |
| **S3バケット** | ソースドキュメント保存先 | ✅ 必須 |
| **Neptune Analytics** | グラフデータベース | ⚠️ オプション（なくてもQA動作可） |

### 前提条件の確認 / Verify Prerequisites

```bash
# Python バージョン確認（3.11以上が必要）
python3 --version

# uv の確認
uv --version

# AWS認証の確認
aws sts get-caller-identity

# LibreOffice の確認
soffice --version

# poppler (pdftoppm) の確認
pdftoppm -v
```

---

## 3. インストール / Installation

```bash
# ステップ1: プロジェクトディレクトリに移動
cd ~/projects/hermes_bedrock_agent

# ステップ2: 依存関係をインストール（.venv/ が自動作成されます）
uv sync

# ステップ3: 動作確認
uv run dualrag --help
```

以下の3つのコマンドが表示されれば成功です：

```
Commands:
  parse     Stage 1: Parse Excel/PDF files from local disk or S3 → VLM markdown.
  build-kb  Stage 2: Parsed markdown → LanceDB vector store + Neptune graph.
  qa        Stage 3: Interactive QA terminal or one-shot query.
```

---

## 4. 設定 / Configuration

### `.env` ファイルの作成 / Create `.env` File

```bash
cp .env.example .env
```

### `.env` の編集 / Edit `.env`

```bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 必須設定（これがないとパイプラインが動きません）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# AWSリージョン
AWS_REGION=ap-northeast-1

# S3バケット名（ドキュメント格納先）
S3_BUCKET=your-bucket-name

# Bedrock VLMモデルID（視覚解析+回答生成）
# 重要: ap-northeast-1 では推論プロファイルプレフィックスが必須！
# ✅ 正しい: jp.anthropic.claude-sonnet-4-6
# ❌ 間違い: anthropic.claude-sonnet-4-20250514-v1:0（ValidationExceptionになる）
BEDROCK_VLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6

# Bedrock 埋め込みモデルID（テキスト→ベクトル変換）
BEDROCK_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0

# ベクトルDBの保存先
VECTOR_LOCAL_STORE_PATH=/home/ubuntu/projects/data/vector_store/lancedb

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# オプション設定（なくても動作するが機能が制限される）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Neptune Analyticsグラフデータベース ID（形式: g-xxxxxxxxxx）
# 未設定の場合、QA回答にグラフコンテキストが含まれません
NEPTUNE_GRAPH_ID=g-xxxxxxxxxx
```

### LibreOffice の起動 / Start LibreOffice

Excel→PDF変換にはLibreOfficeがバックグラウンドで動作している必要があります：

```bash
# ヘッドレスモードで起動（ポート2002でリスン）
soffice --headless --accept="socket,host=localhost,port=2002;urp;" --norestore &

# 起動確認
lsof -i :2002
# ポート2002でプロセスが表示されればOK
```

> ⚠️ LibreOfficeは `dualrag parse` コマンド実行時のみ必要です。
> `dualrag build-kb` や `dualrag qa` には不要です。

---

## 5. 使い方ガイド / Usage Guide

DualRAGは3つのステージで動作します：

| コマンド | ステージ | 処理内容 |
|---------|---------|---------|
| `dualrag parse` | 1. 解析 | Excel/PDFファイルをダウンロード→画像化→AI解析→Markdown生成 |
| `dualrag build-kb` | 2. KB構築 | Markdownをチャンク化→ベクトルDB+グラフDBに格納 |
| `dualrag qa` | 3. 質問応答 | 対話式ターミナルで質問→Dual-RAG検索→マルチモーダル回答生成 |

---

### 5.1 ステージ1: ドキュメント解析 (`dualrag parse`)

S3からExcel/PDFファイルをダウンロードし、AI視覚解析でMarkdownに変換します。

**S3プレフィックスからの解析（最も一般的）：**

```bash
dualrag parse --s3-prefix "14_債務奉行クラウド/"
```

**ローカルファイルの解析：**

```bash
dualrag parse --file /path/to/document.xlsx
```

**project-idと出力先を指定：**

```bash
dualrag parse \
  --s3-prefix "14_債務奉行クラウド/" \
  --project-id "14_債務奉行クラウド" \
  --output-dir outputs/14_債務奉行クラウド
```

> 💡 `--project-id` を省略すると、S3プレフィックスから自動導出されます。

**解析処理の流れ：**

```
1. S3 Discovery: プレフィックス配下の .xlsx / .pdf ファイルを検出
2. Download:     outputs/<run>/downloads/ にダウンロード
3. Excel → PDF:  LibreOffice で各シートを個別PDFに変換
4. PDF → PNG:    pdftoppm でPNG画像にレンダリング
   - 小さいシート → 1枚の画像
   - 大きいシート → 3000pxタイルに分割（300pxオーバーラップ）
5. VLM Parse:    Claude Sonnet が各画像を「見て」Markdownを生成
   - シートタイプ自動検出（マッピング表/フローチャート/仕様書 等）
   - タイプ別の専用プロンプト使用
6. Post-process: Markdown整形
```

**⚠️ 所要時間の目安 / Timing Notes:**

| 対象 | 所要時間 |
|------|---------|
| 1シートあたりVLM解析 | 40〜120秒 |
| 27シートのワークブック | 30〜60分 |
| 14ファイル・43シート | 約2時間 |

> 🚫 VLM解析を並列実行しないでください。タイムアウトカスケードが発生します。

**出力構造 / Output Structure:**

```
outputs/14_債務奉行クラウド/run_20260526_074405/
├── downloads/                                # ダウンロードしたExcelファイル
├── 債務_APIデータ形式/                        # ワークブック1
│   ├── pdf/                                  #   sheet_01.pdf, sheet_02.pdf, ...
│   ├── images/                               #   sheet_01/full.png, ...
│   ├── vlm_parsed/                           #   sheet_01.md, sheet_02.md, ...
│   └── sheet_name_mapping.csv                #   シート番号 → 実際のシート名
├── FY2024_アプリケーション概要_債務奉行クラウド/  # ワークブック2
│   ├── pdf/
│   ├── images/
│   └── vlm_parsed/
└── parse_summary.json                        # 解析サマリー
```

---

### 5.2 ステージ2: ナレッジベース構築 (`dualrag build-kb`)

解析済みMarkdownをチャンク分割し、ベクトルDBとグラフDBに格納します。

**基本的な使い方：**

```bash
dualrag build-kb \
  outputs/14_債務奉行クラウド/run_20260526_074405/債務_APIデータ形式/vlm_parsed/ \
  --project-id "14_債務奉行クラウド"
```

**LLMグラフ抽出付き（高品質、推奨）：**

```bash
dualrag build-kb \
  outputs/14_債務奉行クラウド/run_20260526_074405/債務_APIデータ形式/vlm_parsed/ \
  --workbook "債務_APIデータ形式" \
  --project-id "14_債務奉行クラウド" \
  --use-llm-graph \
  --graph-delay 3.0
```

**オプション一覧 / Options:**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--workbook` / `-w` | ワークブック名（メタデータ用） | ディレクトリ名 |
| `--project-id` | プロジェクトID（**必ず指定**） | 空（警告表示） |
| `--skip-vector` | LanceDBへの格納をスキップ | False |
| `--skip-graph` | Neptuneグラフをスキップ | False |
| `--use-llm-graph` | Claude Sonnetでグラフ抽出（高品質） | False（キーワード抽出） |
| `--graph-delay` | LLM呼び出し間の待機時間（秒） | 3.0 |
| `--dry-run-graph` | グラフ抽出のみ実行（Neptuneに書き込まない） | False |

**グラフ抽出モード / Graph Extraction Modes:**

| モード | 方法 | 品質 | コスト | 用途 |
|--------|------|------|--------|------|
| **Keyword** (デフォルト) | パターンマッチング | 基本 | 無料 | 素早いテスト |
| **LLM** (`--use-llm-graph`) | Claude Sonnetで抽出 | 高い | トークン消費 | 本番構築 |

**構築結果の確認 / Verify Build:**

```bash
# LanceDB の行数確認:
uv run python -c "
import lancedb
db = lancedb.connect('/home/ubuntu/projects/data/vector_store/lancedb')
tbl = db.open_table('murata_excel_vlm_dual_rag')
print(f'Total rows: {tbl.count_rows()}')
"
```

---

### 5.3 ステージ3: 質問応答 (`dualrag qa`)

構築したナレッジベースに対して質問応答を行います。

**対話モード（推奨）：**

```bash
dualrag qa --project-id "14_債務奉行クラウド"
```

**ワンショットクエリ（1つ質問して終了）：**

```bash
dualrag qa --project-id "14_債務奉行クラウド" \
  "仕入伝票APIのデータ形式を教えてください"
```

**オプション：**

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--project-id` | 対象プロジェクト | 空（全プロジェクト横断） |
| `--mode` / `-m` | `answer`(全機能) / `retrieve`(検索のみ) / `graph`(グラフのみ) | `answer` |
| `--top-k` / `-k` | 取得チャンク数 (1-20) | 5 |
| `--no-graph` | グラフコンテキストをスキップ | False |
| `--catalog-dir` | シート閲覧用ディレクトリ | なし |

**対話ターミナル内のスラッシュコマンド / Interactive Commands:**

| コマンド | 機能 |
|---------|------|
| `/mode retrieve` | 検索のみモード（チャンクを表示、回答生成なし） |
| `/mode answer` | 完全回答モード（デフォルト） |
| `/mode graph` | グラフのみモード |
| `/topk 10` | 取得チャンク数を変更 |
| `/verbose` | チャンク全文表示の切り替え |
| `/evidence` | PDF/PNG証拠画像の読み込み切り替え |
| `/sheets` | 利用可能なシート一覧 |
| `/sheet 6` | シート6の内容表示 |
| `/help` | 全コマンド表示 |
| `/quit` | 終了 |

**QAの仕組み（Evidence Flow）：**

```
質問: 「仕入伝票APIのフィールドマッピングは？」
  │
  ├── ① LanceDB検索 → 関連Markdownチャンク（テキスト証拠）
  ├── ② Neptune検索 → 関連グラフコンテキスト
  │     ├─ Business Semantic Graph（システム、API、データフロー）
  │     └─ Implementation Graph（テーブル、フィールド、マッピングルール）
  ├── ③ PDF/PNG画像ロード（視覚的証拠）
  │
  ▼
  全証拠をまとめてClaude Sonnetに送信（マルチモーダル）
  │
  ▼
  根拠付きの回答生成（具体的なシート番号を引用）
```

---

## 6. 自分のドキュメントで試す / Try With Your Own Documents

### 手順概要 / Step-by-Step Guide

自分のExcel設計書でDualRAGを試すには、以下の手順に従ってください：

#### ステップ1: S3にドキュメントをアップロード

```bash
# S3バケットにフォルダを作成してExcelファイルをアップロード
aws s3 cp /path/to/your/設計書.xlsx s3://your-bucket/あなたのプロジェクト名/
aws s3 cp /path/to/your/仕様書.xlsx s3://your-bucket/あなたのプロジェクト名/

# アップロード確認
aws s3 ls s3://your-bucket/あなたのプロジェクト名/
```

#### ステップ2: LibreOfficeを起動

```bash
soffice --headless --accept="socket,host=localhost,port=2002;urp;" --norestore &
sleep 3  # 起動待ち
lsof -i :2002  # 確認
```

#### ステップ3: ドキュメント解析

```bash
dualrag parse \
  --s3-prefix "あなたのプロジェクト名/" \
  --project-id "あなたのプロジェクト名" \
  --output-dir outputs/あなたのプロジェクト名
```

> ⏱️ 所要時間: 1シートあたり約1〜2分。10シートなら10〜20分程度。

#### ステップ4: ナレッジベース構築

```bash
# 解析結果ディレクトリを確認
ls outputs/あなたのプロジェクト名/run_*/

# vlm_parsed/ ディレクトリを指定してKB構築
dualrag build-kb \
  outputs/あなたのプロジェクト名/run_YYYYMMDD_HHMMSS/ワークブック名/vlm_parsed/ \
  --workbook "ワークブック名" \
  --project-id "あなたのプロジェクト名" \
  --use-llm-graph
```

#### ステップ5: 質問応答

```bash
dualrag qa --project-id "あなたのプロジェクト名"
```

### 実例 / Real Example

以下は実際のプロジェクト `14_債務奉行クラウド` の実行例です：

```bash
# 解析（14ファイル、43シート）
dualrag parse --s3-prefix "14_債務奉行クラウド/"

# KB構築（主要ワークブック）
dualrag build-kb \
  outputs/14_債務奉行クラウド/run_20260526_074405/債務_APIデータ形式/vlm_parsed/ \
  --workbook "債務_APIデータ形式" \
  --project-id "14_債務奉行クラウド" \
  --use-llm-graph

# 質問応答
dualrag qa --project-id "14_債務奉行クラウド" \
  "HULFT Squareの債務奉行クラウド連携スクリプトの構成を説明してください"
```

**回答例 / Example Answer:**

```
# HULFT Square 債務奉行クラウド連携スクリプト構成

## スクリプト構成図
[HULFT Square]
      ├─→ 債務奉行_import_buy_slip       （買入伝票インポート）
      ├─← 債務奉行_import_buy_slip_result（結果取得）
      └─→ 債務奉行_import_debt_slip      （債務伝票エクスポート）

## 各スクリプトの詳細
| スクリプト名 | 接続API | 入力 | 出力 |
|...|...|...|...|

[Evidence: sheet_03.pdf, sheet_01.pdf]
```

### ローカルファイルだけで試す / Try Without S3

S3が使えない場合、ローカルファイルから直接解析できます：

```bash
# ローカルExcelファイルを解析
dualrag parse --file /path/to/your/設計書.xlsx --output-dir outputs/local_test

# KB構築
dualrag build-kb outputs/local_test/run_*/設計書/vlm_parsed/ \
  --project-id "local_test"

# QA
dualrag qa --project-id "local_test"
```

### よくある質問形式 / Question Examples

以下のような日本語の質問が有効です：

```
「APIのフィールドマッピングを教えてください」
「〇〇システムから△△へのデータフローを説明して」
「この伝票の必須項目は何ですか？」
「変換ルールの条件分岐を教えて」
「エラー処理のフローを説明してください」
```

---

## 7. マルチプロジェクト対応 / Multi-Project Isolation

### 仕組み / How It Works

LanceDBの全チャンクとNeptuneの全ノード/エッジには `project_id` が付与されます。
クエリ時には指定された `project_id` のデータ**のみ**がフィルタリングされます。

```
プロジェクトA: サンプル20260519（受発注データ連携設計書）
プロジェクトB: 14_債務奉行クラウド（債務奉行クラウドAPI連携設計書）

--project-id "サンプル20260519" で検索:
  → プロジェクトAのチャンクのみ取得
  → プロジェクトAのグラフノードのみ取得
  → プロジェクトBのデータは一切表示されない
```

### project_id のルール / project_id Rules

**⚠️ 重要: `project_id` はS3ディレクトリ名と完全一致でなければなりません。**

| S3パス | 正しい project_id | ❌ 間違い |
|--------|------------------|-----------|
| `s3://bucket/サンプル20260519/` | `サンプル20260519` | `sample_20260519` |
| `s3://bucket/14_債務奉行クラウド/` | `14_債務奉行クラウド` | `saimu_bugyo_cloud` |

正規化、翻訳、短縮、名前変更は**禁止**です。

### マルチプロジェクトの使い方 / Using Multi-Project

```bash
# プロジェクトAを構築
dualrag parse --s3-prefix "サンプル20260519/" --project-id "サンプル20260519"
dualrag build-kb outputs/サンプル20260519/run_*/vlm_parsed/ --project-id "サンプル20260519"

# プロジェクトBを構築
dualrag parse --s3-prefix "14_債務奉行クラウド/" --project-id "14_債務奉行クラウド"
dualrag build-kb outputs/14_債務奉行クラウド/run_*/vlm_parsed/ --project-id "14_債務奉行クラウド"

# 各プロジェクトに独立してクエリ
dualrag qa --project-id "サンプル20260519"
dualrag qa --project-id "14_債務奉行クラウド"
```

### `--project-id` を忘れた場合 / What Happens Without project_id

| コマンド | 動作 |
|---------|------|
| `build-kb` | ⚠️ 警告表示、空のproject_idでデータ保存（後でフィルタ不可） |
| `qa` | ⚠️ 全プロジェクト横断検索（異なるプロジェクトの結果が混在する可能性） |

**本番環境では必ず `--project-id` を指定してください。**

### 分離の確認 / Verify Isolation

```bash
# 存在しないproject_idでクエリ → 結果0件で正常
dualrag qa --project-id "nonexistent_project" "test query"

# デモスクリプトで分離テスト
uv run python scripts/demo_qa_evidence_flow.py \
  --project-id "14_債務奉行クラウド" --no-answer "仕入伝票API"
```

---

## 8. 技術詳細 / Technical Details

### プロジェクト構造 / Project Structure

```
hermes_bedrock_agent/
│
├── src/hermes_bedrock_agent/          # メインPythonパッケージ
│   ├── config.py                      # 設定管理（.envから読み込み）
│   ├── cli.py                         # CLIコマンド: parse, build-kb, qa
│   │
│   ├── clients/                       # AWSサービスラッパー
│   │   ├── bedrock.py                 # Amazon Bedrock (LLM + 埋め込み)
│   │   ├── neptune.py                 # Neptune Analytics (グラフクエリ)
│   │   └── s3.py                      # S3 (ファイルリスト + ダウンロード)
│   │
│   ├── parsing/                       # ステージ1: ドキュメント → Markdown
│   │   ├── s3_discovery.py            # S3内のExcel/PDFファイル検出
│   │   ├── excel_parser.py            # Excel → シート別PDF (LibreOffice)
│   │   ├── pdf_parser.py              # PDF → PNG画像 (タイリング対応)
│   │   ├── vlm_client.py             # 画像 → Claude → Markdown
│   │   ├── image_utils.py            # 画像タイリング、結合、リサイズ
│   │   └── libreoffice.py            # LibreOffice UNO接続ヘルパー
│   │
│   ├── knowledge_base/                # ステージ2: Markdown → ナレッジベース
│   │   ├── schemas.py                 # データモデル (Chunk, GraphNode等)
│   │   ├── chunker.py                 # Markdownのセマンティックチャンク分割
│   │   ├── vector_store.py            # チャンク埋め込み → LanceDB格納
│   │   ├── graph_extractor.py         # エンティティ/関係抽出 (LLM)
│   │   └── graph_loader.py            # グラフ → Neptune書き込み
│   │
│   ├── retrieval/                     # ステージ3: 検索 + 回答
│   │   ├── vector_retriever.py        # LanceDB検索
│   │   ├── graph_retriever.py         # Neptuneグラフコンテキスト取得
│   │   ├── answer_generator.py        # 全証拠統合 → 回答生成
│   │   └── query_router.py            # 検索+回答フロー全体の統制
│   │
│   └── qa/                            # 対話ターミナル
│       └── terminal.py                # REPL (コマンド、スピナー、履歴)
│
├── scripts/                           # デモ・テスト用スクリプト
│   ├── demo_qa_evidence_flow.py       # QA証拠フローの詳細デモ
│   └── verify_project_isolation.py    # プロジェクト分離の自動テスト
│
├── outputs/                           # パイプライン出力（生成物、git管理外）
├── pyproject.toml                     # プロジェクト定義 + 依存関係
├── .env.example                       # 環境変数テンプレート
├── .env                               # 実際の設定（コミット禁止）
└── README.md                          # このファイル
```

### 8.1 VLM解析の仕組み / VLM Parsing Details

```
Excelシート
    │
    ▼ LibreOffice UNO API (port 2002)
シート別PDFファイル（1シート=1ページ、書式保持）
    │
    ▼ pdftoppm (適応型DPI: 36〜150、シートサイズに応じて)
PNG画像
    │  ├─ 小さいシート (< 3000px) → 1枚の画像
    │  └─ 大きいシート (> 3000px) → タイル分割（300pxオーバーラップ）
    │
    ▼ Claude Sonnet Multimodal (Bedrock Converse API経由)
    │  1. シートタイプ自動検出 (mapping / flowchart / spec / overview)
    │  2. タイプ別の専用プロンプト
    │  3. タイル化シート: 各タイルを個別解析→統合
    │  4. 3秒間隔（スロットリング防止）
    │
    ▼
Markdown出力 (sheet_XX.md + メタデータJSON)
```

**⚠️ 重要な制約 / Critical Constraints:**

| 制約 | 理由 |
|------|------|
| VLM呼び出しを並列化しない | 同時リクエストで300秒超のタイムアウトカスケード発生 |
| シート間に最低3秒の間隔 | API スロットリング防止 |
| `max_tokens` ≥ 12000 | 大規模マッピングシートは~8000トークン出力 |
| `boto3 read_timeout` = 600秒 | デフォルト60秒ではタイムアウト |

### 8.2 グラフDB (Neptune Analytics)

2層のグラフ構造：

**Business Semantic Graph（ビジネス意味グラフ）— 高レベル:**

| ノードタイプ | 例 |
|-------------|-----|
| System | SAP S4/HANA, DataSpider, ANDPAD, 債務奉行クラウド |
| DataFlow | 発注データパイプライン |
| InterfaceSpec | IF定義 |
| BusinessProcess | 登録、取消 |

**Implementation Graph（実装グラフ）— 詳細レベル:**

| ノードタイプ | 例 |
|-------------|-----|
| SourceTable / TargetTable | 仕入先データ, ANDPADペイロード |
| SourceField / TargetField | 伝票No., 取引先管理ID |
| MappingRule | フィールド変換ルール |
| BusinessRule | 条件分岐、バリデーション |

**アクセスパターン:**
- プロトコル: openCypher (Gremlinではない)
- 認証: IAM + SigV4署名
- ノード更新: `MERGE` (追加のみ、既存データを削除しない)
- 全クエリが `project_id` でフィルタ

### 8.3 ベクトルDB (LanceDB)

LanceDBはサーバー不要の軽量ベクトルデータベースです：

| 項目 | 値 |
|------|-----|
| 保存先 | `VECTOR_LOCAL_STORE_PATH` (ローカルディスク) |
| テーブル名 | `murata_excel_vlm_dual_rag` |
| 埋め込み次元数 | 1024 (Titan Embed V2) |
| 距離メトリック | コサイン類似度 |
| フィルタリング | `project_id` による pre-filter |

**検索の流れ:**
1. 質問テキスト → Titan Embed V2 → 1024次元ベクトル
2. LanceDBで最近傍K件を検索（コサイン類似度）
3. `project_id` で事前フィルタリング
4. マッチした行のメタデータから証拠PDF/PNGのパスを取得

### 8.4 モデルID設定 (ap-northeast-1)

東京リージョン (ap-northeast-1) では**推論プロファイルプレフィックス**が必須：

| プレフィックス | スコープ | 例 |
|---------------|---------|-----|
| `jp.anthropic.*` | 日本のみ | `jp.anthropic.claude-sonnet-4-6` |
| `apac.anthropic.*` | アジア太平洋 | `apac.anthropic.claude-sonnet-4-6` |
| `global.anthropic.*` | グローバル | `global.anthropic.claude-sonnet-4-6` |

```bash
# 利用可能なプロファイルを確認:
aws bedrock list-inference-profiles --region ap-northeast-1 \
  --query "InferenceProfileSummaries[].InferenceProfileId"
```

---

## 9. トラブルシューティング / Troubleshooting

### 「LibreOffice connection refused on port 2002」

LibreOfficeが起動していないか、クラッシュしています：

```bash
# ゾンビプロセスを終了
pkill -f soffice
# 再起動
soffice --headless --accept="socket,host=localhost,port=2002;urp;" --norestore &
sleep 3
# 確認
lsof -i :2002
```

### 「ValidationException: model ID not found」

モデルIDのフォーマットが間違っています：

```bash
# ❌ 間違い:
BEDROCK_VLM_MODEL_ID=anthropic.claude-sonnet-4-20250514-v1:0

# ✅ 正しい:
BEDROCK_VLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6
```

### 「VLM call timed out after 60 seconds」

boto3のデフォルトタイムアウトが短すぎます。設定で `read_timeout=600` を使用:

```python
from botocore.config import Config
bedrock_config = Config(read_timeout=600, retries={"max_attempts": 3})
```

### 「LanceDB table not found」

ナレッジベースがまだ構築されていません：

```bash
dualrag build-kb outputs/your_project/vlm_parsed/ --project-id "your_project"
```

### 「Neptune: connection error」

Neptuneはオプションです。設定しなくてもQAは動作します：
- `build-kb` → `--skip-graph` で警告を抑制
- `qa` → `--no-graph` で警告を抑制

### 「0 chunks retrieved in QA」

考えられる原因：
1. **project_id が間違い** — `build-kb` 時と同じIDを使用していますか？
2. **LanceDBが空** — `tbl.count_rows()` で確認
3. **質問が短すぎる** — より具体的な質問を試してください

### 「Evidence images: 0」

PDFファイルがメタデータの示す場所にありません：
```bash
# チャンクが期待するパスを確認:
head -1 outputs/*/dual_rag/chunks.jsonl | python3 -c "
import json, sys
chunk = json.loads(sys.stdin.read())
print(chunk.get('source_pdf_s3_path'))
"
```

---

## 10. 開発者向け / Development

### テスト実行 / Running Tests

```bash
uv run pytest -v
uv run pytest tests/test_chunker.py -v
```

### Lint

```bash
uv run ruff check src/
uv run ruff check src/ --fix
```

### インポート確認 / Verify Imports

```bash
uv run python -c "
from hermes_bedrock_agent.config import config
from hermes_bedrock_agent.clients.bedrock import BedrockLLMAdapter
from hermes_bedrock_agent.knowledge_base.schemas import Chunk, QAAnswerResponse
from hermes_bedrock_agent.retrieval.query_router import answer
print('All imports OK')
"
```

### デモスクリプト / Demo Scripts

```bash
# QA証拠フローのデモ（各ステップを詳細表示）
uv run python scripts/demo_qa_evidence_flow.py \
  --project-id "14_債務奉行クラウド" \
  "仕入伝票APIのデータ形式"

# プロジェクト分離テスト
uv run python scripts/verify_project_isolation.py
```

### 新しいドキュメントタイプの追加 / Adding New Document Types

新しいパーサー（例: Wordドキュメント対応）を追加するには：

1. `src/hermes_bedrock_agent/parsing/word_parser.py` を作成
2. .docx → Markdown 変換関数を実装
3. `s3_discovery.py` のファイルタイプ分類にファイル拡張子を追加
4. `cli.py` の `parse` コマンドにフックを追加

ステージ2（KB構築）とステージ3（QA）はMarkdown入力で動作するため、ソースフォーマットに関係なく、ステージ1のみ変更すれば対応可能です。

---

## 現在のデータベース状況 / Current Database Status

| プロジェクト | LanceDB | Neptune ノード | Neptune エッジ | 状態 |
|-------------|---------|---------------|---------------|------|
| サンプル20260519 | 468行 | 1,939 | 3,366 | ✅ 完了 |
| 14_債務奉行クラウド | 267行 | 1,515 | 1,892 | ✅ 完了 |
| **合計** | **735行** | **3,454** | **5,258** | |

---

## ライセンス / License

Internal use only.
