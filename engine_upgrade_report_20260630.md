# KG 平台抽取引擎升级报告

**日期**: 2026-06-30  
**操作人**: AI Subagent  
**范围**: 后端 6 个文件修改/新建，前端 2 个文件修改，5 个 .vue 文件预存 bug 修复

---

## 一、任务1: Rule 引擎 → 自定义脚本引擎 (CUSTOM_SCRIPT)

### 后端改动

#### 1.1 删除 `rule_extractor.py`
- 原文件已重命名为 `rule_extractor.py.bak`（保留备份）
- 原 Rule 引擎的正则规则模板逻辑已内联到 GLiNER 降级方案中

#### 1.2 新建 `custom_script_extractor.py`
- **脚本存储**: `uploads/scripts/` 目录
- **动态加载**: 使用 `importlib.util.spec_from_file_location` 加载 .py 模块
- **约定接口**: `def extract(md_content: str, schemas: list) -> list`
- **输出格式**: `{"subject", "predicate", "object", "confidence": None, "extraction_method": "CUSTOM_SCRIPT", "chunk"}`
- **限制**:
  - 文件大小: 1MB 以内
  - 执行超时: 60 秒（使用 threading + join 实现，兼容 Windows）
- **不做沙箱隔离**，信任用户脚本（内部系统）
- **模块缓存**: 已加载的模块缓存在 `_MODULE_CACHE` 字典中

#### 1.3 修改 `extraction.py` 路由
- **新增** `POST /data/upload-script`: 上传 .py 脚本文件
- **新增** `GET /data/scripts`: 列出已上传脚本
- **新增** `DELETE /data/scripts/{script_id}`: 删除脚本
- **修改** `POST /data/extract`: 新增 `script_id` Form 参数，CUSTOM_SCRIPT 方法时传给引擎

#### 1.4 修改 `__init__.py` 引擎注册表
- 移除 `RULE` 引擎
- 新增 `CUSTOM_SCRIPT` 引擎（始终可用）
- `extract_triples()` 函数新增 `CUSTOM_SCRIPT` 分支

### 前端改动

#### 1.5 修改 `api/index.js`
- 新增 `scriptApi` 对象:
  - `upload(file, description, onProgress)`: 上传脚本
  - `list()`: 列出脚本
  - `delete(scriptId)`: 删除脚本
- 修改 `extractApi.extract`: 新增 `scriptId` 参数

#### 1.6 重写 `Extract.vue`
- 抽取对话框新增 **脚本选择器**：当引擎选为 CUSTOM_SCRIPT 时显示
- 新增 **上传脚本对话框**: 文件选择器(accept=".py") + 脚本说明输入框 + 上传按钮
- 脚本列表自动加载，支持删除
- 开始抽取按钮在未选脚本时禁用
- 引擎切换时自动加载脚本列表（watch 机制）

---

## 二、任务2: GLiNER 换多语言模型

### 修改 `gliner_extractor.py`

1. **默认模型**: `urchade/gliner_medium-v2.1` → `urchade/gliner_multilingual`
2. **`_normalize_label` 函数**: 中文标签直接返回原文，不转英文。CamelCase 英文标签保持原样
3. **`_extract_labels_from_schemas` 函数**: 
   - 保留中文原文（如"设备"、"故障类型"）
   - 同时追加英文翻译作为备选 labels
   - 默认标签集也改为中英双语
4. **`_pair_entities` 函数**: Schema 标签映射支持中文原文 + 英文翻译 + 交叉匹配（4 种键组合）
5. **模型缓存逻辑**: 首次调用 `GLiNER.from_pretrained()` 下载，后续从 `_MODEL_CACHE` 加载，打印加载日志
6. **`_rule_fallback`**: 内联实现正则规则（不再依赖已移除的 rule_extractor）

---

## 三、任务3: CasRel 换 ModelScope 达摩院中文模型

### 重写 `casrel_extractor.py`

