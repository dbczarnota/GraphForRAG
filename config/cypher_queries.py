# config/cypher_queries.py

# --- Constants for Schema Management --
EXCLUDED_PROPERTIES_FOR_DYNAMIC_BTREE = [
    'uuid', 'name', 'content', 'name_embedding', 'content_embedding', 'created_at', 
    'source_description', 'chunk_number', 'processed_at', 
    'entity_count', 'relationship_count',
    'normalized_name', 'label', 
    # 'description', 'description_embedding' # These are removed
    # For Product, explicit properties are name, content, price, sku
    'price', 'sku' 
]

SUITABLE_BTREE_TYPES = [
    "STRING", "INTEGER", "FLOAT", "BOOLEAN", 
    "DATE", "DATETIME", "LOCAL_DATETIME", "TIME", "LOCAL_TIME"
]

# --- Node and Relationship Creation/Update Queries ---
MERGE_SOURCE_NODE = """
MERGE (source:Source {name: $name_param}) // Use name_param for MERGE key
ON CREATE SET
    source.uuid = $source_uuid_param,
    source.created_at = $created_at_ts_param,
    source.name = $name_param, // Ensure name is set on create
    source.content = $source_content_param
ON MATCH SET
    source.content = $source_content_param, // Allow content update on match
    source.name = $name_param // Ensure name is also set on match if different
SET source += $dynamic_properties_param
RETURN source.uuid AS source_uuid, source.name AS source_name, source.content as source_content
"""

ADD_CHUNK_AND_LINK_TO_SOURCE = """
MATCH (source:Source {uuid: $source_node_uuid_param})
WITH source

MERGE (chunk:Chunk {uuid: $chunk_uuid_param})
ON CREATE SET
    // chunk.name is now expected to be in $dynamic_chunk_properties_param
    chunk.content = $chunk_content_param, // Explicitly set content
    chunk.source_description = $source_name_param, // Use source_name_param
    chunk.created_at = $created_at_ts_param,
    chunk.processed_at = null,
    chunk.entity_count = 0,
    chunk.relationship_count = 0
ON MATCH SET
    // chunk.name update can be handled by dynamic_chunk_properties_param if needed
    chunk.content = $chunk_content_param,
    chunk.source_description = $source_name_param
SET chunk += $dynamic_chunk_properties_param // This will set/update name, chunk_number, and other metadata
WITH chunk, source, $chunk_number_param_for_rel AS currentChunkNumberForRel, $created_at_ts_param AS ts

MERGE (chunk)-[r_bts:BELONGS_TO_SOURCE]->(source)
ON CREATE SET r_bts.created_at = ts
WITH chunk, source, currentChunkNumberForRel

CALL apoc.do.when(currentChunkNumberForRel > 1 AND currentChunkNumberForRel IS NOT NULL,
    'MATCH (prev_chunk:Chunk {source_description: $sourceNameParamForApoc, chunk_number: $prevChunkNumberParam})
     MATCH (current_chunk_for_rel:Chunk {uuid: $currentChunkUuidParam})
     MERGE (prev_chunk)-[r_nc:NEXT_CHUNK]->(current_chunk_for_rel)
     ON CREATE SET r_nc.created_at = datetime()
     RETURN prev_chunk, r_nc',
    'RETURN null AS prev_chunk, null AS r_nc',
    {
        sourceNameParamForApoc: source.name, // Use source.name for matching prev_chunk
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
    // entity.description = $description_param, // REMOVED
    entity.created_at = $created_at_ts_param,
    entity.processed_at = null,
    entity.updated_at = $created_at_ts_param
ON MATCH SET 
    entity.updated_at = $created_at_ts_param
RETURN entity.uuid AS entity_uuid, 
       entity.name AS current_entity_name, 
       // entity.description AS current_entity_description, // REMOVED
       entity.label AS entity_label 
"""

UPDATE_ENTITY_NAME = """
MATCH (entity:Entity {uuid: $uuid_param})
SET entity.name = $new_name_param,
    entity.updated_at = $updated_at_param 
RETURN entity.uuid AS entity_uuid, entity.name AS updated_entity_name
"""

# UPDATE_ENTITY_DESCRIPTION = """
# MATCH (entity:Entity {uuid: $uuid_param})
# SET entity.description = $new_description_param,
#     entity.updated_at = $updated_at_param
# RETURN entity.uuid AS entity_uuid, entity.description AS updated_entity_description
# """

