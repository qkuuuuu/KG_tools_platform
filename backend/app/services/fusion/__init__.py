"""知识融合引擎 (Knowledge Fusion Engine)
参考: openSPG 实体对齐 + QKnow 智能融合设计

核心流程:
  1. 实体识别与类型推断
  2. 编辑距离 + 嵌入向量相似度计算
  3. LLM 语义辅助消歧（参考 QKnow: AI初筛 + 人工复核）
  4. 自动合并 / 人工确认分流
  5. 全链路血缘记录

标签说明: ⚠️ 耗时较长 (~15s)，已标记
"""
import re
import math
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class EntityCandidate:
    name: str
    entity_type: str  # 推断的实体类型
    source_triple_ids: List[str]
    first_seen_at: str  # 首次出现位置


def _normalize_name(name: str) -> str:
    """名称标准化：去空白、去标点、全半角转换"""
    name = name.strip()
    # 去除常见后缀
    for suffix in [
        "有限公司", "股份有限公司", "有限责任公司", "集团", "公司",
        "Inc.", "Inc", "Ltd.", "Ltd", "Corp.", "Corp", "Corporation", "LLC",
        "(中国)", "（中国）", "(北京)", "（北京）", "(上海)", "（上海）",
    ]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    # 去括号
    name = re.sub(r"[\(\)（）\[\]【】{}\"]", "", name)
    # 去多余空格
    name = re.sub(r"\s+", "", name)
    return name.lower()


def _levenshtein_similarity(a: str, b: str) -> float:
    """Damerau-Levenshtein 编辑距离相似度 (0-100)"""
    la, lb = len(a), len(b)
    if la == 0 and lb == 0:
        return 100.0
    if la == 0 or lb == 0:
        return 0.0

    # 优化：只计算矩阵两行
    prev = list(range(lb + 1))
    curr = [0] * (lb + 1)
    for i in range(1, la + 1):
        curr[0] = i
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,       # 删除
                curr[j - 1] + 1,   # 插入
                prev[j - 1] + cost  # 替换
            )
            # 换位 (Damerau)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                curr[j] = min(curr[j], prev[j - 2] + cost)
        prev, curr = curr, prev

    distance = prev[lb]
    max_len = max(la, lb)
    return (1.0 - distance / max_len) * 100.0


def _embedding_similarity(name1: str, name2: str, model=None) -> float:
    """使用 Sentence-BERT 计算语义相似度
    
    Args:
        name1, name2: 两个实体名
        model: 预加载的 SentenceTransformer
    
    Returns:
        余弦相似度 * 100
    """
    try:
        from sentence_transformers import SentenceTransformer, util
        if model is None:
            model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        emb = model.encode([name1, name2], convert_to_tensor=True)
        sim = util.cos_sim(emb[0], emb[1])
        return float(sim[0][0]) * 100.0
    except ImportError:
        return _levenshtein_similarity(name1, name2)
    except Exception:
        return _levenshtein_similarity(name1, name2)


def _char_ngram_similarity(name1: str, name2: str, n: int = 3) -> float:
    """字符 n-gram 相似度（对中文短文本有效）"""
    def ngrams(s, k):
        return {s[i:i + k] for i in range(len(s) - k + 1)}

    ng1 = ngrams(name1, n)
    ng2 = ngrams(name2, n)
    if not ng1 or not ng2:
        return 0.0
    intersection = ng1 & ng2
    union = ng1 | ng2
    return (len(intersection) / len(union)) * 100.0


def compute_similarity(name1: str, name2: str, method: str = "hybrid") -> float:
    """融合相似度计算
    
    Args:
        name1, name2: 两个实体名
        method: "edit" (编辑距离) / "ngram" (n-gram) / "hybrid" (混合)
    
    Returns:
        相似度 0-100
    """
    n1 = _normalize_name(name1)
    n2 = _normalize_name(name2)

    if n1 == n2:
        return 100.0

    if method == "edit":
        return _levenshtein_similarity(n1, n2)
    elif method == "ngram":
        return _char_ngram_similarity(n1, n2)
    else:  # hybrid
        edit_sim = _levenshtein_similarity(n1, n2)
        ngram_sim = _char_ngram_similarity(n1, n2)
        return 0.6 * edit_sim + 0.4 * ngram_sim


def cluster_entities(
    triples: List[Dict],
    threshold_auto: float = 95.0,
    threshold_manual: float = 80.0,
) -> Tuple[List[Dict], List[Dict]]:
    """对已抽取的三元组进行实体聚类
    
    参考 openSPG: 相似度 >95% 自动合并, 80-95% 推荐人工确认
    
    Args:
        triples: 三元组列表（需要含 subject/object）
        threshold_auto: 自动合并阈值
        threshold_manual: 人工确认阈值
    
    Returns:
        (auto_clusters, manual_suggestions)
        auto_cluster: [{"standard_name":..., "aliases": [...], "members": [...]}]
        manual_suggestion: [{"entity_1":..., "entity_2":..., "similarity":..., "suggestion":"MERGE/ALIAS"}]
    """
    # 收集所有唯一的实体名
    all_entities = set()
    for t in triples:
        subj = t.get("subject", "").strip()
        obj = t.get("object", "").strip()
        if subj:
            all_entities.add(subj)
        if obj:
            all_entities.add(obj)

    entity_list = list(all_entities)
    n = len(entity_list)

    # 计算相似度矩阵（上三角）
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = compute_similarity(entity_list[i], entity_list[j])
            pairs.append((entity_list[i], entity_list[j], sim))

    # 排序
    pairs.sort(key=lambda x: x[2], reverse=True)

    # 并查集合并
    parent = {e: e for e in entity_list}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[py] = px

    manual_suggestions = []
    for e1, e2, sim in pairs:
        if sim >= threshold_auto:
            union(e1, e2)
        elif sim >= threshold_manual:
            manual_suggestions.append({
                "entity_1": e1,
                "entity_2": e2,
                "similarity": round(sim, 1),
                "suggestion": "MANUAL_CONFIRM",
            })

    # 按聚类分组
    clusters_map = {}
    for e in entity_list:
        root = find(e)
        clusters_map.setdefault(root, []).append(e)

    auto_clusters = []
    for root, members in clusters_map.items():
        if len(members) > 1:
            # 选最长名作为 standard_name
            standard = max(members, key=len)
            aliases = [m for m in members if m != standard]
            auto_clusters.append({
                "standard_name": standard,
                "aliases": aliases,
                "members": members,
            })

    return auto_clusters, manual_suggestions
