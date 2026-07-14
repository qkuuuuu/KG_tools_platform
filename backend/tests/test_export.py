"""环节⑤：资产导出 —— Cypher / JSON-LD / TTL 生成（纯函数，需 rdflib）。"""
import json

from app.services.fusion.neo4j_exporter import generate_cypher_script, generate_jsonld
from app.services.ttl_io import triples_to_ttl, ttl_to_schema


SAMPLE_TTL = """
@prefix : <http://example.com/cement#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:Equipment a owl:Class ;
    rdfs:label "设备" .

:EquipmentComponent a owl:Class ;
    rdfs:label "设备部件" .

:hasComponent a owl:ObjectProperty ;
    rdfs:label "包含部件" ;
    rdfs:domain :Equipment ;
    rdfs:range :EquipmentComponent .
"""


def test_generate_cypher_script(triples):
    out = generate_cypher_script(triples, project_name="水泥")
    assert "回转窑" in out
    assert "包含部件" in out
    assert "MERGE" in out


def test_generate_jsonld(triples):
    out = generate_jsonld(triples, project_name="水泥")
    doc = json.loads(out)
    assert "@graph" in doc
    assert len(doc["@graph"]) >= 1


def test_triples_to_ttl(triples):
    out = triples_to_ttl(triples, project_name="水泥")
    assert "回转窑" in out
    assert "包含部件" in out


def test_ttl_to_schema():
    result = ttl_to_schema(SAMPLE_TTL)
    assert result["namespace"] == "cement"
    assert len(result["relations"]) >= 1
    r = result["relations"][0]
    assert r["subject_type"] == "Equipment"
    assert r["object_type"] == "EquipmentComponent"
    assert r["predicate"] == "hasComponent"
    assert r["subject_label"] == "设备"
    assert r["object_label"] == "设备部件"
    assert r["predicate_label"] == "包含部件"