GET_ENTITY_DETAILS_FOR_UPDATE = """
MATCH (entity:Entity {uuid: $uuid_param})
RETURN entity.uuid AS entity_uuid, 
       entity.name AS current_entity_name, 
       // entity.description AS current_entity_description, // REMOVED
       entity.label AS entity_label 
"""

LINK_CHUNK_TO_ENTITY = """
MATCH (chunk:Chunk {uuid: $chunk_uuid_param})
MATCH (entity:Entity {uuid: $entity_uuid_param})
MERGE (chunk)-[r:MENTIONS]->(entity) 
ON CREATE SET 
    r.uuid = $mention_uuid_param, // ADDED
    r.created_at = $created_at_ts_param,
    r.fact_sentence = $fact_sentence_param, 
    r.source_chunk_uuid = $chunk_uuid_param 
ON MATCH SET 
    r.last_seen_in_chunk_at = $created_at_ts_param,
    r.fact_sentence = $fact_sentence_param 
RETURN type(r) AS relationship_type, r.uuid AS relationship_uuid // Return UUID
"""

SET_ENTITY_NAME_EMBEDDING = """
MATCH (e:Entity {uuid: $entity_uuid_param})
CALL db.create.setNodeVectorProperty(e, 'name_embedding', $embedding_vector_param)
RETURN $entity_uuid_param AS uuid_processed
"""

# SET_ENTITY_DESCRIPTION_EMBEDDING = """
# MATCH (e:Entity {uuid: $entity_uuid_param})
# CALL db.create.setNodeVectorProperty(e, 'description_embedding', $embedding_vector_param)
# RETURN $entity_uuid_param AS uuid_processed
# """

# This query is used by EntityResolver to find candidates for deduplication
FIND_SIMILAR_ENTITIES_BY_VECTOR = """
CALL db.index.vector.queryNodes($index_name_param, $top_k_param, $embedding_vector_param)
YIELD node, score
WHERE node:Entity AND score >= $min_similarity_score_param
// Collect a few fact_sentences from incoming MENTIONS relationships
OPTIONAL MATCH (c:Chunk)-[m:MENTIONS]->(node) WHERE m.fact_sentence IS NOT NULL
WITH node, score, collect(m.fact_sentence)[..3] AS mention_facts // Collect up to 3 facts
RETURN 
    node.uuid AS uuid, 
    node.name AS name, 
    node.label AS label, 
    mention_facts, // ADDED
    score
ORDER BY score DESC
"""

# (Can be placed near FIND_SIMILAR_ENTITIES_BY_VECTOR)
FIND_SIMILAR_PRODUCTS_BY_VECTOR = """
CALL db.index.vector.queryNodes($index_name_param, $top_k_param, $embedding_vector_param)
YIELD node, score
WHERE node:Product AND score >= $min_similarity_score_param
// Collect a few fact_sentences from incoming MENTIONS relationships
OPTIONAL MATCH (c:Chunk)-[m:MENTIONS]->(node) WHERE m.fact_sentence IS NOT NULL
WITH node, score, collect(m.fact_sentence)[..3] AS mention_facts // Collect up to 3 facts
RETURN 
    node.uuid AS uuid, 
    node.name AS name, 
    node.category AS label, // Using category as the display label for product type
    node.content AS content,
    mention_facts, // ADDED
    score
ORDER BY score DESC
"""

MERGE_RELATIONSHIP = """
MATCH (source {uuid: $source_entity_uuid_param}) // REMOVED :Entity label constraint
MATCH (target {uuid: $target_entity_uuid_param}) // REMOVED :Entity label constraint
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
# (Should be placed with other relationship embedding queries)
SET_MENTIONS_FACT_EMBEDDING = """ 
MATCH (c:Chunk {uuid: $chunk_uuid_param})-[r:MENTIONS]->(target_node {uuid: $target_node_uuid_param})
// target_node can be :Entity or :Product
CALL db.create.setRelationshipVectorProperty(r, 'fact_embedding', $embedding_vector_param) // CHANGED property name
RETURN count(r) AS relationships_updated
"""
# --- Product Node Specific Queries ---
MERGE_PRODUCT_NODE = """
MERGE (product:Product {uuid: $product_uuid_param})
ON CREATE SET
    product.name = $name_param,
    product.content = $content_param, // NEW: Store raw JSON string as content
    product.price = $price_param,     // NEW: Explicit price
    product.sku = $sku_param,         // NEW: Explicit SKU
    product.created_at = $created_at_ts_param,
    product.processed_at = null, 
    product.updated_at = $created_at_ts_param
