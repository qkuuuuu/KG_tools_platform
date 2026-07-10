"""融合路由 - 实体对齐 + LLM 辅助消歧 + 自动合并
参考: openSPG 实体对齐 + QKnow 知识融合
标签: ⚠️ 大项目向量嵌入耗时较长
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from app.database import get_db
from app.models import TripleRaw, EntityFused, TripleFused, User, LLMConfig, Project, Document
from app.utils.security import get_current_user, require_admin
from app.config import settings
from app.services.fusion import cluster_entities, compute_similarity
from app.services.fusion.llm_fusion import llm_assisted_fusion
from app.services.fusion.neo4j_exporter import generate_cypher_script, generate_jsonld, try_neo4j_import, query_graph
from app.services.llm_engine import call_llm_api, get_llm_config_for_project

router = APIRouter()


@router.get("/suggestions/{project_id}")
async def get_fusion_suggestions(
    project_id: UUID,
    method: str = Query("hybrid", description="相似度算法: edit/ngram/hybrid"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """获取融合建议
    
    流程（参考 openSPG & QKnow）:
      1. 收集项目中所有已通过审核(PASSED/FUSED)三元组的实体
      2. 编辑距离 + n-gram 相似度计算
      3. >95% 自动合并, 80-95% 推荐人工确认
      4. 返回建议列表
    """
    triples = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status.in_(["PASSED", "FUSED"]),
    ).all()

    if not triples:
        return {"suggestions": [], "auto_clusters": [], "total_entities": 0}

    triples_data = [
        {"subject": t.subject, "predicate": t.predicate, "object": t.object, "id": str(t.id)}
        for t in triples
    ]

    auto_clusters, manual_suggestions = cluster_entities(
        triples_data,
        threshold_auto=settings.FUSION_AUTO_THRESHOLD,
        threshold_manual=settings.FUSION_MANUAL_THRESHOLD,
    )

    return {
        "suggestions": manual_suggestions,
        "auto_clusters": auto_clusters,
        "total_entities": len(set(t.subject for t in triples) | set(t.object for t in triples)),
        "method": method,
    }


@router.post("/llm-disambiguate/{project_id}")
async def llm_disambiguate(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """LLM 辅助消歧：对相似度 80-95% 的实体对进行语义消歧
    
    流程（参考 QKnow: AI初筛 + 人工复核）:
      1. 获取所有 MANUAL_CONFIRM 的建议
      2. 调用 LLM 判断是否应该合并
      3. 返回 LLM 的决策供人工最终确认
    """
    # 收集已通过审核的三元组（实体消歧只处理已审核数据）
    triples = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status.in_(["PASSED", "FUSED"]),
    ).all()

    if not triples:
        return {"message": "没有可消歧的三元组", "decisions": []}

    triples_data = [
        {"subject": t.subject, "predicate": t.predicate, "object": t.object, "id": str(t.id)}
        for t in triples
    ]

    _, suggestions = cluster_entities(
        triples_data,
        threshold_auto=settings.FUSION_AUTO_THRESHOLD,
        threshold_manual=settings.FUSION_MANUAL_THRESHOLD,
    )

    if not suggestions:
        return {"message": "没有需要 LLM 辅助消歧的实体对", "decisions": []}

    # 获取 LLM 配置（用 VERIFICATION 模型做消歧）
    cfg = None
    llm_config = db.query(LLMConfig).filter(
        LLMConfig.project_id == project_id,
        LLMConfig.pipeline_stage == "VERIFICATION",
    ).first()
    if not llm_config:
        # 降级: 用 EXTRACTION 配置
        llm_config = db.query(LLMConfig).filter(
            LLMConfig.project_id == project_id,
            LLMConfig.pipeline_stage == "EXTRACTION",
        ).first()
    
    if llm_config:
        from app.config import decrypt_value
        cfg = {
            "api_provider": llm_config.api_provider,
            "base_url": llm_config.base_url,
            "api_key": decrypt_value(llm_config.api_key_encrypted),
            "model_name": llm_config.model_name,
        }

    if not cfg:
        return {"message": "未配置 LLM，仅使用编辑距离判断", "decisions": suggestions}

    # M4 修复: 使用文档原文(Document.md_content)作为上下文，而非三元组片段(TripleRaw.chunk_text)
    docs = db.query(Document).filter(
        Document.project_id == project_id,
        Document.md_content.isnot(None),
    ).limit(20).all()
    context = " ".join([d.md_content or "" for d in docs])[:5000]

    # LLM 辅助消歧
    enriched = llm_assisted_fusion(suggestions, context, cfg)

    return {
        "decisions": enriched,
        "total_pairs": len(enriched),
        "method": "LLM_ASSISTED",
    }


@router.post("/triple-dedup/{project_id}")
async def triple_dedup(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """项目内三元组 LLM 辅助消歧：发现并合并语义重复的三元组
    
    与 /llm-disambiguate/{project_id} 的区别:
    - llm-disambiguate: 实体级消歧（合并指代同一事物的实体名）
    - triple-dedup: 三元组级消歧（合并讲同一件事的三元组）
    
    流程:
      1. 收集项目所有三元组（PASSED/PENDING/FUSED）
      2. 先按 (subject, predicate, object) 精确去重
      3. 再用 LLM 判断语义相似的三元组是否讲同一件事
      4. 合并重复三元组，保留 confidence 最高的，其余标记为 MERGED
      5. 保留的三元组状态设为 PENDING，进入待审核队列
    """
    triples = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status.in_(["PASSED", "PENDING", "FUSED"]),
    ).all()
    
    if not triples:
        return {"message": "没有可消歧的三元组", "merged": 0}
    
    # 获取 LLM 配置
    cfg = get_llm_config_for_project(db, project_id, "VERIFICATION")
    if not cfg:
        cfg = get_llm_config_for_project(db, project_id, "EXTRACTION")
    
    # 第一步：精确去重（相同 subject+predicate+object）
    exact_groups = {}
    for t in triples:
        key = (t.subject.strip().lower(), t.predicate.strip().lower(), t.object.strip().lower())
        exact_groups.setdefault(key, []).append(t)
    
    merged_count = 0
    for key, group in exact_groups.items():
        if len(group) <= 1:
            continue
        # 保留 confidence 最高的
        keeper = max(group, key=lambda x: x.llm_confidence or 0)
        keeper.status = "PENDING"  # 重新进入待审核
        for t in group:
            if t.id != keeper.id:
                t.status = "MERGED"
                merged_count += 1
    
    db.commit()
    
    # 第二步：如果有 LLM 配置，做语义相似度消歧
    llm_merged = 0
    if cfg and len(triples) > 1:
        # 收集所有未合并的三元组
        active_triples = [t for t in triples if t.status in ("PASSED", "PENDING", "FUSED")]
        
        if len(active_triples) > 1:
            # 按 predicate 分组，只在相同 predicate 的三元组间比较
            pred_groups = {}
            for t in active_triples:
                pred = t.predicate.strip().lower()
                pred_groups.setdefault(pred, []).append(t)
            
            for pred, group in pred_groups.items():
                if len(group) <= 1:
                    continue
                
                # 构造 LLM prompt
                triples_text = "\n".join(
                    f"{i}. ({t.subject}, {t.predicate}, {t.object}) [confidence={t.llm_confidence or 0}]"
                    for i, t in enumerate(group)
                )
                
                system_prompt = """你是知识图谱三元组消歧专家。
