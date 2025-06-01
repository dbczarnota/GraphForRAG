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
    entity.uuid = $uuid_param, // This uuid_param MUST be a NEWLY GENERATED one for this logic
    entity.name = $name_param, 
    entity.normalized_name = $normalized_name_param,
    entity.label = $label_param,
    entity.description = $description_param,
    entity.created_at = $created_at_ts_param,
    entity.processed_at = null,
    entity.updated_at = $created_at_ts_param // Also set updated_at on create
ON MATCH SET 
    // ON MATCH, we primarily just update the timestamp. 
    // Specific property updates for existing nodes will be handled by separate queries.
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

# ... (LINK_CHUNK_TO_ENTITY, SET_ENTITY_NAME_EMBEDDING, FIND_SIMILAR_ENTITIES_BY_VECTOR)
# ... (Index and Constraint queries)
# ... (Drop queries)
# ... (GET_DISTINCT_PROPERTY_KEYS_FOR_LABEL_FALLBACK)
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

FIND_SIMILAR_ENTITIES_BY_VECTOR = """
CALL db.index.vector.queryNodes($index_name_param, $top_k_param, $embedding_vector_param)
YIELD node, score
WHERE score >= $min_similarity_score_param
RETURN 
    node.uuid AS uuid, 
    node.name AS name, 
    node.label AS label, 
    node.description AS description, 
    score
ORDER BY score DESC
"""

# --- Relationship (Edge) Creation and Embedding ---
MERGE_RELATIONSHIP = """
MATCH (source:Entity {uuid: $source_entity_uuid_param})
MATCH (target:Entity {uuid: $target_entity_uuid_param})
// Merge based on source, target, label, and the fact sentence to avoid creating
// identical relationships if the same fact is extracted multiple times for the same pair.
MERGE (source)-[rel:RELATES_TO {
    relation_label: $relation_label_param, 
    fact_sentence: $fact_sentence_param 
}]->(target)
ON CREATE SET
    rel.uuid = $relationship_uuid_param,
    rel.created_at = $created_at_ts_param,
    // fact_sentence and relation_label are already set by MERGE key
    rel.source_chunk_uuid = $source_chunk_uuid_param // Link to the chunk it was extracted from
ON MATCH SET // If we match, it means this exact fact was already found for this pair
    // We might want to append the current chunk_uuid to a list of evidencing chunks later
    // For now, just update the timestamp if we re-encounter it
    rel.last_seen_at = $created_at_ts_param 
RETURN rel.uuid AS relationship_uuid, type(rel) AS relationship_type
"""

SET_RELATIONSHIP_FACT_EMBEDDING = """
MATCH ()-[r:RELATES_TO {uuid: $relationship_uuid_param}]->()
CALL db.create.setRelationshipVectorProperty(r, 'fact_embedding', $embedding_vector_param)
RETURN $relationship_uuid_param AS uuid_processed
"""


# Constraints (implicitly create indexes)
CREATE_CONSTRAINT_CHUNK_UUID = "CREATE CONSTRAINT chunk_uuid IF NOT EXISTS FOR (c:Chunk) REQUIRE c.uuid IS UNIQUE"
CREATE_CONSTRAINT_SOURCE_UUID = "CREATE CONSTRAINT source_uuid IF NOT EXISTS FOR (s:Source) REQUIRE s.uuid IS UNIQUE"
CREATE_CONSTRAINT_SOURCE_NAME = "CREATE CONSTRAINT source_name IF NOT EXISTS FOR (s:Source) REQUIRE s.name IS UNIQUE" # Name is our identifier
CREATE_CONSTRAINT_ENTITY_UUID = "CREATE CONSTRAINT entity_uuid IF NOT EXISTS FOR (e:Entity) REQUIRE e.uuid IS UNIQUE"

