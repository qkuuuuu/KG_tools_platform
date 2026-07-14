"""环节②：多方法三元组抽取 —— LLM / GLiNER / DeepKE / UIE 各引擎。

模型调用一律用假实现（monkeypatch）欺骗，重点验证纯逻辑与降级路径可跑通。
"""
import pytest

from app.services.extraction.llm_extractor import (
    extract_with_llm,
    _parse_triples_from_response,
)
from app.services.extraction.gliner_extractor import (
    extract_with_gliner,
    _rule_fallback,
    _normalize_label,
    _extract_labels_from_schemas,
    _pair_entities,
)
from app.services.extraction.deepke_extractor import (
    _find_entities_by_regex,
    _pair_entities_with_schema,
    _split_sentences,
    _map_ner_label,
    _deepke_regex_fallback,
)
from app.services.extraction.uie_extractor import (
    _to_cn,
    _collect_entity_types,
    _build_relation_schema,
    _split_text_chunks,
    _uie_regex_fallback,
    _merge_entity_relation_results,
)


# ---------------- LLM 抽取 ----------------

def test_parse_triples_from_response_strips_fences():
    resp = "```json\n[{\"subject\":\"A\",\"predicate\":\"r\",\"object\":\"B\"}]\n```"
    out = _parse_triples_from_response(resp)
    assert len(out) == 1
    assert out[0]["subject"] == "A"


def test_parse_triples_from_response_invalid_returns_empty():
    assert _parse_triples_from_response("no json here") == []
    assert _parse_triples_from_response("") == []


def test_extract_with_llm_fake(patch_llm_extractor):
    # 文本必须包含假 LLM 返回里的实体，否则事实核查会丢弃
    text = "回转窑是一种重要设备。该设备出现明显故障。"
    triples = extract_with_llm(text, schemas=[], cfg={"api_key": "x"})
    assert len(triples) == 1
    assert triples[0]["subject"] == "回转窑"
    assert triples[0]["object"] == "故障"


def test_extract_with_llm_empty_text():
    assert extract_with_llm("", schemas=[], cfg={"api_key": "x"}) == []


# ---------------- GLiNER ----------------

def test_gliner_rule_fallback_finds_email_phone():
    text = "联系邮箱 a@b.com，电话 13800138000，官网 https://kg.com"
    triples = _rule_fallback(text)
    preds = {t["predicate"] for t in triples}
    assert "hasEmail" in preds
    assert "hasPhone" in preds
    assert "hasWebsite" in preds


def test_gliner_normalize_label_chinese_kept():
    assert _normalize_label("设备") == "设备"


def test_gliner_normalize_label_camel():
    assert _normalize_label("EquipmentComponent") == "Equipment Component"


def test_gliner_extract_labels_from_schemas(schemas):
    labels = _extract_labels_from_schemas(schemas)
    assert "设备" in labels
    assert "设备部件" in labels


def test_gliner_pair_entities(schemas):
    entities = [
        {"text": "回转窑", "label": "设备"},
        {"text": "托轮", "label": "设备部件"},
    ]
    text = "回转窑的托轮需要维护。回转窑运行正常。"
    triples = _pair_entities(entities, schemas, text)
    # 正向(设备→设备部件)与反向(设备部件→设备)两条 Schema 都在，故产生 2 条
    assert len(triples) == 2
    keys = {(t["subject"], t["predicate"], t["object"]) for t in triples}
    assert ("回转窑", "包含部件", "托轮") in keys


def test_gliner_extract_with_gliner_degrades_to_rule():
    # gliner / spacy 均未安装时，应自然降级到正则规则（无需 mock）
    text = "请联系 a@b.com 或拨 13800138000"
    triples = extract_with_gliner(text, schemas=[])
    assert any(t["predicate"] == "hasEmail" for t in triples)


# ---------------- DeepKE ----------------

def test_deepke_find_entities_by_regex():
    text = "回转窑设备发生断裂故障"
    ents = _find_entities_by_regex(text)
    labels = {e["label"] for e in ents}
    assert "设备" in labels
    assert "故障类型" in labels


def test_deepke_map_ner_label():
    assert _map_ner_label("PER") == "人物"
    assert _map_ner_label("ORG") == "组织"
    assert _map_ner_label("未知标签") == "未知标签"


def test_deepke_split_sentences():
    # _split_sentences 会把短句合并成 <=80 字的块，验证它返回分块列表且内容不丢失
    text = (
        "第一句内容很长需要超过阈值所以这里放很多字用来凑够八十个字符的长度以便触发分块逻辑。"
        "第二句也是类似的长文本内容用来测试分句合并行为是否如预期工作。"
        "第三句依然保持足够长度确保不会被合并进同一块里。"
    )
    sents = _split_sentences(text)
    assert isinstance(sents, list)
    assert len(sents) >= 1
    # 去除分隔符后原文内容应被完整保留
    joined = "".join(sents).replace("\n", "").replace("。", "")
    assert joined == text.replace("。", "").replace("\n", "")


def test_deepke_pair_entities_with_schema(schemas):
    entities = [
        {"text": "回转窑", "label": "设备"},
        {"text": "托轮", "label": "设备部件"},
    ]
    text = "回转窑的托轮需要更换。回转窑振动大。"
    triples = _pair_entities_with_schema(entities, schemas, text)
    assert len(triples) == 2
    keys = {(t["subject"], t["predicate"], t["object"]) for t in triples}
    assert ("回转窑", "包含部件", "托轮") in keys


def test_deepke_regex_fallback(schemas):
    text = "回转窑设备出现断裂故障"
    triples = _deepke_regex_fallback(text, schemas)
    assert isinstance(triples, list)


# ---------------- UIE ----------------

def test_uie_to_cn():
    assert _to_cn("Equipment") == "设备"
    assert _to_cn("设备") == "设备"
    assert _to_cn("hasComponent") == "包含部件"


def test_uie_collect_entity_types(schemas):
    types = _collect_entity_types(schemas)
    assert "设备" in types
    assert "设备部件" in types


def test_uie_build_relation_schema(schemas):
    rel_schema = _build_relation_schema(schemas)
    assert isinstance(rel_schema, list)
    assert len(rel_schema) >= 1
    # 应按主体类型分组
    assert any("设备" in d for d in rel_schema)


def test_uie_split_text_chunks():
    text = "段落一内容\n段落二内容\n段落三内容"
    chunks = _split_text_chunks(text, max_len=20)
    assert len(chunks) >= 1


def test_uie_regex_fallback(schemas):
    text = "回转窑设备发生断裂故障"
    triples = _uie_regex_fallback(text, schemas)
    assert isinstance(triples, list)


def test_uie_merge_entity_relation_results(schemas):
    entities = [
        {"text": "回转窑", "label": "设备"},
        {"text": "托轮", "label": "设备部件"},
    ]
    relations = [
        {"subject": "回转窑", "predicate": "包含部件", "object": "托轮", "chunk": "x"},
    ]
    full_text = "回转窑的托轮需要维护"
    triples = _merge_entity_relation_results(entities, relations, schemas, full_text)
    assert len(triples) >= 1
    assert triples[0]["subject"] == "回转窑"
