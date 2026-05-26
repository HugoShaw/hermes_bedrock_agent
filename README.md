# hermes_bedrock_agent

企業設計ドキュメント (Excel/PDF) を解析し、Dual-RAG ナレッジベースを構築し、マルチモーダル QA ターミナルで質問応答を行うための統合パイプラインです。

## 1. プロジェクトの目的

日本企業の設計ドキュメント（Excel で作成された IF マッピング定義書、業務フロー図、フィールドマッピング表など）を自動解析し、構造化されたナレッジベースを構築します。

**主要機能:**

- **S3 ファイル解析** — S3 バケットからドキュメントをスキャンし、ファイル種別ごとに適切なパーサーにルーティング
- **Excel VLM 解析** — Excel → シート単位 PDF 変換 → PNG レンダリング → Claude Sonnet マルチモーダル解析 → Markdown 出力
- **Dual-RAG ナレッジベース構築** — ベクトルデータベース (LanceDB) + グラフデータベース (Neptune Analytics) の二重知識表現
- **マルチモーダル QA ターミナル** — テキストチャンク + PDF 画像エビデンス + グラフコンテキストを統合した質問応答

## 2. プロジェクトアーキテクチャ

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  S3 Source Documents                                                         │
│  (Excel .xlsx / PDF / Images)                                                │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │ Stage 1: S3 Discovery & Download
                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Document Parsing Pipeline                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ Excel→PDF    │→ │ PDF→PNG      │→ │ VLM Parse    │→ │ Post-process │   │
│  │ (LibreOffice)│  │ (pdftoppm)   │  │ (Claude VLM) │  │ (Markdown)   │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │ Stage 2: Markdown → Chunks → Dual Knowledge Base
                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Knowledge Base Construction                                                 │
│  ┌────────────────────────────────┐  ┌────────────────────────────────┐    │
│  │  Vector Store (LanceDB)        │  │  Graph Store (Neptune Analytics)│    │
│  │  - Titan Embed V2 (1024dim)    │  │  - Business Semantic Graph      │    │
│  │  - Cosine similarity search    │  │  - Implementation Graph         │    │
│  └────────────────────────────────┘  └────────────────────────────────┘    │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │ Stage 3: QA Evidence Flow
                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  QA Interactive Terminal — Full Evidence Flow                                 │
│                                                                              │
│  User Question                                                               │
│    → ① Markdown chunk retrieval (LanceDB vector search)                      │
│    → ② Business Semantic Graph context (Neptune: systems, data flows)        │
│    → ③ Implementation Graph context (Neptune: APIs, fields, rules)           │
│    → ④ PDF/PNG evidence resolution (from chunk metadata → local files)       │
│    → ⑤ Evidence pack → Multimodal VLM → Grounded answer                     │
│                                                                              │
│  If Markdown and PDF/PNG are inconsistent → answer flags the discrepancy     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### QA Evidence Flow (詳細)

```
User Question: "SAP から ANDPAD への発注データフロー"
    │
    ├─① Markdown Chunk Retrieval (LanceDB Top-K)
    │    → sheet_06 / マッピングシート / mapping_table / score 0.16
    │    → chunk metadata: source_pdf_s3_path, sheet_index, workbook_name
    │
    ├─② Business Semantic Graph (Neptune)
    │    → System nodes: SAP, DataSpider, ANDPAD
    │    → Data flow edges: SAP → DataSpider → ANDPAD
    │    → Sheet relationships
    │
    ├─③ Implementation Graph (Neptune)
    │    → API nodes: 発注作成, 発注変更
    │    → Field nodes: 発注管理ID, 代表品名, 正味発注価格
    │    → MappingRule/BusinessRule nodes with conditions
    │
    ├─④ PDF/PNG Evidence Resolution
    │    → chunk.source_pdf_s3_path → local PDF → pdftoppm → PNG bytes
    │    → Or: pre-rendered images/ directory → full.png
    │
    └─⑤ Multimodal VLM Answer Generation
         → All evidence packed into single Bedrock Converse call
         → System prompt instructs: use all sources, flag inconsistencies
         → Grounded answer with sheet citations
```

