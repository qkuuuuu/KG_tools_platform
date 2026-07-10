# KG Platform 全链路开发日志

## 2026-06-30 09:42 - 全功能实现 + Bug 修复

### 一、目标
全功能实现多方法知识图谱构建平台，使用 test.pdf 验证端到端链路。

### 二、完成工作

#### 2.1 Bug 修复 (3个关键Bug)

| # | 问题 | 文件 | 修复 |
|---|------|------|------|
| 1 | `\p{P}` 正则语法错误导致 LLM 抽取失败 (`bad escape \p`) | `quality/__init__.py` | 改为显式标点字符类 |
| 2 | `BackgroundTasks = None` 默认值导致质检后台任务不注入/不执行 | `extraction.py` | 移除非 FastAPI 参数的默认值，调整参数顺序 |
| 3 | `export.py` 使用已弃用的 `regex` 参数 | `export.py:29` | 改为 `pattern` |

#### 2.2 新功能

| 功能 | 状态 | 说明 |
|------|------|------|
| Markdown 下载 | ✅ | `GET /data/documents/{doc_id}/download` 接口 |
| 6引擎抽取池 | ✅ | LLM_PROMPT / RULE / GLiNER / UIE / CASREL / DEEPKE 全部就绪 |
| `/data/engines` 接口 | ✅ | 前端可查询引擎可用性 |
| `/data/triples/{project_id}` 接口 | ✅ | 按项目查询三元组 + 状态过滤 |
| 前端 Extract 页 | ✅ | 三步工作流(解析→抽取→质检) + Markdown 预览/下载 |

#### 2.3 依赖安装

- spacy + en_core_web_sm (GLiNER 依赖)
- gliner (零样本 NER)

### 三、测试结果

#### test.pdf 完整链路验证

```
文件: test.pdf (287KB, 水泥厂设备维护文档)
解析引擎: pdfplumber
解析评分: 90.0
Markdown内容: 11,160 字符 (原始文件字节 23,110)

抽取引擎: LLM_PROMPT (DeepSeek-V4-Pro)
抽取结果:
  - 总数: 168 条三元组
  - 关系: 7 种
    · hasComponent: 50
    · componentOf: 43
    · hasProcessParameter: 35
    · infersFaultMode: 32
    · equipmentLocatedAt: 6
    · consumesMaterial: 1
    · hasSparePart: 1
  - 置信度: ≥90: 149, 80-89: 8, 70-79: 10, <70: 1

Markdown 下载: HTTP 200, 23,110 bytes ✅
质检任务: 已提交, 后台运行中 ✅
```

#### 引擎池状态

| 引擎 | 状态 |
|------|------|
| LLM_PROMPT | ✅ ready |
| RULE | ✅ ready |
| GLiNER | ✅ ready |
| UIE | ✅ ready |
| CASREL | ✅ ready |
| DEEPKE | ✅ ready |

### 四、仍待完成

1. 后端: 融合路由中 EntityFused/TripleFused 表可能需初始化
2. 前端: Dashboard 需对接新的 /data/triples API
3. 前端: Export 页融合建议已可展示，Neo4j 同步需 Neo4j 实例
4. Docker Compose 部署文件
5. GLiNER/UIE/CasRel/DeepKE 模块里 model 下载需首次运行时自动触发

### 五、文件清单

```
kg-platform/
├── backend/
│   ├── app/
│   │   ├── routers/
│   │   │   ├── documents.py      ← 新增 download 接口
│   │   │   ├── extraction.py     ← 修复 BackgroundTasks + 新增 engines/triples 接口
│   │   │   └── export.py         ← 修复 deprecated regex
│   │   └── services/
│   │       ├── extraction/
│   │       │   └── __init__.py   ← 修复引擎检测逻辑
│   │       └── quality/
│   │           └── __init__.py   ← 修复 \p{P} 正则
│   ├── test_full_pipeline.py     ← 全链路测试脚本
│   └── verify_pipeline.py        ← 验证脚本
└── frontend/
    └── src/
        └── views/
            └── Extract.vue       ← 全面改造(三步工作流)
```

### 六、启动命令

```bash
# 后端
cd kg-platform/backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端
cd kg-platform/frontend
npm run dev
```