给定一组相同谓词的三元组，请判断哪些三元组讲的是同一件事（语义等价）。
注意：主语/宾语可能是同一实体的不同称呼或简写。

输出格式: 严格 JSON 数组，每个元素:
{"group": [0, 2], "reason": "简短原因"}

group 是讲同一件事的三元组序号列表。
只输出 JSON，不要解释。"""
                
                user_prompt = f"以下三元组具有相同的谓词 '{pred}'，请判断哪些讲的是同一件事:\n\n{triples_text}"
                
                try:
                    import json
                    import re
                    response = call_llm_api(cfg, system_prompt, user_prompt, temperature=0.0)
                    response = re.sub(r"```json\s*", "", response)
                    response = re.sub(r"```\s*", "", response)
                    start = response.find("[")
                    end = response.rfind("]")
                    if start >= 0 and end > start:
                        decisions = json.loads(response[start:end+1])
                        for dec in decisions:
                            indices = dec.get("group", [])
                            if len(indices) < 2:
                                continue
                            # 验证索引有效性
                            valid = [i for i in indices if isinstance(i, int) and 0 <= i < len(group)]
                            if len(valid) < 2:
                                continue
                            # 保留 confidence 最高的
                            candidates = [group[i] for i in valid]
                            keeper = max(candidates, key=lambda x: x.llm_confidence or 0)
                            keeper.status = "PENDING"
                            for t in candidates:
                                if t.id != keeper.id:
                                    t.status = "MERGED"
                                    llm_merged += 1
                except Exception:
                    continue
            
            db.commit()
    
    total_merged = merged_count + llm_merged
    return {
        "message": f"消歧完成：合并了 {total_merged} 条重复三元组",
        "exact_merged": merged_count,
        "llm_merged": llm_merged,
        "total_merged": total_merged,
        "remaining": db.query(TripleRaw).filter(
            TripleRaw.project_id == project_id,
            TripleRaw.status.in_(["PASSED", "PENDING", "FUSED"]),
        ).count(),
    }


@router.post("/merge")
async def merge_entities(
    entity_1_name: str,
    entity_2_name: str,
    standard_name: str,
    project_id: UUID,
    merge_aliases: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """确认合并两个实体"""
    # 在 entities_fused 中查找或创建
    e1 = db.query(EntityFused).filter(
        EntityFused.project_id == project_id,
        EntityFused.standard_name == entity_1_name,
    ).first()
    e2 = db.query(EntityFused).filter(
        EntityFused.project_id == project_id,
        EntityFused.standard_name == entity_2_name,
    ).first()

    if not e1 and not e2:
        raise HTTPException(status_code=404, detail="实体不存在")

    if e1 and e2:
        # 合并 aliases（受 merge_aliases 参数控制）
        if merge_aliases:
            aliases = list(set((e1.aliases or []) + (e2.aliases or []) + [e2.standard_name]))
        else:
            aliases = list(e1.aliases or [])
        if e1.standard_name != standard_name:
            aliases.append(e1.standard_name)
        e1.standard_name = standard_name
        e1.aliases = aliases

        # 迁移三元组
        triples_2 = db.query(TripleFused).filter(TripleFused.subject_entity_id == e2.id).all()
        for t in triples_2:
            t.subject_entity_id = e1.id
        triples_2_obj = db.query(TripleFused).filter(TripleFused.object_entity_id == e2.id).all()
        for t in triples_2_obj:
            t.object_entity_id = e1.id

        db.delete(e2)
    elif e1:
        # 只需更新 e1
        if merge_aliases:
            aliases = list(set((e1.aliases or []) + [entity_2_name]))
        else:
            aliases = list(e1.aliases or [])
        if e1.standard_name != standard_name:
            aliases.append(e1.standard_name)
        e1.standard_name = standard_name
        e1.aliases = aliases
    elif e2:
        # H2 修复: 补全 not e1 and e2 分支 — 只有 e2 存在时，更新 e2 为标准名
        if merge_aliases:
            aliases = list(set((e2.aliases or []) + [entity_1_name]))
        else:
            aliases = list(e2.aliases or [])
        if e2.standard_name != standard_name:
            aliases.append(e2.standard_name)
        e2.standard_name = standard_name
        e2.aliases = aliases

    db.commit()
    return {"message": "合并成功", "standard_name": standard_name}


@router.post("/auto-fuse-passed/{project_id}")
async def auto_fuse_passed(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """将所有 PASSED 三元组融合到最终知识库
    
    流程:
      1. 实体去重（编辑距离自动合并）
      2. 写入 entities_fused + triples_fused
      3. 生成血缘记录
    """
    passed = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status == "PASSED",
    ).all()

    if not passed:
        return {"message": "没有 PASSED 的三元组", "fused_count": 0}

    # 先做一次自动实体去重
    triples_data = [
        {"subject": t.subject, "predicate": t.predicate, "object": t.object, "id": str(t.id)}
        for t in passed
    ]
    auto_clusters, _ = cluster_entities(
        triples_data,
        threshold_auto=settings.FUSION_AUTO_THRESHOLD,
        threshold_manual=settings.FUSION_MANUAL_THRESHOLD,
    )

    # 实体名 → 标准名映射
    name_map = {}
    for cluster in auto_clusters:
        standard = cluster["standard_name"]
        for alias in cluster["members"]:
            name_map[alias] = standard

    created_entities = {}
    fused_count = 0

    # 检查已存在的融合三元组（避免重复）
    existing_fused = db.query(TripleFused).filter(TripleFused.project_id == project_id).all()
    existing_fused_keys = set()
    existing_entity_map = {}
    # L7 修复: 批量预加载实体，消除 N+1 查询
    all_entity_ids = set()
    for ef in existing_fused:
        all_entity_ids.add(ef.subject_entity_id)
        all_entity_ids.add(ef.object_entity_id)
    entity_cache = {e.id: e for e in db.query(EntityFused).filter(EntityFused.id.in_(all_entity_ids)).all()} if all_entity_ids else {}
    for ef in existing_fused:
        s_ent = entity_cache.get(ef.subject_entity_id)
        o_ent = entity_cache.get(ef.object_entity_id)
        if s_ent and o_ent:
            existing_fused_keys.add((s_ent.standard_name, ef.predicate, o_ent.standard_name))
    # 预加载已存在的 EntityFused
    for e in db.query(EntityFused).filter(EntityFused.project_id == project_id).all():
        existing_entity_map[e.standard_name] = e.id

    for triple in passed:
        # 实体名归一化
        subj_std = name_map.get(triple.subject, triple.subject)
        obj_std = name_map.get(triple.object, triple.object)

        # 跳过已融合的三元组
        if (subj_std, triple.predicate, obj_std) in existing_fused_keys:
            triple.status = "FUSED"
            continue

        # 创建或复用主语实体
        subj_key = subj_std
        if subj_key not in created_entities:
            if subj_key in existing_entity_map:
                created_entities[subj_key] = existing_entity_map[subj_key]
            else:
                existing = db.query(EntityFused).filter(
                    EntityFused.project_id == project_id,
                    EntityFused.standard_name == subj_std,
                ).first()
                if existing:
                    created_entities[subj_key] = existing.id
                else:
                    e = EntityFused(
                        project_id=project_id,
                        standard_name=subj_std,
                        aliases=[triple.subject] if triple.subject != subj_std else [],
                    )
                    db.add(e)
                    db.flush()
                    created_entities[subj_key] = e.id

        # 创建或复用宾语实体
        obj_key = obj_std
        if obj_key not in created_entities:
            if obj_key in existing_entity_map:
                created_entities[obj_key] = existing_entity_map[obj_key]
            else:
                existing = db.query(EntityFused).filter(
                    EntityFused.project_id == project_id,
                    EntityFused.standard_name == obj_std,
                ).first()
                if existing:
                    created_entities[obj_key] = existing.id
                else:
                    e = EntityFused(
                        project_id=project_id,
                        standard_name=obj_std,
                        aliases=[triple.object] if triple.object != obj_std else [],
                    )
                    db.add(e)
                    db.flush()
                    created_entities[obj_key] = e.id

        # 写入最终三元组
        tf = TripleFused(
            project_id=project_id,
            subject_entity_id=created_entities[subj_key],
            predicate=triple.predicate,
            object_entity_id=created_entities[obj_key],
            source_triple_ids=[str(triple.id)],
        )
        db.add(tf)
        triple.status = "FUSED"
        fused_count += 1

    db.commit()  # 批量 commit 一次

    return {
        "message": "融合完成",
        "fused_count": fused_count,
        "entities_created": len(created_entities),
        "auto_clusters": len(auto_clusters),
    }


# ==================== 全局融合接口（不绑定项目） ====================

@router.post("/auto-fuse-multi")
async def auto_fuse_multi(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """跨项目自动融合 - 选择多个项目进行实体对齐和融合
    
    请求体: {"project_ids": ["uuid1", "uuid2", ...]}
    """
    project_ids = payload.get("project_ids", [])
    if not project_ids:
        raise HTTPException(status_code=400, detail="请选择至少一个项目")
    
    all_triples = []
    
    for pid in project_ids:
        passed = db.query(TripleRaw).filter(
            TripleRaw.project_id == pid,
            TripleRaw.status == "PASSED",
        ).all()
        for t in passed:
            all_triples.append({
                "subject": t.subject,
                "predicate": t.predicate,
                "object": t.object,
                "id": str(t.id),
                "project_id": pid,
                "triple_obj": t,
            })
    
    if not all_triples:
        return {"message": "选定项目中没有 PASSED 的三元组", "fused_count": 0}
    
    # 跨项目实体去重
    triples_data = [
        {"subject": t["subject"], "predicate": t["predicate"], "object": t["object"], "id": t["id"]}
        for t in all_triples
    ]
    auto_clusters, _ = cluster_entities(
        triples_data,
        threshold_auto=settings.FUSION_AUTO_THRESHOLD,
        threshold_manual=settings.FUSION_MANUAL_THRESHOLD,
    )
    
    name_map = {}
    for cluster in auto_clusters:
        standard = cluster["standard_name"]
        for alias in cluster["members"]:
            name_map[alias] = standard
    
    fused_count = 0
    entities_created = 0
    
    for pid in project_ids:
        created_entities = {}
        for item in all_triples:
            if item["project_id"] != pid:
                continue
            triple = item["triple_obj"]
            subj_std = name_map.get(triple.subject, triple.subject)
            obj_std = name_map.get(triple.object, triple.object)
            
            if subj_std not in created_entities:
                existing = db.query(EntityFused).filter(
                    EntityFused.project_id == pid,
                    EntityFused.standard_name == subj_std,
                ).first()
                if existing:
                    created_entities[subj_std] = existing.id
                else:
                    e = EntityFused(
                        project_id=pid,
                        standard_name=subj_std,
                        aliases=[triple.subject] if triple.subject != subj_std else [],
                    )
                    db.add(e)
                    db.flush()
                    created_entities[subj_std] = e.id
                    entities_created += 1
            
            if obj_std not in created_entities:
                existing = db.query(EntityFused).filter(
                    EntityFused.project_id == pid,
                    EntityFused.standard_name == obj_std,
                ).first()
                if existing:
                    created_entities[obj_std] = existing.id
                else:
                    e = EntityFused(
                        project_id=pid,
                        standard_name=obj_std,
                        aliases=[triple.object] if triple.object != obj_std else [],
                    )
                    db.add(e)
                    db.flush()
                    created_entities[obj_std] = e.id
                    entities_created += 1
            
            existing_tf = db.query(TripleFused).filter(
                TripleFused.project_id == pid,
                TripleFused.subject_entity_id == created_entities[subj_std],
                TripleFused.predicate == triple.predicate,
                TripleFused.object_entity_id == created_entities[obj_std],
            ).first()
            if not existing_tf:
                tf = TripleFused(
                    project_id=pid,
                    subject_entity_id=created_entities[subj_std],
                    predicate=triple.predicate,
                    object_entity_id=created_entities[obj_std],
                    source_triple_ids=[str(triple.id)],
                )
                db.add(tf)
                triple.status = "FUSED"
                fused_count += 1
    
    db.commit()
    
    return {
        "message": "跨项目融合完成",
        "fused_count": fused_count,
        "entities_created": entities_created,
        "auto_clusters": len(auto_clusters),
        "projects_processed": len(project_ids),
    }


@router.get("/neo4j-graph")
async def get_neo4j_graph(
    limit: int = Query(500, description="最大返回节点数"),
    _: User = Depends(get_current_user),
):
    """从 Neo4j 读取全图谱数据（用于融合页面的图谱可视化）"""
    from app.config import settings as s
    
    cypher_nodes = "MATCH (n) WHERE n.name IS NOT NULL RETURN n.name AS name, labels(n) AS labels, n.project_id AS project_id LIMIT $limit"
    cypher_rels = "MATCH (a)-[r]->(b) WHERE a.name IS NOT NULL AND b.name IS NOT NULL RETURN a.name AS source, b.name AS target, type(r) AS type, r.predicate AS predicate, r.project_id AS project_id, r.confidence AS confidence LIMIT $limit"
    
    nodes_result = query_graph(cypher_nodes, s.NEO4J_URL, s.NEO4J_USER, s.NEO4J_PASSWORD, limit=limit)
    rels_result = query_graph(cypher_rels, s.NEO4J_URL, s.NEO4J_USER, s.NEO4J_PASSWORD, limit=limit)
    
    nodes = []
    for r in nodes_result:
        if isinstance(r, dict) and r.get("name"):
            labels = r.get("labels") or ["Entity"]
            # 过滤掉 Project 根节点标签
            group_label = next((l for l in labels if l != "Project" and l != "Entity"), "Entity")
            nodes.append({
                "id": r["name"],
                "label": r["name"],
                "group": group_label,
                "project_id": r.get("project_id", ""),
            })
    
    edges = []
    for r in rels_result:
        if isinstance(r, dict) and r.get("source") and r.get("target"):
            edges.append({
                "source": r["source"],
                "target": r["target"],
                "label": r.get("predicate") or r.get("type", ""),
                "confidence": r.get("confidence", 80),
                "project_id": r.get("project_id", ""),
            })
    
    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


@router.post("/neo4j-clear")
async def clear_neo4j_graph(
    _: User = Depends(require_admin),
):
    """清空 Neo4j 中所有节点和关系
    
    ⚠️ 危险操作：删除整个图谱，不可恢复。
    """
    from app.config import settings as s
    
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            s.NEO4J_URL or "bolt://localhost:7687",
            auth=(s.NEO4J_USER or "neo4j", s.NEO4J_PASSWORD or "kg_neo4j_2026"),
        )
        driver.verify_connectivity()
        
        with driver.session() as session:
            node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            
            session.run("MATCH ()-[r]->() DELETE r")
            session.run("MATCH (n) DELETE n")
        
        driver.close()
        return {
            "message": "Neo4j 图谱已清空",
            "deleted_nodes": node_count,
            "deleted_rels": rel_count,
        }
    except ImportError:
        raise HTTPException(status_code=500, detail="Neo4j 驱动未安装")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Neo4j 操作失败: {str(e)}")


@router.post("/neo4j-sync-multi")
async def neo4j_sync_multi(
    payload: dict = Body(...),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """模式 A：多项目分别同步到 Neo4j（项目隔离）
    
    请求体: {"project_ids": ["uuid1", "uuid2", ...]}
    每个项目各自写入 Neo4j，节点带 project_id 属性，通过标签隔离。
    """
    from app.config import settings as s
    
    project_ids = payload.get("project_ids", [])
    if not project_ids:
        raise HTTPException(status_code=400, detail="请选择至少一个项目")
    
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            s.NEO4J_URL or "bolt://localhost:7687",
            auth=(s.NEO4J_USER or "neo4j", s.NEO4J_PASSWORD or "kg_neo4j_2026"),
        )
        driver.verify_connectivity()
    except ImportError:
        raise HTTPException(status_code=500, detail="Neo4j 驱动未安装")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Neo4j 连接失败: {str(e)}")
    
    total_rels = 0
    results = []
    with driver.session() as session:
        for pid in project_ids:
            project = db.query(Project).filter(Project.id == pid).first()
            if not project:
                results.append({"project_id": pid, "status": "error", "error": "项目不存在"})
                continue
            
            # 收集融合三元组
            triples_fused = db.query(TripleFused).filter(TripleFused.project_id == pid).all()
            entities = db.query(EntityFused).filter(EntityFused.project_id == pid).all()
            entity_map = {str(e.id): e.standard_name for e in entities}
            
            triples_data = []
            for t in triples_fused:
                subj = entity_map.get(str(t.subject_entity_id), "")
                obj = entity_map.get(str(t.object_entity_id), "")
                if subj and obj:
                    triples_data.append({"subject": subj, "predicate": t.predicate, "object": obj})
            
            # 降级：没有融合三元组则用 PASSED/FUSED 的 raw
            if not triples_data:
                raw_triples = db.query(TripleRaw).filter(
                    TripleRaw.project_id == pid,
                    TripleRaw.status.in_(["PASSED", "FUSED"]),
                ).all()
                triples_data = [
                    {"subject": t.subject, "predicate": t.predicate, "object": t.object}
                    for t in raw_triples
                ]
            
            if not triples_data:
                results.append({"project_id": pid, "status": "ok", "relations": 0, "note": "无三元组"})
                continue
            
            rel_count = 0
            for t in triples_data:
                session.run(
                    "MERGE (a:Entity {name: $subj, project_id: $pid}) "
                    "MERGE (b:Entity {name: $obj, project_id: $pid}) "
                    "MERGE (a)-[r:RELATION {predicate: $pred, project_id: $pid}]->(b)",
                    subj=t["subject"], obj=t["object"], pred=t["predicate"], pid=pid,
                )
                rel_count += 1
            
            total_rels += rel_count
            results.append({"project_id": pid, "status": "ok", "relations": rel_count})
    
    driver.close()
    return {
        "message": f"同步完成: {total_rels} 条关系",
        "total_relations": total_rels,
        "details": results,
    }


@router.post("/neo4j-sync-merged")
async def neo4j_sync_merged(
    payload: dict = Body(...),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """模式 B：跨项目融合后合并为统一图谱写入 Neo4j
    
    请求体: {"project_ids": ["uuid1", "uuid2", ...]}
    将多个项目的融合三元组合并去重后，作为统一图谱写入 Neo4j。
    """
    from app.config import settings as s
    
    project_ids = payload.get("project_ids", [])
    if not project_ids:
        raise HTTPException(status_code=400, detail="请选择至少一个项目")
    
    # 1. 收集所有项目的融合三元组
    all_triples = []
    entity_project_map = {}  # 实体名 -> [project_ids]
    
    for pid in project_ids:
        fused = db.query(TripleFused).filter(TripleFused.project_id == pid).all()
        for tf in fused:
            s_ent = db.query(EntityFused).filter(EntityFused.id == tf.subject_entity_id).first()
            o_ent = db.query(EntityFused).filter(EntityFused.id == tf.object_entity_id).first()
            if not s_ent or not o_ent:
                continue
            key = (s_ent.standard_name, tf.predicate, o_ent.standard_name)
            all_triples.append({
                "subject": s_ent.standard_name,
                "predicate": tf.predicate,
                "object": o_ent.standard_name,
                "project_id": pid,
                "key": key,
            })
            entity_project_map.setdefault(s_ent.standard_name, set()).add(pid)
            entity_project_map.setdefault(o_ent.standard_name, set()).add(pid)
    
    if not all_triples:
        return {"message": "没有融合三元组可同步", "synced": 0}
    
    # 2. 去重（同一 subject-predicate-object 只保留一条，合并 project_id）
    merged = {}
    for t in all_triples:
        k = t["key"]
        if k not in merged:
            merged[k] = {
                "subject": t["subject"],
                "predicate": t["predicate"],
                "object": t["object"],
                "project_ids": set(),
            }
        merged[k]["project_ids"].add(t["project_id"])
    
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            s.NEO4J_URL or "bolt://localhost:7687",
            auth=(s.NEO4J_USER or "neo4j", s.NEO4J_PASSWORD or "kg_neo4j_2026"),
        )
        driver.verify_connectivity()
        
        with driver.session() as session:
            # 先清除旧的 merged 图谱（仅删除 _Merged 标签的节点）
            session.run("MATCH (n:MergedEntity) DETACH DELETE n")
            
            node_count = 0
            rel_count = 0
            
            for k, t in merged.items():
                pids = list(t["project_ids"])
                pids_str = ",".join(pids)
                
                # 创建主语节点（带 MergedEntity 标签）
                session.run(
                    "MERGE (n:MergedEntity {name: $name}) "
                    "SET n.project_ids = $pids",
                    name=t["subject"], pids=pids_str,
                )
                node_count += 1
                
                # 创建宾语节点
                session.run(
                    "MERGE (n:MergedEntity {name: $name}) "
                    "SET n.project_ids = $pids",
                    name=t["object"], pids=pids_str,
                )
                node_count += 1
                
                # 创建关系
                session.run(
                    "MATCH (a:MergedEntity {name: $subj}), (b:MergedEntity {name: $obj}) "
                    "MERGE (a)-[r:RELATION {predicate: $pred}]->(b) "
                    "SET r.project_ids = $pids",
                    subj=t["subject"], obj=t["object"], pred=t["predicate"], pids=pids_str,
                )
                rel_count += 1
        
        driver.close()
        
        return {
            "message": f"合并同步完成: {len(merged)} 条关系",
            "synced": len(merged),
            "nodes_created": node_count,
            "relations_created": rel_count,
            "projects_merged": len(project_ids),
        }
    except ImportError:
        raise HTTPException(status_code=500, detail="Neo4j 驱动未安装")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Neo4j 操作失败: {str(e)}")
