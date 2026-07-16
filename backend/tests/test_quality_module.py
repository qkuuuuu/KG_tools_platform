"""质检模块完整单元测试：规则校验 + LLM 质检评审。

覆盖维度：
  1. 数据校验规则（rule_based_quality）：纯数字 / 纯标点 / 自反 / 单字符 / 空值 / 数值编码等。
  2. 格式要求（llm_quality_review）：LLM 返回的 JSON 格式、index 字段、quality_score 类型、
     verdict 取值（中英文 / 大小写）。
  3. 边界条件：空输入、单条、整批(490 条跨 33 个 batch 的边界)、1-based / 缺失 index、越界 index、
     评分越界、verdict 缺失。

并定位 / 验证导致「490 条三元组仅 40 条通过」低通过率的具体缺陷：
  - 缺陷 A：index 映射脆弱。``r.get("index", 0)`` 在 index 缺失时默认落到第 0 条（多条 review 互相覆盖）；
    ``0 <= idx < len(batch)`` 会把 idx == len(batch) 的末条（LLM 常用 1-based 编号）直接丢弃，
    且其余全部错位 → 整批评分错乱 / 漏评。
  - 缺陷 B：quality_score 类型 / 区间未校验，模型返回字符串或越界值会污染下游 ``score >= threshold``。
  - 缺陷 C：verdict 与 VERIFICATION 评分标准不对齐。评分标准把 70-89 定义为「基本正确」，
    但旧逻辑要求 LLM 必须显式返回 ``"PASS"`` 才算通过；大量「基本正确」三元组既非 PASS 也非 REJECT，
    只能停留在 PENDING（人工待审），最终表现为极低通过率（490→40）。
  - 缺陷 D：未匹配到 review 的三元组（批次末条被丢弃、LLM 返回条目不足等）拿不到任何
    quality_score / verdict，下游路由回退到抽取置信度或直接 KeyError。
"""
import json
import re

import pytest

from app.services.quality import (
    rule_based_quality,
    llm_quality_review,
    _coerce_score,
    _normalize_verdict,
)


# ---------------------------------------------------------------------------
# 工具：可编排的假 LLM 质检响应
# ---------------------------------------------------------------------------

def _count_batch(user_prompt: str) -> int:
    """从 user_prompt 中统计本批次三元组条数。"""
    return len(re.findall(r"^\s*\d+\.\s*\(", user_prompt, re.M))


def make_fake_quality(score=95, verdict="PASS", index_mode="0based"):
    """返回一个可注入 ``app.services.quality._call_llm_for_quality`` 的假实现。

    index_mode:
      - "0based" : 返回 0..n-1（正确）
      - "1based" : 返回 1..n（历史缺陷 A：末条越界被丢弃、其余错位）
      - "missing": 省略 index 字段（历史缺陷 A：旧逻辑默认落到第 0 条）
      - "empty"  : 返回空数组（历史缺陷 D：整批漏评）
    score / verdict 可为常量，或 ``callable(idx, n)``。
    """
    def _fake(cfg, system_prompt, user_prompt):
        n = _count_batch(user_prompt)
        reviews = []
        for i in range(n):
            s = score(i, n) if callable(score) else score
            v = verdict(i, n) if callable(verdict) else verdict
            r = {"quality_score": s, "verdict": v, "reason": "x"}
            if index_mode == "missing":
                pass  # 不返回 index
            elif index_mode == "1based":
                r["index"] = i + 1
            else:
                r["index"] = i
            reviews.append(r)
        if index_mode == "empty":
            return "[]"
        return json.dumps(reviews)

    return _fake


# ===========================================================================
# 一、规则校验（rule_based_quality）
# ===========================================================================

def test_rule_pure_number_subject_and_object():
    triples = [{"subject": "12345", "predicate": "hasCode", "object": "67890"}]
    out = rule_based_quality(triples)
    assert out[0]["rule_check"] == "WARN"
    joined = "".join(out[0].get("rule_reasons", []))
    assert "主语为纯数字" in joined and "宾语为纯数字" in joined