ON MATCH SET
    product.name = $name_param, 
    product.content = $content_param,
    product.price = $price_param,
    product.sku = $sku_param,
    product.updated_at = $created_at_ts_param
SET product += $dynamic_product_properties_param // For other attributes from metadata
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

SET_PRODUCT_CONTENT_EMBEDDING = """
MATCH (p:Product {uuid: $product_uuid_param})
CALL db.create.setNodeVectorProperty(p, 'content_embedding', $embedding_vector_param)
RETURN $product_uuid_param AS uuid_processed
"""


# --- Node Lifecycle / Promotion Queries ---
PROMOTE_ENTITY_TO_PRODUCT = """
MATCH (old_entity:Entity {uuid: $existing_entity_uuid_param})

// 1. Create the new Product node
CREATE (new_product:Product {uuid: $new_product_uuid_param})
SET new_product.name = $new_product_name_param,
    new_product.content = $new_product_content_param,         // CHANGED from description
    new_product.price = $new_product_price_param,           // NEW
    new_product.sku = $new_product_sku_param,               // NEW
    new_product.created_at = $created_at_ts_param,
    new_product.updated_at = $created_at_ts_param,
    new_product.processed_at = null
SET new_product += $new_product_properties_param // For other dynamic attributes

// 2. Copy INCOMING relationships
WITH old_entity, new_product
OPTIONAL MATCH (source_node)-[old_rel_in]->(old_entity)
WITH old_entity, new_product, source_node, old_rel_in, type(old_rel_in) AS rel_in_type, properties(old_rel_in) AS rel_in_props
CALL apoc.do.when(old_rel_in IS NOT NULL,
    'CALL apoc.create.relationship(s, rel_type_dyn, props_dyn, np) YIELD rel RETURN rel',
    'RETURN null AS rel',
    {s: source_node, np: new_product, rel_type_dyn: rel_in_type, props_dyn: rel_in_props}
) YIELD value AS in_rel_creation_result
WITH old_entity, new_product, count(in_rel_creation_result.rel) AS copied_incoming_rels_count

// 3. Copy OUTGOING relationships
WITH old_entity, new_product, copied_incoming_rels_count
OPTIONAL MATCH (old_entity)-[old_rel_out]->(target_node)
WITH old_entity, new_product, copied_incoming_rels_count, target_node, old_rel_out, type(old_rel_out) AS rel_out_type, properties(old_rel_out) AS rel_out_props
CALL apoc.do.when(old_rel_out IS NOT NULL,
    'CALL apoc.create.relationship(np, rel_type_dyn, props_dyn, t) YIELD rel RETURN rel',
    'RETURN null AS rel',
    {np: new_product, t: target_node, rel_type_dyn: rel_out_type, props_dyn: rel_out_props}
) YIELD value AS out_rel_creation_result
WITH old_entity, new_product, copied_incoming_rels_count, count(out_rel_creation_result.rel) AS copied_outgoing_rels_count

// 4. Detach and Delete the old Entity node
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
ON CREATE SET 
    r.uuid = $mention_uuid_param, // ADDED
    r.created_at = $created_at_ts_param,
    r.fact_sentence = $fact_sentence_param, 
    r.source_chunk_uuid = $chunk_uuid_param   
ON MATCH SET 
    r.last_seen_in_chunk_at = $created_at_ts_param,
    r.fact_sentence = $fact_sentence_param  
RETURN type(r) AS relationship_type, r.uuid AS relationship_uuid // Return UUID
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
WITH node, score // node and score are in scope here

CALL (node) { // Explicitly pass 'node' into the subquery scope
    MATCH (node)-[r_out:RELATES_TO]->(other_out)
    RETURN {type: 'RELATES_TO_OUTGOING', label: r_out.relation_label, fact: r_out.fact_sentence, target_node_name: other_out.name, target_node_uuid: other_out.uuid, target_node_labels: labels(other_out)} AS rel_map 
    LIMIT 3
}
WITH node, score, collect(rel_map) AS outgoing_rels_data

CALL (node) { // Explicitly pass 'node'
    MATCH (other_in)-[r_in:RELATES_TO]->(node)
    RETURN {type: 'RELATES_TO_INCOMING', label: r_in.relation_label, fact: r_in.fact_sentence, source_node_name: other_in.name, source_node_uuid: other_in.uuid, source_node_labels: labels(other_in)} AS rel_map 
    LIMIT 3
}
WITH node, score, outgoing_rels_data, collect(rel_map) AS incoming_rels_data

CALL (node) { // Explicitly pass 'node'
    MATCH (chunk:Chunk)-[m:MENTIONS]->(node)
    RETURN {type: 'MENTIONED_IN_CHUNK', fact: m.fact_sentence, mentioning_chunk_name: chunk.name, mentioning_chunk_uuid: chunk.uuid} AS rel_map 
    LIMIT 3
}
WITH node, score, outgoing_rels_data, incoming_rels_data, collect(rel_map) AS mentions_data

WITH node, score, 
     (CASE WHEN outgoing_rels_data IS NULL THEN [] ELSE outgoing_rels_data END) +
     (CASE WHEN incoming_rels_data IS NULL THEN [] ELSE incoming_rels_data END) +
     (CASE WHEN mentions_data IS NULL THEN [] ELSE mentions_data END) AS all_connected_facts_raw
WITH node, score, [item IN all_connected_facts_raw WHERE item IS NOT NULL AND item.type IS NOT NULL] AS all_connected_facts

RETURN node.uuid AS uuid, node.name AS name, node.label AS label,
       score, "keyword_name" AS method_source,
       all_connected_facts[0..5] AS connected_facts
"""

