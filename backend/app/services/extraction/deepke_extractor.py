"""DeepKE 抽取器 (ModelScope NER + 关系配对)
使用 ModelScope 的通用 NER 模型做实体识别，再用 Schema 约束 + 共现窗口做关系配对。

模型: iic/nlp_raner_named-entity-recognition_chinese-base-generic
来源: ModelScope (https://modelscope.cn)

三层降级策略:
  1. ModelScope NER 模型 + Schema 关系配对 (首选)
  2. 正则 NER + Schema 配对 (无外部依赖)
  3. 纯规则 (兜底)
"""
import re
import traceback
from typing import List, Dict, Optional, Tuple
from collections import defaultdict


# ModelScope 管道缓存
_DEEPKE_PIPELINE = None
_MODELSCOPE_AVAILABLE = None


def _get_pipeline():
    """延迟加载 ModelScope NER 管道"""
    global _DEEPKE_PIPELINE, _MODELSCOPE_AVAILABLE
    if _DEEPKE_PIPELINE is not None:
        return _DEEPKE_PIPELINE
    
    try:
        from modelscope.pipelines import pipeline
        from modelscope.utils.constant import Tasks
        
        print("[DeepKE] 正在加载 ModelScope NER 模型 (iic/nlp_raner_named-entity-recognition_chinese-base-generic)...")
        print("[DeepKE] 首次加载会自动下载模型，请耐心等待...")
        
        _DEEPKE_PIPELINE = pipeline(
            Tasks.named_entity_recognition,
            model='iic/nlp_raner_named-entity-recognition_chinese-base-generic'
        )
        print("[DeepKE] 模型加载完成!")
        _MODELSCOPE_AVAILABLE = True
        return _DEEPKE_PIPELINE
    except Exception as e:
        print(f"[DeepKE] ModelScope NER 模型加载失败: {e}")
        print("[DeepKE] 降级到正则 NER 方案")
        _MODELSCOPE_AVAILABLE = False
        return None


def extract_with_deepke(
    md_content: str,
    schemas: List[Dict],
    threshold: float = 0.5,
    use_gpu: bool = False,
    gpu_id: int = 0,
    **kwargs,
) -> List[Dict]:
    """DeepKE (ModelScope NER) 知识抽取
    
    使用 ModelScope 的 RaNER 中文 NER 模型识别实体，
    再用 Schema 约束 + 共现窗口做关系配对。
    不降级，依赖缺失直接报错。
    """
    if not md_content or not md_content.strip():
        return []

    # 直接使用 ModelScope NER 模型
    return _extract_with_modelscope_ner(md_content, schemas, threshold)


def _extract_with_modelscope_ner(
    md_content: str, schemas: List[Dict], threshold: float
) -> List[Dict]:
    """使用 ModelScope NER 管道抽取实体，再配对关系"""
    pipe = _get_pipeline()
    if pipe is None:
        raise RuntimeError("ModelScope NER 模型未安装，请执行: pip install modelscope datasets")
    
    # 分句处理
    sentences = _split_sentences(md_content)
    all_entities = []
    
    for sent in sentences:
        sent = sent.strip()
        if not sent or len(sent) < 5:
            continue
        
        try:
            result = pipe(sent)
        except Exception as e:
            print(f"[DeepKE] NER 句子推理出错: {e}")
            continue
        
        # ModelScope NER 输出格式:
        # {"output": [{"type": "PER", "start": 0, "end": 2, "span": "张三"}, ...]}
        # 或 {"entities": [...]}
        ner_results = []
        if isinstance(result, dict):
            ner_results = result.get('output', result.get('entities', result.get('predictions', [])))
        elif isinstance(result, list):
            ner_results = result
        
        for ent in ner_results:
            if not isinstance(ent, dict):
                continue
            
            entity_text = str(ent.get('span', ent.get('text', ent.get('entity', '')))).strip()
            entity_type = str(ent.get('type', ent.get('label', ent.get('entity_type', '')))).strip()
            
            if not entity_text or len(entity_text) < 1:
                continue
            
            # 映射 ModelScope NER 标签到统一标签
            unified_label = _map_ner_label(entity_type)
            
            all_entities.append({
                "text": entity_text,
                "label": unified_label,
                "raw_label": entity_type,
                "score": float(ent.get('score', 0.85)),
                "sentence": sent,
            })
    
    if not all_entities:
        return []
    
    # 去重 (保留最高分)
    deduped = {}
    for e in all_entities:
        key = e["text"].lower()
        if key not in deduped or e["score"] > deduped[key]["score"]:
            deduped[key] = e
    entity_list = list(deduped.values())
    
    # 关系配对
    triples = _pair_entities_with_schema(entity_list, schemas, md_content)
    
    return triples


def _map_ner_label(label: str) -> str:
    """ModelScope NER 标签 → 统一标签
    
    RaNER 中文模型常见标签:
    - PER / PERSON → 人物
    - ORG → 组织
    - LOC → 地点
    - TIME → 时间
    - MISC → 其他
    """
    label_upper = label.upper()
    mapping = {
        "PER": "人物",
        "PERSON": "人物",
        "ORG": "组织",
        "ORGANIZATION": "组织",
        "LOC": "地点",
        "LOCATION": "地点",
        "GPE": "地点",
        "TIME": "时间",
        "DATE": "日期",
        "MISC": "其他",
        "EQUIPMENT": "设备",
        "FAULT": "故障类型",
        "MATERIAL": "原料",
        "PROCESS": "工序段",
    }
    return mapping.get(label_upper, label)


