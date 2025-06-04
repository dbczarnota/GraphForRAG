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
MERGE (chunk)-[r:MENTIONS]->(entity) # CHANGED from MENTIONS_ENTITY
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

# (Can be placed near FIND_SIMILAR_ENTITIES_BY_VECTOR)
FIND_SIMILAR_PRODUCTS_BY_VECTOR = """
CALL db.index.vector.queryNodes($index_name_param, $top_k_param, $embedding_vector_param)
YIELD node, score
WHERE node:Product AND score >= $min_similarity_score_param  // Target Product nodes
RETURN 
    node.uuid AS uuid, 
    node.name AS name, 
    // For 'label', we can use a specific property like 'category' if Product nodes have it,
    // or default to the string 'Product'. Let's use category if available, else 'Product'.
    // This requires Product nodes to have a 'category' property for best results,
    // or the client needs to handle a generic 'Product' label.
    // For now, to keep it simple and align with Entity's 'label', we'll use 'Product' as the label here.
    // Or, we can make it more dynamic:
    // CASE WHEN node.category IS NOT NULL THEN node.category ELSE 'Product' END AS label,
    // For now, let's just use the node label from Product itself, or a fixed string 'Product'.
    // SchemaManager should ensure Products have a 'label' property, even if it's just "Product".
    // Let's assume Product nodes might have a 'category' property that can serve as a label, or we use 'Product'.
    // For consistency with ExistingEntityCandidate, we need a 'label'.
    // Let's assume Product nodes store their primary category in a property like 'category'.
    // If not, we'll default to "Product".
    // The MERGE_PRODUCT_NODE query doesn't explicitly set a 'category' or 'label' property.
    // We should ensure Product nodes have a 'label' property, similar to Entity nodes.
    // For now, let's assume 'Product' as a fixed label for candidate type identification.
    // The actual display label can come from node.name or node.category.
    // The `ExistingEntityCandidate.label` field is for the candidate's own label.
    // Let's use `node.category` if it exists, otherwise 'Product'.
    // The `ExistingEntityCandidate.node_type` will be 'Product'.
    // The `ExistingEntityCandidate.label` should reflect the Product's category or main type.
    // The `MERGE_PRODUCT_NODE` should ideally set a `category` or `product_type` property from source data.
    // For now, let's output a generic 'Product' label for Product candidates if 'category' isn't consistently there.
    // To simplify, let's have MERGE_PRODUCT_NODE set a 'label' property for products, e.g., from their 'category' field.
    // For this query, we will assume Product nodes have a 'category' field we can use, or we default.
    // For candidate matching, the display name is node.name. The label is for filtering/info.
    // Let's assume the Product nodes have a 'category' field that can be used as their 'label'.
    // If not, we'll need to adjust. For now, using node.category.
    // If Product.category is not guaranteed, we can use a fixed string "Product"
    // Or, even better, if Product nodes are expected to have a 'label' property (like 'Laptop', 'Smartphone')
    // similar to Entity nodes. Let's assume 'label' will be set on Product nodes too.
    // The MERGE_PRODUCT_NODE should be updated to set product.label if not already.
    // For now, we will rely on a property like 'category' or use a fixed 'Product' string.
    // To keep it simple for this step, let's assume products store their type in 'category'.
    // We need to make sure Product nodes have a `label` like property.
    // Let's assume `node.category` or a fixed value.
    // The `ExistingEntityCandidate.label` is for the specific type of product/entity.
    // The `ExistingEntityCandidate.node_type` is "Product" or "Entity".
    // So, for a Product, its label would be "Laptop", "Smartphone", etc.
    // The current MERGE_PRODUCT_NODE doesn't set a generic 'label' property.
    // Let's assume we add a 'category' property to products from JSON.
    node.category AS label, // Using 'category' as the display label for the product
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

# --- Product Node Specific Queries ---
MERGE_PRODUCT_NODE = """
MERGE (product:Product {uuid: $product_uuid_param})
ON CREATE SET
    product.name = $name_param,
    product.description = $description_param,
    product.created_at = $created_at_ts_param,
    product.processed_at = null, // Can be updated later if specific processing happens
    product.updated_at = $created_at_ts_param
ON MATCH SET
    product.name = $name_param, // Allow updates to name/description on match
    product.description = $description_param,
    product.updated_at = $created_at_ts_param