ENTITY_SEARCH_SEMANTIC_NAME_PART = """
CALL db.index.vector.queryNodes($index_name_semantic_entity_name, $semantic_limit_entity_name, $semantic_embedding_entity_name)
YIELD node, score
WHERE node:Entity AND score >= $semantic_min_score_entity_name
WITH node, score

CALL (node) {
    MATCH (node)-[r_out:RELATES_TO]->(other_out)
    RETURN {type: 'RELATES_TO_OUTGOING', label: r_out.relation_label, fact: r_out.fact_sentence, target_node_name: other_out.name, target_node_uuid: other_out.uuid, target_node_labels: labels(other_out)} AS rel_map LIMIT 3
}
WITH node, score, collect(rel_map) AS outgoing_rels_data

CALL (node) {
    MATCH (other_in)-[r_in:RELATES_TO]->(node)
    RETURN {type: 'RELATES_TO_INCOMING', label: r_in.relation_label, fact: r_in.fact_sentence, source_node_name: other_in.name, source_node_uuid: other_in.uuid, source_node_labels: labels(other_in)} AS rel_map LIMIT 3
}
WITH node, score, outgoing_rels_data, collect(rel_map) AS incoming_rels_data

CALL (node) {
    MATCH (chunk:Chunk)-[m:MENTIONS]->(node)
    RETURN {type: 'MENTIONED_IN_CHUNK', fact: m.fact_sentence, mentioning_chunk_name: chunk.name, mentioning_chunk_uuid: chunk.uuid} AS rel_map LIMIT 3
}
WITH node, score, outgoing_rels_data, incoming_rels_data, collect(rel_map) AS mentions_data

WITH node, score, 
     (CASE WHEN outgoing_rels_data IS NULL THEN [] ELSE outgoing_rels_data END) +
     (CASE WHEN incoming_rels_data IS NULL THEN [] ELSE incoming_rels_data END) +
     (CASE WHEN mentions_data IS NULL THEN [] ELSE mentions_data END) AS all_connected_facts_raw
WITH node, score, [item IN all_connected_facts_raw WHERE item IS NOT NULL AND item.type IS NOT NULL] AS all_connected_facts

RETURN node.uuid AS uuid, node.name AS name, node.label AS label, 
       score, "semantic_name" AS method_source,
       all_connected_facts[0..5] AS connected_facts
"""

# ENTITY_SEARCH_SEMANTIC_DESCRIPTION_PART = """
# CALL db.index.vector.queryNodes($index_name_semantic_entity_desc, $semantic_limit_entity_desc, $semantic_embedding_entity_desc)
# YIELD node, score
# WHERE node:Entity AND score >= $semantic_min_score_entity_desc
# RETURN node.uuid AS uuid, node.name AS name, node.label AS label, node.description AS description,
#        score, "semantic_description" AS method_source
# """

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

# --- Product Search Query Parts (New) ---