### Excel VLM 解析フロー (詳細)

```
Excel ファイル (.xlsx)
    │
    ▼ LibreOffice UNO (port 2002)
シート単位 PDF (sheet_01.pdf, sheet_02.pdf, ...)
    │
    ▼ pdftoppm (adaptive DPI: 36-150)
シート単位 PNG 画像
    │  ├─ 小さいシート → 1枚の画像
    │  └─ 大きいシート → タイル分割 (3000px, overlap 300px)
    │
    ▼ Claude Sonnet Multimodal (Bedrock Converse API)
    │  ├─ シート種別判定 (mapping / flowchart / dev_spec / ...)
    │  ├─ 種別ごとの専用プロンプト
    │  ├─ タイル → 個別解析 → 合成 (synthesis)
    │  └─ 3秒間隔 (シート間) / 2秒間隔 (タイル間) — 並列化禁止
    │
    ▼ Markdown 出力
sheet_01.md, sheet_02.md, ... (+ _meta.json, tiles.json)
```

## 3. ディレクトリ構成

```
hermes_bedrock_agent/
├── src/hermes_bedrock_agent/     # メインパッケージ (3365 LOC)
│   ├── __init__.py               # Version 1.0.0
│   ├── config.py                 # 統合設定 (.env ベース)
│   ├── cli.py                    # CLI エントリポイント (parse / build-kb / qa)
│   │
│   ├── clients/                  # AWS サービスクライアント
│   │   ├── bedrock.py            # Converse API (text + multimodal + embedding)
│   │   ├── neptune.py            # Neptune Analytics openCypher + SigV4
│   │   └── s3.py                 # S3 list/download ヘルパー
│   │
│   ├── parsing/                  # Stage 1: ドキュメント解析
│   │   ├── models.py             # Pydantic モデル (SheetInfo, SheetImages, ParseResult)
│   │   ├── s3_discovery.py       # S3 スキャン、ファイル分類、WorkManifest
│   │   ├── excel_parser.py       # Excel → シート単位 PDF (LibreOffice UNO)
│   │   ├── pdf_parser.py         # PDF → PNG (adaptive DPI + タイル分割)
│   │   ├── vlm_client.py         # VLM 解析 (Claude Sonnet multimodal)
│   │   ├── text_parser.py        # Markdown ポスト処理
│   │   ├── image_utils.py        # PIL タイリング、スティッチング、リサイズ
│   │   └── libreoffice.py        # LibreOffice UNO 接続管理
│   │
│   ├── knowledge_base/           # Stage 2: ナレッジベース構築
│   │   ├── schemas.py            # Chunk, GraphNode, GraphEdge, RetrievedChunk, QAResponse
│   │   ├── chunker.py            # Markdown → セマンティックチャンク分割
│   │   ├── vector_store.py       # Titan Embed V2 → LanceDB 格納・検索
│   │   ├── graph_extractor.py    # Claude Sonnet LLM 2パス抽出 (Business + Implementation)
│   │   └── graph_loader.py       # Neptune MERGE ローダー (keyword / LLM 両対応)
│   │
│   ├── retrieval/                # Stage 3: 検索・回答生成
│   │   ├── vector_retriever.py   # LanceDB ベクトル検索
│   │   ├── graph_retriever.py    # Neptune グラフコンテキスト取得
│   │   ├── answer_generator.py   # マルチモーダル回答生成 (chunks + PDF画像 + graph)
│   │   └── query_router.py       # retrieve / answer オーケストレーション
│   │
│   └── qa/                       # Stage 3: インタラクティブ QA
│       └── terminal.py           # REPL (spinner, tab補完, 履歴, /mode, /topk ...)
│
├── scripts/                      # ユーティリティ・デモスクリプト
│   ├── demo_qa_evidence_flow.py  # QA 証跡フロー検証 (全4証跡タイプ)
│   ├── demo_graph_extraction.py  # グラフ抽出テスト (LLM / keyword 両対応)
│   ├── run_parse.py              # hermes parse の直接実行
│   ├── run_build_kb.py           # hermes build-kb の直接実行
│   └── run_qa.py                 # hermes qa の直接実行
│
├── archive/                      # レガシーコード (git mv で履歴保持)
│   ├── app_doc_pipeline/         # 旧パース処理
│   ├── app_dual_rag/             # 旧 QA パイプライン
│   ├── app_excel_parse_pipeline/ # 旧 Excel 解析
│   ├── app_excel_parser/         # 旧 Excel パーサー
│   ├── scripts_legacy/           # 旧スクリプト群
│   ├── src_v1_and_v2/            # v1 + v2 旧コード
│   └── docs_legacy/             # 旧ドキュメント
│
├── configs/                      # YAML 設定ファイル
├── data/                         # ローカルデータ (vector_store, processed, artifacts)
├── outputs/                      # パイプライン出力結果
├── tests/                        # テストスイート
├── pyproject.toml                # プロジェクト定義 + 依存関係
├── .env.example                  # 環境変数テンプレート
└── .env                          # 実環境変数 (git対象外)
```