SET product += $dynamic_product_properties_param // For other attributes from source JSON
RETURN product.uuid AS product_uuid, product.name AS product_name
"""

LINK_PRODUCT_TO_SOURCE = """
MATCH (product:Product {uuid: $product_uuid_param})
MATCH (source:Source {uuid: $source_node_uuid_param})
MERGE (product)-[r:BELONGS_TO_SOURCE]->(source) // Changed from DEFINED_IN_SOURCE
ON CREATE SET r.created_at = $created_at_ts_param
RETURN type(r) AS relationship_type
"""

SET_PRODUCT_NAME_EMBEDDING = """
MATCH (p:Product {uuid: $product_uuid_param})
CALL db.create.setNodeVectorProperty(p, 'name_embedding', $embedding_vector_param)
RETURN $product_uuid_param AS uuid_processed
"""

SET_PRODUCT_DESCRIPTION_EMBEDDING = """
MATCH (p:Product {uuid: $product_uuid_param})
CALL db.create.setNodeVectorProperty(p, 'description_embedding', $embedding_vector_param)
RETURN $product_uuid_param AS uuid_processed
"""

# This relationship will be used in Phase 2
LINK_CHUNK_TO_ENTITY = """
MATCH (chunk:Chunk {uuid: $chunk_uuid_param})
MATCH (entity:Entity {uuid: $entity_uuid_param})
MERGE (chunk)-[r:MENTIONS]->(entity) 
ON CREATE SET r.created_at = $created_at_ts_param
RETURN type(r) AS relationship_type
"""

# --- Node Lifecycle / Promotion Queries ---
PROMOTE_ENTITY_TO_PRODUCT = """
MATCH (old_entity:Entity {uuid: $existing_entity_uuid_param})

// 1. Create the new Product node
CREATE (new_product:Product {uuid: $new_product_uuid_param})
SET new_product.name = $new_product_name_param,
    new_product.description = $new_product_description_param,
    new_product.created_at = $created_at_ts_param,
    new_product.updated_at = $created_at_ts_param,
    new_product.processed_at = null
SET new_product += $new_product_properties_param

// 2. Copy INCOMING relationships
WITH old_entity, new_product
OPTIONAL MATCH (source_node)-[old_rel_in]->(old_entity)
WITH old_entity, new_product, source_node, old_rel_in, type(old_rel_in) AS rel_in_type, properties(old_rel_in) AS rel_in_props
// Only proceed if old_rel_in exists (source_node will also exist)
CALL apoc.do.when(old_rel_in IS NOT NULL,
    'CALL apoc.create.relationship(s, rel_type_dyn, props_dyn, np) YIELD rel RETURN rel',
    'RETURN null AS rel',
    {s: source_node, np: new_product, rel_type_dyn: rel_in_type, props_dyn: rel_in_props}
) YIELD value AS in_rel_creation_result
// Aggregate count of newly created incoming relationships
WITH old_entity, new_product, count(in_rel_creation_result.rel) AS copied_incoming_rels_count

// 3. Copy OUTGOING relationships
WITH old_entity, new_product, copied_incoming_rels_count
OPTIONAL MATCH (old_entity)-[old_rel_out]->(target_node)
WITH old_entity, new_product, copied_incoming_rels_count, target_node, old_rel_out, type(old_rel_out) AS rel_out_type, properties(old_rel_out) AS rel_out_props
// Only proceed if old_rel_out exists (target_node will also exist)
CALL apoc.do.when(old_rel_out IS NOT NULL,
    'CALL apoc.create.relationship(np, rel_type_dyn, props_dyn, t) YIELD rel RETURN rel',
    'RETURN null AS rel',
    {np: new_product, t: target_node, rel_type_dyn: rel_out_type, props_dyn: rel_out_props}
) YIELD value AS out_rel_creation_result
// Aggregate count of newly created outgoing relationships
WITH old_entity, new_product, copied_incoming_rels_count, count(out_rel_creation_result.rel) AS copied_outgoing_rels_count

// 4. Detach and Delete the old Entity node
// new_product is carried through, old_entity is still in scope for deletion
WITH new_product, copied_incoming_rels_count, copied_outgoing_rels_count, old_entity
DETACH DELETE old_entity

// 5. Return the new product's UUID and counts
RETURN new_product.uuid AS new_product_uuid,
       copied_incoming_rels_count AS incoming_rels_copied,
       copied_outgoing_rels_count AS outgoing_rels_copied
"""

LINK_CHUNK_TO_PRODUCT = """
MATCH (chunk:Chunk {uuid: $chunk_uuid_param})
MATCH (product:Product {uuid: $product_uuid_param})
MERGE (chunk)-[r:MENTIONS]->(product) 
ON CREATE SET r.created_at = $created_at_ts_param
RETURN type(r) AS relationship_type
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
CREATE_CONSTRAINT_PRODUCT_UUID = "CREATE CONSTRAINT product_uuid IF NOT EXISTS FOR (p:Product) REQUIRE p.uuid IS UNIQUE"