PRODUCT_SEARCH_KEYWORD_PART = """
CALL db.index.fulltext.queryNodes($index_name_keyword_product, $keyword_query_string_product, {limit: $keyword_limit_param_product})
YIELD node, score
WHERE node:Product
WITH node, score

CALL (node) {
    MATCH (node)-[r_out:RELATES_TO]->(other_out)
    RETURN {type: 'RELATES_TO_OUTGOING', label: r_out.relation_label, fact: r_out.fact_sentence, target_node_name: other_out.name, target_node_uuid: other_out.uuid, target_node_labels: labels(other_out)} AS rel_map LIMIT 3
}
WITH node, score, collect(rel_map) AS outgoing_rels_data

CALL (node) {
    MATCH (other_in)-[r_in:RELATES_TO]->(node)
    RETURN {type: 'RELATES_TO_INCOMING', label: r_in.relation_label, fact: r_in.fact_sentence, source_node_name: other_in.name, source_node_uuid: other_in.uuid, source_node_labels: labels(other_in)} AS rel_map LIMIT 3
}
WITH node, score, outgoing_rels_data, collect(rel_map) AS incoming_rels_data

CALL (node) {
    MATCH (chunk:Chunk)-[m:MENTIONS]->(node)
    RETURN {type: 'MENTIONED_IN_CHUNK', fact: m.fact_sentence, mentioning_chunk_name: chunk.name, mentioning_chunk_uuid: chunk.uuid} AS rel_map LIMIT 3
}
WITH node, score, outgoing_rels_data, incoming_rels_data, collect(rel_map) AS mentions_data

WITH node, score, 
     (CASE WHEN outgoing_rels_data IS NULL THEN [] ELSE outgoing_rels_data END) +
     (CASE WHEN incoming_rels_data IS NULL THEN [] ELSE incoming_rels_data END) +
     (CASE WHEN mentions_data IS NULL THEN [] ELSE mentions_data END) AS all_connected_facts_raw
WITH node, score, [item IN all_connected_facts_raw WHERE item IS NOT NULL AND item.type IS NOT NULL] AS all_connected_facts

RETURN node.uuid AS uuid, node.name AS name, node.content AS content,
       node.sku AS sku, node.price AS price,
       score, "keyword_name_content" AS method_source,
       all_connected_facts[0..5] AS connected_facts
"""

PRODUCT_SEARCH_SEMANTIC_NAME_PART = """
CALL db.index.vector.queryNodes($index_name_semantic_product_name, $semantic_limit_product_name, $semantic_embedding_product_name)
YIELD node, score
WHERE node:Product AND score >= $semantic_min_score_product_name
WITH node, score

CALL (node) {
    MATCH (node)-[r_out:RELATES_TO]->(other_out)
    RETURN {type: 'RELATES_TO_OUTGOING', label: r_out.relation_label, fact: r_out.fact_sentence, target_node_name: other_out.name, target_node_uuid: other_out.uuid, target_node_labels: labels(other_out)} AS rel_map LIMIT 3
}
WITH node, score, collect(rel_map) AS outgoing_rels_data

CALL (node) {
    MATCH (other_in)-[r_in:RELATES_TO]->(node)
    RETURN {type: 'RELATES_TO_INCOMING', label: r_in.relation_label, fact: r_in.fact_sentence, source_node_name: other_in.name, source_node_uuid: other_in.uuid, source_node_labels: labels(other_in)} AS rel_map LIMIT 3
}
WITH node, score, outgoing_rels_data, collect(rel_map) AS incoming_rels_data

CALL (node) {
    MATCH (chunk:Chunk)-[m:MENTIONS]->(node)
    RETURN {type: 'MENTIONED_IN_CHUNK', fact: m.fact_sentence, mentioning_chunk_name: chunk.name, mentioning_chunk_uuid: chunk.uuid} AS rel_map LIMIT 3
}
WITH node, score, outgoing_rels_data, incoming_rels_data, collect(rel_map) AS mentions_data

WITH node, score, 
     (CASE WHEN outgoing_rels_data IS NULL THEN [] ELSE outgoing_rels_data END) +
     (CASE WHEN incoming_rels_data IS NULL THEN [] ELSE incoming_rels_data END) +
     (CASE WHEN mentions_data IS NULL THEN [] ELSE mentions_data END) AS all_connected_facts_raw
WITH node, score, [item IN all_connected_facts_raw WHERE item IS NOT NULL AND item.type IS NOT NULL] AS all_connected_facts

RETURN node.uuid AS uuid, node.name AS name, node.content AS content,
       node.sku AS sku, node.price AS price,
       score, "semantic_name" AS method_source,
       all_connected_facts[0..5] AS connected_facts
"""

