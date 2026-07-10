# KG 平台抽取引擎 API 用法修复报告

**日期**: 2026-06-30  
**修改范围**: 5 个抽取引擎的 API 用法错误  
**项目位置**: `C:\Users\11491\Desktop\KG\kg-platform\backend\app\services\extraction\`

---

## 修复总览

| # | 引擎 | 文件 | 严重程度 | 修复状态 |
|---|------|------|----------|----------|
| 1 | UIE | `uie_extractor.py` | 🔴 最严重 | ✅ 完全重写 |
| 2 | GLiNER | `gliner_extractor.py` | 🟡 中等 | ✅ 修复 |
| 3 | CasRel | `casrel_extractor.py` | 🟡 中等 | ✅ 修复 |
| 4 | DeepKE | `deepke_extractor.py` | 🟡 中等 | ✅ 修复 |
| 5 | Custom Script | `custom_script_extractor.py` | 🔴 Windows 阻断 | ✅ 修复 |

---

## 1. UIE 改用 Taskflow API（最严重）

### 文件
`app/services/extraction/uie_extractor.py`

### 修改内容
**完全重写**，删除所有手动 UIE 推理代码，改用 PaddleNLP 官方 Taskflow API。

### 修改前（Bug）
- 使用 `UIE.from_pretrained` + 手动 `AutoTokenizer` + 手动 `start_prob/end_prob` 解码
- 手动遍历 token 位置做实体解码，逻辑复杂且容易出错
- `paddle.to_tensor` / `paddle.argmax` 等底层 paddle 操作直接暴露
- 关系抽取函数 `_extract_relations_uie` 返回空列表（未实现）

### 修改后（正确）
- 使用 `from paddlenlp import Taskflow` 官方 API
- **实体抽取**: `Taskflow('information_extraction', schema=entity_types, model='uie-base-zh')`
  - 返回格式: `[{'人物': [{'text': '张三', 'start': 0, 'end': 2, 'probability': 0.99}], ...}]`
- **关系抽取**: 使用嵌套 schema `[{主体类型: [{'relation': '谓词', 'object_type': '客体类型'}]}]`
  - 返回格式含 `relations` 嵌套结构
- Taskflow 对象缓存（`_TASKFLOW_ENTITY` / `_TASKFLOW_RELATION`）
- 删除了 `_uie_dynamic_extract`、`_extract_entities_uie`、`_extract_relations_uie` 等手动推理函数
- 新增 `_build_relation_schema()` 构建 Taskflow 嵌套 schema
- 新增 `_merge_entity_relation_results()` 合并实体+关系抽取结果
- 实体配对使用 `_find_all_positions()` 查找所有出现位置（解决重复实体漏抽问题）
- 保留 `_to_cn` 映射 + `_collect_entity_types` + `_uie_fallback_spacy` 降级方案
- `confidence` 统一为 `None`

### 关键差异
| 维度 | 修改前 | 修改后 |
|------|--------|--------|
| 推理方式 | 手动 UIE 模型 + tokenizer | Taskflow 官方 API |
| 实体解码 | 手动遍历 start_prob/end_prob | Taskflow 自动解码 |
| 关系抽取 | 未实现（返回空） | 嵌套 schema 自动抽取 |
| 代码行数 | ~280 行 | ~300 行（但逻辑更清晰） |

---

## 2. GLiNER 修正 labels 和配对逻辑

### 文件
`app/services/extraction/gliner_extractor.py`

### 修改内容

#### 2a. `_extract_labels_from_schemas` — 只保留原文标签
- **修改前**: 对每个标签同时添加中文原文和英文翻译（通过 `_normalize_label` 转换），导致 labels 列表过长，降低 GLiNER 精度
- **修改后**: 只保留 schema 中的原始标签（中文或英文），不追加翻译
- 默认标签集也从 12 个（中英双语）减少为 6 个（仅中文）

#### 2b. `_pair_entities` — 简化匹配逻辑
- **修改前**: 构建 4 套匹配键（中文原文、英文翻译、中英交叉×2），全部用 `.lower()` 归一化，逻辑复杂且容易误匹配
- **修改后**: 直接用 `(subj_label, obj_label) → predicate` 精确匹配，不做 `.lower()` 转换
- 不在 Schema 约束内的实体对直接跳过（不再生成 `{subj_label}-{obj_label}` 这种无意义谓词）

#### 2c. 合并 `_extract_with_gliner_model_chunked` 到 `_extract_with_gliner_model`
- **修改前**: 两个独立函数，主函数先调用 `_extract_with_gliner_model`，失败后调用 `_extract_with_gliner_model_chunked`
- **修改后**: 合并为一个函数，先尝试整段推理，未找到实体则自动分段落重试
- 删除了 `_extract_with_gliner_model_chunked` 函数

### 关键差异
| 维度 | 修改前 | 修改后 |
|------|--------|--------|
| labels 数量 | 原文+翻译（可能 2N 个） | 仅原文（N 个） |
| 配对匹配 | 4 套键 + .lower() | 1 套精确匹配 |
| 分块逻辑 | 独立函数 | 合并到主函数 |

---

## 3. CasRel ModelScope 输出格式修正

### 文件
`app/services/extraction/casrel_extractor.py`

### 修改内容
修正 `_extract_with_modelscope` 中的输出解析逻辑，增加对 `pred_label` 字段的处理。

### 修改前（Bug）
- 只尝试了 `predicate`、`relation` 字段名
- 未处理 ModelScope relation_extraction 模型实际输出的 `pred_label` 字段
- 导致 ModelScope 模型返回的关系数据中 predicate 始终为空字符串

### 修改后（正确）
- `pred_label` 字段映射到 `predicate`
- 兼容 4 种输出格式：
  1. `{"output": [{"pred_label": "...", "subject": "...", "object": "..."}]}`
  2. `{"text-tags-spo": [...]}`
  3. `{"spo": [...]}`
  4. 直接返回列表 `[{"subject": ..., "predicate": ..., "object": ...}]`
- 字段提取顺序: `predicate` → `pred_label` → `relation`

### 关键差异
| 维度 | 修改前 | 修改后 |
|------|--------|--------|
| 谓词字段 | `predicate`, `relation` | `predicate`, `pred_label`, `relation` |
| 格式兼容 | 3 种 | 4 种（含 pred_label） |

---

## 4. DeepKE 共现检查修复

### 文件
`app/services/extraction/deepke_extractor.py`

### 修改内容
修正 `_pair_entities_with_schema` 中的共现窗口检查，使用实体在原文中的所有出现位置。

### 修改前（Bug）
- `full_text.find(subj["text"])` 只返回实体第一次出现的位置
- 如果同一实体在文中出现多次（如"张三"出现在第 10 字和第 500 字），`find` 只返回 10
- 导致与位置较远的实体配对时误判距离 > 800 而漏抽

### 修改后（正确）
- 新增 `_find_all_positions(text, substring)` 函数，返回所有出现位置
- 配对时遍历所有位置组合，取最近距离判断共现
- 如果实体不在原文中，回退到句子级别配对

### 关键差异
| 维度 | 修改前 | 修改后 |
|------|--------|--------|
| 位置查找 | `find()` 仅第一次 | `_find_all_positions()` 所有位置 |
| 距离计算 | 可能误判远距离 | 取最近距离 |

---

## 5. custom_script_extractor.py 修正 signal 用法

### 文件
`app/services/extraction/custom_script_extractor.py`

### 修改内容
删除 Windows 不兼容的 `signal.alarm` 相关代码。

### 修改前（Bug）
- `import signal` 语句在文件中
- `_timeout_handler` 函数使用 `signal.alarm(60)` 做 Unix 超时
- Windows 上 `signal.SIGALRM` 不存在，会引发 `AttributeError`
- 虽然代码后面用了 threading 替代，但 `import signal` 和 `_timeout_handler` 仍然存在

### 修改后（正确）
- 删除 `import signal` 语句
- 删除 `_timeout_handler` 函数
- 只保留 `threading` 超时方案（当前已实现且正确，兼容 Windows）
- 添加注释说明使用 threading 的原因

### 关键差异
| 维度 | 修改前 | 修改后 |
|------|--------|--------|
| signal 导入 | 存在 | 删除 |
| _timeout_handler | 存在 | 删除 |
| 超时方案 | signal + threading（双方案） | 仅 threading（Windows 兼容） |

---

## 验证结果

### 语法检查
```
All 5 files: syntax OK
```

### 引擎可用性检查
```python
from app.services.extraction import get_available_engines
# 返回 6 个引擎，全部 status='ready'
# LLM_PROMPT, CUSTOM_SCRIPT, GLINER, UIE, CASREL, DEEPKE
```

### UIE Taskflow 验证
```python
_collect_entity_types([{'subject_type': 'Person', 'predicate': 'worksFor', 'object_type': 'Organization'}])
# → ['人物', '组织']  ✅

