"""GLiNER 零样本 NER 抽取器 (多语言版本)
论文: GLiNER: Generalist Model for Named Entity Recognition using Bidirectional Transformer
来源: https://github.com/urchade/GLiNER

架构: 基于 BERT 的双向编码器, 支持任意实体类型零样本识别
优势:
  - 模型小 (medium ~340MB), CPU 可跑
  - 零样本: 不需要训练数据, 直接指定实体类型名即可
  - 支持多语言 (urchade/gliner_multilingual)

降级策略:
  1. 有 gliner 模型 → 直接预测 (首选)
  2. 无 GPU/模型未下载 → spaCy NER + 规则匹配
  3. 都不可用 → 降级到正则规则抽取
"""
import re
import traceback
from typing import List, Dict, Optional, Any
from app.config import settings

# 延迟导入标志
_GLINER_AVAILABLE = None
_MODEL_CACHE = None

# 默认多语言模型
DEFAULT_MODEL = "urchade/gliner_multilingual"


def extract_with_gliner(
    md_content: str,
    schemas: List[Dict],
    model_name: str = DEFAULT_MODEL,
    labels: Optional[List[str]] = None,
    threshold: float = 0.3,
    use_gpu: bool = False,
    gpu_id: int = 0,
    **kwargs,
) -> List[Dict]:
    """GLiNER 零样本命名实体识别 → Schema 约束三元组抽取
    
    流程:
      1. 从 Schema 提取所有 entity types 作为 GLiNER 的 labels（保留中文原文 + 英文翻译）
      2. GLiNER 在文本上跑 NER, 找到所有实体 span
      3. 对共现窗口内的实体对, 按 Schema 约束配对
      4. 输出 (subject, predicate, object) 三元组
    
    Args:
        md_content: Markdown 文本
        schemas: Schema 约束列表
        model_name: GLiNER 模型名 (默认 urchade/gliner_multilingual)
        labels: 手动指定的实体类型 (None=从 Schema 自动提取)
        threshold: GLiNER 置信度阈值 [0-1]
    
    Returns:
        三元组列表
    """
    if not md_content or not md_content.strip():
        return []

    # GLiNER 仅做 NER，关系全部来自启发式配对（注水）。
    # 关闭 ALLOW_HEURISTIC_RELATIONS 时，不编造任何关系，直接返回空。
    if not settings.ALLOW_HEURISTIC_RELATIONS:
        return []

    # 从 Schema 提取实体类型 → GLiNER labels
    if labels is None:
        labels = _extract_labels_from_schemas(schemas)
    
    if not labels:
        return _rule_fallback(md_content)

    try:
        global _GLINER_AVAILABLE, _MODEL_CACHE
        import os
        
        if _GLINER_AVAILABLE is False:
            return _spacy_fallback(md_content, schemas, labels)
        
        # 检查本地缓存
        os.environ["HF_ENDPOINT"] = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
        
        if _MODEL_CACHE is None:
            try:
                from gliner import GLiNER
            except ImportError:
                raise RuntimeError(
                    "GLiNER 抽取引擎未部署：请执行 `pip install gliner` 并重启服务。"
                    "首次运行会自动从 HuggingFace 下载 GLiNER 模型（需联网）。"
                )
            _MODEL_CACHE = GLiNER.from_pretrained(model_name)
            print(f"[GLiNER] 模型已加载: {model_name}")
        
        model = _MODEL_CACHE
        triples = _extract_with_gliner_model(md_content, schemas, labels, model, threshold)
        
        return triples
    
    except (ImportError, Exception) as e:
        _GLINER_AVAILABLE = False
        print(f"[GLiNER] 模型加载失败: {e}, 使用 spaCy 降级方案")
        traceback.print_exc()
        return _spacy_fallback(md_content, schemas, labels)


def _extract_labels_from_schemas(schemas: List[Dict]) -> List[str]:
    """从 Schema 提取 GLiNER labels (合并去重)
    
    策略: 只保留原文标签（中文或英文），不追加翻译，
    避免 labels 列表过长降低 GLiNER 精度。
    """
    label_set = set()
    for s in schemas:
        # 同时加入英文标识符与中文标签，提升 GLiNER 实体召回与对齐
        for key in ("subject_type", "subject_label", "object_type", "object_label"):
            v = s.get(key, "")
            if v:
                label_set.add(v)
    
    # 如果提取不到有意义的标签, 就用默认集
    if not label_set:
        label_set = {"设备", "故障类型", "材料", "人员", "组织", "地点"}
    
    return sorted(list(label_set))


def _normalize_label(label: str) -> str:
    """CamelCase 英文标签转空格分隔，中文标签保留原样
    
    中文标签直接用，不转英文。
    CamelCase 英文标签保持原样，但也提供中文映射。
    """
    # 中文直接返回
    if any('\u4e00' <= c <= '\u9fff' for c in label):
        return label
    
    # CamelCase 拆开并大写首字母
    words = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?![a-z])', label)
    return ' '.join(words).strip() if words else label