def _pair_entities_with_schema(
    entities: List[Dict], schemas: List[Dict], full_text: str
) -> List[Dict]:
    """实体配对: Schema 约束 + 共现窗口"""
    if len(entities) < 2:
        return []
    
    triples = []
    
    # 构建 Schema 标签映射
    schema_pairs = {}
    for s in schemas:
        subj_type = s.get("subject_type", "")
        obj_type = s.get("object_type", "")
        pred = s.get("predicate", "relatedTo")
        key = (subj_type.lower(), obj_type.lower())
        schema_pairs[key] = pred
    
    for i, subj in enumerate(entities):
        for j, obj in enumerate(entities):
            if i == j:
                continue
            
            subj_label = subj.get("label", "")
            obj_label = obj.get("label", "")
            
            # 尝试按 Schema 找谓词
            predicate = schema_pairs.get(
                (subj_label.lower(), obj_label.lower()),
                None
            )
            if not predicate:
                # 反向匹配
                predicate = schema_pairs.get(
                    (obj_label.lower(), subj_label.lower()),
                    None
                )
            
            if not predicate:
                # 模糊匹配: 检查 Schema 中是否包含该标签
                for (st, ot), pred in schema_pairs.items():
                    if subj_label.lower() in st or st in subj_label.lower():
                        if obj_label.lower() in ot or ot in obj_label.lower():
                            predicate = pred
                            break
            
            if not predicate:
                continue  # 不在 Schema 约束内，跳过
            
            # 检查共现: 在原文中所有出现位置找最近距离
            subj_positions = _find_all_positions(full_text, subj["text"])
            obj_positions = _find_all_positions(full_text, obj["text"])
            
            if not subj_positions or not obj_positions:
                # 回退到句子级别
                chunk = subj.get("sentence", "")[:500]
            else:
                # 找最近的一对位置
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
                chunk = full_text[max(0, min(best_sp, best_op) - 100):min(len(full_text), max(best_sp, best_op) + 200)]
            
            triples.append({
                "subject": subj["text"],
                "predicate": predicate,
                "object": obj["text"],
                "confidence": None,
                "extraction_method": "DEEPKE",
                "chunk": chunk[:500],
            })
    
    # 去重
    seen = set()
    unique = []
    for t in triples:
        k = (t["subject"], t["predicate"], t["object"])
        if k not in seen:
            seen.add(k)
            unique.append(t)
    
    return unique


def _split_sentences(text: str) -> List[str]:
    """中文分句"""
    sentences = re.split(r'[。！？.!?\n]+', text)
    merged = []
    buffer = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(buffer) + len(sent) < 80:
            buffer = (buffer + sent).strip()
        else:
            if buffer:
                merged.append(buffer)
            buffer = sent
    if buffer:
        merged.append(buffer)
    return merged if merged else [text[:500]]


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
        start = idx + 1  # 移动一位，允许重叠匹配
    return positions


# ============ 降级方案: 正则 NER ============

def _deepke_regex_fallback(
    text: str, schemas: List[Dict], threshold: float = 0.5
) -> List[Dict]:
    """正则 NER + Schema 关系配对降级方案"""
    try:
        entities = _find_entities_by_regex(text)
        
        if not entities:
            return []
        
        triples = _pair_entities_with_schema(entities, schemas, text)
        
        return triples
    
    except Exception as e:
        print(f"[DeepKE] regex fallback 失败: {e}")
        traceback.print_exc()
        return []


def _find_entities_by_regex(text: str) -> List[Dict]:
    """正则实体识别 (中英文混合)"""
    entities = []
    
    patterns = [
        (r'(?:[\u4e00-\u9fff]{2,6})(?:公司|集团|工厂|实验室|部门|系统|设备|装置|传感器|控制器|执行器|电机|轴承)',
         '设备'),
        (r'(?:[\u4e00-\u9fff]{2,6})(?:故障|失效|断裂|磨损|腐蚀|泄漏|堵塞)', '故障类型'),
        (r'(?:[\u4e00-\u9fff]{2,6})(?:材料|物料|原料|成品|半成品|零件|部件|配件|备件)', '原料'),
        (r'(?:[\u4e00-\u9fff]{3,8})(?:工艺|工序|流程|步骤|操作)', '工序段'),
        (r'([\u4e00-\u9fff]{2,4})(?:人|员|工|师|长|经理|主任|主管|教授|医生)', '人物'),
        (r'([\u4e00-\u9fff]{2,10})(?:公司|集团|研究院|中心|实验室|大学|银行|证券)', '组织'),
        (r'([\u4e00-\u9fff]{2,6})(?:省|市|区|县|镇|村|路|街)', '地点'),
        (r'\b[A-Z][a-z]+(?:\s[A-Z][a-z]+){0,3}\b', 'ENTITY'),
        (r'\b[A-Z]{2,6}[-]\d{2,6}\b', 'MODEL'),
    ]
    
    seen = set()
    for pattern, label in patterns:
        for m in re.finditer(pattern, text):
            et = m.group().strip()
            if et not in seen and len(et) >= 2:
                seen.add(et)
                entities.append({
                    "text": et,
                    "label": label,
                    "score": 0.80,
                })
    
    return entities