## 4. メインワークフロー

### End-to-End フロー

```
S3 上の Excel ファイル
    ↓  hermes parse --s3-prefix ...
ローカルにダウンロード → PDF 変換 → PNG レンダリング → VLM 解析 → Markdown
    ↓  hermes build-kb outputs/reparse_wb2/vlm_parsed/
チャンク分割 → Titan Embed V2 → LanceDB 格納 + Neptune グラフ構築
    ↓  hermes qa
インタラクティブ QA ターミナル (retrieve / answer / graph モード)
```

### パイプライン出力構造

```
outputs/run_YYYYMMDD_HHMMSS/
├── downloads/                    # S3 からダウンロードした Excel ファイル
├── workbook_name/
│   ├── pdf/                      # シート単位 PDF
│   │   ├── sheet_01.pdf
│   │   └── sheet_02.pdf
│   ├── images/                   # PNG レンダリング結果
│   │   ├── sheet_01/
│   │   │   ├── full.png          # フルシート画像
│   │   │   └── tiles/            # タイル (大きいシートの場合)
│   │   └── sheet_02/
│   ├── vlm_parsed/               # VLM 解析結果 (Markdown)
│   │   ├── sheet_01.md
│   │   ├── sheet_01_meta.json
│   │   ├── sheet_02.md
│   │   └── cross_sheet_summary.md
│   └── dual_rag/                 # KB 構築出力
│       ├── chunks.jsonl
│       └── kb_summary.json
└── parse_summary.json            # 実行サマリー
```

## 5. How-to ガイド (新規ユーザー向け)

### 5.1 環境セットアップ

**前提条件:**
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) パッケージマネージャ
- AWS 認証情報 (`~/.aws/credentials` または環境変数)
- LibreOffice (Excel→PDF 変換に必要)
- poppler-utils (PDF→PNG 変換に必要: `pdftoppm`, `pdfinfo`)

```bash
# プロジェクトのクローン
cd ~/projects/hermes_bedrock_agent

# 依存関係のインストール
uv sync

# 開発用依存関係も含める場合
uv sync --dev
```

### 5.2 `.env` の設定

```bash
cp .env.example .env
```

**最低限必要な設定:**

```bash
# --- AWS ---
AWS_REGION=ap-northeast-1

# --- S3 (ドキュメントの格納場所) ---
S3_BUCKET=your-bucket-name
S3_PREFIX=output/

# --- Bedrock Models ---
# VLM (マルチモーダル解析 + 回答生成)
VISION_LLM_MODEL_ID=jp.anthropic.claude-sonnet-4-6

# Embedding
EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
EMBEDDING_DIMENSION=1024

# --- Vector Store (LanceDB) ---
VECTOR_LOCAL_STORE_PATH=/home/ubuntu/projects/data/vector_store/lancedb

# --- Neptune Analytics (グラフ DB, オプション) ---
NEPTUNE_GRAPH_ID=g-xxxxxxxxxx
```