# Standard B-Tree Indexes
CREATE_INDEX_CHUNK_NAME = "CREATE INDEX chunk_name IF NOT EXISTS FOR (c:Chunk) ON (c.name)"
CREATE_INDEX_CHUNK_SOURCE_DESC_NUM = "CREATE INDEX chunk_source_desc_num IF NOT EXISTS FOR (c:Chunk) ON (c.source_description, c.chunk_number)"
CREATE_INDEX_SOURCE_CONTENT = "CREATE INDEX source_content IF NOT EXISTS FOR (s:Source) ON (s.content)" # <-- ADDED for potential text search on source content
CREATE_INDEX_ENTITY_NORMALIZED_NAME_LABEL = "CREATE INDEX entity_normalized_name_label IF NOT EXISTS FOR (e:Entity) ON (e.normalized_name, e.label)" # <-- ADDED
CREATE_INDEX_ENTITY_NAME = "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)" # Keep for display name searches
CREATE_INDEX_ENTITY_LABEL = "CREATE INDEX entity_label IF NOT EXISTS FOR (e:Entity) ON (e.label)"
CREATE_INDEX_RELATIONSHIP_LABEL = "CREATE INDEX relationship_label_idx IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON (r.relation_label)"

# Full-Text Indexes
CREATE_FULLTEXT_CHUNK_CONTENT = "CREATE FULLTEXT INDEX chunk_content_ft IF NOT EXISTS FOR (c:Chunk) ON EACH [c.content, c.name]"
CREATE_FULLTEXT_SOURCE_CONTENT = "CREATE FULLTEXT INDEX source_content_ft IF NOT EXISTS FOR (s:Source) ON EACH [s.content, s.name]" # <-- ADDED
CREATE_FULLTEXT_ENTITY_NAME_DESC = "CREATE FULLTEXT INDEX entity_name_desc_ft IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.description]"


# Vector Indexes (Dynamically formatted in Python)
# Template for vector index creation for Chunk content_embedding
# $nodeLabel, $propertyName, $indexName, $dimension, $similarityFunction
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

# Note: Dropping all indexes and constraints programmatically requires fetching their names first
# and then constructing DROP commands. For simplicity in a direct clear,
# we'll provide individual drop commands for the ones we know we create.
# A more robust 'clear_all_indexes_and_constraints' would involve SHOW commands.

# --- Individual DROP commands (for a targeted clear_all_our_indexes_and_constraints) ---
DROP_CONSTRAINT_CHUNK_UUID = "DROP CONSTRAINT chunk_uuid IF EXISTS"
DROP_CONSTRAINT_SOURCE_UUID = "DROP CONSTRAINT source_uuid IF EXISTS"
DROP_CONSTRAINT_SOURCE_NAME = "DROP CONSTRAINT source_name IF EXISTS"
DROP_CONSTRAINT_ENTITY_UUID = "DROP CONSTRAINT entity_uuid IF EXISTS"

DROP_INDEX_CHUNK_NAME = "DROP INDEX chunk_name IF EXISTS" # Correct for RANGE/B-Tree
DROP_INDEX_CHUNK_SOURCE_DESC_NUM = "DROP INDEX chunk_source_desc_num IF EXISTS" # Correct for RANGE/B-Tree
DROP_INDEX_SOURCE_CONTENT = "DROP INDEX source_content IF EXISTS" 
DROP_INDEX_ENTITY_NORMALIZED_NAME_LABEL = "DROP INDEX entity_normalized_name_label IF EXISTS"
DROP_INDEX_ENTITY_NAME = "DROP INDEX entity_name IF EXISTS"
DROP_INDEX_ENTITY_LABEL = "DROP INDEX entity_label IF EXISTS"
DROP_INDEX_RELATIONSHIP_LABEL = "DROP INDEX relationship_label_idx IF EXISTS"

DROP_FULLTEXT_ENTITY_NAME_DESC = "DROP INDEX entity_name_desc_ft IF EXISTS"
DROP_FULLTEXT_CHUNK_CONTENT = "DROP INDEX chunk_content_ft IF EXISTS" 
DROP_FULLTEXT_SOURCE_CONTENT = "DROP INDEX source_content_ft IF EXISTS" 
# Query to get distinct property keys for a given node label (Fallback if APOC not available)
GET_DISTINCT_PROPERTY_KEYS_FOR_LABEL_FALLBACK = """
MATCH (n:$node_label_param)
UNWIND keys(n) AS key
WITH DISTINCT key
WHERE NOT key IN ['uuid', 'name', 'content', 'content_embedding', 'created_at', 
                  'source_description', 'chunk_number', 'processed_at', 
                  'entity_count', 'relationship_count', 
                  'normalized_name', 'label', 'description'] // Added entity specific fields to exclude
RETURN key
"""