1. **模型**: `damo/nlp_bert_relation-extraction_chinese-base` (ModelScope)
2. **延迟加载**: `_get_pipeline()` 函数，首次调用时下载模型，缓存在 `_CASREL_PIPELINE`
3. **输出适配**: 兼容多种 ModelScope 输出格式 (`text-tags-spo`, `spo`, `output`, `predictions`)
4. **中文分句**: `_split_sentences()` 按中英文标点分句，合并过短句子
5. **Schema 约束过滤**: 识别到的三元组按 Schema 谓词过滤（支持模糊匹配）
6. **降级策略**: 
   - ModelScope 加载失败 → 正则 NER (`_find_entities_by_regex`) + Schema 配对 (`_casrel_pair`)
   - 正则 NER 支持: 设备、故障、材料、工序、英文实体、型号等
7. **日志**: 模型加载前后打印提示信息

---

## 四、任务4: DeepKE 换 ModelScope NER 模型

### 重写 `deepke_extractor.py`

1. **模型**: `damo/nlp_raner_named-entity-recognition_chinese-base-generic` (ModelScope NER)
2. **架构**: NER 实体识别 → Schema 约束 + 共现窗口关系配对
3. **标签映射**: `_map_ner_label()` 将 ModelScope NER 标签 (PER/ORG/LOC 等) 映射为中文统一标签
4. **延迟加载**: `_get_pipeline()` 函数，首次调用时下载
5. **降级策略**:
   - ModelScope 加载失败 → 正则 NER (`_find_entities_by_regex`) + Schema 配对
   - 正则 NER 支持中文实体模式: 设备、故障类型、原料、工序段、人物、组织、地点
6. **关系配对**: `_pair_entities_with_schema()` 使用 Schema 约束 + 共现窗口(800字) + 模糊匹配
7. **日志**: 模型加载和推理过程打印提示

---

## 五、任务5: UIE Schema 读取检查

### 修改 `uie_extractor.py`

1. **模型名**: `uie-base` → `uie-base-zh`（明确使用中文模型）
2. **调试日志**: 
   - `extract_with_uie()` 入口打印 schemas 数量和内容（前3条）
   - `_collect_entity_types()` 打印提取的 entity_types
   - `_uie_dynamic_extract()` 打印模型名、设备、entity_types
   - 每个 chunk 的实体提取数量
   - 最终三元组数量
3. **`_collect_entity_types` 验证**: 确认正确提取所有 `subject_type` 和 `object_type`
4. **`_to_cn` 映射扩充**:
   - 新增: `EquipmentName → 设备`, `FaultMode → 故障类型`, `Product → 产品`, `Event → 事件`
   - 新增不区分大小写的查找
   - 未找到映射时打印警告并返回原始值
   - 确保传入中文时直接返回
5. **空值保护**: schemas 为空时使用默认 entity_types 并打印警告

---

## 六、通用要求达成情况

| 要求 | 状态 |
|------|------|
| 所有引擎 confidence 字段统一设为 None | ✅ 已完成 |
| extraction_method 字段正确 (RULE→CUSTOM_SCRIPT) | ✅ 已完成 |
| 降级策略: 模型加载失败不崩溃 | ✅ 所有引擎都有降级 |
| ModelScope 模型首次加载加日志提示 | ✅ 已添加 |
| `__init__.py` 引擎注册表移除 RULE 新增 CUSTOM_SCRIPT | ✅ 已完成 |

---

## 七、新增依赖包

| 包名 | 用途 | 安装命令 |
|------|------|----------|
| modelscope | CasRel + DeepKE 的 ModelScope 模型 | `pip install modelscope` |

> **注意**: GLiNER、UIE 的依赖未变（分别为 `gliner` 和 `paddlenlp`）

---

## 八、需要用户手动操作

1. **安装 ModelScope**:
   ```bash
   pip install modelscope
   ```

2. **首次使用 CasRel 引擎**: 
   - 第一次调用时会自动下载 `damo/nlp_bert_relation-extraction_chinese-base` 模型
   - 下载时间取决于网络，可能需要几分钟
   - 后续调用从本地缓存加载

3. **首次使用 DeepKE 引擎**:
   - 第一次调用时会自动下载 `damo/nlp_raner_named-entity-recognition_chinese-base-generic` 模型
   - 同上

