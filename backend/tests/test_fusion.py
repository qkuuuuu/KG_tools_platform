"""环节④：知识融合与消歧 —— 相似度/聚类（纯逻辑）+ LLM 辅助消歧（假 LLM）。"""
from app.services.fusion import compute_similarity, cluster_entities
from app.services.fusion.llm_fusion import llm_assisted_fusion


def test_compute_similarity_identical():
    assert compute_similarity("回转窑", "回转窑") == 100.0


def test_compute_similarity_different_low():
    sim = compute_similarity("苹果", "水泥")
    assert 0 <= sim <= 100
    assert sim < 50


def test_cluster_entities_structure():
    triples = [
        {"subject": "回转窑", "predicate": "r", "object": "托轮"},
        {"subject": "电机", "predicate": "r", "object": "轴承"},
    ]
    auto, manual = cluster_entities(triples)
    assert isinstance(auto, list)
    assert isinstance(manual, list)


def test_cluster_entities_similar_flagged():
    # "华为技术有限公司" 标准化后为 "华为技术"，与 "华为技术" 完全相同 → 自动合并
    triples = [
        {"subject": "华为技术有限公司", "predicate": "r", "object": "x"},
        {"subject": "华为技术", "predicate": "r", "object": "y"},
    ]
    auto, manual = cluster_entities(triples)
    assert len(auto) >= 1


def test_cluster_entities_dissimilar_not_merged():
    triples = [
        {"subject": "苹果公司", "predicate": "r", "object": "x"},
        {"subject": "香蕉", "predicate": "r", "object": "y"},
    ]
    auto, manual = cluster_entities(triples)
    assert len(auto) == 0
    assert len(manual) == 0


def test_llm_assisted_fusion_fake(patch_fusion_llm):
    pairs = [
        {"entity_1": "华为", "entity_2": "华为技术有限公司", "similarity": 92},
    ]
    out = llm_assisted_fusion(pairs, "华为是华为技术有限公司的简称。", cfg={"api_key": "x"})
    assert len(out) == 1
    assert out[0]["suggestion"] == "LLM_SUGGEST_MERGE"
    assert out[0]["llm_decision"] == "MERGE"


def test_llm_assisted_fusion_empty():
    assert llm_assisted_fusion([], "ctx", cfg={"api_key": "x"}) == []
