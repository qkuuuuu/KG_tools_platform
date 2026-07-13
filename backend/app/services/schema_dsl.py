"""Schema DSL 解析器
解析用户粘贴的 DSL 代码，生成实体类型+属性+关系约束

支持中英文混杂格式:
    namespace Cement1

    EquipmentComponent(设备部件): EntityType
        properties:
            description(描述): Text
            name(名称): Text
        relations:
            componentOf(属于设备): Equipment
            hasSparePart(需要备件): SparePart

也支持中文在前:
    设备部件(EquipmentComponent): EntityType
        properties:
            描述(description): Text
"""
import re
import uuid
from typing import List, Dict, Any
from app.models import SchemaConstraint


def parse_dsl(dsl: str) -> Dict[str, Any]:
    """解析 DSL 文本，返回 {namespace, entities, relations}"""
    if not dsl or not dsl.strip():
        return {"error": "DSL 内容为空", "namespace": "", "entities": [], "relations": []}

    namespace = ""
    entities: List[Dict] = []
    relations: List[Dict] = []
    entity_map: Dict[str, Dict] = {}
    current: Dict = None
    mode: str = None  # 'properties' | 'relations'

    lines = dsl.splitlines()
    for raw_line in lines:
        line = raw_line.replace("\t", "    ")
        trimmed = line.strip()

        # 跳过空行和注释
        if not trimmed or trimmed.startswith("#"):
            continue

        # namespace
        ns_match = re.match(r"^namespace\s+(\S+)", trimmed)
        if ns_match:
            namespace = ns_match.group(1)
            continue

        # properties: 段
        if trimmed == "properties:":
            mode = "properties"
            continue

        # relations: 段
        if trimmed == "relations:":
            mode = "relations"
            continue

        # 实体定义: 支持中英文混杂
        # 格式: Name(中文标签): EntityType|IndexType 或 中文标签(Name): EntityType|IndexType
        # IndexType 用于标记可向量索引的类型(如 AtomicQuery / KnowledgeUnit)
        ent_match = re.match(
            r"^([\w\u4e00-\u9fff]+)\s*\(([^)]+)\)\s*:\s*(?:EntityType|IndexType)\s*$", trimmed
        )
        if ent_match:
            name, label = ent_match.group(1), ent_match.group(2)
            # 判断哪个是英文标识符
            if not re.match(r"^[a-zA-Z]\w*$", name):
                if re.match(r"^[a-zA-Z]\w*$", label):
                    name, label = label, name
            current = {
                "name": name,
                "label": label,
                "namespace": namespace,
                "properties": [],
                "relations": [],
            }
            entities.append(current)
            entity_map[name] = current
            mode = None
            continue

        # 属性/关系行: 支持中英文混杂
        # 格式: name(中文): Type 或 中文(name): Type
        item_match = re.match(
            r"^([\w\u4e00-\u9fff]+)\s*\(([^)]+)\)\s*:\s*(\S+)\s*$", trimmed
        )
        if item_match and current is not None:
            item_name, item_label, item_type = (
                item_match.group(1),
                item_match.group(2),
                item_match.group(3),
            )
            # 判断哪个是英文标识符
            if not re.match(r"^[a-zA-Z]\w*$", item_name):
                if re.match(r"^[a-zA-Z]\w*$", item_label):
                    item_name, item_label = item_label, item_name

            if mode == "properties":
                current["properties"].append(
                    {"name": item_name, "label": item_label, "type": item_type}
                )
            elif mode == "relations":
                current["relations"].append(
                    {"name": item_name, "label": item_label, "target": item_type}
                )
                object_label = entity_map.get(item_type, {}).get("label", item_type)
                relations.append(
                    {
                        "subject_type": current["name"],
                        "subject_label": current["label"],
                        "predicate": item_name,
                        "predicate_label": item_label,
                        "object_type": item_type,
                        "object_label": object_label,
                    }
                )
                if item_type not in entity_map:
                    placeholder = {
                        "name": item_type,
                        "label": item_type,
                        "namespace": namespace,
                        "properties": [],
                        "relations": [],
                    }
                    entities.append(placeholder)
                    entity_map[item_type] = placeholder
            continue

    # 后处理: 用最终实体表回填中文标签
    # 处理「目标类型在 relations 之后才定义」的情况(避免占位实体遗留英文标签)
    for rel in relations:
        subj_ent = entity_map.get(rel["subject_type"])
        if subj_ent:
            rel["subject_label"] = subj_ent["label"]
        obj_ent = entity_map.get(rel["object_type"])
        if obj_ent:
            rel["object_label"] = obj_ent["label"]

    return {
        "namespace": namespace,
        "entities": entities,
        "relations": relations,
    }


def save_schema_constraints(db, project_id, relations):
    """写入 schema_constraints：先清空本项目旧约束再写入（与 import-dsl 一致）。

    relations 项需含: subject_type / predicate / object_type
    以及可选中文标签 subject_label / predicate_label / object_label。
    DSL 导入与 TTL 导入共用此函数，保证两路行为一致。
    """
    db.query(SchemaConstraint).filter(SchemaConstraint.project_id == project_id).delete()
    for rel in relations:
        db.add(SchemaConstraint(
            id=uuid.uuid4(),
            project_id=project_id,
            subject_type=rel.get("subject_type", ""),
            predicate=rel.get("predicate", ""),
            object_type=rel.get("object_type", ""),
            subject_label=rel.get("subject_label"),
            predicate_label=rel.get("predicate_label"),
            object_label=rel.get("object_label"),
        ))
    db.commit()


if __name__ == "__main__":
    sample = """namespace Cement1

EquipmentComponent(设备部件): EntityType
\tproperties:
\t\tdescription(描述): Text
\t\tname(名称): Text
\trelations:
\t\tcomponentOf(属于设备): Equipment
"""
    import json
    result = parse_dsl(sample)
    print(json.dumps(result, ensure_ascii=False, indent=2))