CREATE_INDEX_CHUNK_NAME = "CREATE INDEX chunk_name IF NOT EXISTS FOR (c:Chunk) ON (c.name)"
CREATE_INDEX_CHUNK_SOURCE_DESC_NUM = "CREATE INDEX chunk_source_desc_num IF NOT EXISTS FOR (c:Chunk) ON (c.source_description, c.chunk_number)"
CREATE_INDEX_SOURCE_CONTENT = "CREATE INDEX source_content IF NOT EXISTS FOR (s:Source) ON (s.content)" 
CREATE_INDEX_ENTITY_NORMALIZED_NAME_LABEL = "CREATE INDEX entity_normalized_name_label IF NOT EXISTS FOR (e:Entity) ON (e.normalized_name, e.label)"
CREATE_INDEX_ENTITY_NAME = "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)" 
CREATE_INDEX_ENTITY_LABEL = "CREATE INDEX entity_label IF NOT EXISTS FOR (e:Entity) ON (e.label)"
CREATE_INDEX_RELATIONSHIP_LABEL = "CREATE INDEX relationship_label_idx IF NOT EXISTS FOR ()-[r:RELATES_TO]-() ON (r.relation_label)"
CREATE_INDEX_PRODUCT_NAME = "CREATE INDEX product_name_idx IF NOT EXISTS FOR (p:Product) ON (p.name)"


CREATE_FULLTEXT_CHUNK_CONTENT = "CREATE FULLTEXT INDEX chunk_content_ft IF NOT EXISTS FOR (c:Chunk) ON EACH [c.content, c.name]"
CREATE_FULLTEXT_SOURCE_CONTENT = "CREATE FULLTEXT INDEX source_content_ft IF NOT EXISTS FOR (s:Source) ON EACH [s.content, s.name]"
CREATE_FULLTEXT_ENTITY_NAME_DESC = "CREATE FULLTEXT INDEX entity_name_desc_ft IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.description]"
CREATE_FULLTEXT_RELATIONSHIP_FACT = """
CREATE FULLTEXT INDEX relationship_fact_ft IF NOT EXISTS 
FOR ()-[r:RELATES_TO]-() ON EACH [r.relation_label, r.fact_sentence]
""" 
CREATE_FULLTEXT_PRODUCT_NAME_DESC = "CREATE FULLTEXT INDEX product_name_desc_ft IF NOT EXISTS FOR (p:Product) ON EACH [p.name, p.description]"

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
DROP_CONSTRAINT_PRODUCT_UUID = "DROP CONSTRAINT product_uuid IF EXISTS"




DROP_INDEX_CHUNK_NAME = "DROP INDEX chunk_name IF EXISTS"
DROP_INDEX_CHUNK_SOURCE_DESC_NUM = "DROP INDEX chunk_source_desc_num IF EXISTS"
DROP_INDEX_SOURCE_CONTENT = "DROP INDEX source_content IF EXISTS" 
DROP_INDEX_ENTITY_NORMALIZED_NAME_LABEL = "DROP INDEX entity_normalized_name_label IF EXISTS"
DROP_INDEX_ENTITY_NAME = "DROP INDEX entity_name IF EXISTS"
DROP_INDEX_ENTITY_LABEL = "DROP INDEX entity_label IF EXISTS"
DROP_INDEX_RELATIONSHIP_LABEL = "DROP INDEX relationship_label_idx IF EXISTS"
DROP_INDEX_PRODUCT_NAME = "DROP INDEX product_name_idx IF EXISTS"

DROP_FULLTEXT_ENTITY_NAME_DESC = "DROP INDEX entity_name_desc_ft IF EXISTS"
DROP_FULLTEXT_CHUNK_CONTENT = "DROP INDEX chunk_content_ft IF EXISTS" 
DROP_FULLTEXT_SOURCE_CONTENT = "DROP INDEX source_content_ft IF EXISTS"
DROP_FULLTEXT_RELATIONSHIP_FACT = "DROP INDEX relationship_fact_ft IF EXISTS"
DROP_FULLTEXT_PRODUCT_NAME_DESC = "DROP INDEX product_name_desc_ft IF EXISTS"

GET_DISTINCT_PROPERTY_KEYS_FOR_LABEL_FALLBACK_TEMPLATE = """
MATCH (n:{node_label_placeholder}) 
UNWIND keys(properties(n)) AS key
WITH DISTINCT key WHERE NOT key IN $excluded_props_param 
RETURN key
"""