def test_rule_object_pure_number_is_flagged():
    """数值编码作为宾语（如设备编号）也应被规则捕获为可疑。"""
    out = rule_based_quality([{"subject": "设备A", "predicate": "编号", "object": "12345"}])
    assert out[0]["rule_check"] == "WARN"
    assert "宾语为纯数字" in "".join(out[0]["rule_reasons"])


def test_rule_punctuation_only_subject_and_object():
    # ASCII 标点
    out = rule_based_quality([{"subject": "!?", "predicate": "rel", "object": ",."}])
    assert out[0]["rule_check"] == "WARN"
    joined = "".join(out[0].get("rule_reasons", []))
    assert "主语仅为标点符号" in joined and "宾语仅为标点符号" in joined


def test_rule_fullwidth_punctuation_flagged():
    """格式要求：中文文档常见的全角 / CJK 标点（，。！？、；：）也应被捕获。

    历史缺陷：原规则仅匹配 ASCII 标点，全角标点被放行。
    """
    out = rule_based_quality([{"subject": "！？", "predicate": "rel", "object": "，。"}])
    assert out[0]["rule_check"] == "WARN"
    joined = "".join(out[0].get("rule_reasons", []))
    assert "主语仅为标点符号" in joined and "宾语仅为标点符号" in joined


def test_rule_self_loop_non_reflexive_flagged():
    out = rule_based_quality([{"subject": "X", "predicate": "relatedTo", "object": "X"}])
    assert out[0]["rule_check"] == "WARN"
    assert "主语=宾语" in "".join(out[0]["rule_reasons"])


def test_rule_self_loop_reflexive_ok():
    out = rule_based_quality([{"subject": "A", "predicate": "sameAs", "object": "A"}])
    assert out[0]["rule_check"] == "OK"


def test_rule_single_char_subject_flagged():
    out = rule_based_quality([{"subject": "钢", "predicate": "类型", "object": "材料"}])
    assert out[0]["rule_check"] == "WARN"
    assert "单字符" in "".join(out[0]["rule_reasons"])


def test_rule_single_char_subject_uppercase_abbrev_ok():
    """单字符但为大写缩写（如 "A"）不算可疑。"""
    out = rule_based_quality([{"subject": "A", "predicate": "rel", "object": "设备"}])
    assert out[0]["rule_check"] == "OK"


def test_rule_empty_subject_flagged():
    """空主语应当被规则捕获（实体缺失）。"""
    out = rule_based_quality([{"subject": "", "predicate": "rel", "object": "托轮"}])
    assert out[0]["rule_check"] == "WARN"


def test_rule_whitespace_only_subject_flagged():
    out = rule_based_quality([{"subject": "   ", "predicate": "rel", "object": "托轮"}])
    assert out[0]["rule_check"] == "WARN"


def test_rule_clean_chinese_triple_ok():
    out = rule_based_quality(
        [{"subject": "回转窑", "predicate": "包含部件", "object": "托轮"}]
    )
    assert out[0]["rule_check"] == "OK"
    assert "rule_reasons" not in out[0]


def test_rule_does_not_mutate_original_keys():
    t = {"subject": "回转窑", "predicate": "包含部件", "object": "托轮"}
    rule_based_quality([t])
    assert t["subject"] == "回转窑"


def test_rule_warns_reduce_confidence_within_bounds():
    t = {"subject": "X", "predicate": "relatedTo", "object": "X", "confidence": 80}
    out = rule_based_quality([t])
    # 单条 reason -> 扣 10，下限为 0
    assert 0 <= out[0]["confidence"] <= 80


def test_rule_asymmetry_subject_vs_object_single_char():
    """已知不对称点：规则4只检查主语单字符，宾语单字符不告警（边界/格式要求覆盖）。"""
    subj_only = rule_based_quality([{"subject": "钢", "predicate": "rel", "object": "托轮"}])
    obj_only = rule_based_quality([{"subject": "托轮", "predicate": "rel", "object": "钢"}])
    assert subj_only[0]["rule_check"] == "WARN"
    assert obj_only[0]["rule_check"] == "OK"  # 宾语单字符未被规则覆盖


# ===========================================================================
# 二、评分 / verdict 归一化辅助函数
# ===========================================================================

