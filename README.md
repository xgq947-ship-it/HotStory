# HotStory

HotStory 是一个 macOS 本地运行的热点纪实剧本生成器。它先研究和核验事实，再组织时间线、真实案例、故事主线与价值方向，最终生成每个关键表达都能回溯到 `event_id` / `source_id` 的纪录片式短视频剧本。

> AI 负责搜索、提取、归纳、组织和表达，不负责创造现实世界中没有发生过的事实。

## 核心能力

- 手动输入热点，或从百度、微博、今日头条热榜选择社会纪实选题。
- 通过多视角研究问题执行背景、数据、案例、转折、社会反应和官方回应五轮搜索。
- 静态网页优先使用 HTTPX + Trafilatura；正文过短时可选 Crawl4AI fallback。
- 来源按规范化 URL、正文哈希和标题相似度去重。
- 事实、事件、时间线、故事和剧本全部保存到 SQLite 与独立 JSON/Markdown 文件。
- 死亡、自杀、犯罪、重大财产损失、医疗、未成年人等敏感事实必须至少有两个独立来源。
- 每个 Pipeline 步骤保存状态；服务中断后可从已完成步骤继续，不重复搜索、抓取或模型调用。
- 剧本完成后自动审校，低于 85 分最多修订两次。

## 架构

```text
Next.js UI
    ↓
FastAPI / SQLite
    ↓
NativeResearchEngine（可换 GPTResearcherEngine）
    ├─ SearchProvider：DuckDuckGo / Tavily / Brave / Serper
    ├─ CrawlerProvider：SimpleHttp / Crawl4AI / Auto
    └─ LLMProvider：DeepSeek / Codex CLI / OpenAI / Anthropic / OpenAI-compatible
             ↓
Fact Extractor → Event Cluster → Verification → Timeline
             ↓
Story Builder → Value Builder → Script Writer → Review
```

第三方项目均通过 Library、HTTP API、Adapter 或 Provider 接入，不复制其源码。版本与 License 见 [THIRD_PARTY.md](./THIRD_PARTY.md)。

## 环境要求

