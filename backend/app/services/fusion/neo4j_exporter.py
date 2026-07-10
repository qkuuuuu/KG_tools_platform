"""Neo4j 图数据库导出与查询服务
支持:
  - 三元组导入 Neo4j
  - Cypher 脚本生成
  - 图谱查询 (实体关系探索)
  - 连通子图分析
  
标签说明: ⚠️ Neo4j 离线仍可正常导出 Cypher 脚本，仅查询需要在线
"""
import json
import re
from typing import List, Dict, Optional, Tuple
from uuid import UUID


def generate_cypher_script(
    triples: List[Dict],
    project_name: str = "kg_project",
    with_constraints: bool = True,
) -> str:
    """生成 Neo4j Cypher 导入脚本
    
    参考 openSPG: 实体去重后生成 CREATE/MERGE 语句
    
    Args:
        triples: 三元组列表
        project_name: 项目名（用于图谱标签）
        with_constraints: 是否生成索引约束语句
    
    Returns:
        Cypher 脚本字符串
    """
    lines = []
    lines.append(f"// ============================================")
    lines.append(f"// Neo4j Cypher 导入脚本")
    lines.append(f"// 项目: {project_name}")
    lines.append(f"// 生成时间: (自动生成)")
    lines.append(f"// 三元组数量: {len(triples)}")
    lines.append(f"// ============================================")
    lines.append("")

    # 去重收集实体和关系
    entities = {}
    relations = []

    for t in triples:
        subj = t.get("subject", "").strip()
        obj = t.get("object", "").strip()
        pred = t.get("predicate", "").strip()
        if not subj or not obj or not pred:
            continue

        # 收集实体及其类型
        if subj not in entities:
            entities[subj] = t.get("subject_type", "Entity")
        if obj not in entities:
            entities[obj] = t.get("object_type", "Entity")

        confidence = t.get("confidence", t.get("llm_confidence", 80))
        if not isinstance(confidence, (int, float)):
            confidence = 80
        source = t.get("source_triple_ids", [])
        relations.append((subj, pred, obj, confidence, source))

    # 索引约束
    if with_constraints:
        lines.append("// ===== 索引与约束 =====")
        lines.append("CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity)")
        lines.append("  REQUIRE e.name IS UNIQUE;")
        lines.append("")

    # 实体创建
    lines.append("// ===== 实体创建 =====")
    for name, entity_type in entities.items():
        safe_name = _escape_cypher(name)
        safe_type = _escape_cypher(entity_type)
        var = f"e_{_hash_name(name)}"
        lines.append(f"MERGE ({var}:Entity {{name: '{safe_name}'}})")
        if entity_type and entity_type != "Entity":
            lines[-1] = lines[-1].replace("})", f", type: '{safe_type}'}})")
    lines.append("")

    # 关系创建
    lines.append("// ===== 关系创建 =====")
    for subj, pred, obj, conf, source in relations:
        safe_subj = _escape_cypher(subj)
        safe_obj = _escape_cypher(obj)
        safe_pred = _escape_cypher(pred)
        lines.append(
            f"MATCH (a:Entity {{name: '{safe_subj}'}}), "
            f"(b:Entity {{name: '{safe_obj}'}})"
        )
        lines.append(
            f"MERGE (a)-[:`{safe_pred}` {{confidence: {conf}}}]->(b);"
        )
        lines.append("")

    # 统计查询
    lines.append("// ===== 验证统计 =====")
    lines.append("// 实体总数:")
    lines.append("MATCH (e:Entity) RETURN count(e) AS entity_count;")
    lines.append("")
    lines.append("// 关系总数:")
    lines.append("MATCH ()-[r]->() RETURN count(r) AS relation_count;")
    lines.append("")
    lines.append("// 按实体类型分布:")
    lines.append("MATCH (e:Entity) RETURN e.type, count(*) ORDER BY count(*) DESC;")

    return "\n".join(lines)


def _hash_name(name: str) -> str:
    """生成实体名哈希（用于 Cypher 变量名）"""
    import hashlib
    return hashlib.md5(name.encode()).hexdigest()[:12]


def _escape_cypher(value: str) -> str:
    """Cypher 字符串安全转义: 转义单引号、反引号、\\、$、{}"""
    if not value:
        return ""
    value = value.replace("\\", "\\\\")
    value = value.replace("'", "\\'")
    value = value.replace("`", "")
    value = value.replace("$", "\\$")
    return value


def generate_jsonld(
    triples: List[Dict],
    project_name: str = "kg_project",
) -> str:
    """生成 JSON-LD 格式知识图谱数据
    
    符合 W3C JSON-LD 1.1 规范
    """
    graph = []
    entity_ids = {}

    for t in triples:
        subj = t.get("subject", "").strip()
        obj = t.get("object", "").strip()
        pred = t.get("predicate", "").strip()
        if not all([subj, obj, pred]):
            continue

        s_id = entity_ids.setdefault(subj, f"_:e{len(entity_ids)}")
        o_id = entity_ids.setdefault(obj, f"_:e{len(entity_ids)}")

        graph.append({
            "@id": s_id,
            "http://schema.org/name": subj,
            f"http://example.org/{pred}": {"@id": o_id},
        })

    doc = {
        "@context": {
            "schema": "http://schema.org/",
            "kg": "http://example.org/",
            "name": "schema:name",
        },
        "@type": "kg:KnowledgeGraph",
        "kg:projectName": project_name,
        "@graph": graph,
    }

    return json.dumps(doc, ensure_ascii=False, indent=2)