@pytest.mark.parametrize(
    "raw,expected",
    [
        (95, 95.0),
        ("88", 88.0),
        ("  77  ", 77.0),
        (150, 100.0),     # 越界 -> 截断到 100
        (-5, 0.0),        # 越界 -> 截断到 0
        ("abc", 50.0),    # 非数字 -> 默认
        (None, 50.0),
        (True, 50.0),     # bool 不应被当 1
    ],
)
def test_coerce_score(raw, expected):
    assert _coerce_score(raw) == expected


@pytest.mark.parametrize(
    "verdict_raw,score,expected",
    [
        ("PASS", 95, "PASS"),
        ("pass", 95, "PASS"),
        ("通过", 95, "PASS"),
        ("REJECT", 10, "REJECT"),
        ("拒绝", 10, "REJECT"),
        ("UNCERTAIN", 50, "UNCERTAIN"),
        ("待定", 50, "UNCERTAIN"),
        (None, 95, "PASS"),       # 缺失 -> 按评分推导
        (None, 80, "PASS"),       # 基本正确(70-89) -> PASS
        (None, 55, "UNCERTAIN"),  # 怀疑(40-69) -> 待定
        (None, 20, "REJECT"),     # 明显错误 -> 拒绝
        ("garbled", 80, "PASS"),  # 无法识别且 70-89 -> PASS
    ],
)
def test_normalize_verdict(verdict_raw, score, expected):
    assert _normalize_verdict(verdict_raw, score) == expected


# ===========================================================================
# 三、llm_quality_review —— 格式要求 / 边界条件
# ===========================================================================

def test_llm_review_empty_input(monkeypatch):
    assert llm_quality_review([], "text", cfg={}) == []


def test_llm_review_0based_ok(monkeypatch):
    """正常 0-based index：每条三元组拿到对应评分与 verdict。"""
    triples = [
        {"subject": "回转窑", "predicate": "包含部件", "object": "托轮"},
        {"subject": "托轮", "predicate": "属于设备", "object": "回转窑"},
    ]
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(score=95, verdict="PASS", index_mode="0based"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)
    assert len(out) == 2
    assert out[0]["verdict"] == "PASS" and out[0]["quality_score"] == 95.0
    assert out[1]["verdict"] == "PASS" and out[1]["quality_score"] == 95.0


def test_defectA_1based_index_no_longer_drops_or_misaligns(monkeypatch):
    """缺陷 A 验证：LLM 用 1-based 编号时，末条不应被丢弃、其余不应错位。"""
    n = 5
    triples = [{"subject": f"S{i}", "predicate": "p", "object": f"O{i}"} for i in range(n)]
    # 每条返回不同分数，便于检测错位
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(score=lambda i, _: 90 + i, verdict="PASS", index_mode="1based"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)
    for i in range(n):
        # 修复后：第 i 条应得到 90+i（而非错位或被丢弃导致的缺字段）
        assert "quality_score" in out[i], f"第 {i} 条缺失 quality_score（缺陷 A 复现）"
        assert out[i]["quality_score"] == pytest.approx(90 + i), f"第 {i} 条评分错位（缺陷 A 复现）"
        assert out[i]["verdict"] == "PASS"


def test_defectA_missing_index_does_not_corrupt_triple0(monkeypatch):
    """缺陷 A 验证：index 字段缺失时不应把所有 review 写到第 0 条。"""
    n = 4
    triples = [{"subject": f"S{i}", "predicate": "p", "object": f"O{i}"} for i in range(n)]
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(score=lambda i, _: 91 + i, verdict="PASS", index_mode="missing"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)
    for i in range(n):
        assert out[i]["quality_score"] == pytest.approx(91 + i), (
            f"第 {i} 条被错误覆盖为第0条分数（缺陷 A 复现）"
        )


def test_defectB_score_string_coerced(monkeypatch):
    """缺陷 B 验证：quality_score 为字符串时仍能正确比较 / 落库。"""
    triples = [{"subject": "回转窑", "predicate": "包含部件", "object": "托轮"}]
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(score="88", verdict="PASS", index_mode="0based"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)
    assert isinstance(out[0]["quality_score"], float)
    assert out[0]["quality_score"] == 88.0


