# C:\Users\czarn\Documents\A_PYTHON\GraphForRAG\graphforrag_core\config\cypher_queries.py

MERGE_SOURCE_NODE = """
MERGE (source:Source {name: $source_identifier_param})
ON CREATE SET
    source.uuid = $source_uuid_param,
    source.created_at = $created_at_ts_param
SET source += $dynamic_properties_param
RETURN source.uuid AS source_uuid, source.name AS source_name
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

// Changed relationship type to BELONGS_TO_SOURCE
MERGE (chunk)-[r_bts:BELONGS_TO_SOURCE]->(source)  // << CHANGED HERE
ON CREATE SET r_bts.created_at = ts               // << CHANGED HERE (variable name for rel)
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

# --- Index and Constraint Queries ---
# Constraints (implicitly create indexes)
CREATE_CONSTRAINT_CHUNK_UUID = "CREATE CONSTRAINT chunk_uuid IF NOT EXISTS FOR (c:Chunk) REQUIRE c.uuid IS UNIQUE"
CREATE_CONSTRAINT_SOURCE_UUID = "CREATE CONSTRAINT source_uuid IF NOT EXISTS FOR (s:Source) REQUIRE s.uuid IS UNIQUE"
CREATE_CONSTRAINT_SOURCE_NAME = "CREATE CONSTRAINT source_name IF NOT EXISTS FOR (s:Source) REQUIRE s.name IS UNIQUE" # Name is our identifier

# Standard B-Tree Indexes
CREATE_INDEX_CHUNK_NAME = "CREATE INDEX chunk_name IF NOT EXISTS FOR (c:Chunk) ON (c.name)"
CREATE_INDEX_CHUNK_SOURCE_DESC_NUM = "CREATE INDEX chunk_source_desc_num IF NOT EXISTS FOR (c:Chunk) ON (c.source_description, c.chunk_number)"

# Full-Text Indexes
CREATE_FULLTEXT_CHUNK_CONTENT = "CREATE FULLTEXT INDEX chunk_content_ft IF NOT EXISTS FOR (c:Chunk) ON EACH [c.content, c.name]"
# We might also want a full-text index on Source name/metadata later

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
DROP_INDEX_CHUNK_NAME = "DROP INDEX chunk_name IF EXISTS" # Correct for RANGE/B-Tree
DROP_INDEX_CHUNK_SOURCE_DESC_NUM = "DROP INDEX chunk_source_desc_num IF EXISTS" # Correct for RANGE/B-Tree

# Correct way to drop FULLTEXT and VECTOR indexes is just "DROP INDEX <name>"
DROP_FULLTEXT_CHUNK_CONTENT = "DROP INDEX chunk_content_ft IF EXISTS" # << CORRECTED
DROP_VECTOR_CHUNK_CONTENT_EMBEDDING = "DROP INDEX chunk_content_embedding_vector IF EXISTS" # << CORRECTED (assuming this is the name)


SET_CHUNK_CONTENT_EMBEDDING = """
MATCH (c:Chunk {uuid: $chunk_uuid_param})
CALL db.create.setNodeVectorProperty(c, 'content_embedding', $embedding_vector_param)
// The procedure works by side effect. We don't need to YIELD from it.
// We simply return the input UUID to confirm the MATCH part of the query found the node
// and the CALL was attempted. The success of the CALL is implied if no error occurs.
RETURN $chunk_uuid_param AS uuid_processed 
"""