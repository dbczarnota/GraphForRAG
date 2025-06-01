# config/cypher_queries.py

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

CHECK_CHUNK_EXISTS_BY_NAME = """
MATCH (existing_chunk:Chunk {name: $name})
RETURN existing_chunk.uuid AS uuid
LIMIT 1
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

# --- Entity Node and Relationship Creation ---
MERGE_ENTITY_NODE = """
// Merge based on normalized_name and label
MERGE (entity:Entity {normalized_name: $normalized_name_param, label: $label_param}) 
ON CREATE SET 
    entity.uuid = $uuid_param,
    entity.name = $name_param, // Store the original "display" name
    entity.normalized_name = $normalized_name_param,
    entity.label = $label_param,
    entity.description = $description_param,
    entity.created_at = $created_at_ts_param,
    entity.processed_at = null
ON MATCH SET
    // Update description if it's new or different
    entity.description = CASE 
        WHEN $description_param IS NOT NULL AND (entity.description IS NULL OR entity.description <> $description_param) 
        THEN $description_param 
        ELSE entity.description 
    END,
    // We will handle entity.name update conditionally in Python after this query
    entity.updated_at = $created_at_ts_param 
RETURN entity.uuid AS entity_uuid, entity.name AS current_entity_name, entity.label AS entity_label 
"""
# Note: RETURNed entity.name as current_entity_name

UPDATE_ENTITY_NAME = """
MATCH (entity:Entity {uuid: $uuid_param})
SET entity.name = $new_name_param
RETURN entity.uuid AS entity_uuid, entity.name AS updated_entity_name
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

# --- Index and Constraint Queries ---
# Constraints (implicitly create indexes)
CREATE_CONSTRAINT_CHUNK_UUID = "CREATE CONSTRAINT chunk_uuid IF NOT EXISTS FOR (c:Chunk) REQUIRE c.uuid IS UNIQUE"
CREATE_CONSTRAINT_SOURCE_UUID = "CREATE CONSTRAINT source_uuid IF NOT EXISTS FOR (s:Source) REQUIRE s.uuid IS UNIQUE"
CREATE_CONSTRAINT_SOURCE_NAME = "CREATE CONSTRAINT source_name IF NOT EXISTS FOR (s:Source) REQUIRE s.name IS UNIQUE"
CREATE_CONSTRAINT_ENTITY_UUID = "CREATE CONSTRAINT entity_uuid IF NOT EXISTS FOR (e:Entity) REQUIRE e.uuid IS UNIQUE"

# Standard B-Tree Indexes (for statically known properties)
CREATE_INDEX_CHUNK_NAME = "CREATE INDEX chunk_name IF NOT EXISTS FOR (c:Chunk) ON (c.name)"
CREATE_INDEX_CHUNK_SOURCE_DESC_NUM = "CREATE INDEX chunk_source_desc_num IF NOT EXISTS FOR (c:Chunk) ON (c.source_description, c.chunk_number)"
CREATE_INDEX_SOURCE_CONTENT = "CREATE INDEX source_content IF NOT EXISTS FOR (s:Source) ON (s.content)"
CREATE_INDEX_ENTITY_NORMALIZED_NAME_LABEL = "CREATE INDEX entity_normalized_name_label IF NOT EXISTS FOR (e:Entity) ON (e.normalized_name, e.label)"
CREATE_INDEX_ENTITY_NAME = "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)" # Keep for display name searches
CREATE_INDEX_ENTITY_LABEL = "CREATE INDEX entity_label IF NOT EXISTS FOR (e:Entity) ON (e.label)"

# Full-Text Indexes
CREATE_FULLTEXT_CHUNK_CONTENT = "CREATE FULLTEXT INDEX chunk_content_ft IF NOT EXISTS FOR (c:Chunk) ON EACH [c.content, c.name]"
CREATE_FULLTEXT_SOURCE_CONTENT = "CREATE FULLTEXT INDEX source_content_ft IF NOT EXISTS FOR (s:Source) ON EACH [s.content, s.name]"
CREATE_FULLTEXT_ENTITY_NAME_DESC = "CREATE FULLTEXT INDEX entity_name_desc_ft IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.description]"


# Vector Indexes (Template - dynamically formatted in Python)
# Parameters: $index_name, $node_label, $property_name, $dimension, $similarity_function
CREATE_VECTOR_INDEX_TEMPLATE = """
CREATE VECTOR INDEX $index_name IF NOT EXISTS
FOR (n:$node_label) ON (n.$property_name)
OPTIONS {indexConfig: {
    `vector.dimensions`: $dimension,
    `vector.similarity_function`: '$similarity_function'
}}
"""

# --- Data and Schema Clearing Queries ---
CLEAR_ALL_NODES_AND_RELATIONSHIPS = "MATCH (n) DETACH DELETE n"

# --- Individual DROP commands for statically named indexes and constraints ---
DROP_CONSTRAINT_CHUNK_UUID = "DROP CONSTRAINT chunk_uuid IF EXISTS"
DROP_CONSTRAINT_SOURCE_UUID = "DROP CONSTRAINT source_uuid IF EXISTS"
DROP_CONSTRAINT_SOURCE_NAME = "DROP CONSTRAINT source_name IF EXISTS"
DROP_CONSTRAINT_ENTITY_UUID = "DROP CONSTRAINT entity_uuid IF EXISTS"


DROP_INDEX_CHUNK_NAME = "DROP INDEX chunk_name IF EXISTS"
DROP_INDEX_CHUNK_SOURCE_DESC_NUM = "DROP INDEX chunk_source_desc_num IF EXISTS"
DROP_INDEX_SOURCE_CONTENT = "DROP INDEX source_content IF EXISTS"
DROP_INDEX_ENTITY_NORMALIZED_NAME_LABEL = "DROP INDEX entity_normalized_name_label IF EXISTS" # <-- ADDED
DROP_INDEX_ENTITY_NAME = "DROP INDEX entity_name IF EXISTS"
DROP_INDEX_ENTITY_LABEL = "DROP INDEX entity_label IF EXISTS"

DROP_FULLTEXT_CHUNK_CONTENT = "DROP INDEX chunk_content_ft IF EXISTS"
DROP_FULLTEXT_SOURCE_CONTENT = "DROP INDEX source_content_ft IF EXISTS"
DROP_FULLTEXT_ENTITY_NAME_DESC = "DROP INDEX entity_name_desc_ft IF EXISTS"


# Note: Vector indexes and dynamically created B-Tree indexes are dropped by
# constructing their names in Python and then using "DROP INDEX <name> IF EXISTS".
# So, no specific static DROP templates are needed here for those,
# beyond what SchemaManager constructs.

# Query to get distinct property keys for a given node label (Fallback if APOC not available)
# This is kept here as a reference or if needed, but SchemaManager prioritizes APOC.
GET_DISTINCT_PROPERTY_KEYS_FOR_LABEL_FALLBACK = """
MATCH (n:$node_label_param)
UNWIND keys(n) AS key
WITH DISTINCT key
WHERE NOT key IN ['uuid', 'name', 'content', 'content_embedding', 'created_at', 'source_description', 'chunk_number', 'processed_at', 'entity_count', 'relationship_count']
RETURN key
"""