PRODUCT_SEARCH_SEMANTIC_CONTENT_PART = """
CALL db.index.vector.queryNodes($index_name_semantic_product_content, $semantic_limit_product_content, $semantic_embedding_product_content)
YIELD node, score
WHERE node:Product AND score >= $semantic_min_score_product_content
WITH node, score

CALL (node) {
    MATCH (node)-[r_out:RELATES_TO]->(other_out)
    RETURN {type: 'RELATES_TO_OUTGOING', label: r_out.relation_label, fact: r_out.fact_sentence, target_node_name: other_out.name, target_node_uuid: other_out.uuid, target_node_labels: labels(other_out)} AS rel_map LIMIT 3
}
WITH node, score, collect(rel_map) AS outgoing_rels_data

CALL (node) {
    MATCH (other_in)-[r_in:RELATES_TO]->(node)
    RETURN {type: 'RELATES_TO_INCOMING', label: r_in.relation_label, fact: r_in.fact_sentence, source_node_name: other_in.name, source_node_uuid: other_in.uuid, source_node_labels: labels(other_in)} AS rel_map LIMIT 3
}
WITH node, score, outgoing_rels_data, collect(rel_map) AS incoming_rels_data

CALL (node) {
    MATCH (chunk:Chunk)-[m:MENTIONS]->(node)
    RETURN {type: 'MENTIONED_IN_CHUNK', fact: m.fact_sentence, mentioning_chunk_name: chunk.name, mentioning_chunk_uuid: chunk.uuid} AS rel_map LIMIT 3
}
WITH node, score, outgoing_rels_data, incoming_rels_data, collect(rel_map) AS mentions_data

WITH node, score, 
     (CASE WHEN outgoing_rels_data IS NULL THEN [] ELSE outgoing_rels_data END) +
     (CASE WHEN incoming_rels_data IS NULL THEN [] ELSE incoming_rels_data END) +
     (CASE WHEN mentions_data IS NULL THEN [] ELSE mentions_data END) AS all_connected_facts_raw
WITH node, score, [item IN all_connected_facts_raw WHERE item IS NOT NULL AND item.type IS NOT NULL] AS all_connected_facts

RETURN node.uuid AS uuid, node.name AS name, node.content AS content,
       node.sku AS sku, node.price AS price,
       score, "semantic_content" AS method_source,
       all_connected_facts[0..5] AS connected_facts
"""

# --- Mention Search Query Parts (New) ---
MENTION_SEARCH_KEYWORD_PART = """
CALL db.index.fulltext.queryRelationships($index_name_keyword_mention_fact, $keyword_query_string_mention_fact, {limit: $keyword_limit_param_mention_fact})
YIELD relationship, score
// Match the MENTIONS relationship and its source (Chunk) and target (Entity or Product)
MATCH (source_node)-[r:MENTIONS]->(target_node) WHERE elementId(r) = elementId(relationship)
RETURN r.uuid AS uuid, 
       r.fact_sentence AS fact_sentence,
       source_node.uuid AS source_node_uuid, // UUID of the Chunk (or other mentioning node)
       target_node.uuid AS target_node_uuid, // UUID of the Entity/Product being mentioned
       target_node.name AS name, // Name of the Entity/Product being mentioned
       labels(target_node) as target_node_labels, // To distinguish Entity from Product target
       score, "keyword_fact" AS method_source
"""