### 5.3 Document Parsing Pipeline の実行

**ローカル Excel ファイルを解析:**

```bash
uv run python -m hermes_bedrock_agent.cli parse --file /path/to/document.xlsx
```

**S3 上のファイルを解析:**

```bash
uv run python -m hermes_bedrock_agent.cli parse --s3-prefix output/murata/
```

**出力先の指定:**

```bash
uv run python -m hermes_bedrock_agent.cli parse \
  --file document.xlsx \
  --output-dir outputs/my_run
```

**注意:** Excel VLM 解析は 1 シートあたり 40-120 秒かかります。27 シートの Excel ファイルで約 30-60 分程度です。

### 5.4 Dual-RAG Knowledge Base の構築

```bash
# 基本コマンド（既存の parsed Markdown から KB 構築）:
uv run python -m hermes_bedrock_agent.cli build-kb \
  outputs/reparse_wb2/vlm_parsed/ \
  --workbook "MW_IFマッピング定義書_205_発注情報(登録・変更・取消)" \
  --s3-excel-key "サンプル20260519/MW_IFマッピング定義書_205_発注情報(登録・変更・取消).xlsx" \
  --project-id "murata_205_order"
```

> **注意:** `--project-id` を省略すると警告が表示され、全プロジェクトの既存データが上書きされる可能性があります。
> PDF パスは `outputs/<parsed_dir_parent>/pdf/` から自動導出されます。必要に応じて `--s3-pdf-prefix` で上書き可能です。

**Neptune グラフをスキップ (ベクトルDB のみ):**

```bash
uv run python -m hermes_bedrock_agent.cli build-kb \
  outputs/reparse_wb2/vlm_parsed/ \
  --skip-graph
```

**Dry-run (Neptune 書き込みなし、抽出結果の確認のみ):**

```bash
uv run python -m hermes_bedrock_agent.cli build-kb \
  outputs/reparse_wb2/vlm_parsed/ \
  --dry-run-graph
```

**LLM グラフ抽出 (Claude Sonnet で高品質グラフ生成):**

```bash
# 2パス LLM 抽出: Business + Implementation Graph
uv run python -m hermes_bedrock_agent.cli build-kb \
  outputs/reparse_wb2/vlm_parsed/ \
  --use-llm-graph \
  --graph-delay 3.0

# Dry-run で結果確認後、Neptune に書き込み
uv run python -m hermes_bedrock_agent.cli build-kb \
  outputs/reparse_wb2/vlm_parsed/ \
  --use-llm-graph --dry-run-graph
```

**グラフ抽出の 2 つのモード:**

| モード | フラグ | 品質 | コスト | 用途 |
|--------|--------|------|--------|------|
| Keyword | (default) | △ 浅い | 無料 | 高速テスト、初期検証 |
| LLM | `--use-llm-graph` | ◎ 高品質 | Claude Sonnet 呼び出し | 本番 KB 構築 |

**LLM グラフ抽出の仕組み:**

```
Parsed Markdown (.md) + cross_sheet_summary.md (workbook-level context)
    │
    ├─ Pass 1: Business Semantic Graph (シート単位 × 1 LLM call)
    │    Context: workbook概要 + シート全文 (最大12K chars)
    │    → System nodes (SAP, DataSpider, ANDPAD)
    │    → InterfaceSpec nodes (IF-ID, 仕様定義)
    │    → DataFlow nodes (発注データ連携, 発注ヘッダ情報)
    │    → BusinessProcess nodes (発注情報登録, 税込額算出)
    │    → API nodes (【Send】発注作成, 発注一覧取得)
    │    → Edges: SENDS_DATA_TO, CALLS_API, TRIGGERS, PRODUCES, PART_OF
    │
    ├─ Pass 2: Implementation / Evidence Graph (チャンク単位 × N LLM calls)
    │    Context: チャンク全文 (最大12K chars, フィールドマッピング含む)
    │    → SourceTable / TargetTable nodes (SAP→ANDPAD テーブル構造)
    │    → SourceField / TargetField nodes (項目レベル定義)
    │    → MappingRule nodes (変換ロジック: CONV-001, CONV-002...)
    │    → BusinessRule nodes (条件分岐: 工事区分判定, 税率ゼロ処理)
    │    → Edges: HAS_FIELD, MAPS_TO, TRANSFORMS_TO, HAS_CONDITION
    │
    └─ All nodes/edges → Neptune MERGE
         (evidence_pdf_s3_path + chunk_id でソース追跡可能)
```

