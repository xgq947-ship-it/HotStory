# Third-party dependencies

HotStory 使用 Adapter / Provider 接入第三方能力，不复制第三方项目源码。Python 与 Node 的精确版本分别锁定在 `backend/requirements*.txt` 和 `frontend/package-lock.json`。

## 核心运行依赖

| 项目 | 当前锁定版本 | License | 用途 |
|---|---:|---|---|
| FastAPI | 0.141.1 | MIT | 本地 API |
| SQLAlchemy | 2.0.51 | MIT | SQLite ORM |
| Pydantic | 2.13.4 | MIT | 数据与 LLM JSON 校验 |
| HTTPX | 0.28.1 | BSD-3-Clause | HTTP Provider |
| Trafilatura | 2.2.0 | Apache-2.0 | 静态网页正文提取 |
| Beautiful Soup | 4.15.0 | MIT | HTML fallback |
| DDGS | 9.14.4 | MIT | 默认无 Key 搜索入口 |
| Next.js | 16.3.0 | MIT | 前端 |
| React | 19.2.8 | MIT | 前端 |
| Tailwind CSS | 4.3.3 | MIT | UI 样式 |

## 可选开源集成

| 项目 | 当前锁定/参考版本 | License | 集成边界 |
|---|---:|---|---|
| [Crawl4AI](https://github.com/unclecode/crawl4ai) | 0.9.2 | Apache-2.0，包含上游要求的公开署名条款 | Python Library；仅静态抓取失败时启用 |
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | 0.16.0 | Apache-2.0 | Python Library；转换为 HotStory `ResearchResultData` |
| [DailyHotApi](https://github.com/imsyy/DailyHotApi) | HTTP Provider | MIT | 只提供选题入口，不作为事实来源 |
| [TrendRadar](https://github.com/sansan0/TrendRadar) | HTTP Adapter | MIT | 只消费统一 Hotspot 数据结构 |
| [STORM](https://github.com/stanford-oval/storm) | 架构参考 | 上游仓库为准 | 只参考多视角研究思路，不复制或耦合代码 |
| [Open Deep Research](https://github.com/langchain-ai/open_deep_research) | 架构参考 | MIT | V1 不集成，仅作后续并行研究参考 |

若未来修改可选集成版本，应重新检查上游 License 与安全公告。

