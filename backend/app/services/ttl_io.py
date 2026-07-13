"""TTL (Turtle) 导入导出服务
兼容 Protégé 导出的 OWL/RDF Turtle 格式
依赖: rdflib
"""
from typing import List, Dict, Optional
from rdflib import Graph, Literal, URIRef, Namespace, BNode, RDF, RDFS, OWL
from rdflib.namespace import XSD


# 通用命名空间
SCHEMA = Namespace("http://schema.org/")
KG = Namespace("http://kg.example.org/entity/")
KG_REL = Namespace("http://kg.example.org/relation/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")


def ttl_to_triples(ttl_content: str) -> Dict:
    """解析 TTL (Turtle) 字符串 → 三元组 + 实体类型
    
    兼容 Protégé 导出格式:
      - owl:Class / rdfs:Class → 实体类型
      - rdf:Property / owl:ObjectProperty → 关系
      - 实例声明 (rdf:type) → 实体
      - 三元组断言 → 关系
    
    Returns:
        {"schemas": [...], "triples": [...], "entities": [...], "stats": {...}}
    """
    g = Graph()
    g.parse(data=ttl_content, format="turtle")
    
    schemas = []
    triples = []
    entities = []
    class_map = {}  # URI → 类型名
    entity_set = set()
    
    # ---- 第一遍: 收集类定义和标签 ----
    for s, p, o in g:
        # 类定义
        if p in (RDF.type, ) and o in (OWL.Class, RDFS.Class):
            class_name = _uri_to_name(s)
            class_map[str(s)] = class_name
            label = _get_label(g, s) or class_name
            schemas.append({
                "type": "class",
                "name": class_name,
                "label": label,
                "uri": str(s),
            })
        
        # 收集 rdfs:label
        if p == RDFS.label:
            subject_name = _uri_to_name(s)
            entity_set.add(subject_name)
    
    # ---- 第二遍: 收集属性/关系定义 ----
    for s, p, o in g:
        if p in (RDF.type, ) and o in (OWL.ObjectProperty, RDF.Property, OWL.DatatypeProperty):
            prop_name = _uri_to_name(s)
            label = _get_label(g, s) or prop_name
            
            # 找 domain/range
            domain = None
            range_ = None
            for s2, p2, o2 in g.triples((s, None, None)):
                if p2 == RDFS.domain:
                    domain = _uri_to_name(o2)
                elif p2 == RDFS.range:
                    range_ = _uri_to_name(o2)
            
            schemas.append({
                "type": "property",
                "name": prop_name,
                "label": label,
                "domain": domain,
                "range": range_,
                "uri": str(s),
            })
    
    # ---- 第三遍: 收集三元组（实例关系） ----
    for s, p, o in g:
        subj_name = _uri_to_name(s)
        pred_name = _uri_to_name(p)
        obj_name = _uri_to_name(o) if isinstance(o, URIRef) else str(o)
        obj_literal = None if isinstance(o, URIRef) else str(o)
        
        skip_preds = {
            str(RDF.type), str(RDFS.label), str(RDFS.comment),
            str(RDFS.domain), str(RDFS.range),
            str(OWL.versionInfo), str(OWL.imports),
        }
        if str(p) in skip_preds:
            continue
        
        # 字面值当属性
        if not isinstance(o, URIRef):
            triples.append({
                "subject": subj_name,
                "predicate": "has" + pred_name[0].upper() + pred_name[1:] if pred_name else "value",
                "object": obj_name,
                "confidence": 95.0,
                "source": "ttl-import",
            })
            continue
        
        # 跳过大类关系（class-subclass 等，保留用户三元组）
        if o in (OWL.Class, RDFS.Class, OWL.ObjectProperty, RDF.Property, OWL.DatatypeProperty, OWL.Thing):
            continue
        
        # URI 对 URI → 三元组
        triples.append({
            "subject": subj_name,
            "predicate": pred_name,
            "object": obj_name,
            "confidence": 95.0,
            "source": "ttl-import",
        })
    
    # ---- 统计 ----
    stats = {
        "total_triples_raw": len(list(g)),
        "classes": sum(1 for s in schemas if s["type"] == "class"),
        "properties": sum(1 for s in schemas if s["type"] == "property"),
        "triples_extracted": len(triples),
        "entities_found": len(entity_set),
    }
    
    return {
        "schemas": schemas,
        "triples": triples,
        "entities": sorted(entity_set),
        "stats": stats,
    }