def _extract_with_gliner_model(
    text: str, schemas: List[Dict], labels: List[str],
    model: Any, threshold: float = 0.3,
) -> List[Dict]:
    """GLiNER 模型推理 + 实体配对
    
    自动分块处理长文本（GLiNER 模型有 token 限制 ~512）。
    先整段推理，如果未找到实体则分段落重试。
    """
    # 先尝试不分段落，一次性推理
    entities = model.predict_entities(text[:1500], labels, threshold=threshold)
    
    if not entities and len(text) > 1500:
        # 未找到实体且有长文本 → 分段落处理
        paragraphs = text.split("\n\n")
        all_entities = []
        for para in paragraphs:
            para = para.strip()
            if len(para) < 10:
                continue
            try:
                ents = model.predict_entities(para[:1500], labels, threshold=threshold)
                all_entities.extend(ents)
            except Exception:
                continue
        entities = all_entities
    
    if not entities:
        return []
    
    # 去重合并实体
    entity_map = {}
    for ent in entities:
        et = ent.get("text", "").strip()
        if not et or len(et) < 2:
            continue
        key = et.lower()
        if key not in entity_map:
            entity_map[key] = {
                "text": et,
                "label": ent.get("label", ""),
                "score": ent.get("score", 0.5),
                "start": ent.get("start", 0),
                "end": ent.get("end", 0),
            }
    
    entity_list = list(entity_map.values())
    
    # 按 Schema 配对
    triples = _pair_entities(entity_list, schemas, text, threshold)
    return triples


def _spacy_fallback(
    text: str, schemas: List[Dict], labels: List[str] = None,
) -> List[Dict]:
    """spaCy NER 降级方案"""
    try:
        import spacy
        
        # 尝试加载中文或英文模型
        model_names = ["zh_core_web_sm", "en_core_web_sm"]
        nlp = None
        for m in model_names:
            try:
                nlp = spacy.load(m)
                break
            except Exception:
                continue
        
        if nlp is None:
            return _rule_fallback(text)
        
        doc = nlp(text[:10000])  # spaCy 有长度限制
        entities = [
            {"text": ent.text, "label": ent.label_, "score": 0.8}
            for ent in doc.ents if len(ent.text) >= 2
        ]
        
        triples = _pair_entities(entities, schemas, text, 80.0, method="GLINER_SPACY")
        return triples
    
    except Exception:
        return _rule_fallback(text)


def _rule_fallback(text: str) -> List[Dict]:
    """纯规则降级 (内部正则抽取，无外部依赖)"""
    triples = []
    
    # 预定义规则模板
    rule_templates = [
        (r'([\w.\-]+@[\w\-]+\.[\w]+)', 'hasEmail'),
        (r'(1[3-9]\d{9})', 'hasPhone'),
        (r'(https?://[\w\-\.]+(?:[\w\-\./?#&=%~]+)?)', 'hasWebsite'),
        (r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}(?:日)?)', 'hasDate'),
        (r'(\d+(?:,\d{3})*(?:\.\d+)?\s*(?:万元|亿元|元|美元|人民币))', 'hasRevenue'),
        (r'(\d+(?:\.\d+)?%)', 'hasPercentage'),
    ]
    
    seen_keys = set()
    for pattern, predicate in rule_templates:
        for m in re.finditer(pattern, text):
            value = m.group(1).strip()
            key = (predicate, value.lower())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            triples.append({
                "subject": "文档",
                "predicate": predicate,
                "object": value,
                "confidence": None,
                "extraction_method": "GLINER_RULE",
                "chunk": text[max(0, m.start() - 50):m.end() + 50][:500],
            })
    
    return triples


def _pair_entities(
    entities: List[Dict], schemas: List[Dict], text: str,
    base_confidence: float = 0.0, method: str = "GLINER_HEURISTIC",
) -> List[Dict]:
    """实体配对: 共现窗口 + Schema 约束
    
    使用精确标签匹配 (subj_label, obj_label) → predicate
    """
    if len(entities) < 2:
        return []
    
    triples = []
    
    # 构建 Schema 标签映射: (subj_label, obj_label) → (predicate, predicate_label)
    # 同时注册英文标识符与中文标签两种 key，兼容不同 NER 输出
    schema_label_map = {}
    schema_pred_label_map = {}
    for s in schemas:
        subj_type = s.get("subject_type", "")
        obj_type = s.get("object_type", "")
        subj_label = s.get("subject_label", "") or subj_type
        obj_label = s.get("object_label", "") or obj_type
        pred = s.get("predicate", "关联")
        pred_label = s.get("predicate_label", "") or pred
        key_pairs = [
            (subj_type, obj_type),
            (subj_label, obj_label),
            (subj_label, obj_type),
            (subj_type, obj_label),
        ]
        for k in key_pairs:
            if not k[0] or not k[1]:
                continue
            if k not in schema_label_map:
                schema_label_map[k] = pred
                schema_pred_label_map[k] = pred_label
    
    for i, subj in enumerate(entities):
        for j, obj in enumerate(entities):
            if i == j:
                continue
            
            subj_label = subj.get("label", "")
            obj_label = obj.get("label", "")
            
            # 精确匹配 Schema
            predicate = schema_label_map.get((subj_label, obj_label), None)
            if not predicate:
                # 反向匹配
                predicate = schema_label_map.get((obj_label, subj_label), None)
            if not predicate:
                continue  # 不在 Schema 约束内，跳过
            
            # 优先使用中文谓词（predicate_label），避免中英混排
            out_predicate = schema_pred_label_map.get((subj_label, obj_label)) \
                or schema_pred_label_map.get((obj_label, subj_label)) \
                or predicate
            
            chunk_start = text.find(subj["text"])
            chunk_end = text.find(obj["text"])
            if chunk_start >= 0 and chunk_end >= 0:
                s = text[max(0, min(chunk_start, chunk_end) - 50):min(len(text), max(chunk_start + len(subj["text"]), chunk_end + len(obj["text"])) + 50)]
            else:
                s = ""
            
            triples.append({
                "subject": subj["text"],
                "predicate": out_predicate,
                "object": obj["text"],
                "confidence": settings.HEURISTIC_CONFIDENCE,
                "extraction_method": method,
                "chunk": s[:500],
            })
    
    # 去重
    seen = set()
    unique = []
    for t in triples:
        key = (t["subject"], t["predicate"], t["object"])
        if key not in seen:
            seen.add(key)
            unique.append(t)
    
    return unique
