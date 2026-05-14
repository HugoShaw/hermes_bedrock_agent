# Hermes Session Viewer

将 Hermes Agent 会话数据转换为交互式 HTML 可视化页面。支持三层可展开结构（主流程阶段 → 内部作业 → 原始事件），三语言界面切换（中文/English/日本語）。

## 数据源

**优先从 `~/.hermes/state.db` (SQLite) 加载**，支持精确的每条消息级时间戳。  
如果 DB 中未找到指定会话，自动回退到 JSON 文件。

| 数据源 | 时间戳精度 | 额外元数据 |
|--------|-----------|-----------|
| state.db | ✓ 精确（Unix epoch per message） | token数、费用、模型、标题 |
| JSON 文件 | ○ 估算（线性插值） | 仅 session_start / last_updated |

## 安装

```bash
cd ~/projects/hermes_bedrock_agent/hermes_session_viewer
pip install -e .
```

或直接使用 PYTHONPATH：

```bash
cd ~/projects/hermes_bedrock_agent/hermes_session_viewer
PYTHONPATH=src python -m hermes_session_viewer --help
```

## 使用方式

### 列出数据库中的会话

```bash
python -m hermes_session_viewer --list-sessions --output-dir /tmp/out
```

### 从数据库加载（推荐）

```bash
# 仅指定 session-id，自动从 state.db 查询
python -m hermes_session_viewer \
  --session-id 20260511_074713_ef0316 \
  --output-dir ~/projects/data/session_viewer/
```

### 从数据库加载，JSON 文件作为后备

```bash
python -m hermes_session_viewer \
  --session-id 20260511_074713_ef0316 \
  --session-file /path/to/session.json \
  --output-dir ~/projects/data/session_viewer/
```

### 仅从 JSON 文件加载（旧模式）

```bash
python -m hermes_session_viewer \
  --session-file /tmp/session_export/session_20260511_074713_ef0316.json \
  --output-dir ~/projects/data/session_viewer/
```

### 指定自定义数据库路径

```bash
python -m hermes_session_viewer \
  --session-id 20260511_074713_ef0316 \
  --db-path /custom/path/state.db \
  --output-dir ~/projects/data/session_viewer/
```

## 输出文件

| 文件 | 说明 |
|------|------|
| `session_{ID}_viewer.html` | 交互式可视化页面（单文件，无外部依赖） |
| `parsed_events.json` | 标准化事件列表（含三语言摘要） |
| `timeline.json` | 聚合后的时间线阶段 |
| `timestamp_quality.json` | 时间戳质量报告 |

## HTML 页面特性

- **三层可展开结构**：L1 主流程阶段 → L2 事件明细 → L3 原始 JSON
- **三语言切换**：日本語（默认）/ 中文 / English，通过右上角按钮切换，偏好保存在 localStorage
- **暗色主题**：专业风格，适合工程师日常使用
- **搜索功能**：支持按事件内容搜索并高亮
- **展开/折叠全部**：一键操作
- **时间戳质量指示器**：绿色（精确）/ 黄色（估算）/ 红色（缺失）

## 数据加载优先级

```
--session-id 指定时:
  1. 查询 ~/.hermes/state.db（或 --db-path 指定的路径）
  2. 找到 → 使用 DB 数据（精确时间戳）
  3. 未找到 → 检查是否提供了 --session-file
     - 有 → 使用 JSON 文件（估算时间戳）
     - 无 → 报错退出

--session-file 单独指定时:
  直接使用 JSON 文件
```

## 运行测试

```bash
cd ~/projects/hermes_bedrock_agent/hermes_session_viewer
PYTHONPATH=src python -m pytest tests/ -v
```

## 模块说明

| 模块 | 职责 |
|------|------|
| `cli.py` | 命令行入口，参数解析，流程编排 |
| `db_loader.py` | 从 state.db 加载会话（SQLite） |
| `loader.py` | 从 JSON 文件加载会话 |
| `timestamp.py` | 时间戳提取与估算（DB精确 / JSON线性插值） |
| `parser.py` | 消息 → 标准化事件模型转换 |
| `classifier.py` | 事件 → L1 阶段分类（12类） |
| `aggregator.py` | 连续同阶段事件聚合 |
| `natural_language.py` | 生成三语言自然语言摘要 |
| `i18n.py` | UI 翻译字典（zh/en/ja） |
| `html_renderer.py` | HTML 页面渲染 |
| `models.py` | 数据模型定义（Pydantic） |
| `utils.py` | 工具函数 |

## 限制与后续增强

### 当前限制
- 自然语言摘要基于规则模板，未使用 LLM
- 阶段分类基于关键词匹配，复杂场景可能误分类
- 不支持跨会话对比
- 不支持实时/增量更新

### 后续可增强方向
- LLM 辅助摘要（调用 Claude/GPT 生成更精准的自然语言描述）
- 时间轴图表可视化（甘特图、火焰图）
- 成本分析面板（基于 DB 中的 token/cost 数据）
- 多会话对比视图
- Datadog / OpenTelemetry 导出
- Web 服务模式（Flask/FastAPI 提供实时浏览）
