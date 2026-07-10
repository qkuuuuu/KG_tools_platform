"""智能助手引擎 - KAG 式知识图谱推理问答

参考 OpenSPG/KAG 的核心思想:
1. 问题分析: 识别问题中的实体和关系意图
2. 知识检索: 从三元组数据库检索相关子图
3. 推理合成: 将子图作为上下文，让 LLM 推理出答案
4. 推理路径: 返回用到的节点和关系，支持可解释性
"""
import json
import re
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from app.models import TripleRaw, TripleFused, EntityFused, Project
from app.services.llm_engine import _call_llm, _get_llm_config


def _collect_triples(db: Session, project_ids: List[str], status_filter: Optional[List[str]] = None) -> List[Dict]:
    """从多个项目收集三元组，支持融合后的图谱"""
    all_triples = []
    
    for pid in project_ids:
        # 优先取融合后的三元组
        fused = db.query(TripleFused).filter(TripleFused.project_id == pid).all()
        entities = db.query(EntityFused).filter(EntityFused.project_id == pid).all()
        entity_map = {str(e.id): e.standard_name for e in entities}
        
        if fused:
            for t in fused:
                s_name = entity_map.get(str(t.subject_entity_id), str(t.subject_entity_id)[:8])
                o_name = entity_map.get(str(t.object_entity_id), str(t.object_entity_id)[:8])
                all_triples.append({
                    "subject": s_name,
                    "predicate": t.predicate,
                    "object": o_name,
                    "confidence": len(t.source_triple_ids) if t.source_triple_ids else 80,
                    "project_id": str(pid),
                    "status": "FUSED",
                })
        
        # 补充原始三元组（去重）— 默认只加载已通过审核的三元组
        existing_keys = {(t["subject"], t["predicate"], t["object"]) for t in all_triples}
        raw_query = db.query(TripleRaw).filter(TripleRaw.project_id == pid)
        # 未指定 status_filter 时默认只取 PASSED 和 FUSED
        effective_filter = status_filter if status_filter else ["PASSED", "FUSED"]
        raw_query = raw_query.filter(TripleRaw.status.in_(effective_filter))
        raw_triples = raw_query.all()
        for t in raw_triples:
            key = (t.subject, t.predicate, t.object)
            if key not in existing_keys:
                all_triples.append({
                    "subject": t.subject,
                    "predicate": t.predicate,
                    "object": t.object,
                    "confidence": t.llm_confidence or 50,
                    "project_id": str(pid),
                    "status": t.status,
                })
                existing_keys.add(key)
    
    return all_triples


def _extract_entities_from_question(question: str, triples: List[Dict]) -> List[str]:
    """从问题中识别实体（基于三元组中的实体进行匹配）"""
    # 收集所有已知实体
    known_entities = set()
    for t in triples:
        known_entities.add(t["subject"])
        known_entities.add(t["object"])
    
    # 按长度降序排列，优先匹配长实体
    sorted_entities = sorted(known_entities, key=len, reverse=True)
    
    found = []
    question_lower = question.lower()
    for entity in sorted_entities:
        if entity.lower() in question_lower:
            # 避免子串重复匹配
            if not any(entity in f or f in entity for f in found if f != entity):
                found.append(entity)
    
    return found[:10]  # 最多返回10个实体


def _extract_subgraph(triples: List[Dict], entities: List[str], max_hops: int = 2) -> Tuple[List[Dict], List[Dict]]:
    """从三元组中提取与实体相关的子图（BFS 扩展 max_hops 跳）"""
    if not entities:
        return [], []
    
    # 构建邻接表
    adj = {}  # entity -> [(predicate, neighbor, triple)]
    for t in triples:
        s, p, o = t["subject"], t["predicate"], t["object"]
        adj.setdefault(s, []).append((p, o, t))
        adj.setdefault(o, []).append((p, s, t))
    
    # BFS 扩展
    visited_nodes = set(entities)
    visited_edges = []
    visited_triple_keys = set()
    
    frontier = list(entities)
    for hop in range(max_hops):
        next_frontier = []
        for node in frontier:
            for pred, neighbor, triple in adj.get(node, []):
                key = (triple["subject"], triple["predicate"], triple["object"])
                if key not in visited_triple_keys:
                    visited_triple_keys.add(key)
                    visited_edges.append(triple)
                if neighbor not in visited_nodes:
                    visited_nodes.add(neighbor)
                    next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break
    
    # 限制子图大小
    if len(visited_edges) > 50:
        visited_edges = visited_edges[:50]
    
    nodes = [{"id": n, "label": n} for n in visited_nodes]
    return nodes, visited_edges


def _build_reasoning_prompt(question: str, subgraph_nodes: List[Dict], subgraph_edges: List[Dict], 
                            found_entities: List[str], conversation_history: List[Dict]) -> Tuple[str, str]:
    """构建推理提示词（系统 + 用户）"""
    
    # 格式化子图为文本
    triples_text = "\n".join(
        f"- ({e['subject']}) --[{e['predicate']}]--> ({e['object']})"
        for e in subgraph_edges
    ) if subgraph_edges else "（无相关图谱数据）"
    
    entities_text = ", ".join(found_entities) if found_entities else "未识别到已知实体"
    
    # 对话历史
    history_text = ""
    if conversation_history:
        history_text = "\n\n之前的对话历史:\n"
        for msg in conversation_history[-6:]:  # 最近6轮
            role = "用户" if msg.get("role") == "user" else "助手"
            history_text += f"{role}: {msg.get('content', '')}\n"
    
    system_prompt = f"""你是知识图谱智能助手，基于图谱中的结构化知识回答用户问题。

你的工作流程（参考 KAG 框架）:
1. 分析用户问题，识别关键实体和关系意图
2. 基于知识图谱中的三元组进行推理
3. 如果问题需要多跳推理，逐步推导
4. 结合图谱知识和 LLM 常识给出答案

当前知识图谱中识别到的实体: {entities_text}

相关知识三元组（子图）:
{triples_text}

回答要求:
1. 优先基于图谱中的三元组回答，引用具体的关系
2. 如果图谱中没有足够信息，说明"图谱中暂无相关数据"，再用常识补充
3. 推理过程要清晰，说明用到了哪些实体和关系
4. 回答使用中文，简洁专业"""

    user_prompt = f"{history_text}\n\n用户问题: {question}\n\n请基于上述知识图谱信息回答。如果需要多跳推理，请展示推理链路。"
    
    return system_prompt, user_prompt


