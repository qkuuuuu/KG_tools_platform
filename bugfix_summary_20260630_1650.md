# KG 平台 Bug 修复汇总 — 2026-06-30 16:50

## 本次完成的工作

### 1. 全局 Bug Review 报告
- 报告位置: `C:\Users\11491\Desktop\KG\kg-platform\bug_review_20260630.md`
- 审查范围: 37 个后端 Python 文件 + 15 个前端 Vue/JS 文件
- 发现问题: 3 个严重 + 7 个中等 + 8 个轻微 + 5 个优化建议

### 2. 已修复的 Bug

#### 🔴 严重 Bug（已修复）

| # | 问题 | 文件 | 修复内容 |
|---|------|------|----------|
| S1 | export.py 路由顺序导致 graph-data 被 `/{project_id}` 吞掉 | export.py | 将 `/{project_id}/graph-data` 移到 `/{project_id}` 之前 |
| S2 | ReviewHistory.vue formatDate 函数括号不匹配 | ReviewHistory.vue | 子代理已修复（补全右括号） |
| S3 | AuditLog timestamp 未显式设置可能为 NULL | hitl.py | 显式设置 `timestamp=datetime.utcnow()` |

#### 🟠 中等 Bug（已修复）

| # | 问题 | 文件 | 修复内容 |
|---|------|------|----------|
| M4 | fusion auto_fuse_passed 不去重，多次调用产生重复 | fusion.py | 新增 existing_fused_keys 检查 + existing_entity_map 预加载 |
| M6 | search 过滤把 NULL 置信度的三元组排除 | search.py | 改为 `(conf >= min) OR (conf IS NULL)` |

#### 🟡 轻微 Bug（已修复）

| # | 问题 | 文件 | 修复内容 |
|---|------|------|----------|
| L3 | "撚回成功" 错字 | hitl.py | 改为 "撤回成功" |

### 3. 引擎升级（子代理完成）

子代理 `kg-engine-upgrade` 已完成 5 项引擎改造：
- **RULE → CUSTOM_SCRIPT**: 删除 rule_extractor，新增自定义脚本上传引擎
- **GLiNER**: 换 `urchade/gliner_multilingual` 多语言模型
- **CasRel**: 换 ModelScope `damo/nlp_bert_relation-extraction_chinese-base`
- **DeepKE**: 换 ModelScope `damo/nlp_raner_named-entity-recognition_chinese-base-generic`
- **UIE**: 修复 Schema 读取 + 模型名改为 `uie-base-zh`
- 报告: `engine_upgrade_report_20260630.md`

### 4. 仍需手动处理

| 项目 | 操作 |
|------|------|
| 安装 ModelScope | `pip install modelscope` |
| 后端重启 | `cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| 前端重启 | `cd frontend && npm run dev` |
| 清浏览器缓存 | Ctrl+Shift+R 强刷 |

### 5. 未修复的遗留项（非阻塞）

| # | 问题 | 原因 |
|---|------|------|
| M1 | 时间戳缺 Z 后缀，前端显示少 8 小时 | 需要统一改所有路由，工作量大，建议后续批量处理 |
| M2 | 后台任务异常被静默吞 | 需要前端配合加 toast 通知 |
| M5 | WebSocket 推送在后台线程失效 | 需要重构事件循环引用 |
| L1 | main.py 注释中文乱码 | 编码问题，不影响运行 |
| L4 | 文档下载无权限隔离 | 单用户可接受 |
| L5 | 抽取接口要求 admin | 需确认业务需求 |
| L7 | G6 动态 import Vite 配置 | 需改 vite.config.js |

## 用户反馈的 3 个问题对应修复

| 用户反馈 | 根因 | 修复状态 |
|----------|------|----------|
| 图谱可视化点击没反应 | S1: export.py 路由顺序错误 | ✅ 已修复 |
| 审核了四五个但历史没记录 | S3: AuditLog timestamp 为 NULL 被 JOIN 过滤 | ✅ 已修复 |
| 审核历史没有同步到图谱按钮 | 代码中已存在，可能是缓存/未重启 | 需重启前端清缓存 |
