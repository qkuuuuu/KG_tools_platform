"""环节③：大模型质检 —— 规则校验（纯逻辑）+ LLM 反思评分（假 LLM）。"""
from app.services.quality import rule_based_quality, llm_quality_review


def test_rule_based_quality_pure_number_flagged():
    triples = [{"subject": "设备A", "predicate": "hasCode", "object": "12345"}]
    out = rule_based_quality(triples)
    assert out[0]["rule_check"] == "WARN"
    assert "纯数字" in "".join(out[0]["rule_reasons"])


def test_rule_based_quality_self_loop_flagged():
    triples = [{"subject": "X", "predicate": "relatedTo", "object": "X"}]
    out = rule_based_quality(triples)
    assert out[0]["rule_check"] == "WARN"


def test_rule_based_quality_clean_ok():
    triples = [{"subject": "回转窑", "predicate": "包含部件", "object": "托轮"}]
    out = rule_based_quality(triples)
    assert out[0]["rule_check"] == "OK"


def test_rule_based_quality_does_not_mutate_input_keys():
    t = {"subject": "回转窑", "predicate": "包含部件", "object": "托轮"}
    rule_based_quality([t])
    assert "回转窑" == t["subject"]


def test_llm_quality_review_fake(patch_quality_llm):
    triples = [{"subject": "回转窑", "predicate": "包含部件", "object": "托轮"}]
    out = llm_quality_review(triples, "回转窑包含托轮。", cfg={"api_key": "x"})
    assert len(out) == 1
    assert out[0]["verdict"] == "PASS"
    assert out[0]["quality_score"] == 95


def test_llm_quality_review_empty():
    assert llm_quality_review([], "text", cfg={"api_key": "x"}) == []