def test_defectB_score_out_of_range_clamped(monkeypatch):
    triples = [{"subject": "回转窑", "predicate": "包含部件", "object": "托轮"}]
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(score=150, verdict="PASS", index_mode="0based"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)
    assert out[0]["quality_score"] == 100.0


def test_verdict_chinese_normalized(monkeypatch):
    triples = [{"subject": "回转窑", "predicate": "包含部件", "object": "托轮"}]
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(score=95, verdict="通过", index_mode="0based"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)
    assert out[0]["verdict"] == "PASS"


def test_defectC_basic_correct_band_passes(monkeypatch):
    """缺陷 C 验证：评分 70-89（「基本正确」）应视为通过，而非停留在 PENDING。"""
    triples = [{"subject": "回转窑", "predicate": "包含部件", "object": "托轮"}]
    # LLM 返回「基本正确」分数但未显式给 PASS（旧逻辑会因此不通过）
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(score=82, verdict="UNCERTAIN", index_mode="0based"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)
    assert out[0]["verdict"] == "PASS"
    assert out[0]["quality_score"] == 82.0


def test_defectC_suspect_band_stays_uncertain(monkeypatch):
    """评分 40-69（「存在怀疑点」）应保持 UNCERTAIN，进入人工复核。"""
    triples = [{"subject": "回转窑", "predicate": "包含部件", "object": "托轮"}]
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(score=55, verdict="UNCERTAIN", index_mode="0based"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)
    assert out[0]["verdict"] == "UNCERTAIN"


def test_defectC_low_score_rejected(monkeypatch):
    triples = [{"subject": "回转窑", "predicate": "包含部件", "object": "托轮"}]
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(score=20, verdict="UNCERTAIN", index_mode="0based"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)
    assert out[0]["verdict"] == "REJECT"


def test_defectD_no_review_still_gets_fields(monkeypatch):
    """缺陷 D 验证：LLM 返回空数组（整批漏评）时，每条三元组仍应有兜底字段。"""
    triples = [
        {"subject": "回转窑", "predicate": "包含部件", "object": "托轮", "confidence": 88},
        {"subject": "托轮", "predicate": "属于设备", "object": "回转窑", "confidence": 92},
    ]
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(index_mode="empty"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)
    for t in out:
        assert "quality_score" in t
        assert "verdict" in t
        # 兜底：用原始置信度推导 verdict（88 -> PASS, 92 -> PASS）
        assert t["verdict"] == "PASS"


def test_large_batch_boundary_490_triples(monkeypatch):
    """边界：490 条三元组（batch_size=15 -> 33 个批次）全部获得评分与 verdict。"""
    triples = [{"subject": f"S{i}", "predicate": "p", "object": f"O{i}"} for i in range(490)]
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(score=85, verdict="UNCERTAIN", index_mode="0based"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)
    assert len(out) == 490
    # 末条（第 489 条，属于最后一个不足 15 的批次）也必须被评分
    assert out[489]["quality_score"] == 85.0
    assert out[489]["verdict"] == "PASS"  # 85 属「基本正确」-> PASS
    assert all("quality_score" in t for t in out)


def test_reproduction_490_pass_rate(monkeypatch):
    """复现并验证「490->40」低通过率缺陷已被修复。

    场景：490 条三元组，其中 40 条评分 95（显式 PASS），450 条评分 75（「基本正确」，
    但旧逻辑下 verdict 为 UNCERTAIN 且 75<90 阈值 -> 不通过）。
    旧逻辑结果：仅 40 条通过（即线上观察到的 490->40）。
    修复后结果：450 条「基本正确」也判为 PASS，共 490 条通过。
    """
    n = 490
    triples = [{"subject": f"S{i}", "predicate": "p", "object": f"O{i}"} for i in range(n)]

    def _score(i, _n):
        return 95 if i < 40 else 75

    def _verdict(i, _n):
        return "PASS" if i < 40 else "UNCERTAIN"

    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        make_fake_quality(score=_score, verdict=_verdict, index_mode="0based"),
    )
    out = llm_quality_review(triples, "文本", cfg={}, batch_size=15)

    passed = [t for t in out if t["verdict"] == "PASS"]
    assert len(passed) == 490, "修复后「基本正确」三元组应全部通过"
