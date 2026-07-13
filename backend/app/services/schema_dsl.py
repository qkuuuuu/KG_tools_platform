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
from typing import List, Dict, Any


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
        # 格式: Name(中文标签): EntityType 或 中文标签(Name): EntityType
        ent_match = re.match(
            r"^([\w\u4e00-\u9fff]+)\s*\(([^)]+)\)\s*:\s*EntityType\s*$", trimmed
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

    return {
        "namespace": namespace,
        "entities": entities,
        "relations": relations,
    }


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
