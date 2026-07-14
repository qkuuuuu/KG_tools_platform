"""今日新增需求单测：向量语义相似度 + EMBEDDING 阶段接入。

覆盖：
- similarity.py: _normalize / triple_key / triple_similarity / _cosine /
  TripleEmbedder（缓存 + 批量 + find_similar 阈值）/ make_embedder /
  find_similar_triples（向量路径 + difflib 降级路径）
- llm_engine.get_embeddings: 单字符串/列表输入、空文本占位、空列表返回、顺序对齐

所有模型/网络调用都用 monkeypatch 替换为假实现，纯逻辑离线可跑。
"""
import pytest

from app.services.similarity import (
    _normalize,
    triple_key,
    triple_similarity,
    _cosine,
    TripleEmbedder,
    make_embedder,
    find_similar_triples,
)
from app.services.llm_engine import get_embeddings


# ---------------------------------------------------------------------------
# 假 embedding 客户端 / 假 get_embeddings
# ---------------------------------------------------------------------------

class _FakeEmb:
    def __init__(self, index, embedding):
        self.index = index
        self.embedding = embedding


class _FakeResp:
    def __init__(self, data):
        self.data = data


class _FakeEmbeddings:
    def __init__(self, capture):
        self.capture = capture

    def create(self, model, input):
        # 记录本次实际传给模型的内容（用于校验空文本被替换为占位空格）
        self.capture["input"] = list(input)
        # 按顺序返回向量：[i+1, 0, 0] 形状固定，长度与输入一致
        return _FakeResp([_FakeEmb(i, [float(i + 1), 0.0, 0.0]) for i in range(len(input))])


class _FakeClient:
    def __init__(self, capture):
        self.embeddings = _FakeEmbeddings(capture)


def _fake_get_embeddings_by_keyword(texts, cfg):
    """按文本是否含『苹果』返回两类向量，便于验证语义聚簇。"""
    if isinstance(texts, str):
        texts = [texts]

    def vec(t):
        return [1.0, 0.0, 0.0] if "苹果" in t else [0.0, 1.0, 0.0]

    return [vec(t) for t in texts]


# ---------------------------------------------------------------------------
# 归一化 / 词面相似度
# ---------------------------------------------------------------------------

def test_normalize_strips_punctuation_and_case():
    assert _normalize("  “苹果公司”  ") == "苹果公司"
    assert _normalize("Apple.Inc") == "apple.inc"
    assert _normalize("") == ""


def test_triple_key_concatenates_normalized_parts():
    assert triple_key("苹果", "生产", "手机") == "苹果|生产|手机"
    assert triple_key(" Apple ", " 生产 ", " 手机 ") == "apple|生产|手机"


def test_triple_similarity_identical_is_one():
    a = {"subject": "苹果", "predicate": "生产", "object": "手机"}
    b = {"subject": "苹果", "predicate": "生产", "object": "手机"}
    assert triple_similarity(a, b) == 1.0


def test_triple_similarity_different_is_low():
    a = {"subject": "苹果", "predicate": "生产", "object": "手机"}
    b = {"subject": "香蕉", "predicate": "生长于", "object": "热带"}
    assert triple_similarity(a, b) < 0.5


def test_triple_similarity_empty_returns_zero():
    a = {"subject": "", "predicate": "", "object": ""}
    b = {"subject": "x", "predicate": "y", "object": "z"}
    assert triple_similarity(a, b) == 0.0


# ---------------------------------------------------------------------------
# 余弦相似度
# ---------------------------------------------------------------------------