**マッピングチェーン抽出パターン:**

```
SourceField (SAP)                          TargetField (ANDPAD)
  ├── 代表品名 ──── MAPS_TO ──────────────→ 発注名
  ├── 対向注文番号 ── MAPS_TO ────────────→ 発注管理ID
  ├── 仕入先確定コード ── TRANSFORMS_TO ──→ [取引先管理ID変換] ── MAPS_TO → 取引先管理ID
  │   部門コード ─────── TRANSFORMS_TO ──┘         ↓
  │                                         HAS_CONDITION
  │                                              ↓
  └── 工事区分 ──── TRANSFORMS_TO ────────→ [発注種別変換] ── MAPS_TO → 発注種別
                                                  ↓
                                           BusinessRule: 工事区分による分岐
```

**デモ: LLM グラフ抽出テスト:**

```bash
# 1シート分のみ LLM テスト (約 60 秒):
uv run python scripts/demo_graph_extraction.py \
  outputs/reparse_wb2/vlm_parsed/sheet_06.md

# Keyword のみ (LLM なし、即座):
uv run python scripts/demo_graph_extraction.py --keyword-only \
  outputs/reparse_wb2/vlm_parsed/sheet_06.md

# 複数シート (max 3):
uv run python scripts/demo_graph_extraction.py --max-sheets 3 \
  outputs/reparse_wb2/vlm_parsed/
```

### 5.5 QA Interactive Terminal の実行

**インタラクティブモード:**

```bash
uv run python -m hermes_bedrock_agent.cli qa
```

**カタログディレクトリ付き (シート名マッピング + 原文参照):**

```bash
uv run python -m hermes_bedrock_agent.cli qa \
  --catalog-dir outputs/reparse_wb2/
```

**ワンショットクエリ:**

```bash
uv run python -m hermes_bedrock_agent.cli qa \
  "SAP から ANDPAD への発注データフローを説明してください"
```

**QA ターミナル内コマンド:**

| コマンド | 説明 |
|---------|------|
| `/mode [retrieve\|answer\|graph]` | クエリモード切替 |
| `/topk N` | Top-K 結果数の設定 (1-20) |
| `/verbose` | チャンク全文表示の切替 |
| `/evidence` | エビデンス画像の読み込み切替 |
| `/sheets` | 利用可能なシート一覧 |
| `/sheet N` | シート N の内容表示 |
| `/history` | クエリ履歴 |
| `/stats` | セッション統計 |
| `/help` | ヘルプ |
| `/quit` | 終了 |

### 5.6 Evidence Flow デモスクリプト

エビデンスフロー全体をステップごとに確認するためのデモスクリプトです:

```bash
# 全ステップ実行 (VLM 回答生成含む)
uv run python scripts/demo_qa_evidence_flow.py "SAP発注データのフロー"

# 検索のみ (VLM 呼び出しなし — 高速テスト用)
uv run python scripts/demo_qa_evidence_flow.py --no-answer --no-images "発注データ"

# Top-K を 3 に減らして全ステップ実行
uv run python scripts/demo_qa_evidence_flow.py --top-k 3 "マッピングシート"

# 全オプション表示
uv run python scripts/demo_qa_evidence_flow.py --help
```

