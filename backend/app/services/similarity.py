"""三元组语义相似度

用于需求4「三元组入库前消歧」：抽取新三元组入库前，检索库中是否已存在
语义相似的三元组，以判断是否需要消歧。

两种模式：
1. 向量语义匹配（推荐）：项目在「模型配置」中配置了 EMBEDDING 阶段的向量模型后，
   使用向量余弦相似度做真正的语义匹配（见 TripleEmbedder / make_embedder）。
2. 词面相似度（降级）：未配置向量模型或调用失败时，回退到「归一化 + difflib
   序列相似度」，开箱即用、无需外部服务。
"""
import re
import math
import logging
from difflib import SequenceMatcher
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _normalize(s: str) -> str:
    """归一化实体文本：转小写、去空白、去常见的标点/引号包裹"""
    s = (s or "").lower().strip()
    s = re.sub(r"[\s\u3000]+", "", s)
    # 去掉包裹的标点/引号（含中文全角与书名号等常见形式）
    s = s.strip('"\'“”‘’。.，,：:；;、（）()【】《》「」『』')
    return s


def triple_key(subject: str, predicate: str, object_: str) -> str:
    """生成三元组的归一化标识键（用于快速去重/相似比较）"""
    return f"{_normalize(subject)}|{_normalize(predicate)}|{_normalize(object_)}"


def _triple_text(t: Dict) -> str:
    """把三元组拼成一句自然文本，供向量模型编码"""
    return f"{t.get('subject', '')} {t.get('predicate', '')} {t.get('object', '')}".strip()


def triple_similarity(a: Dict, b: Dict) -> float:
    """计算两个三元组的词面相似度 (0~1)

    a, b: 含 subject/predicate/object 的字典
    """
    ka = triple_key(a.get("subject", ""), a.get("predicate", ""), a.get("object", ""))
    kb = triple_key(b.get("subject", ""), b.get("predicate", ""), b.get("object", ""))
    # triple_key 用 "|" 连接，全空三元组会得到 "||"，需剥掉分隔符再判空
    if not ka.strip("|") or not kb.strip("|"):
        return 0.0
    return SequenceMatcher(None, ka, kb).ratio()


def _cosine(a: List[float], b: List[float]) -> float:
    """余弦相似度 (0~1，负值截断为 0)"""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    sim = dot / (na * nb)
    return max(0.0, min(1.0, sim))


class TripleEmbedder:
    """向量语义相似度封装：带缓存、批量编码、失败降级。

    - 复用同一实例可跨多次 find_similar 调用共享向量缓存（已有三元组只需编码一次）。
    - 任意步骤出错会抛出异常，交由 find_similar_triples 捕获后降级到词面相似度。
    """

    def __init__(self, cfg: Dict):
        self.cfg = cfg
        self._cache: Dict[str, List[float]] = {}

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """批量编码，命中缓存的不重复请求"""
        todo = [t for t in texts if t not in self._cache]
        if todo:
            from app.services.llm_engine import get_embeddings
            vecs = get_embeddings(todo, self.cfg)
            for t, v in zip(todo, vecs):
                self._cache[t] = v
        return [self._cache[t] for t in texts]

    def similarity(self, a: Dict, b: Dict) -> float:
        va, vb = self._embed([_triple_text(a), _triple_text(b)])
        return _cosine(va, vb)

    def find_similar(self, candidate: Dict, existing: List[Dict], threshold: float) -> List[Dict]:
        if not existing:
            return []
        texts = [_triple_text(candidate)] + [_triple_text(e) for e in existing]
        vecs = self._embed(texts)
        cand_v = vecs[0]
        results = []
        for ex, v in zip(existing, vecs[1:]):
            sim = _cosine(cand_v, v)
            if sim >= threshold:
                r = dict(ex)
                r["similarity"] = round(sim, 4)
                results.append(r)
        results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
        return results


def make_embedder(db, project_id: str) -> Optional[TripleEmbedder]:
    """若项目配置了 EMBEDDING 阶段且已启用(enabled)的向量模型，返回 TripleEmbedder；否则 None。

    调用方拿到 None 时，find_similar_triples 会自动使用词面相似度。
    """
    try:
        from app.services.llm_engine import get_llm_config_for_project
        cfg = get_llm_config_for_project(db, project_id, "EMBEDDING")
        if (
            cfg
            and cfg.get("enabled", True)
            and cfg.get("api_key")
            and cfg.get("model_name")
        ):
            return TripleEmbedder(cfg)
    except Exception as e:
        logger.warning("初始化向量模型失败，将回退词面相似度: %s", e)
    return None


def find_similar_triples(
    candidate: Dict,
    existing: List[Dict],
    threshold: float = None,
    embedder: Optional[TripleEmbedder] = None,
    embedding_threshold: float = None,
) -> List[Dict]:
    """在 existing 中找出与 candidate 相似度 >= threshold 的三元组

    Args:
        candidate: 含 subject/predicate/object 的候选三元组
        existing: 已有三元组列表
        threshold: 词面(difflib)相似度阈值 (0~1)，默认 0.85
        embedder: 可选的向量相似度器；提供时优先用向量语义匹配，失败自动降级
        embedding_threshold: 向量(余弦)相似度阈值 (0~1)。与 threshold 含义不同：
            文本比率 0.85≈几乎相同文本，而余弦 0.85 对多数 embedding 模型仅表示
            "相关"。不传则复用 threshold。

    Returns:
        相似三元组列表（附带 similarity 字段，降序）
    """
    if threshold is None:
        threshold = 0.85
    # 向量模式使用独立阈值（余弦空间），避免与词面阈值混用导致召回差异
    eff_embedding_threshold = embedding_threshold if embedding_threshold is not None else threshold

    if embedder is not None:
        try:
            return embedder.find_similar(candidate, existing, eff_embedding_threshold)
        except Exception as e:
            logger.warning("向量相似度计算失败，本次回退词面相似度: %s", e)

    # ===== 降级：difflib 词面相似度 =====
    results = []
    for ex in existing:
        sim = triple_similarity(candidate, ex)
        if sim >= threshold:
            r = dict(ex)
            r["similarity"] = round(sim, 4)
            results.append(r)
    results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    return results