def ttl_to_schema(ttl_content: str) -> Dict:
    """解析 OWL/Turtle 本体 → 与 parse_dsl 同构的 {namespace, entities, relations}

    用于把 Protégé 导出的 TTL 本体自动转换成「实体-关系-实体」Schema 约束。
    提取 owl:ObjectProperty 的 (domain -> range) 作为关系，
    rdfs:label 作为中文关系名 / 实体名。

    Returns: {"namespace": str, "entities": [...], "relations": [...]}
      relations 项: {subject_type, subject_label, predicate, predicate_label, object_type, object_label}
    """
    g = Graph()
    g.parse(data=ttl_content, format="turtle")

    # 本体命名空间（默认前缀 : 对应的 base）
    ontology_ns = None
    for pfx, ns in g.namespaces():
        if pfx == "":  # 默认前缀 :
            ontology_ns = str(ns)
            break
    if not ontology_ns:
        for pfx, ns in g.namespaces():
            s = str(ns)
            if s.startswith("http"):
                ontology_ns = s
                break
    if ontology_ns and ontology_ns.endswith("#"):
        ontology_ns = ontology_ns[:-1]

    EXTERNAL = {
        "http://www.w3.org/2002/07/owl",
        "http://www.w3.org/2000/01/rdf-schema",
        "http://www.w3.org/1999/02/22-rdf-syntax-ns",
        "http://www.w3.org/2001/XMLSchema",
        "http://purl.org/dc/elements/1.1",
    }

    def to_local(uri):
        """URI → 本体内的本地名；外部词汇（owl:/rdfs:/xsd:/dc:）返回 None"""
        s = str(uri)
        for ns in EXTERNAL:
            if s.startswith(ns):
                return None
        if ontology_ns and s.startswith(ontology_ns):
            tail = s[len(ontology_ns):]
            return tail.lstrip("#/") or None
        for sep in ("#", "/"):
            if sep in s:
                return s.rsplit(sep, 1)[-1] or None
        return None

    # 实体标签（owl:Class / rdfs:Class + rdfs:label）
    class_labels = {}
    for cls in g.subjects(RDF.type, OWL.Class):
        lbl = g.value(cls, RDFS.label)
        if lbl:
            class_labels[str(cls)] = str(lbl)
    for cls in g.subjects(RDF.type, RDFS.Class):
        lbl = g.value(cls, RDFS.label)
        if lbl:
            class_labels[str(cls)] = str(lbl)

    def expand(node):
        """展开 owl:unionOf 的 BNode 为成员列表；普通 URI 直接返回"""
        if isinstance(node, BNode):
            u = g.value(node, OWL.unionOf)
            if u is not None:
                return [m for m in g.items(u)]
        return [node]

    relations = []
    seen = set()
    for prop in g.subjects(RDF.type, OWL.ObjectProperty):
        pname = to_local(prop)
        if not pname:
            continue
        plabel = g.value(prop, RDFS.label)
        plabel = str(plabel) if plabel else pname

        domains = list(g.objects(prop, RDFS.domain))
        ranges = list(g.objects(prop, RDFS.range))
        if not domains or not ranges:
            continue

        dom_targets = []
        for d in domains:
            dom_targets += expand(d)
        rng_targets = []
        for r in ranges:
            rng_targets += expand(r)

        for dt in dom_targets:
            subj = to_local(dt)
            if not subj:
                continue
            for rt in rng_targets:
                obj = to_local(rt)
                if not obj:
                    continue
                key = (subj, pname, obj)
                if key in seen:
                    continue
                seen.add(key)
                relations.append({
                    "subject_type": subj,
                    "subject_label": class_labels.get(str(dt)) or subj,
                    "predicate": pname,
                    "predicate_label": plabel,
                    "object_type": obj,
                    "object_label": class_labels.get(str(rt)) or obj,
                })

    # 实体集合（用于 namespace / 计数）
    entities = []
    seen_ent = set()
    for uri, lbl in class_labels.items():
        nm = to_local(uri)
        if not nm or nm in seen_ent:
            continue
        seen_ent.add(nm)
        entities.append({"name": nm, "label": lbl})

    ns_name = ""
    for pfx, ns in g.namespaces():
        if pfx == "":
            ns_name = str(ns).rstrip("#/").rsplit("/", 1)[-1]
            break

    return {
        "namespace": ns_name or "ontology",
        "entities": entities,
        "relations": relations,
    }


