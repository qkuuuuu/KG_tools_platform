"""UIE 统一信息抽取器 (百度 PaddleNLP Taskflow API)
论文: Unified Structure Generation for Universal Information Extraction
GitHub: https://github.com/PaddlePaddle/PaddleNLP

架构:
  - 使用 PaddleNLP Taskflow('information_extraction') 官方 API
  - Taskflow 封装了模型加载、tokenizer、解码逻辑
  - 实体抽取: schema=["实体类型1", "实体类型2", ...]
  - 关系抽取: schema=[{"主体类型": [{"relation": "谓词", "object_type": "客体类型"}]}]

降级策略:
  1. Taskflow information_extraction 实体抽取 (首选)
  2. Taskflow 关系抽取 (嵌套 schema)
  3. spacy NER 降级 (无 PaddleNLP)
"""
import re
import traceback
from typing import List, Dict, Optional, Any


# Taskflow 缓存，避免重复加载模型
_TASKFLOW_ENTITY = None
_TASKFLOW_RELATION = None


def extract_with_uie(
    md_content: str,
    schemas: List[Dict],
    model_name: str = "uie-base",
    threshold: float = 0.5,
    cfg: Optional[Dict] = None,
    use_gpu: bool = False,
    gpu_id: int = 0,
    **kwargs,
) -> List[Dict]:
    """UIE 统一信息抽取 (使用 PaddleNLP Taskflow API)

    Args:
        md_content: Markdown 文本
        schemas: Schema 约束 [{subject_type, predicate, object_type}]
        model_name: UIE 模型名 (默认 uie-base)
        threshold: 置信度阈值 [0-1]
        cfg: LLM 配置（保留参数，UIE 不使用 LLM）
        use_gpu: 是否使用 GPU
        gpu_id: GPU 设备 ID

    Returns:
        三元组列表 [{subject, predicate, object, confidence, extraction_method, chunk}]
    """
    if not md_content or not md_content.strip():
        return []

    print(f"[UIE] 收到 schemas: {len(schemas) if schemas else 0} 条, device={'GPU'+str(gpu_id) if use_gpu else 'CPU'}")
    if schemas:
        for i, s in enumerate(schemas[:3]):
            print(f"  Schema[{i}]: subject_type={s.get('subject_type', '')}, predicate={s.get('predicate', '')}, object_type={s.get('object_type', '')}")

    entity_types = _collect_entity_types(schemas)
    print(f"[UIE] 提取的 entity_types: {entity_types}")

    if not entity_types:
        print("[UIE] 警告: entity_types 为空! schemas 可能未正确传入")
        entity_types = ["人名", "组织", "地点", "时间", "产品", "事件"]
        print(f"[UIE] 使用默认 entity_types: {entity_types}")

    # 直接调用 PaddleNLP Taskflow，不降级
    return _uie_taskflow_extract(md_content, schemas, model_name, threshold, use_gpu=use_gpu, gpu_id=gpu_id)


