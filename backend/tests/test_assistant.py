"""环节⑦：KAG 智能助手 —— 子图检索/提示词构建（纯逻辑）+ 推理问答（假 LLM + 假 DB 收集）。"""
import pytest

from app.services.assistant_engine import (
    chat_with_graph,
    _extract_entities_from_question,
    _extract_subgraph,
    _build_reasoning_prompt,
)


FAKE_TRIPLES = [
    {"subject": "回转窑", "predicate": "包含部件", "object": "托轮", "confidence": 90},
    {"subject": "托轮", "predicate": "属于设备", "object": "回转窑", "confidence": 85},
]


def test_extract_entities_from_question():
    q = "回转窑和托轮之间有什么关系？"
    found = _extract_entities_from_question(q, FAKE_TRIPLES)
    assert "回转窑" in found
    assert "托轮" in found


def test_extract_subgraph():
    nodes, edges = _extract_subgraph(FAKE_TRIPLES, ["回转窑"], max_hops=2)
    assert len(nodes) >= 1
    assert len(edges) >= 1
    assert any(e["subject"] == "回转窑" for e in edges)


def test_build_reasoning_prompt():
    nodes, edges = _extract_subgraph(FAKE_TRIPLES, ["回转窑"], max_hops=2)
    system, user = _build_reasoning_prompt(
        "回转窑有什么部件？", nodes, edges, ["回转窑"], []
    )
    assert isinstance(system, str) and isinstance(user, str)
    assert "KAG" in system


def test_chat_with_graph_fake(monkeypatch):
    # 欺骗三个依赖：子图收集 / LLM 配置 / LLM 调用
    monkeypatch.setattr(
        "app.services.assistant_engine._collect_triples",
        lambda db, pids, status_filter=None: list(FAKE_TRIPLES),
    )
    monkeypatch.setattr(
        "app.services.assistant_engine._get_llm_config",
        lambda db, pid, stage=None: {
            "api_key": "fake",
            "base_url": "http://fake",
            "model_name": "m",
            "api_provider": "OPENAI",
        },
    )
    monkeypatch.setattr(
        "app.services.assistant_engine._call_llm",
        lambda cfg, sp, up, temperature=0.3: "回转窑包含托轮等部件。",
    )
    monkeypatch.setattr(
        "app.services.assistant_engine._get_project_sources",
        lambda db, pids: [],
    )

    result = chat_with_graph(
        db=None,
        project_ids=["p1"],
        question="回转窑有什么部件？",
    )
    assert result["answer"] == "回转窑包含托轮等部件。"
    assert "reasoning_path" in result
    assert "回转窑" in result["reasoning_path"]["entities"]


def test_chat_with_graph_no_llm_config(monkeypatch):
    # 未配置 LLM 时的优雅降级：仍返回图谱检索结果，不抛异常
    monkeypatch.setattr(
        "app.services.assistant_engine._collect_triples",
        lambda db, pids, status_filter=None: list(FAKE_TRIPLES),
    )
    monkeypatch.setattr(
        "app.services.assistant_engine._get_llm_config",
        lambda db, pid, stage=None: None,
    )
    monkeypatch.setattr(
        "app.services.assistant_engine._get_project_sources",
        lambda db, pids: [],
    )
    result = chat_with_graph(db=None, project_ids=["p1"], question="回转窑？")
    assert "回转窑" in result["answer"]
    assert "未配置 LLM" in result["answer"] or "LLM" in result["answer"]