MENTION_SEARCH_SEMANTIC_PART = """
CALL db.index.vector.queryRelationships($index_name_semantic_mention_fact, $semantic_limit_mention_fact, $semantic_embedding_mention_fact)
YIELD relationship, score
// Match the MENTIONS relationship and its source (Chunk) and target (Entity or Product)
MATCH (source_node)-[r:MENTIONS]->(target_node) WHERE elementId(r) = elementId(relationship) AND score >= $semantic_min_score_mention_fact
RETURN r.uuid AS uuid,
       r.fact_sentence AS fact_sentence,
       source_node.uuid AS source_node_uuid, 
       target_node.uuid AS target_node_uuid,
       target_node.name AS name,
       labels(target_node) as target_node_labels,
       score, "semantic_fact" AS method_source
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
CREATE_FULLTEXT_ENTITY_NAME = "CREATE FULLTEXT INDEX entity_name_ft IF NOT EXISTS FOR (e:Entity) ON EACH [e.name]"
CREATE_FULLTEXT_RELATIONSHIP_FACT = """
CREATE FULLTEXT INDEX relationship_fact_ft IF NOT EXISTS 
FOR ()-[r:RELATES_TO]-() ON EACH [r.relation_label, r.fact_sentence]
""" 
CREATE_FULLTEXT_PRODUCT_NAME_CONTENT = "CREATE FULLTEXT INDEX product_name_content_ft IF NOT EXISTS FOR (p:Product) ON EACH [p.name, p.content]"

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

# --- Orphaned Entity Cleanup ---
DELETE_ORPHANED_ENTITIES = """
MATCH (e:Entity)
OPTIONAL MATCH (origin)-[:MENTIONS]->(e)
OPTIONAL MATCH (e)-[rel_relates_to:RELATES_TO]-()
WITH e, collect(DISTINCT origin) AS mention_origins, collect(DISTINCT rel_relates_to) AS all_relates_to
WHERE size(mention_origins) = 0 AND size(all_relates_to) = 0
WITH e // Ensure 'e' is carried over for deletion; not strictly necessary here but good practice if more clauses followed
DETACH DELETE e
RETURN count(e) AS deleted_count
"""

# ... (at an appropriate place, perhaps grouped with other deletion/lifecycle queries)

# --- Source Deletion Queries ---
GET_CHUNKS_FOR_SOURCE = "MATCH (s:Source {uuid: $source_uuid})<-[:BELONGS_TO_SOURCE]-(c:Chunk) RETURN c.uuid AS node_uuid"
GET_PRODUCTS_FOR_SOURCE = "MATCH (s:Source {uuid: $source_uuid})<-[:BELONGS_TO_SOURCE]-(p:Product) RETURN p.uuid AS node_uuid"

GET_MENTIONED_TARGETS_BY_ORIGINS = """
MATCH (origin_node)-[:MENTIONS]->(target_node)
WHERE origin_node.uuid IN $origin_uuids
RETURN DISTINCT target_node.uuid AS target_uuid, target_node.name AS target_name, labels(target_node) AS target_labels
"""

# Query for collecting a broader set of potentially orphaned nodes
GET_POTENTIAL_ORPHANS_CONNECTED_TO_ORIGINS = """
UNWIND $origin_uuids AS origin_uuid
MATCH (origin_node {uuid: origin_uuid})
// Explicitly pass origin_node into the CALL subquery scope if it's used across UNIONs
// The parameter $origin_uuids is globally available to all parts of the subquery.
CALL {
    WITH origin_node // origin_node is needed in all UNION parts
    MATCH (origin_node)-[:MENTIONS]->(target)
    RETURN target AS candidate_node
    UNION
    WITH origin_node // origin_node is needed
    MATCH (origin_node)-[r:RELATES_TO]->(target)
    WHERE r.source_chunk_uuid = origin_node.uuid
    RETURN target AS candidate_node
    UNION
    WITH origin_node // origin_node is needed
    MATCH (source_entity)-[r:RELATES_TO]->(origin_node)
    // $origin_uuids is directly accessible here as it's a query parameter
    WHERE r.source_chunk_uuid = origin_node.uuid 
          OR (r.source_chunk_uuid IN $origin_uuids AND r.source_chunk_uuid <> origin_node.uuid) 
    RETURN source_entity AS candidate_node
}
WITH candidate_node // Apply WHERE after CALL
WHERE (candidate_node:Entity OR candidate_node:Product) 
RETURN DISTINCT candidate_node.uuid AS node_uuid, 
                candidate_node.name AS node_name, 
                labels(candidate_node) AS node_labels
"""

DELETE_RELATES_TO_BY_SOURCE_CHUNK_UUIDS = """
MATCH ()-[r:RELATES_TO]->()
WHERE r.source_chunk_uuid IN $origin_uuids
WITH r, r.uuid as rel_uuid
DELETE r
RETURN count(rel_uuid) as deleted_count
"""

DELETE_MENTIONS_BY_ORIGIN_UUIDS = "MATCH (origin_node)-[m:MENTIONS]->() WHERE origin_node.uuid IN $origin_uuids DELETE m RETURN count(m) as total_deleted"

CHECK_ENTITY_MENTIONED_BY_OTHERS = """
MATCH (other_origin)-[:MENTIONS]->(e:Entity {uuid: $entity_uuid})
WHERE NOT other_origin.uuid IN $deleted_origin_uuids
RETURN count(other_origin) > 0 AS is_mentioned_by_others
"""

CHECK_ENTITY_HAS_OTHER_RELATIONSHIPS = """
MATCH (e:Entity {uuid: $entity_uuid})-[r:RELATES_TO]-()
WHERE NOT r.source_chunk_uuid IN $deleted_origin_uuids OR r.source_chunk_uuid IS NULL
RETURN count(r) > 0 AS has_other_relationships
"""

DELETE_ENTITIES_BY_UUIDS = "MATCH (e:Entity) WHERE e.uuid IN $entity_uuids DETACH DELETE e RETURN count(e) as deleted_count"

GET_PRODUCT_DETAILS_FOR_DEMOTION = "MATCH (p:Product {uuid: $uuid}) RETURN p.name AS name, p.category AS category"

CHECK_PRODUCT_MENTIONED_EXTERNALLY = """
MATCH (other_origin)-[m:MENTIONS]->(p:Product {uuid: $product_uuid})
WHERE NOT other_origin.uuid IN $deleted_origin_uuids
RETURN count(m) > 0 AS is_mentioned_externally
"""

CHECK_PRODUCT_RELATED_EXTERNALLY_AS_TARGET = """
MATCH (other_node)-[r:RELATES_TO]->(p:Product {uuid: $product_uuid})
WHERE (r.source_chunk_uuid IS NOT NULL AND NOT r.source_chunk_uuid IN $deleted_origin_uuids) OR 
      (r.source_chunk_uuid IS NULL AND NOT other_node.uuid IN $deleted_origin_uuids) 
