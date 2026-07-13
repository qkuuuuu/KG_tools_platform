"""导出路由 - 多格式导出 + Neo4j 同步 + TTL 导入导出
标签: ⚠️ Neo4j 同步需要 Neo4j 在线
"""
import csv
import json
import io
import re
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Body, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID
from app.database import get_db
from app.models import TripleFused, EntityFused, Project, TripleRaw, User, SchemaConstraint
from app.utils.security import get_current_user, require_admin
from app.services.fusion.neo4j_exporter import (
    generate_cypher_script, generate_jsonld, try_neo4j_import, query_graph,
)
from app.services.ttl_io import ttl_to_schema, triples_to_ttl
from app.services.schema_dsl import save_schema_constraints

router = APIRouter()


def _entity_group(name: str) -> str:
    """根据实体名推断分组（用于图谱着色）"""
    if not name:
        return "Unknown"
    # 按实体名特征分类
    lower = name.lower()
    if any(kw in lower for kw in ["公司", "集团", "corp", "inc", "ltd"]):
        return "Organization"
    if any(kw in lower for kw in ["设备", "部件", "equipment", "component", "pump", "motor", "valve"]):
        return "Equipment"
    if any(kw in lower for kw in ["故障", "fault", "failure", "error"]):
        return "Fault"
    if any(kw in lower for kw in ["人", "person", "engineer", "manager"]):
        return "Person"
    if any(kw in lower for kw in ["地", "city", "country", "location"]):
        return "Location"
    if any(kw in lower for kw in ["材料", "material", "原料", "product"]):
        return "Material"
    if any(kw in lower for kw in ["工艺", "process", "工序"]):
        return "Process"
    # 默认: 首字母大写分组（减少颜色种类）
    return name[0].upper() if name[0].isalpha() else "#"