def chat_with_graph(
    db: Session,
    project_ids: List[str],
    question: str,
    conversation_history: List[Dict] = None,
    max_triples: int = 500,
) -> Dict:
    """智能问答主入口
    
    Args:
        db: 数据库会话
        project_ids: 要查询的项目ID列表（可以是一个项目或多个融合项目）
        question: 用户问题
        conversation_history: 对话历史 [{"role": "user"/"assistant", "content": "..."}]
        max_triples: 最多加载的三元组数量
    
    Returns:
        {
            "answer": "回答文本",
            "reasoning_path": {
                "entities": ["识别到的实体"],
                "nodes": [{"id":..., "label":...}],
                "edges": [{"subject":..., "predicate":..., "object":...}],
            },
            "subgraph_stats": {"node_count": N, "edge_count": M},
            "sources": [{"project_id":..., "project_name":...}],
        }
    """
    # 1. 收集三元组
    triples = _collect_triples(db, project_ids)
    if len(triples) > max_triples:
        triples = triples[:max_triples]
    
    if not triples:
        return {
            "answer": "当前项目中暂无三元组数据，请先上传文档并进行抽取。",
            "reasoning_path": {"entities": [], "nodes": [], "edges": []},
            "subgraph_stats": {"node_count": 0, "edge_count": 0},
            "sources": [],
        }
    
    # 2. 实体识别
    found_entities = _extract_entities_from_question(question, triples)
    
    # 3. 子图提取
    subgraph_nodes, subgraph_edges = _extract_subgraph(triples, found_entities, max_hops=2)
    
    # 如果没有识别到实体，用全部三元组的前N条作为上下文
    if not found_entities or not subgraph_edges:
        subgraph_edges = triples[:30]
        subgraph_nodes = [{"id": t["subject"], "label": t["subject"]} for t in subgraph_edges]
        subgraph_nodes += [{"id": t["object"], "label": t["object"]} for t in subgraph_edges]
        # 去重
        seen = set()
        unique_nodes = []
        for n in subgraph_nodes:
            if n["id"] not in seen:
                seen.add(n["id"])
                unique_nodes.append(n)
        subgraph_nodes = unique_nodes
    
    # 4. 获取 LLM 配置（优先用 ASSISTANT 阶段，fallback 到 EXTRACTION/FUSION/QUALITY）
    cfg = None
    for stage in ["ASSISTANT", "EXTRACTION", "FUSION", "QUALITY"]:
        cfg = _get_llm_config(db, project_ids[0], stage)
        if cfg and cfg.get("api_key"):
            break
    
    if not cfg or not cfg.get("api_key"):
        # 没有 LLM 配置，返回纯图谱检索结果
        entity_str = ", ".join(found_entities) if found_entities else "无"
        return {
            "answer": f"识别到实体: {entity_str}。\n"
                     f"找到 {len(subgraph_nodes)} 个相关节点和 {len(subgraph_edges)} 条关系。\n"
                     f"但项目未配置 LLM，无法进行推理问答。请先在\"模型配置\"中设置 LLM。",
            "reasoning_path": {
                "entities": found_entities,
                "nodes": subgraph_nodes[:50],
                "edges": subgraph_edges[:50],
            },
            "subgraph_stats": {"node_count": len(subgraph_nodes), "edge_count": len(subgraph_edges)},
            "sources": _get_project_sources(db, project_ids),
        }
    
    # 5. 构建提示词并调用 LLM
    system_prompt, user_prompt = _build_reasoning_prompt(
        question, subgraph_nodes, subgraph_edges, found_entities, conversation_history or []
    )
    
    try:
        answer = _call_llm(cfg, system_prompt, user_prompt, temperature=0.3)
    except Exception as e:
        answer = f"推理过程中出现错误: {str(e)}\n\n图谱中识别到的实体: {', '.join(found_entities) if found_entities else '无'}"
    
    return {
        "answer": answer,
        "reasoning_path": {
            "entities": found_entities,
            "nodes": subgraph_nodes[:100],
            "edges": [{"source": e["subject"], "target": e["object"], "label": e["predicate"], 
                       "confidence": e.get("confidence", 50)} for e in subgraph_edges[:100]],
        },
        "subgraph_stats": {"node_count": len(subgraph_nodes), "edge_count": len(subgraph_edges)},
        "sources": _get_project_sources(db, project_ids),
    }


def _get_project_sources(db: Session, project_ids: List[str]) -> List[Dict]:
    """获取项目来源信息"""
    sources = []
    for pid in project_ids:
        proj = db.query(Project).filter(Project.id == pid).first()
        if proj:
            sources.append({"project_id": str(proj.id), "project_name": proj.name})
    return sources
