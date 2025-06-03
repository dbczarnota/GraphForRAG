# config/cypher_queries.py

# --- Constants for Schema Management --
EXCLUDED_PROPERTIES_FOR_DYNAMIC_BTREE = [
    'uuid', 'name', 'content', 'content_embedding', 'created_at', 
    'source_description', 'chunk_number', 'processed_at', 
    'entity_count', 'relationship_count',
    'normalized_name', 'label', 'description', 'name_embedding', 'description_embedding'
]

SUITABLE_BTREE_TYPES = [
    "STRING", "INTEGER", "FLOAT", "BOOLEAN", 
    "DATE", "DATETIME", "LOCAL_DATETIME", "TIME", "LOCAL_TIME"
]

# --- Node and Relationship Creation/Update Queries ---
MERGE_SOURCE_NODE = """
MERGE (source:Source {name: $source_identifier_param})
ON CREATE SET
    source.uuid = $source_uuid_param,
    source.created_at = $created_at_ts_param,
    source.content = $source_content_param
SET source += $dynamic_properties_param
RETURN source.uuid AS source_uuid, source.name AS source_name, source.content as source_content
"""

ADD_CHUNK_AND_LINK_TO_SOURCE = """
MATCH (source:Source {uuid: $source_node_uuid_param})
WITH source

MERGE (chunk:Chunk {uuid: $chunk_uuid_param})
ON CREATE SET
    chunk.content = $chunk_content_param,
    chunk.source_description = $source_identifier_param,
    chunk.created_at = $created_at_ts_param,
    chunk.processed_at = null,
    chunk.entity_count = 0,
    chunk.relationship_count = 0
ON MATCH SET
    chunk.content = $chunk_content_param,
    chunk.source_description = $source_identifier_param
SET chunk += $dynamic_chunk_properties_param
WITH chunk, source, $chunk_number_param_for_rel AS currentChunkNumberForRel, $created_at_ts_param AS ts

MERGE (chunk)-[r_bts:BELONGS_TO_SOURCE]->(source)
ON CREATE SET r_bts.created_at = ts
WITH chunk, source, currentChunkNumberForRel

CALL apoc.do.when(currentChunkNumberForRel > 1 AND currentChunkNumberForRel IS NOT NULL,
    'MATCH (prev_chunk:Chunk {source_description: $sourceNameParam, chunk_number: $prevChunkNumberParam})
     MATCH (current_chunk_for_rel:Chunk {uuid: $currentChunkUuidParam})
     MERGE (prev_chunk)-[r_nc:NEXT_CHUNK]->(current_chunk_for_rel)
     ON CREATE SET r_nc.created_at = datetime()
     RETURN prev_chunk, r_nc',
    'RETURN null AS prev_chunk, null AS r_nc',
    {
        sourceNameParam: source.name,
        prevChunkNumberParam: currentChunkNumberForRel - 1,
        currentChunkUuidParam: chunk.uuid
    }
) YIELD value

RETURN chunk.uuid AS chunk_uuid,
       value.prev_chunk AS prev_chunk_linked,
       value.r_nc AS next_chunk_rel_created
"""

SET_CHUNK_CONTENT_EMBEDDING = """
MATCH (c:Chunk {uuid: $chunk_uuid_param})
CALL db.create.setNodeVectorProperty(c, 'content_embedding', $embedding_vector_param)
RETURN $chunk_uuid_param AS uuid_processed 
"""

SET_SOURCE_CONTENT_EMBEDDING = """
MATCH (s:Source {uuid: $source_uuid_param})
CALL db.create.setNodeVectorProperty(s, 'content_embedding', $embedding_vector_param)
RETURN $source_uuid_param AS uuid_processed
"""

MERGE_ENTITY_NODE = """
MERGE (entity:Entity {normalized_name: $normalized_name_param, label: $label_param}) 
ON CREATE SET 
    entity.uuid = $uuid_param, 
    entity.name = $name_param, 
    entity.normalized_name = $normalized_name_param,
    entity.label = $label_param,
    entity.description = $description_param,
    entity.created_at = $created_at_ts_param,
    entity.processed_at = null,
    entity.updated_at = $created_at_ts_param
ON MATCH SET 
    entity.updated_at = $created_at_ts_param
RETURN entity.uuid AS entity_uuid, 
       entity.name AS current_entity_name, 
       entity.description AS current_entity_description,
       entity.label AS entity_label 
"""