@router.get("/multi-project-graph")
async def get_multi_project_graph(
    project_ids: str = Query(..., description="逗号分隔的项目ID列表"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """多项目图谱融合查询
    
    将多个项目的三元组融合为一个图谱，用于跨项目知识关联分析。
    """
    pid_list = [UUID(p.strip()) for p in project_ids.split(",") if p.strip()]
    if not pid_list:
        raise HTTPException(status_code=400, detail="至少需要一个项目ID")

    nodes_map = {}
    edges = []
    
    for pid in pid_list:
        project = db.query(Project).filter(Project.id == pid).first()
        if not project:
            continue
        project_label = project.name
        
        triples_fused = db.query(TripleFused).filter(TripleFused.project_id == pid).all()
        entities = db.query(EntityFused).filter(EntityFused.project_id == pid).all()
        entity_map = {str(e.id): e for e in entities}
        
        if triples_fused:
            for t in triples_fused:
                s_ent = entity_map.get(str(t.subject_entity_id))
                o_ent = entity_map.get(str(t.object_entity_id))
                s_name = s_ent.standard_name if s_ent else str(t.subject_entity_id)[:8]
                o_name = o_ent.standard_name if o_ent else str(t.object_entity_id)[:8]
                
                if s_name not in nodes_map:
                    nodes_map[s_name] = {"id": s_name, "label": s_name, "group": _entity_group(s_name), "projects": [project_label]}
                else:
                    if project_label not in nodes_map[s_name]["projects"]:
                        nodes_map[s_name]["projects"].append(project_label)
                
                if o_name not in nodes_map:
                    nodes_map[o_name] = {"id": o_name, "label": o_name, "group": _entity_group(o_name), "projects": [project_label]}
                else:
                    if project_label not in nodes_map[o_name]["projects"]:
                        nodes_map[o_name]["projects"].append(project_label)
                
                edges.append({
                    "source": s_name, "target": o_name,
                    "label": t.predicate,
                    "project": project_label,
                    "confidence": 85,
                    "source_count": len(t.source_triple_ids) if t.source_triple_ids else 1,
                })
        else:
            raw_triples = db.query(TripleRaw).filter(
                TripleRaw.project_id == pid,
                TripleRaw.status.in_(["PASSED", "FUSED"]),
            ).all()
            for t in raw_triples:
                s_name = t.subject[:50]
                o_name = t.object[:50]
                if s_name not in nodes_map:
                    nodes_map[s_name] = {"id": s_name, "label": s_name, "group": _entity_group(s_name), "projects": [project_label]}
                else:
                    if project_label not in nodes_map[s_name]["projects"]:
                        nodes_map[s_name]["projects"].append(project_label)
                if o_name not in nodes_map:
                    nodes_map[o_name] = {"id": o_name, "label": o_name, "group": _entity_group(o_name), "projects": [project_label]}
                else:
                    if project_label not in nodes_map[o_name]["projects"]:
                        nodes_map[o_name]["projects"].append(project_label)
                edges.append({
                    "source": s_name, "target": o_name,
                    "label": t.predicate,
                    "project": project_label,
                    "confidence": t.llm_confidence or 80,
                })
    
    shared_nodes = [n for n in nodes_map.values() if len(n.get("projects", [])) > 1]
    
    return {
        "nodes": list(nodes_map.values()),
        "edges": edges,
        "stats": {
            "node_count": len(nodes_map),
            "edge_count": len(edges),
            "shared_node_count": len(shared_nodes),
            "project_count": len(pid_list),
        },
        "shared_nodes": shared_nodes,
    }


@router.get("/{project_id}/graph-data")
async def get_graph_data(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """获取图谱可视化数据 (nodes + edges)
    
    前端可用 AntV G6 / vis-network / ECharts 渲染。
    返回:
      - nodes: [{id, label, group}]
      - edges: [{source, target, label, confidence}]
    """
    triples_fused = db.query(TripleFused).filter(TripleFused.project_id == project_id).all()
    entities = db.query(EntityFused).filter(EntityFused.project_id == project_id).all()
    entity_map = {str(e.id): e for e in entities}

    nodes_map = {}
    edges = []

    # 1) 先加载已融合的三元组
    if triples_fused:
        for t in triples_fused:
            s_ent = entity_map.get(str(t.subject_entity_id))
            o_ent = entity_map.get(str(t.object_entity_id))
            s_name = s_ent.standard_name if s_ent else str(t.subject_entity_id)[:8]
            o_name = o_ent.standard_name if o_ent else str(t.object_entity_id)[:8]
            
            if s_name not in nodes_map:
                nodes_map[s_name] = {"id": s_name, "label": s_name, "group": _entity_group(s_ent.standard_name if s_ent else s_name)}
            if o_name not in nodes_map:
                nodes_map[o_name] = {"id": o_name, "label": o_name, "group": _entity_group(o_ent.standard_name if o_ent else o_name)}
            
            edges.append({
                "source": s_name, "target": o_name,
                "label": t.predicate,
                "confidence": 85,
                "source_count": len(t.source_triple_ids) if t.source_triple_ids else 1,
                "status": "FUSED",
            })
    
    # 2) 再加载 TripleRaw 中已通过审核但未融合的三元组
    #    只加载 PASSED 和 FUSED 状态，不包含 PENDING（待审核）和 REJECTED（已拒绝）
    raw_triples = db.query(TripleRaw).filter(
        TripleRaw.project_id == project_id,
        TripleRaw.status.in_(["PASSED", "FUSED"]),
    ).all()
    fused_keys = set()
    for e in edges:
        fused_keys.add((e["source"], e["label"], e["target"]))
    for t in raw_triples:
        s_name = t.subject[:50]
        o_name = t.object[:50]
        key = (s_name, t.predicate, o_name)
        if key in fused_keys:
            continue
        if s_name not in nodes_map:
            nodes_map[s_name] = {"id": s_name, "label": s_name, "group": _entity_group(s_name)}
        if o_name not in nodes_map:
            nodes_map[o_name] = {"id": o_name, "label": o_name, "group": _entity_group(o_name)}
        edges.append({
            "source": s_name, "target": o_name,
            "label": t.predicate,
            "confidence": t.llm_confidence or 80,
            "status": t.status,
        })

    return {
        "nodes": list(nodes_map.values()),
        "edges": edges,
        "stats": {
            "node_count": len(nodes_map),
            "edge_count": len(edges),
        }
    }


@router.get("/{project_id}")
async def export_project(
    project_id: UUID,
    format: str = Query(default="json", pattern="^(csv|json|cypher|jsonld|ttl)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """导出项目图谱资产
    
    支持格式:
      - csv: 标准 CSV
      - json: JSON 三元组数组
      - cypher: Neo4j Cypher 导入脚本
      - jsonld: W3C JSON-LD 格式
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 收集所有已融合的三元组
    triples_fused = db.query(TripleFused).filter(TripleFused.project_id == project_id).all()
    entities = db.query(EntityFused).filter(EntityFused.project_id == project_id).all()
    entity_map = {str(e.id): e.standard_name for e in entities}

    # 构建三元组数据结构
    triples_data = []
    for t in triples_fused:
        s = entity_map.get(str(t.subject_entity_id), "")
        o = entity_map.get(str(t.object_entity_id), "")
        triples_data.append({
            "subject": s,
            "predicate": t.predicate,
            "object": o,
            "confidence": 85,
            "source_count": len(t.source_triple_ids) if t.source_triple_ids else 1,
            "fused_at": str(t.fused_at) if t.fused_at else "",
        })

    # 如果没有融合数据，从 triples_raw 读取
    if not triples_data:
        raw_triples = db.query(TripleRaw).filter(
            TripleRaw.project_id == project_id,
            TripleRaw.status.in_(["PASSED", "FUSED"]),
        ).all()
        triples_data = [
            {
                "subject": t.subject, "predicate": t.predicate, "object": t.object,
                "confidence": t.llm_confidence or 80, "fused_at": "",
            }
            for t in raw_triples
        ]

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["subject", "predicate", "object", "confidence"])
        for t in triples_data:
            writer.writerow([t["subject"], t["predicate"], t["object"], t.get("confidence", "")])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={project.name}_kg.csv"},
        )

    elif format == "json":
        return Response(
            content=json.dumps(triples_data, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={project.name}_kg.json"},
        )

    elif format == "jsonld":
        content = generate_jsonld(triples_data, project.name)
        return Response(
            content=content,
            media_type="application/ld+json",
            headers={"Content-Disposition": f"attachment; filename={project.name}_kg.jsonld"},
        )

    elif format == "ttl":
        content = triples_to_ttl(triples_data, project.name)
        return Response(
            content=content,
            media_type="text/turtle",
            headers={"Content-Disposition": f"attachment; filename={project.name}_kg.ttl"},
        )

    else:  # cypher
        content = generate_cypher_script(triples_data, project.name)
        return Response(
            content=content,
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename={project.name}_kg.cypher"},
        )


@router.post("/{project_id}/neo4j-sync")
async def sync_to_neo4j(
    project_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """同步融合后的知识图谱到 Neo4j
    
    标签说明: ⚠️ Neo4j 必须在线且开通 Bolt 端口(7687)
    """
    from app.config import settings as s

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 收集所有三元组
    triples_fused = db.query(TripleFused).filter(TripleFused.project_id == project_id).all()
    entities = db.query(EntityFused).filter(EntityFused.project_id == project_id).all()
    entity_map = {str(e.id): e.standard_name for e in entities}

    triples_data = []
    for t in triples_fused:
        subj = entity_map.get(str(t.subject_entity_id), "")
        obj = entity_map.get(str(t.object_entity_id), "")
        triples_data.append({"subject": subj, "predicate": t.predicate, "object": obj, "confidence": 85})

    if not triples_data:
        raw_triples = db.query(TripleRaw).filter(
            TripleRaw.project_id == project_id,
            TripleRaw.status.in_(["PASSED", "FUSED"]),
        ).all()
        triples_data = [
            {"subject": t.subject, "predicate": t.predicate, "object": t.object, "confidence": t.llm_confidence or 80}
            for t in raw_triples
        ]

    result = try_neo4j_import(
        triples_data,
        project_id=str(project_id),
        project_name=project.name,
        neo4j_url=s.NEO4J_URL,
        neo4j_user=s.NEO4J_USER,
        neo4j_password=s.NEO4J_PASSWORD,
    )

    if result.get("status") == "success":
        return {
            "message": "Neo4j 同步成功",
            "relations": result.get("relations_created", 0),
        }
    elif result.get("status") == "driver_missing":
        return {
            "message": "Neo4j 驱动未安装，已生成 Cypher 脚本供手动导入",
            "note": "pip install neo4j",
        }
    else:
        return {
            "message": "Neo4j 不可用，已生成 Cypher 脚本可手动导入",
            "error": result.get("error", ""),
        }


@router.post("/{project_id}/neo4j-query")
async def neo4j_query(
    project_id: UUID,
    cypher: str = Query(..., description="Cypher 查询语句（仅支持只读查询）"),
    _: User = Depends(require_admin),
):
    """执行 Neo4j Cypher 只读查询（需 admin 权限）

    安全限制: 仅允许 MATCH / RETURN / WITH / ORDER BY / LIMIT / SKIP / WHERE / COUNT / DISTINCT 等只读操作。
    禁止 CREATE / DELETE / SET / REMOVE / MERGE / DROP / CALL 等写操作。

    示例:
      MATCH (e:Entity) RETURN e.name LIMIT 20
      MATCH (a:Entity)-[r]->(b:Entity) RETURN a.name, type(r), b.name LIMIT 50
    """
    # 只读校验: 拒绝任何写/删/改操作
    # 先剥离字符串字面量，防止字面量中包含关键词导致误判或绕过
    cypher_no_strings = re.sub(r"'[^']*'", "''", cypher.upper().strip())
    cypher_no_strings = re.sub(r'"[^"]*"', '""', cypher_no_strings)
    forbidden_keywords = [
        "CREATE", "DELETE", "DETACH", "SET", "REMOVE", "MERGE",
        "DROP", "CALL", "FOREACH",
    ]
    for kw in forbidden_keywords:
        if re.search(r'\b' + kw + r'\b', cypher_no_strings):
            raise HTTPException(
                status_code=403,
                detail=f"安全限制: 只读查询不允许包含 '{kw}' 操作"
            )
    # 也检查 LOAD CSV 和 PERIODIC COMMIT（多词关键词）
    if re.search(r'\bLOAD\s+CSV\b', cypher_no_strings) or re.search(r'\bPERIODIC\s+COMMIT\b', cypher_no_strings):
        raise HTTPException(status_code=403, detail="安全限制: 只读查询不允许 LOAD CSV / PERIODIC COMMIT")
    # 必须以 MATCH 或 WITH 开头（只读查询的典型入口）
    if not (cypher_no_strings.startswith("MATCH") or cypher_no_strings.startswith("WITH")):
        raise HTTPException(
            status_code=403,
            detail="安全限制: 查询必须以 MATCH 或 WITH 开头"
        )

    from app.config import settings as s
    results = query_graph(cypher, s.NEO4J_URL, s.NEO4J_USER, s.NEO4J_PASSWORD)
    return {"results": results, "query": cypher}


# ====== TTL 导入导出 ======

@router.post("/{project_id}/import-ttl")
async def import_ttl(
    project_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """导入 Protégé TTL (Turtle) 本体文件，自动解析为「实体-关系-实体」Schema 约束

    前端通过文件上传（.ttl）调用；后端用 rdflib 解析 OWL ObjectProperty，
    提取 (domain -> range) 作为关系，rdfs:label 作为中文关系名 / 实体名，
    写入 schema_constraints 表（与 DSL 导入一致）。会先清空本项目旧约束再写入。
    """
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("utf-8", errors="ignore")
    if not content.strip():
        raise HTTPException(status_code=400, detail="TTL 文件内容为空")

    try:
        result = ttl_to_schema(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"TTL 解析失败: {str(e)}")

    save_schema_constraints(db, project_id, result["relations"])
    return {
        "message": f"导入成功: {len(result['relations'])} 条关系约束, {len(result['entities'])} 个实体类型",
        "relations_imported": len(result["relations"]),
        "entities_count": len(result["entities"]),
        "namespace": result["namespace"],
    }


# [已上移到 /{project_id} 之前避免路由吞掉]
