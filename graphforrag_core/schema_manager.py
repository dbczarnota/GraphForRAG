# graphforrag_core/schema_manager.py
import logging
import re
from neo4j import AsyncDriver # type: ignore
from config import cypher_queries # Import the whole module
from .embedder_client import EmbedderClient
from .types import FlaggedPropertiesConfig
from dotenv import load_dotenv
import os
import textwrap
from langchain_neo4j import Neo4jGraph
from typing import List, Optional

logger = logging.getLogger("graph_for_rag.schema")

class SchemaManager:
    def __init__(self, driver: AsyncDriver, database: str, embedder: EmbedderClient, flagged_properties_config: Optional[FlaggedPropertiesConfig] = None):
        self.driver: AsyncDriver = driver
        self.database: str = database
        self.embedder: EmbedderClient = embedder
        self.flagged_properties_config = flagged_properties_config if flagged_properties_config else FlaggedPropertiesConfig() # Store the config

    async def _get_distinct_property_values(self, node_label: str, property_name: str, limit: int) -> Optional[List[str]]:
        """
        Fetches distinct non-null string values for a given property of a node label.
        Returns None if an error occurs or no values are found.
        """
        if not re.match(r"^[A-Za-z0-9_]+$", node_label) or not re.match(r"^[A-Za-z0-9_]+$", property_name):
            logger.error(f"Invalid node_label ('{node_label}') or property_name ('{property_name}') for distinct value query.")
            return None
        
        # Constructing the query string safely.
        # This query now handles both direct string properties and lists of strings.
        query = cypher_queries.GET_DISTINCT_NODE_PROPERTY_VALUES.format(
            node_label_placeholder=node_label,
            property_name_placeholder=property_name
        )
        try:
            results, _, _ = await self.driver.execute_query(
                query,
                limit_param=limit,
                database_=self.database
            ) # type: ignore
            distinct_values = [str(record["value"]) for record in results if record["value"] is not None]
            if distinct_values:
                logger.debug(f"Fetched {len(distinct_values)} distinct values for {node_label}.{property_name}: {distinct_values}")
                return distinct_values
            else:
                logger.debug(f"No distinct non-null string values found for {node_label}.{property_name} within limit {limit}.")
                return None
        except Exception as e:
            logger.error(f"Error fetching distinct values for {node_label}.{property_name}: {e}", exc_info=True)
            return None
        
    async def _get_distinct_rel_property_values(self, rel_type: str, property_name: str, limit: int) -> Optional[List[str]]:
        """
        Fetches distinct non-null string values for a given property of a relationship type.
        Returns None if an error occurs or no values are found.
        """
        if not re.match(r"^[A-Za-z0-9_]+$", rel_type) or not re.match(r"^[A-Za-z0-9_]+$", property_name):
            logger.error(f"Invalid rel_type ('{rel_type}') or property_name ('{property_name}') for distinct value query.")
            return None

        query = cypher_queries.GET_DISTINCT_REL_PROPERTY_VALUES.format(
            rel_type_placeholder=rel_type,
            property_name_placeholder=property_name
        )
        try:
            results, _, _ = await self.driver.execute_query(
                query,
                limit_param=limit,
                database_=self.database
            ) # type: ignore
            distinct_values = [str(record["value"]) for record in results if record["value"] is not None]
            if distinct_values:
                logger.debug(f"Fetched {len(distinct_values)} distinct values for {rel_type}.{property_name}: {distinct_values}")
                return distinct_values
            else:
                logger.debug(f"No distinct non-null string values found for {rel_type}.{property_name} within limit {limit}.")
                return None
        except Exception as e:
            logger.error(f"Error fetching distinct values for {rel_type}.{property_name}: {e}", exc_info=True)
            return None

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
            (cypher_queries.CREATE_CONSTRAINT_PRODUCT_UUID, {}),
            (cypher_queries.CREATE_INDEX_CHUNK_NAME, {}), # B-tree on Chunk.name (from dynamic_props)
            (cypher_queries.CREATE_INDEX_CHUNK_SOURCE_DESC_NUM, {}),
            (cypher_queries.CREATE_INDEX_SOURCE_CONTENT, {}), # B-tree on Source.content
            (cypher_queries.CREATE_INDEX_ENTITY_NAME, {}), 
            (cypher_queries.CREATE_INDEX_ENTITY_LABEL, {}),
            (cypher_queries.CREATE_INDEX_ENTITY_NORMALIZED_NAME_LABEL, {}),
            (cypher_queries.CREATE_INDEX_PRODUCT_NAME, {}), 
            # Specific B-tree indexes for Product.price and Product.sku
            ("CREATE INDEX product_price_idx IF NOT EXISTS FOR (p:Product) ON (p.price)", {}),
            ("CREATE INDEX product_sku_idx IF NOT EXISTS FOR (p:Product) ON (p.sku)", {}),
            # B-tree on Product.content (JSON string) might not be very useful unless exact matches are needed.
            # A full-text index is generally better for text/JSON string content.
            # ("CREATE INDEX product_content_idx IF NOT EXISTS FOR (p:Product) ON (p.content)", {}),


            (cypher_queries.CREATE_FULLTEXT_CHUNK_CONTENT, {}), # Indexes Chunk.name and Chunk.content
            (cypher_queries.CREATE_FULLTEXT_SOURCE_CONTENT, {}), # Indexes Source.name and Source.content
            (cypher_queries.CREATE_FULLTEXT_ENTITY_NAME, {}),    # Now only Entity.name
            (cypher_queries.CREATE_FULLTEXT_PRODUCT_NAME_CONTENT, {}), # Indexes Product.name and Product.content
            (cypher_queries.CREATE_INDEX_RELATIONSHIP_LABEL, {}),
            (cypher_queries.CREATE_FULLTEXT_RELATIONSHIP_FACT, {}),
            # Full-text index on MENTIONS.mention_context (NEW)
            ("CREATE FULLTEXT INDEX mentions_fact_sentence_ft IF NOT EXISTS FOR ()-[r:MENTIONS]-() ON EACH [r.fact_sentence]", {}), # CHANGED 
        ]

        # Vector index for Chunk content
        chunk_node_label = "Chunk"
        chunk_content_property = "content_embedding" # Chunk.content is embedded
        chunk_vector_index_name = f"{chunk_node_label.lower()}_{chunk_content_property}_vector"
        create_vector_index_chunk_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", chunk_vector_index_name
        ).replace("$node_label", chunk_node_label).replace("$property_name", chunk_content_property).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_chunk_query, {}))

        # Vector index for Source content
        source_node_label = "Source"
        source_content_property = "content_embedding" # Source.content is embedded
        source_vector_index_name = f"{source_node_label.lower()}_{source_content_property}_vector" 
        create_vector_index_source_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", source_vector_index_name
        ).replace("$node_label", source_node_label).replace("$property_name", source_content_property).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_source_query, {}))

        # Vector index for Entity name
        entity_node_label = "Entity"
        entity_name_property = "name_embedding" # Entity.name is embedded
        entity_name_vector_index = f"{entity_node_label.lower()}_{entity_name_property}_vector"
        create_vector_index_entity_name_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", entity_name_vector_index
        ).replace("$node_label", entity_node_label).replace("$property_name", entity_name_property).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_entity_name_query, {}))
        # Entity description/content embedding index is REMOVED

        # Vector indexes for Product name and content
        product_node_label = "Product"
        product_name_property = "name_embedding" # Product.name is embedded
        product_name_vector_index = f"{product_node_label.lower()}_{product_name_property}_vector"
        create_vector_index_product_name_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", product_name_vector_index
        ).replace("$node_label", product_node_label).replace("$property_name", product_name_property).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_product_name_query, {}))

        product_content_property = "content_embedding" # Product.content (JSON string) is embedded
        product_content_vector_index = f"{product_node_label.lower()}_{product_content_property}_vector"
        create_vector_index_product_content_query = cypher_queries.CREATE_VECTOR_INDEX_TEMPLATE.replace(
            "$index_name", product_content_vector_index
        ).replace("$node_label", product_node_label).replace("$property_name", product_content_property).replace("$dimension", str(self.embedder.dimension)).replace("$similarity_function", "cosine")
        static_queries_and_params.append((create_vector_index_product_content_query, {}))

        # Vector index for Relationship fact
        rel_type_for_vector = "RELATES_TO" # This is for :RELATES_TO relationships
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
        
        # Vector index for MENTIONS.fact_embedding (NEW/RENAMED from mention_context_embedding)
        mentions_rel_type = "MENTIONS"
        mentions_fact_property = "fact_embedding" # CHANGED from mention_context_embedding
        mentions_fact_vector_index = f"{mentions_rel_type.lower()}_{mentions_fact_property}_vector" # Name reflects property
        create_vector_index_mentions_fact_query = f"""
        CREATE VECTOR INDEX {mentions_fact_vector_index} IF NOT EXISTS
        FOR ()-[r:{mentions_rel_type}]-() ON (r.{mentions_fact_property}) // Use fact_embedding
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {self.embedder.dimension},
            `vector.similarity_function`: 'cosine'
        }}}}
        """
        static_queries_and_params.append((create_vector_index_mentions_fact_query, {}))
        
        all_queries_to_run = list(static_queries_and_params) # This should be after all static_queries_and_params are defined

        # Dynamic B-tree indexes (Chunk.name, Source.name, Product.name are already covered by specific B-tree indexes above)
        # Dynamic B-tree on Product.content (JSON string) is probably not useful.
        # We might want dynamic B-tree on specific metadata fields for Product if they are frequently filtered on.
        # For Entity, only name is primary, other identifiable fields come from MENTIONS relationship.
        # Let's review which dynamic B-trees are still needed.
        # `name` is now explicit for all main node types.
        # `content` is also explicit.
        # `EXCLUDED_PROPERTIES_FOR_DYNAMIC_BTREE` should be updated.
        
        # For now, let's assume dynamic B-tree indexing is mostly for metadata fields beyond explicit ones.
        for node_label in ["Chunk", "Source", "Entity", "Product"]:
            dynamic_props = await self._get_dynamic_properties_for_btree_indexing(node_label)
            for prop_key in dynamic_props:
                # Avoid re-creating indexes on already explicitly indexed core fields like price, sku for Product.
                if node_label == "Product" and prop_key in ["price", "sku"]: # Already have specific indexes
                    continue
                
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
            cypher_queries.DROP_INDEX_PRODUCT_NAME,
            "DROP INDEX product_price_idx IF EXISTS", # For Product.price
            "DROP INDEX product_sku_idx IF EXISTS",   # For Product.sku
            # "DROP INDEX product_content_idx IF EXISTS", # If we had one for Product.content

            cypher_queries.DROP_FULLTEXT_CHUNK_CONTENT, 
            cypher_queries.DROP_FULLTEXT_SOURCE_CONTENT, 
            "DROP INDEX entity_name_ft IF EXISTS", # Was DROP_FULLTEXT_ENTITY_NAME_DESC
            "DROP INDEX product_name_content_ft IF EXISTS", # Was DROP_FULLTEXT_PRODUCT_NAME_DESC
             "DROP INDEX mentions_fact_sentence_ft IF EXISTS", # CHANGED from mentions_context_ft
            "DROP INDEX product_name_desc_ft IF EXISTS", 

            cypher_queries.DROP_CONSTRAINT_CHUNK_UUID,
            cypher_queries.DROP_CONSTRAINT_SOURCE_UUID,
            cypher_queries.DROP_CONSTRAINT_SOURCE_NAME,
            cypher_queries.DROP_CONSTRAINT_ENTITY_UUID,
            cypher_queries.DROP_CONSTRAINT_PRODUCT_UUID,
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
        
        # entity_desc_vector_index = "entity_description_embedding_vector" # This one is removed
        # queries_to_drop_str.append(f"DROP INDEX {entity_desc_vector_index} IF EXISTS") # So remove its drop

        product_name_vector_index = "product_name_embedding_vector"
        queries_to_drop_str.append(f"DROP INDEX {product_name_vector_index} IF EXISTS")
        
        product_content_vector_index = "product_content_embedding_vector" # Was product_description_embedding_vector
        queries_to_drop_str.append(f"DROP INDEX {product_content_vector_index} IF EXISTS")

        rel_vector_index_name = "relates_to_fact_embedding_vector"
        queries_to_drop_str.append(f"DROP INDEX {rel_vector_index_name} IF EXISTS")

        mentions_fact_vector_index = "mentions_fact_embedding_vector" # CHANGED from mentions_mention_context_embedding_vector
        queries_to_drop_str.append(f"DROP INDEX {mentions_fact_vector_index} IF EXISTS")

        for node_label in ["Chunk", "Source", "Entity", "Product"]:
            try:
                dynamic_props = await self._get_dynamic_properties_for_btree_indexing(node_label)
                for prop_key in dynamic_props:
                    if node_label == "Product" and prop_key in ["price", "sku"]: # Already handled
                        continue
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


    async def get_schema_string(self) -> str:
        """
        Retrieves and formats the database schema string.
        Uses APOC for detailed property types and relationship patterns if available, 
        with fallbacks to simpler schema introspection queries.
        Includes Node properties, Relationship properties, Relationship patterns, and Available Indexes.
        """
        schema_parts: List[str] = []
        
        excluded_labels_for_nodes = ["_Bloom_Perspective_", "_Bloom_Scene_", "__KGBuilder__", "__Entity__", "_GraphView_", "_DbView_", "_Token_"]
        excluded_rel_types_list = ["_Bloom_HAS_SCENE_"]

        # --- Section: Node Properties ---
        node_properties_list: List[str] = ["Node properties:"]
        try:
            node_schema_results, _, _ = await self.driver.execute_query(
                cypher_queries.SCHEMA_GET_NODE_PROPERTIES_APOC,
                excludedLabels=excluded_labels_for_nodes, 
                database_=self.database
            ) # type: ignore

            if node_schema_results:
                for record in node_schema_results:
                    output = record["output"]
                    label = output["label"]
                    # Sort properties alphabetically for consistent output
                    props = sorted(output["properties"], key=lambda x: x["property"]) 
                    prop_details = []
                    for p in props:
                        prop_name = p["property"]
                        neo4j_type_raw = p["type"] # Type string from apoc.meta.data
                        
                        prop_type_str = neo4j_type_raw.upper() # Default to uppercase
                        if "LIST" in prop_type_str:
                            prop_type_str = "LIST"
                        elif prop_type_str in ["DATETIME", "ZONED DATETIME", "LOCAL DATETIME"]:
                            prop_type_str = "DATE_TIME"
                        elif prop_type_str == "TEXT": # APOC can return "TEXT" for string-like
                            prop_type_str = "STRING"
                        elif prop_type_str == "LONG":
                            prop_type_str = "INTEGER"
                        elif prop_type_str == "DOUBLE":
                            prop_type_str = "FLOAT"
                        
                        property_display_string = f"{prop_name}: {prop_type_str}"

                        # Check if this property is flagged for distinct value fetching
                        if self.flagged_properties_config.nodes and \
                           label in self.flagged_properties_config.nodes and \
                           prop_name in self.flagged_properties_config.nodes[label] and \
                           prop_type_str in ["STRING", "LIST"]: # Now also check for LIST type
                            
                            value_config = self.flagged_properties_config.nodes[label][prop_name]
                            distinct_values = await self._get_distinct_property_values(label, prop_name, value_config.limit)
                            if distinct_values:
                                values_str = ", ".join(distinct_values)
                                property_display_string += f" {{possible values: {{{values_str}}}}}"
                        
                        prop_details.append(property_display_string)
                    
                    if prop_details:
                        formatted_props = "\n".join([f"  {pd}" for pd in prop_details])
                        node_properties_list.append(f"{label} {{\n{formatted_props}\n}}")
                    else:
                        node_properties_list.append(f"{label} {{}}") # Node with no properties
            else: 
                # Fallback if APOC for nodes failed or returned nothing
                logger.warning("APOC meta data for nodes returned no results or failed. Falling back to basic label listing for node properties.")
                node_labels_results_fb, _, _ = await self.driver.execute_query(
                    cypher_queries.SCHEMA_GET_NODE_LABELS_FALLBACK, 
                    database_=self.database
                ) # type: ignore
                for record_fb in node_labels_results_fb:
                    node_properties_list.append(f"{record_fb['label']} {{}}") # No property info in this specific fallback

        except Exception as e_node_props:
            logger.error(f"Error retrieving node properties: {e_node_props}", exc_info=True)
            node_properties_list.append("  Error: Could not retrieve node properties.")
        
        schema_parts.extend(node_properties_list)
        schema_parts.append("") # Blank line separator

        # --- Section: Relationship Properties ---
        rel_properties_list: List[str] = ["Relationship properties:"]
        try:
            rel_schema_results, _, _ = await self.driver.execute_query(
                cypher_queries.SCHEMA_GET_REL_PROPERTIES_APOC, 
                excludedRelTypes=excluded_rel_types_list, 
                database_=self.database
            ) # type: ignore
            
            if rel_schema_results:
                for record in rel_schema_results:
                    output = record["output"]
                    rel_type_name = output["type"]
                    props = sorted(output["properties"], key=lambda x: x["property"])
                    prop_details = []
                    for p in props:
                        prop_name = p["property"]
                        neo4j_type_raw = p["type"]
                        
                        prop_type_str = neo4j_type_raw.upper()
                        if "LIST" in prop_type_str:
                            prop_type_str = "LIST"
                        elif prop_type_str in ["DATETIME", "ZONED DATETIME", "LOCAL DATETIME"]:
                            prop_type_str = "DATE_TIME"
                        elif prop_type_str == "TEXT":
                            prop_type_str = "STRING"
                        elif prop_type_str == "LONG":
                            prop_type_str = "INTEGER"
                        elif prop_type_str == "DOUBLE":
                            prop_type_str = "FLOAT"
                        
                        property_display_string = f"{prop_name}: {prop_type_str}"

                        # Check if this relationship property is flagged for distinct value fetching
                        if self.flagged_properties_config.relationships and \
                           rel_type_name in self.flagged_properties_config.relationships and \
                           prop_name in self.flagged_properties_config.relationships[rel_type_name] and \
                           prop_type_str in ["STRING", "LIST"]: # Now also check for LIST type
                            
                            value_config = self.flagged_properties_config.relationships[rel_type_name][prop_name]
                            # Use the new helper method for relationship properties
                            distinct_values = await self._get_distinct_rel_property_values(rel_type_name, prop_name, value_config.limit)
                            if distinct_values:
                                values_str = ", ".join(distinct_values)
                                property_display_string += f" {{possible values: {{{values_str}}}}}"

                        prop_details.append(property_display_string)
                    
                    if prop_details:
                        formatted_props = "\n".join([f"  {pd}" for pd in prop_details])
                        rel_properties_list.append(f"{rel_type_name} {{\n{formatted_props}\n}}")
                    else:
                        rel_properties_list.append(f"{rel_type_name} {{}}") # Relationship with no properties
            else: 
                logger.warning("APOC meta data for relationships returned no results or failed. Falling back to basic rel type listing for relationship properties.")
                rel_types_results_fb, _, _ = await self.driver.execute_query(
                    cypher_queries.SCHEMA_GET_REL_TYPES_FALLBACK, 
                    database_=self.database
                ) # type: ignore
                for record_fb in rel_types_results_fb:
                    rel_properties_list.append(f"{record_fb['relationshipType']} {{}}")

        except Exception as e_rel_props:
            logger.error(f"Error retrieving relationship properties: {e_rel_props}", exc_info=True)
            rel_properties_list.append("  Error: Could not retrieve relationship properties.")

        schema_parts.extend(rel_properties_list)
        schema_parts.append("")

        # --- Section: Relationship Patterns ---
        rel_connections_list: List[str] = ["The relationships:"]
        try:
            connection_results, _, _ = await self.driver.execute_query(
                cypher_queries.SCHEMA_GET_REL_CONNECTIONS_APOC, 
                excludedLabels=excluded_labels_for_nodes, 
                database_=self.database
            ) # type: ignore
            if connection_results:
                for record in connection_results:
                    rel_connections_list.append(record["connection"])
            else: 
                logger.warning("APOC meta data for relationship connections returned no results. Falling back to db.schema.visualization().")
                connection_results_fb, _, _ = await self.driver.execute_query(
                    cypher_queries.SCHEMA_GET_REL_CONNECTIONS_VISUALIZATION_FALLBACK, 
                    database_=self.database
                ) # type: ignore
                for record_fb in connection_results_fb:
                    rel_connections_list.append(record_fb["connection"])
        except Exception as e_apoc_conn:
             logger.error(f"Error generating relationship connections via APOC: {e_apoc_conn}", exc_info=False)
             logger.warning("Falling back to db.schema.visualization() for relationship connections due to APOC error.")
             try:
                 connection_results_fb, _, _ = await self.driver.execute_query(
                    cypher_queries.SCHEMA_GET_REL_CONNECTIONS_VISUALIZATION_FALLBACK, 
                    database_=self.database
                ) # type: ignore
                 for record_fb in connection_results_fb:
                     rel_connections_list.append(record_fb["connection"])
             except Exception as e_viz_fallback:
                 logger.error(f"Fallback db.schema.visualization() also failed: {e_viz_fallback}", exc_info=True)
                 rel_connections_list.append("  Error: Could not retrieve relationship patterns.")
        
        schema_parts.extend(rel_connections_list)
        schema_parts.append("")


        # # --- Section: Available Indexes ---
        # index_info_list: List[str] = ["Available Indexes:"]
        # fulltext_indexes_str: List[str] = []
        # vector_indexes_str: List[str] = []
        # other_indexes_str: List[str] = [] # For RANGE, POINT etc.

        # try:
        #     index_results, _, _ = await self.driver.execute_query(
        #         cypher_queries.SCHEMA_GET_INDEX_INFO,
        #         database_=self.database
        #     ) # type: ignore

        #     for record in index_results:
        #         name = record["name"]
        #         index_type_raw = record["type"]
        #         index_type = index_type_raw.upper() if index_type_raw else "UNKNOWN"
        #         entity_type = record["entityType"].upper() if record["entityType"] else "UNKNOWN"
        #         labels_or_types = record["labelsOrTypes"] if record["labelsOrTypes"] else []
        #         properties = record["properties"] if record["properties"] else []
        #         options = record["options"] if isinstance(record["options"], dict) else {}

        #         # Filter out some common system/internal/less relevant indexes for LLM context
        #         if name.startswith("constraint_") or name.startswith("dynamic_idx_") or name.startswith("token_lookup_"):
        #             continue
        #         if "_Bloom_" in name or name in ["nodes_entity_unique_id", "relationship_id_index", "relationships_unique_id_rels"]: # More specific exclusions
        #             continue

        #         formatted_props = ", ".join(properties)
        #         on_clause_entity_part = ""
        #         if labels_or_types: # Handle cases where labelsOrTypes might be None or empty
        #             on_clause_entity_part = f":{labels_or_types[0]}" if labels_or_types else ""
                
        #         on_clause = f"ON {entity_type}{on_clause_entity_part}({formatted_props})"

        #         if index_type == "TEXT" or index_type == "FULLTEXT":
        #             fulltext_indexes_str.append(f"  - {name} (TYPE: {index_type}, {on_clause})")
        #         elif index_type == "VECTOR":
        #             options_str_parts = []
        #             if options.get("indexProvider"): # e.g., 'vector-1.0'
        #                 # options_str_parts.append(f"provider: {options['indexProvider']}")
        #                 pass # Provider often not needed for LLM to use the index by name
        #             vec_dims = options.get("vector.dimensions")
        #             if vec_dims is not None: options_str_parts.append(f"dimensions: {vec_dims}")
        #             vec_sim = options.get("vector.similarity_function")
        #             if vec_sim: options_str_parts.append(f"similarity: {vec_sim}")
                    
        #             options_display = f" OPTIONS {{{', '.join(options_str_parts)}}}" if options_str_parts else ""
        #             vector_indexes_str.append(f"  - {name} (TYPE: {index_type}, {on_clause}{options_display})")
        #         elif index_type in ["RANGE", "POINT", "LOOKUP"]: # Explicitly list other relevant types
        #             other_indexes_str.append(f"  - {name} (TYPE: {index_type}, {on_clause})")
        #         # Silently ignore other index types not explicitly handled if any

        # except Exception as e_index:
        #     logger.error(f"Error fetching or formatting index information: {e_index}", exc_info=True)
        #     index_info_list.append("  Error: Could not retrieve index information.")

        # if fulltext_indexes_str:
        #     index_info_list.append("Full-text Indexes:")
        #     index_info_list.extend(sorted(fulltext_indexes_str))
        # if vector_indexes_str:
        #     index_info_list.append("Vector Indexes:")
        #     index_info_list.extend(sorted(vector_indexes_str))
        # if other_indexes_str:
        #     index_info_list.append("Other Relevant Indexes (e.g., RANGE, POINT):")
        #     index_info_list.extend(sorted(other_indexes_str))
        
        # if not fulltext_indexes_str and not vector_indexes_str and not other_indexes_str and "Error: Could not retrieve index information." not in index_info_list:
        #     index_info_list.append("  No user-defined Full-text or Vector indexes found (or they were filtered out).")
        
        # schema_parts.extend(index_info_list)
        
        return "\n".join(schema_parts)