UPDATE_ENTITY_NAME = """
MATCH (entity:Entity {uuid: $uuid_param})
SET entity.name = $new_name_param,
    entity.updated_at = $updated_at_param 
RETURN entity.uuid AS entity_uuid, entity.name AS updated_entity_name
"""

UPDATE_ENTITY_DESCRIPTION = """
MATCH (entity:Entity {uuid: $uuid_param})
SET entity.description = $new_description_param,
    entity.updated_at = $updated_at_param
RETURN entity.uuid AS entity_uuid, entity.description AS updated_entity_description
"""

GET_ENTITY_DETAILS_FOR_UPDATE = """
MATCH (entity:Entity {uuid: $uuid_param})
RETURN entity.uuid AS entity_uuid, 
       entity.name AS current_entity_name, 
       entity.description AS current_entity_description,
       entity.label AS entity_label 
"""

LINK_CHUNK_TO_ENTITY = """
MATCH (chunk:Chunk {uuid: $chunk_uuid_param})
MATCH (entity:Entity {uuid: $entity_uuid_param})
MERGE (chunk)-[r:MENTIONS_ENTITY]->(entity)
ON CREATE SET r.created_at = $created_at_ts_param
RETURN type(r) AS relationship_type
"""

SET_ENTITY_NAME_EMBEDDING = """
MATCH (e:Entity {uuid: $entity_uuid_param})
CALL db.create.setNodeVectorProperty(e, 'name_embedding', $embedding_vector_param)
RETURN $entity_uuid_param AS uuid_processed
"""

SET_ENTITY_DESCRIPTION_EMBEDDING = """
MATCH (e:Entity {uuid: $entity_uuid_param})
CALL db.create.setNodeVectorProperty(e, 'description_embedding', $embedding_vector_param)
RETURN $entity_uuid_param AS uuid_processed
"""

# This query is used by EntityResolver to find candidates for deduplication
FIND_SIMILAR_ENTITIES_BY_VECTOR = """
CALL db.index.vector.queryNodes($index_name_param, $top_k_param, $embedding_vector_param)
YIELD node, score
WHERE node:Entity AND score >= $min_similarity_score_param
RETURN 
    node.uuid AS uuid, 
    node.name AS name, 
    node.label AS label, 
    node.description AS description, 
    score
ORDER BY score DESC
"""

MERGE_RELATIONSHIP = """
MATCH (source:Entity {uuid: $source_entity_uuid_param})
MATCH (target:Entity {uuid: $target_entity_uuid_param})
MERGE (source)-[rel:RELATES_TO {
    relation_label: $relation_label_param, 
    fact_sentence: $fact_sentence_param 
}]->(target)
ON CREATE SET
    rel.uuid = $relationship_uuid_param,
    rel.created_at = $created_at_ts_param,
    rel.source_chunk_uuid = $source_chunk_uuid_param
ON MATCH SET 
    rel.last_seen_at = $created_at_ts_param 
RETURN rel.uuid AS relationship_uuid, type(rel) AS relationship_type
"""

SET_RELATIONSHIP_FACT_EMBEDDING = """
MATCH ()-[r:RELATES_TO {uuid: $relationship_uuid_param}]->()
CALL db.create.setRelationshipVectorProperty(r, 'fact_embedding', $embedding_vector_param)
RETURN $relationship_uuid_param AS uuid_processed
"""

# --- Combined Search Query Parts ---

# CHUNK SEARCH PARTS
CHUNK_SEARCH_KEYWORD_PART = """
CALL db.index.fulltext.queryNodes($index_name_keyword_chunk, $keyword_query_string_chunk, {limit: $keyword_limit_param_chunk})
YIELD node, score
WHERE node:Chunk
RETURN node.uuid AS uuid, node.name AS name, node.content AS content, 
       node.source_description AS source_description, node.chunk_number AS chunk_number,
       score, "keyword" AS method_source
"""

CHUNK_SEARCH_SEMANTIC_PART = """
CALL db.index.vector.queryNodes($index_name_semantic_chunk, $semantic_top_k_param_chunk, $semantic_embedding_vector_param_chunk)
YIELD node, score
WHERE node:Chunk AND score >= $semantic_min_similarity_score_param_chunk
RETURN node.uuid AS uuid, node.name AS name, node.content AS content,
       node.source_description AS source_description, node.chunk_number AS chunk_number,
       score, "semantic" AS method_source
"""