def _uie_taskflow_extract(
    text: str, schemas: List[Dict], model_name: str = "uie-base-zh",
    threshold: float = 0.5,
    use_gpu: bool = False,
    gpu_id: int = 0,
) -> List[Dict]:
    """使用 PaddleNLP Taskflow 官方 API 进行信息抽取

    实体抽取:
      ie = Taskflow('information_extraction', schema=['人物', '组织'], model='uie-base-zh')
      result = ie("文本")
      # 返回: [{'人物': [{'text': '张三', 'start': 0, 'end': 2, 'probability': 0.99}],
      #         '组织': [{'text': '阿里巴巴', 'start': 3, 'end': 7, 'probability': 0.98}]}]

    关系抽取:
      schema = [{'人物': [{'relation': '任职', 'object_type': '组织'}]}]
      ie = Taskflow('information_extraction', schema=schema, model='uie-base-zh')
      result = ie("文本")
      # 返回: [{'人物': [{'text': '张三', 'start': 0, 'end': 2, 'probability': 0.99,
      #          'relations': {'任职': [{'text': '阿里巴巴', 'start': 3, 'end': 7, 'probability': 0.95}]}}]}]
    """
    global _TASKFLOW_ENTITY, _TASKFLOW_RELATION

    from paddlenlp import Taskflow

    # 设备选择
    dev_id = gpu_id if use_gpu else -1  # PaddlePaddle: -1=CPU, >=0=GPU id
    dev_label = f"GPU{gpu_id}" if use_gpu else "CPU"

    # ---- 1. 实体抽取 ----
    entity_types = _collect_entity_types(schemas)
    if not entity_types:
        entity_types = ["人名", "组织", "地点", "时间", "产品", "事件"]
        print(f"[UIE] entity_types 为空, 使用默认: {entity_types}")

    # 缓存 Taskflow (实体抽取) — 设备或 schema 变化时重建
    _entity_cache_key = (tuple(entity_types), use_gpu, gpu_id)
    if _TASKFLOW_ENTITY is None or getattr(_TASKFLOW_ENTITY, '_cache_key', None) != _entity_cache_key:
        print(f"[UIE] 初始化 Taskflow 实体抽取, schema={entity_types}, device={dev_label}")
        _TASKFLOW_ENTITY = Taskflow(
            'information_extraction',
            schema=entity_types,
            model=model_name,
            device_id=dev_id,
        )
        _TASKFLOW_ENTITY._cache_key = _entity_cache_key

    # 分块处理（Taskflow 内部有长度限制）
    chunks = _split_text_chunks(text, max_len=450)
    all_entity_results = {}

    for chunk_idx, chunk in enumerate(chunks):
        try:
            result = _TASKFLOW_ENTITY(chunk)
            # result: [{'人物': [{'text': '...', 'start': 0, 'end': 2, 'probability': 0.99}],
            #            '组织': [{'text': '...', 'start': ..., 'end': ..., 'probability': ...}]}]
            if isinstance(result, list) and len(result) > 0:
                chunk_entities = result[0]  # result 是列表，第一项是抽取结果
                for etype, ents in chunk_entities.items():
                    if etype not in all_entity_results:
                        all_entity_results[etype] = []
                    all_entity_results[etype].extend(ents)
        except Exception as e:
            print(f"[UIE] Chunk {chunk_idx} 实体抽取异常: {e}")
            continue

    # 展平实体列表: [{"text": "...", "label": "人物", "score": 0.99, "start": 0, "end": 2}, ...]
    flat_entities = []
    for etype, ents in all_entity_results.items():
        for ent in ents:
            prob = ent.get("probability", 0.9)
            if prob < threshold:
                continue
            flat_entities.append({
                "text": ent.get("text", ""),
                "label": etype,
                "score": prob,
                "start": ent.get("start", 0),
                "end": ent.get("end", 0),
            })

    if flat_entities:
        print(f"[UIE] 实体抽取完成: {len(flat_entities)} 个实体")

    # ---- 2. 关系抽取 (使用嵌套 schema) ----
    relation_schemas = _build_relation_schema(schemas)

    flat_relations = []
    if relation_schemas:
        # 重建 Taskflow (关系抽取)
        _TASKFLOW_RELATION = Taskflow(
            'information_extraction',
            schema=relation_schemas,
            model=model_name,
            device_id=dev_id,
        )

        for chunk_idx, chunk in enumerate(chunks):
            try:
                result = _TASKFLOW_RELATION(chunk)
                # result: [{'人物': [{'text': '张三', 'start': 0, 'end': 2, 'probability': 0.99,
                #           'relations': {'任职': [{'text': '阿里巴巴', 'start': 3, 'end': 7, 'probability': 0.95}]}}]}]
                if isinstance(result, list) and len(result) > 0:
                    chunk_relations = result[0]
                    for etype, ents in chunk_relations.items():
                        for ent in ents:
                            subj_text = ent.get("text", "")
                            subj_prob = ent.get("probability", 0.9)
                            relations = ent.get("relations", {})
                            for rel_name, rel_objs in relations.items():
                                for rel_obj in rel_objs:
                                    obj_text = rel_obj.get("text", "")
                                    obj_prob = rel_obj.get("probability", 0.9)
                                    if subj_prob < threshold or obj_prob < threshold:
                                        continue
                                    flat_relations.append({
                                        "subject": subj_text,
                                        "predicate": rel_name,
                                        "object": obj_text,
                                        "score": (subj_prob + obj_prob) / 2,
                                        "chunk": chunk,
                                    })
            except Exception as e:
                print(f"[UIE] Chunk {chunk_idx} 关系抽取异常: {e}")
                continue

    if flat_relations:
        print(f"[UIE] 关系抽取完成: {len(flat_relations)} 个关系")

    # ---- 3. 合并实体关系和纯实体配对 ----
    triples = _merge_entity_relation_results(flat_entities, flat_relations, schemas, text)

    # 标记抽取方法
    for t in triples:
        t["extraction_method"] = "UIE"

    print(f"[UIE] 最终抽取三元组: {len(triples)} 条")
    return triples


def _collect_entity_types(schemas: List[Dict]) -> List[str]:
    """从 Schema 提取唯一实体类型集

    确保正确提取所有 subject_type 和 object_type
    """
    types = set()
    for s in schemas:
        st = _to_cn(s.get("subject_type", ""))
        ot = _to_cn(s.get("object_type", ""))
        if st:
            types.add(st)
        if ot:
            types.add(ot)
    return list(types)