RETURN count(r) > 0 AS is_related_to_as_target_externally
"""

CREATE_DEMOTED_ENTITY_FROM_PRODUCT = """
CREATE (e:Entity {
    uuid: $new_uuid,
    name: $name,
    label: $label,
    original_product_uuid: $original_uuid,
    demoted_at: datetime(),
    source_of_demotion_info: 'Demoted from Product due to source deletion'
})
"""

RELINK_MENTIONS_TO_DEMOTED_ENTITY = """
MATCH (origin_node)-[old_m:MENTIONS]->(p:Product {uuid: $original_product_uuid})
WHERE NOT origin_node.uuid IN $deleted_origin_uuids 
WITH origin_node, old_m, p
MATCH (demoted_e:Entity {uuid: $new_demoted_entity_uuid})
CREATE (origin_node)-[new_m:MENTIONS]->(demoted_e)
SET new_m = properties(old_m)
REMOVE new_m.uuid 
SET new_m.uuid = randomUUID()  // CHANGED from apoc.create.uuid()
DELETE old_m
RETURN count(new_m) as relinked_count
"""

RELINK_INCOMING_RELATES_TO_TO_DEMOTED_ENTITY = """
MATCH (origin_node)-[old_r:RELATES_TO]->(p:Product {uuid: $original_product_uuid})
WHERE (old_r.source_chunk_uuid IS NOT NULL AND NOT old_r.source_chunk_uuid IN $deleted_origin_uuids) OR
      (old_r.source_chunk_uuid IS NULL AND NOT origin_node.uuid IN $deleted_origin_uuids)
WITH origin_node, old_r, p
MATCH (demoted_e:Entity {uuid: $new_demoted_entity_uuid})
CREATE (origin_node)-[new_r:RELATES_TO]->(demoted_e)
SET new_r = properties(old_r)
REMOVE new_r.uuid
SET new_r.uuid = randomUUID() // CHANGED from apoc.create.uuid()
DELETE old_r
RETURN count(new_r) as relinked_count
"""

RELINK_OUTGOING_RELATES_TO_FROM_DEMOTED_ENTITY = """
MATCH (p:Product {uuid: $original_product_uuid})-[old_r:RELATES_TO]->(target_node)
WITH p, old_r, target_node
MATCH (demoted_e:Entity {uuid: $new_demoted_entity_uuid})
CREATE (demoted_e)-[new_r:RELATES_TO]->(target_node)
SET new_r = properties(old_r)
SET new_r.source_chunk_uuid = CASE 
                              WHEN old_r.source_chunk_uuid = $original_product_uuid THEN $new_demoted_entity_uuid
                              ELSE old_r.source_chunk_uuid
                            END
REMOVE new_r.uuid
SET new_r.uuid = randomUUID() // CHANGED from apoc.create.uuid()
DELETE old_r
RETURN count(new_r) as relinked_count
"""

DELETE_PRODUCT_BY_UUID_DETACH = "MATCH (p:Product {uuid: $uuid}) DETACH DELETE p RETURN count(p) as deleted_product_count" # Used for demoted products
DELETE_PRODUCTS_BY_UUIDS_DETACH = "MATCH (p:Product) WHERE p.uuid IN $product_uuids DETACH DELETE p RETURN count(p) as deleted_count" # Used for non-demoted products
DELETE_CHUNKS_BY_UUIDS_DETACH = "MATCH (c:Chunk) WHERE c.uuid IN $chunk_uuids DETACH DELETE c RETURN count(c) as deleted_count"
DELETE_SOURCE_BY_UUID_DETACH = "MATCH (s:Source {uuid: $source_uuid}) DETACH DELETE s RETURN count(s) as deleted_count"