**出力例:**
```
① Markdown Chunk Retrieval:  5 chunks from sheets [6, 7]
② Business Graph:            6 nodes, 20 edges (SAP, DataSpider, ANDPAD…)
③ Implementation Graph:      60 nodes, 70 edges (APIs, fields, rules…)
④ Visual evidence:           2 PDF/PNG page(s)
⑤ Answer generated in 12.3s  (4,200 in / 900 out tokens)
```

### 5.7 出力結果とログの確認

**解析サマリー:**
```bash
cat outputs/reparse_wb2/parse_summary.json
```

**KB 構築サマリー:**
```bash
cat outputs/reparse_wb2/dual_rag/kb_summary.json
```

**詳細ログの有効化:**
```bash
uv run python -m hermes_bedrock_agent.cli parse --file doc.xlsx --log-level DEBUG
```

**チャンク JSONL の確認:**
```bash
head -5 outputs/reparse_wb2/dual_rag/chunks.jsonl | python -m json.tool
```

## 6. 重要な注意事項

### AWS リソース要件

| リソース | 用途 | 必須 |
|---------|------|------|
| **Bedrock (Claude Sonnet)** | VLM 解析 + 回答生成 | ✅ |
| **Bedrock (Titan Embed V2)** | テキスト埋め込み (1024次元) | ✅ |
| **S3 バケット** | ソースドキュメント格納 | ✅ |
| **Neptune Analytics** | グラフ知識表現 | ⚠️ オプション |

### Bedrock モデル設定

ap-northeast-1 リージョンでは、推論プロファイルプレフィックスが必要です:

```
✅ jp.anthropic.claude-sonnet-4-6
❌ anthropic.claude-sonnet-4-20250514-v1:0  (ValidationException)
```

プレフィックス一覧:
- `jp.anthropic.*` — Japan リージョン
- `apac.anthropic.*` — APAC リージョン
- `global.anthropic.*` — グローバル

### VLM 解析の制約 (重要)

- **並列化禁止** — 同時に複数の VLM 呼び出しを行うと、Bedrock で 300 秒以上のカスケードタイムアウトが発生します
- **シート間: 3 秒間隔** — `config.vlm_delay_seconds`
- **タイル間: 2 秒間隔** — ハードコード
- **max_tokens ≥ 12000** — 大きいマッピングシートの出力には最低 12000 トークン必要
- **boto3 read_timeout = 600 秒** — VLM 出力が大きい場合、デフォルトの 60 秒では不足

### LanceDB 設定

- デフォルトパス: `/home/ubuntu/projects/data/vector_store/lancedb`
- コレクション名: `murata_excel_vlm_dual_rag`
- build-kb 実行時、既存テーブルは自動的にドロップ＆再構築されます

### Neptune Analytics 設定

- Graph ID 形式: `g-xxxxxxxxxx`
- リージョン: `ap-northeast-1`
- 認証: IAM + SigV4
- openCypher クエリ (Gremlin ではない)
- MERGE + SET パターンでノード・エッジを upsert

### 画像処理の制約

- 最大画像サイズ: 7900px (Bedrock 制限: 8000px)
- タイルサイズ: 3000px (overlap: 300px)
- リサイズ: LANCZOS アルゴリズム
- PIL.MAX_IMAGE_PIXELS = 500,000,000 (大きなシートの処理用)

### LibreOffice 要件

Excel→PDF 変換には LibreOffice がリスニングモードで起動している必要があります:

```bash
soffice --headless --accept="socket,host=localhost,port=2002;urp;" --norestore &
```

### 既知の制限

1. `chunker.py` はシート番号 1-27 をハードコードしています（将来的に動的検出に改善予定）
2. グラフ抽出はルールベース + キーワードマッチング（LLM 抽出は `--use-llm-graph` で利用可能だが大規模ワークロードではコスト高）
3. ~~ベクトル検索は build-kb 実行ごとに全テーブルを再構築します~~ → プロジェクト単位で分離済み（v1.1.0）

## 7. マルチプロジェクト分離 (Multi-Project Isolation)