def _build_relation_schema(schemas: List[Dict]) -> List[Dict]:
    """从 Schema 列表构建 Taskflow 关系抽取的嵌套 schema

    Args:
        schemas: [{subject_type, predicate, object_type}, ...]

    Returns:
        Taskflow relation schema 格式:
        [{"主体类型": [{"relation": "谓词", "object_type": "客体类型"}], ...}]
    """
    from collections import defaultdict

    # 按 subject_type 分组
    grouped = defaultdict(list)
    for s in schemas:
        st = _to_cn(s.get("subject_type", ""))
        pred = s.get("predicate", "")
        ot = _to_cn(s.get("object_type", ""))
        if st and pred and ot:
            grouped[st].append({
                "relation": pred,
                "object_type": ot,
            })

    if not grouped:
        return []

    # 转换为 Taskflow 格式
    relation_schema = []
    for st, rels in grouped.items():
        relation_schema.append({st: rels})

    return relation_schema


def _merge_entity_relation_results(
    entities: List[Dict],
    relations: List[Dict],
    schemas: List[Dict],
    full_text: str,
) -> List[Dict]:
    """合并实体抽取和关系抽取结果 → 三元组

    优先级: 关系抽取结果 > 实体配对结果
    """
    triples = []

    if not schemas:
        print("[UIE] 警告: schemas 为空, 无法配对")
        return []

    # ---- 1. 优先使用关系抽取结果 ----
    seen_keys = set()
    for rel in relations:
        key = (rel["subject"], rel["predicate"], rel["object"])
        if key not in seen_keys:
            seen_keys.add(key)
            triples.append({
                "subject": rel["subject"],
                "predicate": rel["predicate"],
                "object": rel["object"],
                "confidence": None,
                "chunk": rel.get("chunk", full_text[:500]),
            })

    # ---- 2. 实体配对补全 (关系抽取未覆盖的三元组) ----
    for schema_item in schemas:
        subj_type_cn = _to_cn(schema_item.get("subject_type", ""))
        obj_type_cn = _to_cn(schema_item.get("object_type", ""))
        predicate = schema_item.get("predicate", "")

        subj_candidates = [e for e in entities if e["label"] == subj_type_cn]
        obj_candidates = [e for e in entities if e["label"] == obj_type_cn]

        for subj in subj_candidates:
            for obj in obj_candidates:
                if subj["text"] == obj["text"]:
                    continue  # 不抽自环

                key = (subj["text"], predicate, obj["text"])
                if key in seen_keys:
                    continue  # 已通过关系抽取产出

                # 共现检查
                subj_positions = _find_all_positions(full_text, subj["text"])
                obj_positions = _find_all_positions(full_text, obj["text"])

                if not subj_positions or not obj_positions:
                    continue

                # 找最近距离
                min_dist = float('inf')
                best_sp = subj_positions[0]
                best_op = obj_positions[0]
                for sp in subj_positions:
                    for op in obj_positions:
                        d = abs(sp - op)
                        if d < min_dist:
                            min_dist = d
                            best_sp = sp
                            best_op = op

                if min_dist > 800:
                    continue

                seen_keys.add(key)
                triples.append({
                    "subject": subj["text"],
                    "predicate": predicate,
                    "object": obj["text"],
                    "confidence": None,
                    "chunk": full_text[max(0, min(best_sp, best_op) - 100):min(len(full_text), max(best_sp, best_op) + 200)],
                })

    # ---- 3. 降级: 没有关系抽取结果时，做宽松配对 ----
    if not triples and len(entities) >= 2:
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                subj = entities[i]
                obj = entities[j]
                if subj["text"] == obj["text"]:
                    continue

                # 找匹配的 schema
                for s in schemas:
                    st_cn = _to_cn(s.get("subject_type", ""))
                    ot_cn = _to_cn(s.get("object_type", ""))
                    pred = s.get("predicate", "relatedTo")
                    if subj["label"] == st_cn and obj["label"] == ot_cn:
                        triples.append({
                            "subject": subj["text"],
                            "predicate": pred,
                            "object": obj["text"],
                            "confidence": None,
                            "chunk": full_text[:500],
                        })
                        break

    return triples