# ENTITY SEARCH PARTS
ENTITY_SEARCH_KEYWORD_PART = """
CALL db.index.fulltext.queryNodes($index_name_keyword_entity, $keyword_query_string_entity, {limit: $keyword_limit_param_entity})
YIELD node, score
WHERE node:Entity
RETURN node.uuid AS uuid, node.name AS name, node.label AS label, node.description AS description,
       score, "keyword_name_desc" AS method_source
"""

ENTITY_SEARCH_SEMANTIC_NAME_PART = """
CALL db.index.vector.queryNodes($index_name_semantic_entity_name, $semantic_limit_entity_name, $semantic_embedding_entity_name)
YIELD node, score
WHERE node:Entity AND score >= $semantic_min_score_entity_name
RETURN node.uuid AS uuid, node.name AS name, node.label AS label, node.description AS description,
       score, "semantic_name" AS method_source
"""

ENTITY_SEARCH_SEMANTIC_DESCRIPTION_PART = """
CALL db.index.vector.queryNodes($index_name_semantic_entity_desc, $semantic_limit_entity_desc, $semantic_embedding_entity_desc)
YIELD node, score
WHERE node:Entity AND score >= $semantic_min_score_entity_desc
RETURN node.uuid AS uuid, node.name AS name, node.label AS label, node.description AS description,
       score, "semantic_description" AS method_source
"""

# RELATIONSHIP SEARCH PARTS
RELATIONSHIP_SEARCH_KEYWORD_PART = """
CALL db.index.fulltext.queryRelationships($index_name_keyword_rel, $keyword_query_string_rel, {limit: $keyword_limit_param_rel})
YIELD relationship, score
MATCH (s)-[r:RELATES_TO]->(t) WHERE elementId(r) = elementId(relationship)
RETURN r.uuid AS uuid, r.relation_label AS name, r.fact_sentence AS fact_sentence,
       s.uuid AS source_entity_uuid, t.uuid AS target_entity_uuid,
       score, "keyword_fact" AS method_source
"""

RELATIONSHIP_SEARCH_SEMANTIC_PART = """
CALL db.index.vector.queryRelationships($index_name_semantic_rel_fact, $semantic_limit_rel_fact, $semantic_embedding_rel_fact)
YIELD relationship, score
MATCH (s)-[r:RELATES_TO]->(t) WHERE elementId(r) = elementId(relationship) AND score >= $semantic_min_score_rel_fact
RETURN r.uuid AS uuid, r.relation_label AS name, r.fact_sentence AS fact_sentence,
       s.uuid AS source_entity_uuid, t.uuid AS target_entity_uuid,
       score, "semantic_fact" AS method_source
"""

# SOURCE SEARCH PARTS
SOURCE_SEARCH_KEYWORD_PART = """
CALL db.index.fulltext.queryNodes($index_name_keyword_source, $keyword_query_string_source, {limit: $keyword_limit_param_source})
YIELD node, score
WHERE node:Source
RETURN node.uuid AS uuid, node.name AS name, node.content AS content,
       score, "keyword_content" AS method_source
"""

SOURCE_SEARCH_SEMANTIC_PART = """
CALL db.index.vector.queryNodes($index_name_semantic_source_content, $semantic_limit_source_content, $semantic_embedding_source_content)
YIELD node, score
WHERE node:Source AND score >= $semantic_min_score_source_content
RETURN node.uuid AS uuid, node.name AS name, node.content AS content,
       score, "semantic_content" AS method_source
"""

# --- Schema Management Queries (Constraints, Indexes, Drop commands) ---
# ... (rest of the schema queries remain the same) ...
CREATE_CONSTRAINT_CHUNK_UUID = "CREATE CONSTRAINT chunk_uuid IF NOT EXISTS FOR (c:Chunk) REQUIRE c.uuid IS UNIQUE"
CREATE_CONSTRAINT_SOURCE_UUID = "CREATE CONSTRAINT source_uuid IF NOT EXISTS FOR (s:Source) REQUIRE s.uuid IS UNIQUE"
CREATE_CONSTRAINT_SOURCE_NAME = "CREATE CONSTRAINT source_name IF NOT EXISTS FOR (s:Source) REQUIRE s.name IS UNIQUE"
CREATE_CONSTRAINT_ENTITY_UUID = "CREATE CONSTRAINT entity_uuid IF NOT EXISTS FOR (e:Entity) REQUIRE e.uuid IS UNIQUE"