本番環境では数百〜数十万のプロジェクトが存在し、各プロジェクトのドキュメントは独立したナレッジスコープとして扱われます。

### 設計方針

- `project_id` は S3 プレフィックスから自動導出（例: `s3://bucket/murata/205_order/` → `project_id = "murata/205_order"`）
- `--project-id` オプションで明示的に指定も可能
- LanceDB: `project_id` カラムで WHERE フィルタリング（1テーブルで全プロジェクト管理）
- Neptune: 全ノード/エッジに `project_id` プロパティを付与し、openCypher WHERE 句でフィルタ
- **プロジェクト間のデータ汚染なし** — build-kb は指定プロジェクトの行のみ削除・再構築

### 使用方法

```bash
# 1. S3 プレフィックスからドキュメント解析（project_id 自動導出）
uv run python -m hermes_bedrock_agent.cli parse \
  --s3-prefix "murata/205_order" \
  --project-id "murata_205_order"

# 2. 解析済み Markdown から KB 構築（プロジェクト限定）
uv run python -m hermes_bedrock_agent.cli build-kb \
  outputs/reparse_wb2/vlm_parsed/ \
  --project-id "murata_205_order" \
  --use-llm-graph

# 3. プロジェクト限定 QA ターミナル起動
uv run python -m hermes_bedrock_agent.cli qa --project-id "murata_205_order"

# 4. ワンショットクエリ（プロジェクト限定）
uv run python -m hermes_bedrock_agent.cli qa \
  --project-id "murata_205_order" \
  "SAP発注データのフロー"
```

### QA ターミナル内でのプロジェクト切替

```
[answer] @murata_205_order Query> 発注データ
# プロジェクト切替:
@project another_project
[answer] @another_project Query> 別のプロジェクトの質問
```

### 検証手順

```bash
# プロジェクト分離の自動テスト（MERGE キー、エッジフィルタ、ベクトル分離）:
uv run python scripts/verify_project_isolation.py

# プロジェクト分離が正しく動作していることの確認:
uv run python scripts/demo_qa_evidence_flow.py \
  --project-id "murata_205_order" \
  --no-answer "発注データ"
# → project_id=murata_205_order のチャンクのみが返される

# 存在しない project_id では 0 件:
uv run python scripts/demo_qa_evidence_flow.py \
  --project-id "nonexistent" \
  --no-answer "発注データ"
# → 0 results

# project_id 未指定時の警告表示確認:
uv run python -m hermes_bedrock_agent.cli qa
# → "⚠ WARNING: --project-id not set..." と表示される
```

### プロジェクト分離の保証

以下の層でプロジェクト分離が保証されています:

| 層 | 保護メカニズム |
|---|---|
| **Neptune MERGE (node)** | `MERGE (n:Label {node_id: '...', project_id: '...'})` — 同じ node_id でも project_id が異なれば別ノード |
| **Neptune MERGE (edge)** | MATCH 時に from/to 両端点を `project_id` でフィルタ — 異なるプロジェクトのノード間にエッジ不可 |
| **Neptune 検索** | 全ての近傍探索クエリで `AND n.project_id = '...'` / `AND m.project_id = '...'` |
| **LanceDB 検索** | `WHERE project_id = '...'` プレフィルタで他プロジェクトのチャンクを除外 |
| **LanceDB 構築** | `--project-id` 指定時はそのプロジェクトの行のみ削除→再構築（他プロジェクト無影響）|
| **CLI 全コマンド** | `--project-id` 未指定時に `⚠ WARNING` を表示 |
| **QA ターミナル** | 起動時に警告表示 + Evidence Flow Summary にスコープ表示 |

## 開発

```bash
# リンター
uv run ruff check src/

# テスト
uv run pytest -v

# インポート検証
uv run python -c "import hermes_bedrock_agent; print(hermes_bedrock_agent.__version__)"

# CLI ヘルプ
uv run python -m hermes_bedrock_agent.cli --help
```

## ライセンス

社内利用限定。
