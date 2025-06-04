# graphforrag_core/schema_manager.py
import logging
import re
from neo4j import AsyncDriver # type: ignore
from config import cypher_queries # Import the whole module
from .embedder_client import EmbedderClient 

logger = logging.getLogger("graph_for_rag.schema")

class SchemaManager:
    def __init__(self, driver: AsyncDriver, database: str, embedder: EmbedderClient):
        self.driver: AsyncDriver = driver
        self.database: str = database
        self.embedder: EmbedderClient = embedder

    async def _get_dynamic_properties_for_btree_indexing(self, node_label: str) -> list[str]:
        logger.debug(f"Fetching dynamic properties for B-Tree indexing on label: {node_label}")
        properties_to_index: list[str] = []
        try:
            query_string_get_props_with_apoc = """ 
            CALL apoc.meta.schema() YIELD value
            UNWIND value AS node_meta
            WITH node_meta WHERE node_meta.name = $node_label_param AND node_meta.type = 'node'
            UNWIND keys(node_meta.properties) AS prop_name
            WITH prop_name, node_meta.properties[prop_name].type AS prop_type
            WHERE NOT prop_name IN $excluded_props AND prop_type IN $suitable_types
            RETURN DISTINCT prop_name
            """
            results, _, _ = await self.driver.execute_query( # type: ignore
                query_string_get_props_with_apoc,
                node_label_param=node_label,
                excluded_props=cypher_queries.EXCLUDED_PROPERTIES_FOR_DYNAMIC_BTREE,
                suitable_types=cypher_queries.SUITABLE_BTREE_TYPES,
                database_=self.database
            )
            properties_to_index = [record["prop_name"] for record in results]
            logger.debug(f"Found suitable dynamic properties for {node_label} via APOC: {properties_to_index}")
        except Exception as e:
            if "Unknown function 'apoc.meta.schema'" in str(e) or \
               "No function with name `apoc.meta.schema`" in str(e):
                logger.warning(f"APOC procedure 'apoc.meta.schema' not found. Falling back for label '{node_label}'.")
                
                if not re.match(r"^[A-Za-z0-9_]+$", node_label):
                    logger.error(f"Invalid node_label format for fallback query: {node_label}")
                    return []
                
                fallback_query_string = cypher_queries.GET_DISTINCT_PROPERTY_KEYS_FOR_LABEL_FALLBACK_TEMPLATE.replace(
                    "{node_label_placeholder}", node_label
                )
                
                results, _, _ = await self.driver.execute_query( # type: ignore
                    fallback_query_string, 
                    excluded_props_param=cypher_queries.EXCLUDED_PROPERTIES_FOR_DYNAMIC_BTREE, 
                    database_=self.database
                ) 
                properties_to_index = [record["key"] for record in results]
                logger.debug(f"Found suitable dynamic properties for {node_label} via fallback: {properties_to_index}")
            else:
                logger.error(f"Error fetching dynamic property keys using APOC for label '{node_label}': {e}", exc_info=True)
        return properties_to_index

    async def ensure_indices_and_constraints(self):
        logger.info("Ensuring database indices and constraints...")
        
        static_queries_and_params = [
            (cypher_queries.CREATE_CONSTRAINT_CHUNK_UUID, {}),
            (cypher_queries.CREATE_CONSTRAINT_SOURCE_UUID, {}),
            (cypher_queries.CREATE_CONSTRAINT_SOURCE_NAME, {}),
            (cypher_queries.CREATE_CONSTRAINT_ENTITY_UUID, {}),
            (cypher_queries.CREATE_CONSTRAINT_PRODUCT_UUID, {}), # ADDED for Product
            (cypher_queries.CREATE_INDEX_CHUNK_NAME, {}),
            (cypher_queries.CREATE_INDEX_CHUNK_SOURCE_DESC_NUM, {}),
            (cypher_queries.CREATE_INDEX_SOURCE_CONTENT, {}),
            (cypher_queries.CREATE_INDEX_ENTITY_NAME, {}), 
            (cypher_queries.CREATE_INDEX_ENTITY_LABEL, {}),
            (cypher_queries.CREATE_INDEX_ENTITY_NORMALIZED_NAME_LABEL, {}),
            (cypher_queries.CREATE_INDEX_PRODUCT_NAME, {}), # ADDED for Product
            (cypher_queries.CREATE_FULLTEXT_CHUNK_CONTENT, {}),
            (cypher_queries.CREATE_FULLTEXT_SOURCE_CONTENT, {}), 
            (cypher_queries.CREATE_FULLTEXT_ENTITY_NAME_DESC, {}),
            (cypher_queries.CREATE_FULLTEXT_PRODUCT_NAME_DESC, {}), # ADDED for Product
            (cypher_queries.CREATE_INDEX_RELATIONSHIP_LABEL, {}),
            (cypher_queries.CREATE_FULLTEXT_RELATIONSHIP_FACT, {}),
        ]

        # Vector index for Chunk content
        chunk_node_label = "Chunk"
        chunk_property_name = "content_embedding"
        chunk_vector_index_name = f"{chunk_node_label.lower()}_{chunk_property_name}_vector"
        create_vector_index_chunk_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", chunk_vector_index_name
        ).replace("$node_label", chunk_node_label).replace("$property_name", chunk_property_name).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_chunk_query, {}))

        # Vector index for Source content
        source_node_label = "Source"
        source_property_name = "content_embedding"
        source_vector_index_name = f"{source_node_label.lower()}_{source_property_name}_vector" 
        create_vector_index_source_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", source_vector_index_name
        ).replace("$node_label", source_node_label).replace("$property_name", source_property_name).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_source_query, {}))

        # Vector indexes for Entity name and description
        entity_node_label = "Entity"
        entity_name_property = "name_embedding"
        entity_name_vector_index = f"{entity_node_label.lower()}_{entity_name_property}_vector"
        create_vector_index_entity_name_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", entity_name_vector_index
        ).replace("$node_label", entity_node_label).replace("$property_name", entity_name_property).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_entity_name_query, {}))

        entity_desc_property = "description_embedding"
        entity_desc_vector_index = f"{entity_node_label.lower()}_{entity_desc_property}_vector"
        create_vector_index_entity_desc_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", entity_desc_vector_index
        ).replace("$node_label", entity_node_label).replace("$property_name", entity_desc_property).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_entity_desc_query, {}))
        
        # Vector indexes for Product name and description (NEW)
        product_node_label = "Product"
        product_name_property = "name_embedding"
        product_name_vector_index = f"{product_node_label.lower()}_{product_name_property}_vector"
        create_vector_index_product_name_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", product_name_vector_index
        ).replace("$node_label", product_node_label).replace("$property_name", product_name_property).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_product_name_query, {}))

        product_desc_property = "description_embedding"
        product_desc_vector_index = f"{product_node_label.lower()}_{product_desc_property}_vector"
        create_vector_index_product_desc_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", product_desc_vector_index
        ).replace("$node_label", product_node_label).replace("$property_name", product_desc_property).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_product_desc_query, {}))

        # Vector index for Relationship fact
        rel_type_for_vector = "RELATES_TO"
        rel_property_name_for_vector = "fact_embedding"
        rel_vector_index_name = f"{rel_type_for_vector.lower()}_{rel_property_name_for_vector}_vector"
        create_vector_index_rel_query = f"""
        CREATE VECTOR INDEX {rel_vector_index_name} IF NOT EXISTS
        FOR ()-[r:{rel_type_for_vector}]-() ON (r.{rel_property_name_for_vector})
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {self.embedder.dimension},
            `vector.similarity_function`: 'cosine'
        }}}}
        """
        static_queries_and_params.append((create_vector_index_rel_query, {}))
        
        all_queries_to_run = list(static_queries_and_params)

        for node_label in ["Chunk", "Source", "Entity", "Product"]: # ADDED "Product" to list for dynamic B-tree
            dynamic_props = await self._get_dynamic_properties_for_btree_indexing(node_label)
            for prop_key in dynamic_props:
                safe_prop_key_for_name = re.sub(r'[^a-zA-Z0-9_]', '_', prop_key)
                index_name = f"dynamic_idx_{node_label.lower()}_{safe_prop_key_for_name.lower()}"
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
                    logger.error(f"Failed to execute schema query '{query_string.strip()}': {e}", exc_info=True) 
                    if "relationship_fact_ft" in query_string and "CREATE FULLTEXT INDEX" in query_string:
                        logger.error(f"Specifically failed to create full-text index 'relationship_fact_ft': {e}", exc_info=True)
                    
        logger.info("Finished ensuring database indices and constraints.")

    async def clear_all_known_indexes_and_constraints(self):
        logger.warning("Attempting to drop known indexes and constraints...")
        
        queries_to_drop_str = [
            cypher_queries.DROP_INDEX_CHUNK_NAME,
            cypher_queries.DROP_INDEX_CHUNK_SOURCE_DESC_NUM,
            cypher_queries.DROP_INDEX_SOURCE_CONTENT,
            cypher_queries.DROP_INDEX_ENTITY_NAME, 
            cypher_queries.DROP_INDEX_ENTITY_LABEL,
            cypher_queries.DROP_INDEX_ENTITY_NORMALIZED_NAME_LABEL,
            cypher_queries.DROP_INDEX_PRODUCT_NAME, # ADDED for Product
            cypher_queries.DROP_FULLTEXT_CHUNK_CONTENT, 
            cypher_queries.DROP_FULLTEXT_SOURCE_CONTENT, 
            cypher_queries.DROP_FULLTEXT_ENTITY_NAME_DESC,
            cypher_queries.DROP_FULLTEXT_PRODUCT_NAME_DESC, # ADDED for Product
            cypher_queries.DROP_CONSTRAINT_CHUNK_UUID,
            cypher_queries.DROP_CONSTRAINT_SOURCE_UUID,
            cypher_queries.DROP_CONSTRAINT_SOURCE_NAME,
            cypher_queries.DROP_CONSTRAINT_ENTITY_UUID,
            cypher_queries.DROP_CONSTRAINT_PRODUCT_UUID, # ADDED for Product
            cypher_queries.DROP_INDEX_RELATIONSHIP_LABEL,
            "DROP INDEX relationship_fact_ft IF EXISTS", 
        ]
        
        # Vector index drops
        chunk_vector_index_name = "chunk_content_embedding_vector"
        queries_to_drop_str.append(f"DROP INDEX {chunk_vector_index_name} IF EXISTS")
        
        source_vector_index_name = "source_content_embedding_vector" 
        queries_to_drop_str.append(f"DROP INDEX {source_vector_index_name} IF EXISTS") 
        
        entity_name_vector_index = "entity_name_embedding_vector"
        queries_to_drop_str.append(f"DROP INDEX {entity_name_vector_index} IF EXISTS")
        
        entity_desc_vector_index = "entity_description_embedding_vector"
        queries_to_drop_str.append(f"DROP INDEX {entity_desc_vector_index} IF EXISTS")

        # Vector index drops for Product (NEW)
        product_name_vector_index = "product_name_embedding_vector"
        queries_to_drop_str.append(f"DROP INDEX {product_name_vector_index} IF EXISTS")
        
        product_desc_vector_index = "product_description_embedding_vector"
        queries_to_drop_str.append(f"DROP INDEX {product_desc_vector_index} IF EXISTS")

        rel_vector_index_name = "relates_to_fact_embedding_vector"
        queries_to_drop_str.append(f"DROP INDEX {rel_vector_index_name} IF EXISTS")

        for node_label in ["Chunk", "Source", "Entity", "Product"]: # ADDED "Product" to list for dynamic B-tree
            try:
                dynamic_props = await self._get_dynamic_properties_for_btree_indexing(node_label)
                for prop_key in dynamic_props:
                    safe_prop_key_for_name = re.sub(r'[^a-zA-Z0-9_]', '_', prop_key)
                    index_name = f"dynamic_idx_{node_label.lower()}_{safe_prop_key_for_name.lower()}"
                    queries_to_drop_str.append(f"DROP INDEX {index_name} IF EXISTS")
            except Exception as e:
                logger.error(f"Could not prepare dynamic indexes for dropping on label {node_label}: {e}")
        
        async with self.driver.session(database=self.database) as session:
            for query_string in queries_to_drop_str:
                try:
                    logger.debug(f"Executing to drop: {query_string.strip()}")
                    await session.run(query_string)
                except Exception as e:
                    logger.warning(f"Potentially ignorable error dropping index/constraint with query '{query_string.strip()}': {e}", exc_info=False)
        logger.info("Finished attempting to drop known indexes and constraints.")

    async def clear_all_data(self):
        logger.warning("Attempting to delete ALL nodes and relationships from the database...")
        try:
            async with self.driver.session(database=self.database) as session:
                await session.run(cypher_queries.CLEAR_ALL_NODES_AND_RELATIONSHIPS)
            logger.info("Successfully cleared all data.")
        except Exception as e:
            logger.error(f"Error clearing all data: {e}", exc_info=True)
            raise