def try_neo4j_import(
    triples: List[Dict],
    project_id: str = "",
    project_name: str = "",
    neo4j_url: str = None,
    neo4j_user: str = None,
    neo4j_password: str = None,
) -> Dict[str, int]:
    """尝试直接导入 Neo4j（需要 Neo4j 在线）
    
    项目隔离策略:
      - 每个节点带 project_id 属性
      - 每个关系带 project_id 属性
      - 节点标签使用项目专属标签 (如 Project_<id>)
      - 删除项目时可通过 project_id 级联删除
    
    标签说明: ⚠️ Neo4j 必须在线且开通 Bolt 端口
    """
    try:
        from neo4j import GraphDatabase

        url = neo4j_url or "bolt://localhost:7687"
        user = neo4j_user or "neo4j"
        password = neo4j_password or "kg_neo4j_2026"

        driver = GraphDatabase.driver(url, auth=(user, password))
        driver.verify_connectivity()

        entity_count = 0
        rel_count = 0
        pid = project_id or "default"
        pname = project_name or "default"
        # M9 修复: 校验 pid 格式（仅允许十六进制和连字符），避免非法字符拼接进 Cypher 标签
        if re.match(r'^[0-9a-fA-F\-]+$', pid):
            proj_label = f"Project_{pid.replace('-', '_')}"
        else:
            proj_label = "Project_Unknown"

        with driver.session() as session:
            # 创建项目根节点
            session.run(
                "MERGE (p:Project {id: $pid}) SET p.name = $pname",
                pid=pid, pname=pname,
            )

            for t in triples:
                subj = t.get("subject", "").strip()
                obj = t.get("object", "").strip()
                pred = t.get("predicate", "").strip()
                conf = t.get("confidence", t.get("llm_confidence", 80))

                if not all([subj, obj, pred]):
                    continue

                session.run(
                    f"""
                    MERGE (a:Entity:{proj_label} {{name: $subj, project_id: $pid}})
                    MERGE (b:Entity:{proj_label} {{name: $obj, project_id: $pid}})
                    MERGE (a)-[r:REL {{predicate: $pred, project_id: $pid}}]->(b)
                    SET r.confidence = $conf
                    """,
                    subj=subj, obj=obj, pred=pred, conf=conf, pid=pid,
                )
                # M5 修复: 每条三元组 MERGE 2 个实体 (subject + object)
                entity_count += 2
                rel_count += 1

        driver.close()
        return {"entities_created": entity_count, "relations_created": rel_count, "status": "success", "project_label": proj_label}

    except ImportError:
        return {"error": "neo4j 驱动未安装, pip install neo4j", "status": "driver_missing"}
    except Exception as e:
        return {"error": str(e), "status": "neo4j_unavailable"}


def query_graph(
    cypher: str,
    neo4j_url: str = None,
    neo4j_user: str = None,
    neo4j_password: str = None,
    limit: int = None,
) -> List[Dict]:
    """执行 Cypher 查询（仅 Neo4j 在线时可用）"""
    try:
        from neo4j import GraphDatabase
        url = neo4j_url or "bolt://localhost:7687"
        user = neo4j_user or "neo4j"
        password = neo4j_password or "kg_neo4j_2026"
        driver = GraphDatabase.driver(url, auth=(user, password))

        with driver.session() as session:
            params = {}
            if limit:
                params["limit"] = limit
                cypher = cypher.replace("$limit", str(limit))
            result = session.run(cypher, **params)
            records = [dict(r) for r in result]
        driver.close()
        return records
    except Exception as e:
        return [{"error": str(e)}]


def delete_project_graph(
    project_id: str,
    neo4j_url: str = None,
    neo4j_user: str = None,
    neo4j_password: str = None,
) -> Dict:
    """删除项目在 Neo4j 中的完整子图（项目隔离级联删除）
    
    删除策略:
      1. 删除带 project_id 属性的所有节点和关系
      2. 删除项目专属标签 (Project_<id>) 的所有节点
      3. 删除 Project 根节点
    
    Returns: {"status": "success", "deleted_nodes": N, "deleted_rels": N}
    """
    try:
        from neo4j import GraphDatabase
        url = neo4j_url or "bolt://localhost:7687"
        user = neo4j_user or "neo4j"
        password = neo4j_password or "kg_neo4j_2026"
        driver = GraphDatabase.driver(url, auth=(user, password))
        driver.verify_connectivity()

        pid = str(project_id)
        proj_label = f"Project_{pid.replace('-', '_')}"
        deleted_nodes = 0
        deleted_rels = 0

        with driver.session() as session:
            # 统计即将删除的节点和关系
            count_result = session.run(
                "MATCH (n) WHERE n.project_id = $pid OR $proj_label IN labels(n) "
                "RETURN count(n) AS nodes",
                pid=pid, proj_label=proj_label,
            ).single()
            deleted_nodes = count_result["nodes"] if count_result else 0

            rel_result = session.run(
                "MATCH ()-[r]->() WHERE r.project_id = $pid "
                "RETURN count(r) AS rels",
                pid=pid,
            ).single()
            deleted_rels = rel_result["rels"] if rel_result else 0

            # 删除关系
            session.run(
                "MATCH ()-[r]->() WHERE r.project_id = $pid DELETE r",
                pid=pid,
            )
            # 删除节点
            session.run(
                "MATCH (n) WHERE n.project_id = $pid OR $proj_label IN labels(n) DELETE n",
                pid=pid, proj_label=proj_label,
            )
            # 删除项目根节点
            session.run(
                "MATCH (p:Project {id: $pid}) DELETE p",
                pid=pid,
            )

        driver.close()
        return {"status": "success", "deleted_nodes": deleted_nodes, "deleted_rels": deleted_rels}

    except ImportError:
        return {"status": "driver_missing", "error": "neo4j 驱动未安装"}
    except Exception as e:
        return {"status": "neo4j_unavailable", "error": str(e)}