_build_relation_schema(schemas)
# → [{'人物': [{'relation': 'worksFor', 'object_type': '组织'}]}]  ✅
```

### GLiNER labels 验证
```python
_extract_labels_from_schemas([{'subject_type': '人物', ...}, {'subject_type': 'Person', ...}])
# → ['Organization', 'Person', '人物', '组织']  (4 个，不再有翻译重复)  ✅
```

### Custom Script signal 验证
```python
# has signal import: False  ✅
# has _timeout_handler: False  ✅
# has threading: True  ✅
```

### CasRel pred_label 验证
```python
# has pred_label: True  ✅
```

### DeepKE _find_all_positions 验证
```python
_find_all_positions('张三去北京张三回家', '张三')
# → [0, 5]  ✅ (返回所有位置)
```

---

## 需要用户手动操作

### 必须安装
| 引擎 | 依赖 | 安装命令 |
|------|------|----------|
| UIE | paddlenlp | `pip install paddlenlp` |
| GLiNER | gliner | `pip install gliner` |
| CasRel | modelscope | `pip install modelscope` |
| DeepKE | modelscope | `pip install modelscope` |

### 可选安装（降级方案用）
| 引擎 | 降级依赖 | 安装命令 |
|------|----------|----------|
| UIE | spacy + 英文模型 | `pip install spacy && python -m spacy download en_core_web_sm` |
| GLiNER | spacy + 中文/英文模型 | `pip install spacy && python -m spacy download zh_core_web_sm` |

### 模型下载（首次运行自动下载）
| 引擎 | 模型 | 大小（约） |
|------|------|-----------|
| UIE | uie-base-zh | ~150MB |
| GLiNER | urchade/gliner_multilingual | ~340MB |
| CasRel | damo/nlp_bert_relation-extraction_chinese-base | ~400MB |
| DeepKE | damo/nlp_raner_named-entity-recognition_chinese-base-generic | ~400MB |

---

## 遗留问题

1. **UIE Taskflow schema 不可变**: Taskflow 初始化后 schema 不可修改，当前实现在每次调用时如果 entity_types 变化会重建 Taskflow 对象。如果 schemas 频繁变化，可考虑按 schema 做缓存 key。
2. **UIE 关系抽取依赖 PaddlePaddle**: Taskflow 需要 paddlepaddle 底层框架，Windows 安装可能有兼容性问题，建议使用 `pip install paddlepaddle==2.6.1`（CPU 版本）。
3. **GLiNER `_normalize_label` 函数保留**: 虽然 labels 提取不再使用它，但函数本身保留未删除（未来可能有用）。
4. **CasRel/DeepKE ModelScope 模型格式**: 不同版本的 ModelScope pipeline 输出格式可能有差异，当前代码已兼容 4 种格式，但仍建议用户使用最新版 modelscope。
5. **所有引擎 confidence 统一为 None**: 按要求，非 LLM 引擎不输出置信度，等 LLM 质检后才赋值。

---

## 文件变更清单

| 文件 | 变更类型 | 行数变化 |
|------|----------|----------|
| `uie_extractor.py` | 完全重写 | ~280 → ~300 |
| `gliner_extractor.py` | 部分修改 | ~280 → ~250（-30，合并重复函数） |
| `casrel_extractor.py` | 小修改 | ~240 → ~245（+5，增加 pred_label 处理） |
| `deepke_extractor.py` | 小修改 | ~230 → ~250（+20，增加 _find_all_positions） |
| `custom_script_extractor.py` | 小修改 | ~175 → ~170（-5，删除 signal 代码） |

---

*报告生成时间: 2026-06-30 17:00 GMT+8*