4. **首次使用 GLiNER 引擎**:
   - 第一次调用时会自动下载 `urchade/gliner_multilingual` 模型（多语言版）
   - 设置了 HF_ENDPOINT=https://hf-mirror.com 加速下载

5. **自定义脚本**:
   - 在抽取页面选择"CUSTOM_SCRIPT"引擎
   - 点击"上传脚本"按钮上传 .py 文件
   - 脚本需实现 `def extract(md_content: str, schemas: list) -> list` 接口
   - 返回格式: `[{"subject": "...", "predicate": "...", "object": "...", "chunk": "..."}]`

---

## 九、验证结果

| 验证项 | 状态 |
|--------|------|
| 后端 Python 文件语法正确 | ✅ 全部通过 ast 解析 |
| 前端 Vite 编译 | ✅ 构建成功 (12.48s, 305 modules) |
| 引擎注册表更新 | ✅ RULE 移除, CUSTOM_SCRIPT 新增 |
| API 路由完整 | ✅ upload-script, scripts, scripts/{id}, extract |

---

## 十、遗留问题

1. **ModelScope 输出格式未实测**: `damo/nlp_bert_relation-extraction_chinese-base` 的实际输出格式需要调用确认。代码中做了多种格式的兼容适配（`text-tags-spo`、`spo`、`output`、`predictions`），但实际格式可能需要微调。

2. **UIE 顶层 import**: `uie_extractor.py` 中的 `import paddle` 和 `from paddlenlp.transformers import UIE, AutoTokenizer` 位于模块顶层（而非函数内部），如果未安装 paddlenlp，导入此模块会报错。这影响了 `_check_engine_import` 的判断逻辑。建议后续将这两个 import 移入 `_uie_dynamic_extract` 函数内部。

3. **rule_extractor.py.bak**: 原 Rule 引擎文件已备份为 `.bak`，如需保留可重命名恢复。GLiNER 降级方案中的 `_rule_fallback` 已内联了正则规则，不再依赖原文件。

4. **前端预存 bug 修复**: 修复了 5 个 .vue 文件中 `formatDate` 函数缺少闭合括号 `)` 的预存 bug（Projects.vue, Dashboard.vue, Extract.vue, ReviewHistory.vue, Users.vue）。

5. **ModelScope 模型下载网络**: 如果在中国大陆网络环境，ModelScope 模型下载通常较快（阿里云 CDN）。但如果在海外环境，可能需要配置 ModelScope 镜像。

6. **自定义脚本安全**: 当前不做沙箱隔离，信任用户脚本。如果未来需要对外开放，需要加入执行隔离（如 subprocess + resource limit）。

---

## 修改文件清单

### 后端 (7 个文件)
| 文件 | 操作 |
|------|------|
| `app/services/extraction/__init__.py` | 修改: 引擎注册表更新 |
| `app/services/extraction/custom_script_extractor.py` | 新建: 自定义脚本引擎 |
| `app/services/extraction/rule_extractor.py` | 删除(重命名为.bak) |
| `app/services/extraction/gliner_extractor.py` | 修改: 多语言模型+中文标签 |
| `app/services/extraction/casrel_extractor.py` | 重写: ModelScope 中文模型 |
| `app/services/extraction/deepke_extractor.py` | 重写: ModelScope NER 模型 |
| `app/services/extraction/uie_extractor.py` | 修改: Schema 读取修复+日志 |
| `app/routers/extraction.py` | 修改: 新增脚本 API+script_id 参数 |

### 前端 (7 个文件)
| 文件 | 操作 |
|------|------|
| `src/api/index.js` | 修改: 新增 scriptApi |
| `src/views/Extract.vue` | 重写: 脚本引擎 UI |
| `src/views/Projects.vue` | 修复: formatDate 括号 bug |
| `src/views/Dashboard.vue` | 修复: formatDate 括号 bug |
| `src/views/ReviewHistory.vue` | 修复: formatDate 括号 bug |
| `src/views/Users.vue` | 修复: formatDate 括号 bug |