CREATE_INDEX_CHUNK_NAME = "CREATE INDEX chunk_name IF NOT EXISTS FOR (c:Chunk) ON (c.name)"
CREATE_INDEX_CHUNK_SOURCE_DESC_NUM = "CREATE INDEX chunk_source_desc_num IF NOT EXISTS FOR (c:Chunk) ON (c.source_description, c.chunk_number)"
CREATE_INDEX_SOURCE_CONTENT = "CREATE INDEX source_content IF NOT EXISTS FOR (s:Source) ON (s.content)" 
CREATE_INDEX_ENTITY_NORMALIZED_NAME_LABEL = "CREATE INDEX entity_normalized_name_label IF NOT EXISTS FOR (e:Entity) ON (e.normalized_name, e.label)"
CREATE_INDEX_ENTITY_NAME = "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)" 
CREATE_INDEX_ENTITY_LABEL = "CREATE INDEX entity_label IF NOT EXISTS FOR (e:Entity) ON (e.label)"
CREATE_INDEX_RELATIONSHIP_LABEL = "CREATE INDEX relationship_label_idx IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON (r.relation_label)"

CREATE_FULLTEXT_CHUNK_CONTENT = "CREATE FULLTEXT INDEX chunk_content_ft IF NOT EXISTS FOR (c:Chunk) ON EACH [c.content, c.name]"
CREATE_FULLTEXT_SOURCE_CONTENT = "CREATE FULLTEXT INDEX source_content_ft IF NOT EXISTS FOR (s:Source) ON EACH [s.content, s.name]"
CREATE_FULLTEXT_ENTITY_NAME_DESC = "CREATE FULLTEXT INDEX entity_name_desc_ft IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.description]"
CREATE_FULLTEXT_RELATIONSHIP_FACT = """
CREATE FULLTEXT INDEX relationship_fact_ft IF NOT EXISTS 
FOR ()-[r:RELATES_TO]-() ON EACH [r.relation_label, r.fact_sentence]
""" 

CREATE_VECTOR_INDEX_TEMPLATE = """
CREATE VECTOR INDEX $index_name IF NOT EXISTS
FOR (n:$node_label) ON (n.$property_name)
OPTIONS {indexConfig: {
    `vector.dimensions`: $dimension,
    `vector.similarity_function`: '$similarity_function'
}}
"""

CLEAR_ALL_NODES_AND_RELATIONSHIPS = "MATCH (n) DETACH DELETE n"

DROP_CONSTRAINT_CHUNK_UUID = "DROP CONSTRAINT chunk_uuid IF EXISTS"
DROP_CONSTRAINT_SOURCE_UUID = "DROP CONSTRAINT source_uuid IF EXISTS"
DROP_CONSTRAINT_SOURCE_NAME = "DROP CONSTRAINT source_name IF EXISTS"
DROP_CONSTRAINT_ENTITY_UUID = "DROP CONSTRAINT entity_uuid IF EXISTS"

DROP_INDEX_CHUNK_NAME = "DROP INDEX chunk_name IF EXISTS"
DROP_INDEX_CHUNK_SOURCE_DESC_NUM = "DROP INDEX chunk_source_desc_num IF EXISTS"
DROP_INDEX_SOURCE_CONTENT = "DROP INDEX source_content IF EXISTS" 
DROP_INDEX_ENTITY_NORMALIZED_NAME_LABEL = "DROP INDEX entity_normalized_name_label IF EXISTS"
DROP_INDEX_ENTITY_NAME = "DROP INDEX entity_name IF EXISTS"
DROP_INDEX_ENTITY_LABEL = "DROP INDEX entity_label IF EXISTS"
DROP_INDEX_RELATIONSHIP_LABEL = "DROP INDEX relationship_label_idx IF EXISTS"

DROP_FULLTEXT_ENTITY_NAME_DESC = "DROP INDEX entity_name_desc_ft IF EXISTS"
DROP_FULLTEXT_CHUNK_CONTENT = "DROP INDEX chunk_content_ft IF EXISTS" 
DROP_FULLTEXT_SOURCE_CONTENT = "DROP INDEX source_content_ft IF EXISTS"
DROP_FULLTEXT_RELATIONSHIP_FACT = "DROP INDEX relationship_fact_ft IF EXISTS"


GET_DISTINCT_PROPERTY_KEYS_FOR_LABEL_FALLBACK_TEMPLATE = """
MATCH (n:{node_label_placeholder}) 
UNWIND keys(properties(n)) AS key
WITH DISTINCT key WHERE NOT key IN $excluded_props_param 
RETURN key
"""