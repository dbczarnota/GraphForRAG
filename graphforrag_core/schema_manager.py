# graphforrag_core/schema_manager.py
import logging
import re
from neo4j import AsyncDriver # type: ignore
from config import cypher_queries # Assuming your cypher_queries.py is in a config directory
from .embedder_client import EmbedderClient 

logger = logging.getLogger("graph_for_rag.schema")

# Properties we will not attempt to create B-Tree indexes on dynamically
# (either already indexed, complex, or vector indexed)
EXCLUDED_PROPERTIES_FOR_DYNAMIC_BTREE = [
    'uuid', 'name', 'content', 'content_embedding', 'created_at', 
    'source_description', 'chunk_number', 'processed_at', 
    'entity_count', 'relationship_count'
    # Add other known non-scalar or special properties if any
]

# Neo4j data types that are generally suitable for B-Tree indexing
SUITABLE_BTREE_TYPES = [
    "STRING", "INTEGER", "FLOAT", "BOOLEAN", 
    "DATE", "DATETIME", "LOCAL_DATETIME", "TIME", "LOCAL_TIME"
    # We might exclude "POINT", "DURATION" explicitly if not desired for general indexing
]


class SchemaManager:
    def __init__(self, driver: AsyncDriver, database: str, embedder: EmbedderClient):
        self.driver: AsyncDriver = driver
        self.database: str = database
        self.embedder: EmbedderClient = embedder

    async def _get_dynamic_properties_for_btree_indexing(self, node_label: str) -> list[str]:
        """
        Fetches distinct, scalar property keys for a given label suitable for B-Tree indexing,
        using APOC to inspect schema.
        """
        logger.debug(f"Fetching dynamic properties for B-Tree indexing on label: {node_label}")
        properties_to_index: list[str] = []
        try:
            # Query to get schema information for the given label using APOC
            # This query focuses on properties of nodes with the specified label
            query_string_get_props_with_apoc = f"""
            CALL apoc.meta.schema() YIELD value
            UNWIND value AS node_meta
            WITH node_meta WHERE node_meta.name = '{node_label}' AND node_meta.type = 'node'
            UNWIND keys(node_meta.properties) AS prop_name
            WITH prop_name, node_meta.properties[prop_name].type AS prop_type
            WHERE NOT prop_name IN $excluded_props AND prop_type IN $suitable_types
            RETURN DISTINCT prop_name
            """
            
            results, _, _ = await self.driver.execute_query( # type: ignore
                query_string_get_props_with_apoc,
                excluded_props=EXCLUDED_PROPERTIES_FOR_DYNAMIC_BTREE,
                suitable_types=SUITABLE_BTREE_TYPES,
                database_=self.database
            )
            properties_to_index = [record["prop_name"] for record in results]
            logger.debug(f"Found suitable dynamic properties for {node_label}: {properties_to_index}")
            
        except Exception as e:
            # Check if it's an APOC availability error
            if "Unknown function 'apoc.meta.schema'" in str(e) or \
               "No function with name `apoc.meta.schema`" in str(e):
                logger.warning(
                    f"APOC procedure 'apoc.meta.schema' not found or not available. "
                    f"Falling back to non-APOC method for discovering properties for label '{node_label}'. "
                    f"Dynamic indexing might be less precise regarding property types."
                )
                # Fallback to the previous method if APOC is not available
                # (this is the method from the previous step, slightly adapted)
                fallback_query = f"""
                    MATCH (n:{node_label})
                    UNWIND keys(properties(n)) AS key
                    WITH DISTINCT key
                    WHERE NOT key IN $excluded_props
                    RETURN key
                """
                results, _, _ = await self.driver.execute_query( # type: ignore
                    fallback_query,
                    excluded_props=EXCLUDED_PROPERTIES_FOR_DYNAMIC_BTREE,
                    database_=self.database
                )
                properties_to_index = [record["key"] for record in results]
            else:
                logger.error(f"Error fetching dynamic property keys using APOC for label '{node_label}': {e}", exc_info=True)
        
        return properties_to_index

    async def ensure_indices_and_constraints(self):
        logger.info("Ensuring database indices and constraints...")
        
        static_queries_and_params = [
            # ... (Chunk and Source constraints/indexes) ...
            (cypher_queries.CREATE_CONSTRAINT_CHUNK_UUID, {}),
            (cypher_queries.CREATE_CONSTRAINT_SOURCE_UUID, {}),
            (cypher_queries.CREATE_CONSTRAINT_SOURCE_NAME, {}),
            (cypher_queries.CREATE_INDEX_CHUNK_NAME, {}),
            (cypher_queries.CREATE_INDEX_CHUNK_SOURCE_DESC_NUM, {}),
            (cypher_queries.CREATE_INDEX_SOURCE_CONTENT, {}),
            (cypher_queries.CREATE_FULLTEXT_CHUNK_CONTENT, {}),
            (cypher_queries.CREATE_FULLTEXT_SOURCE_CONTENT, {}),

            # Entity constraints & static indexes
            (cypher_queries.CREATE_CONSTRAINT_ENTITY_UUID, {}),
            (cypher_queries.CREATE_INDEX_ENTITY_NAME, {}), 
            (cypher_queries.CREATE_INDEX_ENTITY_LABEL, {}),
            (cypher_queries.CREATE_INDEX_ENTITY_NORMALIZED_NAME_LABEL, {}), # <-- ADDED
            (cypher_queries.CREATE_FULLTEXT_ENTITY_NAME_DESC, {}),
        ]

        # ... (Vector index creation for Chunk, Source, Entity remains the same) ...
        # Vector Index for Chunk content_embedding
        chunk_node_label = "Chunk"
        chunk_property_name = "content_embedding"
        chunk_vector_index_name = f"{chunk_node_label.lower()}_{chunk_property_name}_vector"
        create_vector_index_chunk_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", chunk_vector_index_name
        ).replace("$node_label", chunk_node_label).replace("$property_name", chunk_property_name).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_chunk_query, {}))

        # Vector Index for Source content_embedding
        source_node_label = "Source"
        source_property_name = "content_embedding"
        source_vector_index_name = f"{source_node_label.lower()}_{source_property_name}_vector"
        create_vector_index_source_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", source_vector_index_name
        ).replace("$node_label", source_node_label).replace("$property_name", source_property_name).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_source_query, {}))

        # Vector Index for Entity name_embedding
        entity_node_label = "Entity"
        entity_property_name = "name_embedding"
        entity_vector_index_name = f"{entity_node_label.lower()}_{entity_property_name}_vector"
        create_vector_index_entity_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", entity_vector_index_name
        ).replace("$node_label", entity_node_label).replace("$property_name", entity_property_name).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_entity_query, {}))
        
        all_queries_to_run = list(static_queries_and_params)

        for node_label in ["Chunk", "Source", "Entity"]:
            dynamic_props = await self._get_dynamic_properties_for_btree_indexing(node_label)
            for prop_key in dynamic_props:
                # Ensure prop_key is safe (though it comes from DB)
                # Basic sanitization: replace potential problematic characters for index names if any, or ensure it's simple
                safe_prop_key_for_name = re.sub(r'[^a-zA-Z0-9_]', '_', prop_key)
                index_name = f"dynamic_idx_{node_label.lower()}_{safe_prop_key_for_name.lower()}"
                # Property key in Cypher needs backticks if it contains special chars or spaces
                safe_prop_key_for_cypher = prop_key.replace("`", "``")
                
                dynamic_index_query = f"CREATE INDEX {index_name} IF NOT EXISTS FOR (n:{node_label}) ON (n.`{safe_prop_key_for_cypher}`)"
                all_queries_to_run.append((dynamic_index_query, {}))
                logger.debug(f"Prepared dynamic index query for {node_label} on property '{prop_key}' with name '{index_name}'")

        async with self.driver.session(database=self.database) as session:
            for query_string, params in all_queries_to_run:
                try:
                    logger.debug(f"Executing: {query_string.strip()} with params {params if params else ''}")
                    await session.run(query_string, params)
                except Exception as e:
                    if "dynamic_idx_" in query_string:
                         logger.warning(f"Could not create dynamic index with query '{query_string.strip()}'. Error: {e}")
                    else: 
                        logger.error(f"Error creating static index/constraint with query '{query_string.strip()}': {e}", exc_info=True)
        logger.info("Finished ensuring database indices and constraints.")


    async def clear_all_known_indexes_and_constraints(self):
        logger.warning("Attempting to drop known indexes and constraints...")
        
        queries_to_drop_str = [
            # ... (existing chunk and source drops) ...
            cypher_queries.DROP_INDEX_CHUNK_NAME,
            cypher_queries.DROP_INDEX_CHUNK_SOURCE_DESC_NUM,
            cypher_queries.DROP_INDEX_SOURCE_CONTENT,
            
            cypher_queries.DROP_INDEX_ENTITY_NAME,
            cypher_queries.DROP_INDEX_ENTITY_LABEL,
            cypher_queries.DROP_INDEX_ENTITY_NORMALIZED_NAME_LABEL, # <-- ADDED

            cypher_queries.DROP_FULLTEXT_CHUNK_CONTENT, 
            cypher_queries.DROP_FULLTEXT_SOURCE_CONTENT, 
            cypher_queries.DROP_FULLTEXT_ENTITY_NAME_DESC,

            cypher_queries.DROP_CONSTRAINT_CHUNK_UUID,
            cypher_queries.DROP_CONSTRAINT_SOURCE_UUID,
            cypher_queries.DROP_CONSTRAINT_SOURCE_NAME,
            cypher_queries.DROP_CONSTRAINT_ENTITY_UUID,
        ]
        
        # ... (vector index drop logic for Chunk, Source, Entity) ...
        chunk_vector_index_name = "chunk_content_embedding_vector" # Match defined name
        queries_to_drop_str.append(f"DROP INDEX {chunk_vector_index_name} IF EXISTS")

        source_vector_index_name = "source_content_embedding_vector" # Match defined name
        queries_to_drop_str.append(f"DROP INDEX {source_vector_index_name} IF EXISTS")
        
        entity_vector_index_name = "entity_name_embedding_vector" # Match defined name
        queries_to_drop_str.append(f"DROP INDEX {entity_vector_index_name} IF EXISTS")

        for node_label in ["Chunk", "Source", "Entity"]:
            try:
                dynamic_props = await self._get_dynamic_properties_for_btree_indexing(node_label)
                for prop_key in dynamic_props:
                    safe_prop_key_for_name = re.sub(r'[^a-zA-Z0-9_]', '_', prop_key)
                    index_name = f"dynamic_idx_{node_label.lower()}_{safe_prop_key_for_name.lower()}"
                    queries_to_drop_str.append(f"DROP INDEX {index_name} IF EXISTS")
            except Exception as e:
                logger.error(f"Could not prepare dynamic indexes for dropping on label {node_label}: {e}")
        
        # ... (rest of method) ...
        async with self.driver.session(database=self.database) as session:
            for query_string in queries_to_drop_str:
                try:
                    logger.debug(f"Executing: {query_string.strip()}")
                    result = await session.run(query_string)
                    await result.consume() 
                except Exception as e:
                    logger.warning(f"Potentially ignorable error dropping index/constraint with query '{query_string.strip()}': {e}", exc_info=False)
        logger.info("Finished attempting to drop known indexes and constraints.")

    async def clear_all_data(self):
        logger.warning("Attempting to delete ALL nodes and relationships from the database...")
        try:
            async with self.driver.session(database=self.database) as session:
                result = await session.run(cypher_queries.CLEAR_ALL_NODES_AND_RELATIONSHIPS)
                summary = await result.consume()

                logger.info(
                    f"Successfully cleared all data. Nodes deleted: {summary.counters.nodes_deleted}, "
                    f"Relationships deleted: {summary.counters.relationships_deleted}"
                )
        except Exception as e:
            logger.error(f"Error clearing all data: {e}", exc_info=True)
            raise