def test_cosine_identical():
    assert _cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_cosine_orthogonal_is_zero():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_handles_empty():
    assert _cosine([], [1.0]) == 0.0
    assert _cosine([1.0], [0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# TripleEmbedder：缓存 / 批量 / find_similar 阈值
# ---------------------------------------------------------------------------

def test_triple_embedder_cache_avoids_repeat_calls(monkeypatch):
    call_count = {"n": 0}

    def fake_emb(texts, cfg):
        call_count["n"] += 1
        return _fake_get_embeddings_by_keyword(texts, cfg)

    monkeypatch.setattr("app.services.llm_engine.get_embeddings", fake_emb)
    emb = TripleEmbedder({"model_name": "m", "api_key": "k"})

    cand = {"subject": "苹果", "predicate": "发布", "object": "手机"}
    ex = {"subject": "苹果公司", "predicate": "生产", "object": "iPhone"}
    # 第一次比较触发编码
    emb.similarity(cand, ex)
    # 第二次相同文本应从缓存取，不再调用模型
    emb.similarity(cand, ex)
    assert call_count["n"] == 1


def test_triple_embedder_find_similar_respects_threshold(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm_engine.get_embeddings", _fake_get_embeddings_by_keyword
    )
    emb = TripleEmbedder({"model_name": "m", "api_key": "k"})

    cand = {"subject": "苹果", "predicate": "发布", "object": "手机"}
    existing = [
        {"id": "1", "subject": "苹果公司", "predicate": "生产", "object": "iPhone"},  # 含苹果 → 同类
        {"id": "2", "subject": "香蕉", "predicate": "生长于", "object": "热带"},        # 不同类
    ]
    res = emb.find_similar(cand, existing, threshold=0.9)
    assert len(res) == 1
    assert res[0]["id"] == "1"
    assert res[0]["similarity"] == 1.0  # 同为 [1,0,0] 向量


def test_triple_embedder_find_similar_empty_existing():
    emb = TripleEmbedder({"model_name": "m", "api_key": "k"})
    assert emb.find_similar({"subject": "a", "predicate": "b", "object": "c"}, [], 0.8) == []


# ---------------------------------------------------------------------------
# make_embedder：按 EMBEDDING 配置决定是否启用向量
# ---------------------------------------------------------------------------

def test_make_embedder_none_when_no_config(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm_engine.get_llm_config_for_project",
        lambda db, pid, stage: None,
    )
    assert make_embedder(None, "p1") is None


def test_make_embedder_none_when_missing_api_key(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm_engine.get_llm_config_for_project",
        lambda db, pid, stage: {"model_name": "m"},  # 无 api_key
    )
    assert make_embedder(None, "p1") is None


def test_make_embedder_returns_embedder_when_configured(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm_engine.get_llm_config_for_project",
        lambda db, pid, stage: {"api_key": "k", "model_name": "m", "base_url": "x", "enabled": True},
    )
    emb = make_embedder(None, "p1")
    assert isinstance(emb, TripleEmbedder)


def test_make_embedder_none_when_disabled(monkeypatch):
    # enabled=False → 即使配置了 key/model，也视为关闭，回退词面相似度
    monkeypatch.setattr(
        "app.services.llm_engine.get_llm_config_for_project",
        lambda db, pid, stage: {"api_key": "k", "model_name": "m", "enabled": False},
    )
    assert make_embedder(None, "p1") is None


# ---------------------------------------------------------------------------
# find_similar_triples：向量路径 + difflib 降级路径
# ---------------------------------------------------------------------------

def test_find_similar_triples_difflib_fallback(monkeypatch):
    # make_embedder 返回 None → 走 difflib
    monkeypatch.setattr(
        "app.services.similarity.make_embedder", lambda db, pid: None
    )
    cand = {"subject": "苹果", "predicate": "生产", "object": "手机"}
    existing = [
        {"id": "1", "subject": "苹果", "predicate": "生产", "object": "手机"},
        {"id": "2", "subject": "香蕉", "predicate": "生长于", "object": "热带"},
    ]
    res = find_similar_triples(cand, existing, threshold=0.85, embedder=None)
    assert len(res) == 1
    assert res[0]["id"] == "1"
    assert res[0]["similarity"] == 1.0


def test_find_similar_triples_uses_embedder(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm_engine.get_embeddings", _fake_get_embeddings_by_keyword
    )
    emb = TripleEmbedder({"model_name": "m", "api_key": "k"})
    cand = {"subject": "苹果", "predicate": "发布", "object": "手机"}
    existing = [
        {"id": "1", "subject": "苹果公司", "predicate": "生产", "object": "iPhone"},
        {"id": "2", "subject": "香蕉", "predicate": "生长于", "object": "热带"},
    ]
    res = find_similar_triples(cand, existing, threshold=0.9, embedder=emb)
    assert len(res) == 1
    assert res[0]["id"] == "1"


def test_find_similar_triples_embedder_failure_falls_back(monkeypatch):
    # 向量调用抛错 → 自动降级到 difflib，不应让异常冒泡
    def boom(texts, cfg):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr("app.services.llm_engine.get_embeddings", boom)
    emb = TripleEmbedder({"model_name": "m", "api_key": "k"})

    cand = {"subject": "苹果", "predicate": "生产", "object": "手机"}
    existing = [{"id": "1", "subject": "苹果", "predicate": "生产", "object": "手机"}]
    res = find_similar_triples(cand, existing, threshold=0.85, embedder=emb)
    # 降级后 difflib 命中完全相同的三元组
    assert len(res) == 1
    assert res[0]["id"] == "1"


def test_find_similar_triples_vector_uses_embedding_threshold(monkeypatch):
    # 向量余弦相似度约 0.707，处于文本阈值(0.5)与向量阈值(0.9)之间，
    # 用于验证向量路径用的是 embedding_threshold 而非文本 threshold。
    def fake_map(texts, cfg):
        mapping = {
            "alpha rel beta": [1.0, 0.0, 0.0],
            "gamma rel delta": [0.7, 0.7, 0.0],  # 与 [1,0,0] 余弦≈0.707
        }
        return [mapping.get(t, [0.0, 0.0, 1.0]) for t in texts]

    monkeypatch.setattr("app.services.llm_engine.get_embeddings", fake_map)
    emb = TripleEmbedder({"model_name": "m", "api_key": "k"})

    cand = {"subject": "alpha", "predicate": "rel", "object": "beta"}
    existing = [{"id": "1", "subject": "gamma", "predicate": "rel", "object": "delta"}]

    # 向量阈值 0.9（高于 0.707）→ 不匹配；注意此时文本阈值 0.5 若生效会匹配，证明用了向量阈值
    res_high = find_similar_triples(cand, existing, threshold=0.5, embedder=emb, embedding_threshold=0.9)
    assert res_high == []

    # 向量阈值 0.5（低于 0.707）→ 匹配
    res_low = find_similar_triples(cand, existing, threshold=0.9, embedder=emb, embedding_threshold=0.5)
    assert len(res_low) == 1
    assert res_low[0]["id"] == "1"


# ---------------------------------------------------------------------------
# llm_engine.get_embeddings：输入形态 / 空文本 / 顺序
# ---------------------------------------------------------------------------

def test_get_embeddings_single_string(monkeypatch):
    capture = {}
    monkeypatch.setattr(
        "app.services.llm_engine._make_client", lambda cfg: _FakeClient(capture)
    )
    out = get_embeddings("hello", {"model_name": "m", "api_key": "k"})
    assert len(out) == 1
    assert len(out[0]) == 3
    assert capture["input"] == ["hello"]


def test_get_embeddings_list(monkeypatch):
    capture = {}
    monkeypatch.setattr(
        "app.services.llm_engine._make_client", lambda cfg: _FakeClient(capture)
    )
    out = get_embeddings(["a", "b", "c"], {"model_name": "m", "api_key": "k"})
    assert len(out) == 3
    # 输入顺序应与输出顺序一致（第 i 个向量为 [i+1,0,0]）
    assert out[0][0] == 1.0 and out[2][0] == 3.0
    assert capture["input"] == ["a", "b", "c"]


def test_get_embeddings_empty_text_replaced_with_placeholder(monkeypatch):
    capture = {}
    monkeypatch.setattr(
        "app.services.llm_engine._make_client", lambda cfg: _FakeClient(capture)
    )
    out = get_embeddings(["", "abc"], {"model_name": "m", "api_key": "k"})
    # 空文本被替换为占位空格，但输出长度仍与输入一致
    assert len(out) == 2
    assert capture["input"][0] == " "
    assert capture["input"][1] == "abc"


def test_get_embeddings_empty_list_returns_empty():
    # 空列表直接返回空，不触发任何客户端调用
    assert get_embeddings([], {"model_name": "m", "api_key": "k"}) == []


class _FakeEmbNoIndex:
    """模拟不返回 index 字段的 OpenAI 兼容服务（仅含 embedding）"""
    def __init__(self, embedding):
        self.embedding = embedding


def test_get_embeddings_without_index_preserves_order(monkeypatch):
    # 部分兼容服务不返回 index：应信任服务按输入顺序返回，不做重排
    capture = {}

    class _Client:
        class _Emb:
            def create(self, model, input):
                capture["input"] = list(input)
                # 故意乱序返回，验证无 index 时按返回顺序（即输入顺序）映射
                return _FakeResp([_FakeEmbNoIndex([float(i + 1), 0.0, 0.0]) for i in range(len(input))])

        embeddings = _Emb()

    monkeypatch.setattr("app.services.llm_engine._make_client", lambda cfg: _Client())
    out = get_embeddings(["a", "b", "c"], {"model_name": "m", "api_key": "k"})
    assert len(out) == 3
    # 无 index 时按服务返回顺序映射，与输入顺序一致
    assert out[0][0] == 1.0 and out[2][0] == 3.0
    assert capture["input"] == ["a", "b", "c"]