- macOS
- Python 3.12+
- Node.js 20+（已在 Node.js 24 验证）
- npm 10+
- [uv](https://docs.astral.sh/uv/)

## 快速启动

项目已经创建好 Python 3.12 虚拟环境和前端依赖，直接运行：

```bash
cd /Users/dasheng/Desktop/HotStory
./scripts/dev.sh
```

打开：

- UI：<http://127.0.0.1:3000>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

首次在其他机器安装：

```bash
cd backend
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt

cd ../frontend
npm install
```

## LLM Provider

配置文件是项目根目录 `.env`，该文件已加入 `.gitignore`，API Key 不进入前端。

### DeepSeek（推荐）

```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
LLM_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=你的密钥
```

模型请求默认 60 秒超时、最多重试 1 次；坏来源会被记录并跳过，不会把整轮研究卡死。写稿或自动修订遇到超时、空响应时，会改用已核验素材生成安全版本。可用 `LLM_TIMEOUT_SECONDS` 与 `LLM_MAX_RETRIES` 调整。

DeepSeek 通过兼容 Chat Completions 的 `/chat/completions` 接口调用，结构化阶段使用 JSON Output。模型目录可能变化，升级前请检查 [DeepSeek 官方文档](https://api-docs.deepseek.com/)。

### Codex CLI（无 API Key 的本地备用）

```env
LLM_PROVIDER=codex_cli
CODEX_CLI_PATH=codex
CODEX_CLI_MODEL=
```

需要先让本机 Codex CLI 完成登录。HotStory 以 `--ephemeral --sandbox read-only --ignore-rules` 调用，避免模型修改项目文件。Codex CLI 适合本地备用，但多次子进程调用通常比直接 API 慢。

### OpenAI / Anthropic / OpenAI-compatible

```env
LLM_PROVIDER=openai
LLM_MODEL=你的模型 ID
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.openai.com/v1
```

```env
LLM_PROVIDER=anthropic
LLM_MODEL=你的模型 ID
ANTHROPIC_API_KEY=你的密钥
LLM_BASE_URL=https://api.anthropic.com/v1
```

其他兼容接口使用 `LLM_PROVIDER=openai_compatible`，并填写模型、Key 与 Base URL。

## Search Provider

默认 DuckDuckGo，无需 Key：

```env
SEARCH_PROVIDER=duckduckgo
```

也支持 `tavily`、`brave`、`serper`：

```env
SEARCH_PROVIDER=tavily
SEARCH_API_KEY=你的密钥
```

热榜只是选题入口，不会直接作为最终事实来源。每个标题仍会进入独立搜索与核验链路。

## Crawl4AI 与 Playwright

默认 `CRAWLER_PROVIDER=auto`：先使用轻量静态抓取，失败或正文过短时尝试 Crawl4AI。可选安装：

```bash
cd backend
uv pip install --python .venv/bin/python -r requirements-optional.txt
.venv/bin/crawl4ai-setup
.venv/bin/python -m playwright install chromium
```

如果不安装可选依赖，SimpleHttpCrawler 仍可独立运行。

## GPT Researcher

安装可选依赖后设置：

```env
RESEARCH_ENGINE=gpt_researcher
```

HotStory 仅复用其研究与来源发现能力，随后转换成自己的 `ResearchResultData`。事实提取、核验、时间线、故事与剧本仍由 HotStory 负责。默认 `native` 不依赖 GPT Researcher。

## 自动热点

默认 `auto` 先读取百度、微博、今日头条公开热榜；若不可用，再尝试 DailyHotApi。入口会硬过滤政治、外交、选举等新闻，并优先推荐普通人处境、教育、职场、消费、医疗、金融风险、公共安全与平台争议等社会事件。DailyHot 与平台接口都由独立 Provider 隔离：

```env
HOTSPOT_PROVIDER=auto
DAILYHOT_API_BASE_URL=https://api-hot.imsyy.top
```

如使用自己部署的 DailyHotApi，可设置 `HOTSPOT_PROVIDER=dailyhot`；当前 Adapter 支持 `baidu`、`weibo`、`zhihu`。

如已有 TrendRadar HTTP 输出：

```env
HOTSPOT_PROVIDER=trendradar
TRENDRADAR_API_BASE_URL=http://127.0.0.1:你的端口/你的接口
```

Provider 输出会统一成 `HotspotData`，上游接口异常不会影响历史项目读取。

## 数据与断点恢复

SQLite：

```text
data/hotstory.db
```

每个主题的独立档案：

```text
data/projects/{topic_id}/
├── topic.json
├── research_plan.json
├── search_results.json
├── sources.json
├── facts.json
├── events.json
├── timeline.json
├── story_arc.json
├── value.json
├── review.json
├── script.md
└── llm_raw/
```

`step_runs` 记录每一步的开始、完成、错误和重试次数；`search_runs` 缓存每个查询；`sources` 缓存正文；`llm_calls` 保存原始模型响应。点击“继续深挖”只补充新查询并运行未完成步骤。

需要重置时使用可恢复方式：

```bash
./scripts/reset_db.sh --yes
```

旧数据会移动到 `data/trash/{时间戳}/`，不会直接删除。

## API

```text
POST /api/topics
GET  /api/topics
GET  /api/topics/{id}
POST /api/topics/{id}/research
GET  /api/topics/{id}/status
GET  /api/topics/{id}/sources
GET  /api/topics/{id}/facts
GET  /api/topics/{id}/events
GET  /api/topics/{id}/timeline
GET  /api/topics/{id}/story
GET  /api/topics/{id}/script
GET  /api/topics/{id}/script/download
POST /api/topics/{id}/continue
POST /api/topics/{id}/rewrite-script
GET  /api/hotspots
```

完整请求结构见运行后的 `/docs`。

## 质量门槛

默认只有达到以下标准才写剧本：

```text
有效来源 >= 10
已核验事实 >= 12
时间节点 >= 5
真实个人案例 >= 2
关键数据 >= 2
```

不足时 Topic 会显示“研究素材不足”，前端提供“继续深挖”，系统不会让模型补造事实。

## 验证

```bash
./scripts/check.sh
```

该命令执行：

- Ruff 静态检查
- Pytest 后端测试
- TypeScript 检查
- Next.js 生产构建

## 故障排查

**健康检查显示 `llm_ready=false`**：检查 `.env` 中对应 Provider 的模型与 Key。Codex CLI 模式检查 `codex --version` 和登录状态。

**搜索结果较少**：DuckDuckGo 可能限流，可切换 Tavily / Brave / Serper；也可点击“继续深挖”增加本地语言与原始资料查询。

**部分网页抓取失败**：这是正常现象，系统会记录错误并继续其他来源。动态页面可安装 Crawl4AI 与 Chromium。

**服务意外退出**：重新运行 `./scripts/dev.sh`，打开原 Topic 后点击继续。成功步骤不会重复消耗 API。

**端口被占用**：关闭占用 8000 或 3000 的本地进程后重启。

## 原则

```text
真实性 > 戏剧性
来源 > AI 推断
事实 > 情绪
多来源验证 > 单一爆款帖子
原始资料 > 二手转载
```

HotStory 不提供投资建议、涨跌预测或高杠杆鼓励；涉及金融事件时，默认价值方向是理性、风险意识、量力而行与长期主义。
