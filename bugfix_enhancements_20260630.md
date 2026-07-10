# KG 平台 Bug 修复 + 新功能 — 2026-06-30

## 目标
代码审查发现的 Bug 修复 + 新增实用功能 + 性能优化。

## Bug 修复 (9 项)

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| B1 | extraction.py | BackgroundTasks=None 导致质检任务不启动 | 改为 `BackgroundTasks` 无默认值 |
| B2 | quality/__init__.py | Python re 不支持 `\p{P}` 正则 | 替换为字符类 |
| B3 | extraction.py | doc_id/threshold 参数未标 Form() | 添加 Form(...) |
| B4 | HITL.vue | markAction 逻辑：编辑模式进/出都 push | 只在退出编辑时 push MODIFY |
| B5 | rule_extractor.py | register_rule_rule 函数名错误 | 改为 register_rule_template |
| B7 | neo4j_exporter.py | Cypher 脚本转义不完整 | 新增 _escape_cypher 函数 |
| B9 | Extract.vue | downloadMarkdown 用 localStorage 直读 token | 改用 useAuthStore |
| B12 | extraction.py | 无去重，同文档多次抽取产生重复 | 新增基于 (subject,predicate,object) 的去重 |
| B14 | export.py | graph-data 节点 group 用首字母，颜色过多 | 改为基于实体类型的分组 |

## 性能优化 (5 项)

| # | 文件 | 优化 |
|---|------|------|
| P1 | main.py | CORS 改为可配置 (KG_CORS_ORIGINS 环境变量) |
| P2 | config.py | JWT_SECRET 优先环境变量 |
| P3 | config.py | ENCRYPTION_KEY 优先环境变量 |
| P5 | llm_config.py | 空 api_key 不覆盖已有 key |
| P8 | fusion.py | 实体创建改 flush，最终统一 commit |

## 新功能 (6 项)

| # | 功能 | 后端 | 前端 |
|---|------|------|------|
| F2 | 抽取结果去重 | extraction.py 增加 seen_keys 去重 | — |
| F3 | 多项目图谱融合 | GET /export/multi-project-graph | MultiGraph.vue (G6 力导向图) |
| F4 | 审核历史 | GET /review/{pid}/history + /stats | ReviewHistory.vue (统计卡片+日志) |
| F5 | 三元组搜索 | GET /search/{pid}/triples-search | Search.vue (高亮+分页+过滤) |
| F7 | LLM 抽取缓存 | llm_cache.py (24h TTL, SHA256 key) | — |
| F8 | 文档列表分页 | GET /data/documents?page=&page_size= | — |
| F10 | WebSocket 进度推送 | /ws/tasks/{project_id} | 前端待对接 |

## 延迟导入优化
- GLiNER: 全局缓存 `_MODEL_CACHE`，首次调用才加载模型
- UIE: 保持 paddle 延迟 import

## 验证结果
- 后端启动: OK (20 routes)
- Search API: 6 results ✅
- Review History API: 0 records (无审核数据) ✅
- Review Stats API: 0 reviews ✅
- Multi-Project Graph API: 228 nodes, 157 edges ✅