def triples_to_ttl(triples: List[Dict], project_name: str = "kg") -> str:
    """三元组列表 → TTL Turtle 字符串 (Protégé 兼容)
    
    生成标准 Turtle 格式, Protégé 可直接导入。
    包含:
      - 前缀声明
      - 实体类定义
      - 实体实例
      - 关系断言
    """
    g = Graph()
    
    # 绑定前缀
    g.bind("rdf", RDF)
    g.bind("rdfs", RDFS)
    g.bind("owl", OWL)
    g.bind("xsd", XSD)
    g.bind("kg", KG)
    g.bind("kgrel", KG_REL)
    g.bind("schema", SCHEMA)
    g.bind("skos", SKOS)
    
    # 项目本体声明
    ontology_uri = KG[project_name.replace(" ", "_")]
    g.add((ontology_uri, RDF.type, OWL.Ontology))
    g.add((ontology_uri, RDFS.label, Literal(project_name)))
    
    # 收集所有实体
    entities = set()
    for t in triples:
        entities.add(t.get("subject", ""))
        entities.add(t.get("object", ""))
    entities.discard("")
    
    # 实体类定义
    entity_class = KG["Entity"]
    g.add((entity_class, RDF.type, OWL.Class))
    g.add((entity_class, RDFS.label, Literal("Entity")))
    
    # 实体实例
    for ent_name in entities:
        safe_name = _safe_uri_fragment(ent_name)
        ent_uri = KG[safe_name]
        g.add((ent_uri, RDF.type, entity_class))
        g.add((ent_uri, RDFS.label, Literal(ent_name)))
    
    # 关系定义
    relations = set()
    for t in triples:
        pred = t.get("predicate", "")
        if pred:
            relations.add(pred)
    
    for rel in relations:
        safe_rel = _safe_uri_fragment(rel)
        rel_uri = KG_REL[safe_rel]
        g.add((rel_uri, RDF.type, OWL.ObjectProperty))
        g.add((rel_uri, RDFS.label, Literal(rel)))
    
    # 三元组断言
    for t in triples:
        s_name = _safe_uri_fragment(t.get("subject", ""))
        p_name = _safe_uri_fragment(t.get("predicate", ""))
        o_name = _safe_uri_fragment(t.get("object", ""))
        
        if not s_name or not p_name or not o_name:
            continue
        
        s_uri = KG[s_name]
        p_uri = KG_REL[p_name]
        o_uri = KG[o_name]
        
        g.add((s_uri, p_uri, o_uri))
    
    return g.serialize(format="turtle")


def _uri_to_name(uri) -> str:
    """URI → 人类可读名称"""
    if not uri:
        return ""
    s = str(uri)
    # 取最后一个 # 或 / 后面的部分
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[-1]
    return s


def _get_label(g: Graph, uri) -> Optional[str]:
    """从图中获取 rdfs:label"""
    for _, _, label in g.triples((uri, RDFS.label, None)):
        return str(label)
    return None


def _safe_uri_fragment(name: str) -> str:
    """清理名称作为 URI 片段"""
    if not name:
        return "unnamed"
    import re
    # 替换非法字符
    safe = re.sub(r'[^\w\-.]', '_', name)
    # 确保不以数字开头
    if safe and safe[0].isdigit():
        safe = "e" + safe
    return safe or "unnamed"