def _find_all_positions(text: str, substring: str) -> List[int]:
    """查找子串在文本中的所有出现位置"""
    if not substring or not text:
        return []
    positions = []
    start = 0
    while True:
        idx = text.find(substring, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    return positions


def _uie_fallback_spacy(text: str, schemas: List[Dict]) -> List[Dict]:
    """降级方案: spacy 英文 NER"""
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")

        entities = []
        doc = nlp(text[:100000])

        for ent in doc.ents:
            entities.append({
                "text": ent.text,
                "label": ent.label_,
                "score": 0.85,
            })

        if not entities:
            return []

        triples = []
        for s in schemas:
            subj_type = s.get("subject_type", "")
            obj_type = s.get("object_type", "")
            predicate = s.get("predicate", "")

            label_map = {"Person": "PERSON", "Organization": "ORG", "Location": "GPE", "Date": "DATE", "Product": "PRODUCT"}
            subj_label = label_map.get(subj_type, subj_type.upper())
            obj_label = label_map.get(obj_type, obj_type.upper())

            subj_ents = [e for e in entities if e["label"] == subj_label]
            obj_ents = [e for e in entities if e["label"] == obj_label]

            for subj in subj_ents:
                for obj in obj_ents:
                    if subj["text"] != obj["text"]:
                        triples.append({
                            "subject": subj["text"], "predicate": predicate,
                            "object": obj["text"], "confidence": None,
                            "extraction_method": "UIE", "chunk": text[:200],
                        })
        return triples

    except Exception:
        return []


def _uie_regex_fallback(text: str, schemas: List[Dict]) -> List[Dict]:
    """降级方案: 正则 NER + Schema 关系配对（复用 DeepKE 的正则方案）"""
    from .deepke_extractor import _find_entities_by_regex, _pair_entities_with_schema
    
    entities = _find_entities_by_regex(text)
    if not entities:
        return []
    
    triples = _pair_entities_with_schema(entities, schemas, text)
    for t in triples:
        t["extraction_method"] = "UIE"
    return triples


def _to_cn(name: str) -> str:
    """实体/关系名 → 中文标签

    确保覆盖所有 Schema 中的实体类型。
    如果传入的已经是中文，直接返回。
    """
    if not name:
        return ""

    # 如果已经是中文，直接返回
    if any('\u4e00' <= c <= '\u9fff' for c in name):
        return name

    mapping = {
        # 实体类型
        "Person": "人物", "Organization": "组织", "Location": "地点",
        "Date": "日期", "Time": "时间",
        "Equipment": "设备", "EquipmentComponent": "设备部件",
        "EquipmentName": "设备",
        "FaultType": "故障类型", "FaultMode": "故障类型", "Symptom": "症状",
        "MaintenanceScheme": "维修方案", "SparePart": "备件",
        "MonitoringPoint": "监测点", "Feature": "特征",
        "ProcessSection": "工序段", "ProcessParameter": "工艺参数",
        "RawMaterial": "原料", "FinishedProduct": "成品", "SemiProduct": "半成品",
        "KnowledgeUnit": "知识单元", "Chunk": "文本片段",
        "IndexType": "指标类型", "AtomicQuery": "原子查询",
        "Product": "产品", "Event": "事件",
        # 关系类型
        "hasComponent": "包含部件", "componentOf": "组成部分",
        "hasFaultType": "故障类型", "infersFaultMode": "推断故障模式",
        "hasProcessParameter": "工艺参数", "equipmentLocatedAt": "所在位置",
        "consumesMaterial": "消耗物料", "producesProduct": "生产产品",
        "hasSparePart": "备件", "hasInterlock": "联锁",
        "belongsToProcess": "所属工序", "recommendsMaintenanceScheme": "推荐方案",
        "feedsTo": "供给", "sourceChunk": "来源",
        "relatedTo": "关联", "satisfiesSymptom": "满足症状",
        "featureProducedBy": "产生来源",
        "worksFor": "任职", "locatedIn": "位于",
        "produces": "生产", "founded": "创建",
        "hasEmail": "邮箱", "hasPhone": "电话",
        "hasModelNumber": "型号", "hasRevenue": "营收", "hasWebsite": "网站",
        "hasPercentage": "百分比", "hasIDNumber": "身份证",
        "hasDate": "日期",
    }

    if name in mapping:
        return mapping[name]

    # 尝试不区分大小写
    for k, v in mapping.items():
        if k.lower() == name.lower():
            return v

    # 未找到映射，返回原始名称
    print(f"[UIE] 警告: 未找到 '{name}' 的中文映射，使用原始值")
    return name


def _split_text_chunks(text: str, max_len: int = 450) -> List[str]:
    """分块"""
    chunks = []
    current = ""
    for para in text.split("\n"):
        if len(current) + len(para) > max_len:
            if current:
                chunks.append(current)
            current = para
        else:
            current += "\n" + para
    if current:
        chunks.append(current)
    return chunks if chunks else [text[:max_len]]
