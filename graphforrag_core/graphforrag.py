import logging
import uuid
from datetime import datetime, timezone, date
import json
from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncResult, ResultSummary
from langchain_core.documents import Document

from config import cypher_queries
from .embedder_client import EmbedderClient, EmbedderConfig # Import base classes
# Import a default embedder (optional, or make it mandatory)
from .openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig


logger = logging.getLogger("graph_for_rag")

def _preprocess_metadata_for_neo4j(metadata: dict | None) -> dict:
    # ... (function remains the same)
    if not metadata:
        return {}
    processed_props = {}
    for key, value in metadata.items():
        if isinstance(value, dict):
            processed_props[key] = json.dumps(value)
        elif isinstance(value, (datetime, date)):
            processed_props[key] = value.isoformat()
        elif isinstance(value, list):
            new_list = []
            for item in value:
                if isinstance(item, dict):
                    new_list.append(json.dumps(item))
                elif isinstance(item, (datetime, date)):
                    new_list.append(item.isoformat())
                elif isinstance(item, (str, int, float, bool)) or item is None:
                    new_list.append(item)
                else:
                    logger.warning(f"Item of type {type(item)} in list for key '{key}' converted to string.")
                    new_list.append(str(item))
            processed_props[key] = new_list
        elif isinstance(value, (str, int, float, bool)) or value is None:
            processed_props[key] = value
        else:
            logger.warning(f"Metadata field '{key}' with type {type(value)} converted to string.")
            processed_props[key] = str(value)
    return processed_props

class GraphForRAG:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        embedder_client: EmbedderClient | None = None # New parameter
    ):
        try:
            self.driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=(user, password))
            self.database: str = database
            if embedder_client:
                self.embedder = embedder_client
            else:
                logger.info("No embedder client provided, defaulting to OpenAIEmbedder. Vector indices will use its configuration.")
                # You might want to make API key configurable here or ensure it's in env
                self.embedder = OpenAIEmbedder() # Default embedder
            
            logger.info(f"Using embedder: {self.embedder.config.model_name} with dimension {self.embedder.dimension}")
            logger.info(f"Successfully initialized Neo4j driver for database '{database}' at '{uri}'")
        except Exception as e:
            logger.error(f"Failed to initialize GraphForRAG: {e}", exc_info=True)
            raise

    async def close(self):
        # ... (close remains the same)
        if self.driver:
            await self.driver.close()
            logger.info("Neo4j driver closed.")

    async def ensure_indices(self, drop_existing: bool = False):
        logger.info("Ensuring database indices and constraints...")
        
        queries_and_params_to_run = [
            (cypher_queries.CREATE_CONSTRAINT_CHUNK_UUID, {}),
            (cypher_queries.CREATE_CONSTRAINT_SOURCE_UUID, {}),
            (cypher_queries.CREATE_CONSTRAINT_SOURCE_NAME, {}),
            (cypher_queries.CREATE_INDEX_CHUNK_NAME, {}),
            (cypher_queries.CREATE_INDEX_CHUNK_SOURCE_DESC_NUM, {}),
            (cypher_queries.CREATE_FULLTEXT_CHUNK_CONTENT, {}),
        ]

        # Vector Index for Chunk content_embedding
        # Construct the query string in Python using f-strings for structural parts
        node_label_for_vector = "Chunk"
        property_name_for_vector = "content_embedding" # This property doesn't exist on nodes yet
        vector_index_name = f"{node_label_for_vector.lower()}_{property_name_for_vector}_vector" # e.g., chunk_content_embedding_vector
        
        # Using the template is fine, but we need to format it correctly
        # This is safer than directly building the whole string with f-strings if parts are complex
        # However, for label and property, direct formatting is needed.

        # Correct approach: Format the parts that CANNOT be parameters
        # Then pass the parts that CAN be parameters ($dimension, $similarity_function)
        
        # For simplicity, let's define the fully formatted string here for the vector index
        # and pass only the remaining values as parameters if needed, or none if all are formatted.
        
        # Get dimension and similarity function from embedder
        dimension = self.embedder.dimension
        similarity_function = "cosine" # Commonly used, make configurable if needed

        # Construct the vector index query string dynamically in Python
        # It's crucial that node_label_for_vector and property_name_for_vector are controlled
        # by your code and not user input if you were to use f-strings directly for security.
        # Here, they are hardcoded/derived, so it's safe.
        
        create_vector_index_chunk_query = f"""
        CREATE VECTOR INDEX {vector_index_name} IF NOT EXISTS
        FOR (n:{node_label_for_vector}) ON (n.{property_name_for_vector})
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {dimension},
            `vector.similarity_function`: '{similarity_function}'
        }}}}
        """
        queries_and_params_to_run.append(
            (create_vector_index_chunk_query, {}) # No parameters needed as all values are formatted in
        )

        async with self.driver.session(database=self.database) as session:
            for query_string, params in queries_and_params_to_run:
                try:
                    logger.debug(f"Executing: {query_string.strip()} with params {params if params else ''}")
                    await session.run(query_string, params)
                except Exception as e:
                    logger.error(f"Error creating index/constraint with query '{query_string.strip()}': {e}", exc_info=True)
        logger.info("Finished ensuring database indices and constraints.")

    async def clear_all_data(self):
        """
        Deletes ALL nodes and relationships from the database. Use with caution!
        """
        logger.warning("Attempting to delete ALL nodes and relationships from the database...")
        try:
            async with self.driver.session(database=self.database) as session:
                result: AsyncResult = await session.run(cypher_queries.CLEAR_ALL_NODES_AND_RELATIONSHIPS)
                # Consume the result to ensure the operation is complete and summary is populated
                summary: ResultSummary = await result.consume()

                logger.info(
                    f"Successfully cleared all data. Nodes deleted: {summary.counters.nodes_deleted}, "
                    f"Relationships deleted: {summary.counters.relationships_deleted}"
                )
        except Exception as e:
            logger.error(f"Error clearing all data: {e}", exc_info=True)
            raise

    async def clear_all_known_indexes_and_constraints(self):
        """
        Drops all known indexes and constraints created by ensure_indices.
        """
        logger.warning("Attempting to drop known indexes and constraints...")
        
        queries_to_drop_str = [
            cypher_queries.DROP_INDEX_CHUNK_NAME,
            cypher_queries.DROP_INDEX_CHUNK_SOURCE_DESC_NUM,
            cypher_queries.DROP_FULLTEXT_CHUNK_CONTENT, # Uses corrected query
            cypher_queries.DROP_CONSTRAINT_CHUNK_UUID,
            cypher_queries.DROP_CONSTRAINT_SOURCE_UUID,
            cypher_queries.DROP_CONSTRAINT_SOURCE_NAME,
        ]
        
        node_label_for_vector = "Chunk"
        property_name_for_vector = "content_embedding"
        vector_index_name = f"{node_label_for_vector.lower()}_{property_name_for_vector}_vector"
        # Prepend the dynamically named vector index drop query
        # It should already be using "DROP INDEX <name> IF EXISTS" from the previous fix
        queries_to_drop_str.insert(0, f"DROP INDEX {vector_index_name} IF EXISTS")


        async with self.driver.session(database=self.database) as session:
            for query_string in queries_to_drop_str:
                try:
                    logger.debug(f"Executing: {query_string.strip()}")
                    # For DROP operations, we don't typically need to process records or detailed summary
                    # Just run and ensure no error.
                    result = await session.run(query_string)
                    await result.consume() # Ensure it's processed
                except Exception as e:
                    logger.error(f"Error dropping index/constraint with query '{query_string.strip()}': {e}", exc_info=False)
        logger.info("Finished attempting to drop known indexes and constraints.")

    async def _create_or_merge_source_node(
        self,
        source_identifier: str,
        source_dynamic_metadata: dict | None = None
    ) -> str | None:
        # ... (method remains largely the same, uses _preprocess_metadata_for_neo4j)
        source_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, source_identifier))
        created_at = datetime.now(timezone.utc)
        dynamic_props_for_cypher = _preprocess_metadata_for_neo4j(source_dynamic_metadata)
        params = {
            "source_identifier_param": source_identifier,
            "source_uuid_param": source_uuid,
            "created_at_ts_param": created_at,
            "dynamic_properties_param": dynamic_props_for_cypher
        }
        try:
            results, summary, _ = await self.driver.execute_query(
                cypher_queries.MERGE_SOURCE_NODE, params, database_=self.database
            )
            if results and results[0]["source_uuid"]:
                returned_uuid = results[0]["source_uuid"]
                action = "created" if summary.counters.nodes_created > 0 else "merged"
                if summary.counters.nodes_created == 0 and summary.counters.properties_set > 0 and source_dynamic_metadata:
                    action = "updated properties for"
                elif summary.counters.nodes_created == 0 and summary.counters.properties_set == 0:
                    action = "matched (no changes to)"
                logger.debug(f"Source node {action}: [green]{returned_uuid}[/green] (Identifier: '[magenta]{source_identifier}[/magenta]').")
                return returned_uuid
            return None
        except Exception as e:
            logger.error(f"Error in _create_or_merge_source_node for '{source_identifier}': {e}", exc_info=True)
            return None

    async def _add_single_chunk_and_link(
        self,
        raw_content: str, # This is the original doc.page_content
        source_node_uuid: str,
        source_identifier_for_chunk_desc: str, # For Chunk.source_description
        all_chunk_properties_from_doc: dict,   # This is doc.metadata
        allow_same_name_chunks_flag: bool = True
    ) -> str | None: # Returns chunk_uuid if successful (including base creation)
        
        # 1. Prepare Chunk Identifiers and Core Properties from Metadata
        chunk_uuid_str = str(all_chunk_properties_from_doc.pop("chunk_uuid", uuid.uuid4()))
        # Initial name from metadata, might be overridden by JSON content later
        name_from_meta = all_chunk_properties_from_doc.pop("name", None)
        # Get chunk_number, will be None if not present (e.g., for products)
        chunk_number_for_rel = all_chunk_properties_from_doc.pop("chunk_number", None)

        # 2. Prepare dynamic properties map and handle content type
        dynamic_props_for_chunk = all_chunk_properties_from_doc.copy() # Start with remaining metadata
        content_type = dynamic_props_for_chunk.pop("content_type", "text").lower()
        
        actual_chunk_content_to_store = raw_content # What gets stored in chunk.content (text or JSON string)
        text_content_to_embed = raw_content     # What gets passed to the embedder

        name_str = name_from_meta # Default to name from metadata, may be overridden

        if content_type == "json":
            try:
                json_data = json.loads(raw_content)
                if isinstance(json_data, dict):
                    # Add all top-level JSON fields to dynamic_props_for_chunk
                    # This will overwrite any identically named keys from original metadata
                    for key, value in json_data.items():
                        dynamic_props_for_chunk[key] = value
                    
                    # Try to derive a more specific name from JSON content
                    name_override_keys = ["productName", "title", "item_name", "name"]
                    derived_name = name_from_meta # Start with name from metadata if any
                    for key in name_override_keys:
                        if key in json_data and isinstance(json_data[key], str) and json_data[key]: # Check if not empty
                            derived_name = json_data[key]
                            logger.debug(f"    Derived chunk name '{derived_name}' from JSON key '{key}'.")
                            break
                    name_str = derived_name 
                    
                    # For embedding JSON: currently embedding the raw JSON string.
                    # Alternative: construct a descriptive string from key fields.
                    # text_content_to_embed = f"Product: {name_str}, Category: {json_data.get('category', '')}, Price: {json_data.get('price', '')}"
                else:
                    logger.warning(f"    Chunk content for '{name_from_meta or chunk_uuid_str}' was marked JSON but not a dict. Storing as text, embedding raw content.")
            except json.JSONDecodeError:
                logger.warning(f"    Failed to parse JSON content for '{name_from_meta or chunk_uuid_str}'. Storing as raw text, embedding raw content.")
        
        # Fallback name generation if name_str is still None or empty
        if not name_str:
            name_str = (raw_content[:50] + '...') if len(raw_content) > 50 else raw_content
        
        # Ensure 'name' and 'chunk_number' (if it exists) are in the dynamic properties map
        # These will be processed by _preprocess_metadata_for_neo4j
        dynamic_props_for_chunk["name"] = name_str
        if chunk_number_for_rel is not None:
            dynamic_props_for_chunk["chunk_number"] = chunk_number_for_rel
        
        # Preprocess all dynamic properties (including name, chunk_number, and the rest from metadata/JSON)
        final_dynamic_props_for_chunk = _preprocess_metadata_for_neo4j(dynamic_props_for_chunk)
        created_at = datetime.now(timezone.utc)

        # 3. Pre-check for duplicate chunk names if configured
        if not allow_same_name_chunks_flag:
            try:
                check_params = {"name": name_str} # Use the final determined name_str
                existing_chunk_records, _, _ = await self.driver.execute_query(
                    cypher_queries.CHECK_CHUNK_EXISTS_BY_NAME, check_params, database_=self.database
                )
                if existing_chunk_records:
                    found_uuid = existing_chunk_records[0]["uuid"]
                    if found_uuid != chunk_uuid_str: 
                        logger.warning(
                            f"Operation on chunk (target UUID: [yellow]{chunk_uuid_str}[/yellow]) with name '[cyan]{name_str}[/cyan]' blocked. "
                            f"Another chunk (UUID: [yellow]{found_uuid}[/yellow]) already has this name. 'allow_same_name_chunks' is False."
                        )
                        return None
            except Exception as e:
                logger.error(f"Error during pre-check for chunk name '{name_str}': {e}", exc_info=True)
                return None

        # 4. Prepare parameters for the main Cypher query
        parameters_for_chunk_creation = {
            "source_node_uuid_param": source_node_uuid,
            "chunk_uuid_param": chunk_uuid_str,
            "chunk_content_param": actual_chunk_content_to_store, 
            "source_identifier_param": source_identifier_for_chunk_desc, # For Chunk.source_description
            "created_at_ts_param": created_at,
            "dynamic_chunk_properties_param": final_dynamic_props_for_chunk,
            "chunk_number_param_for_rel": chunk_number_for_rel if chunk_number_for_rel is not None else 0,
        }
        
        created_chunk_uuid_from_db = None # Initialize
        try:
            # Execute main query to create/update chunk and relationships
            results, summary, _ = await self.driver.execute_query(
                cypher_queries.ADD_CHUNK_AND_LINK_TO_SOURCE, 
                parameters_for_chunk_creation, 
                database_=self.database
            )
            if results and results[0]["chunk_uuid"]:
                created_chunk_uuid_from_db = results[0]["chunk_uuid"]
                action = "added"
                if not summary.counters.nodes_created and summary.counters.properties_set > 0:
                    action = "updated"
                elif not summary.counters.nodes_created and summary.counters.properties_set == 0:
                    action = "matched (no changes)"

                log_chunk_num_str = f", Num: {chunk_number_for_rel}" if chunk_number_for_rel is not None else ""
                logger.debug(
                    f"  Chunk {action}: [blue]{created_chunk_uuid_from_db}[/blue] (Name: '[cyan]{name_str}[/cyan]'{log_chunk_num_str}, Type: {content_type}). Linked to source via BELONGS_TO_SOURCE."
                )
                if results[0]["prev_chunk_linked"]: 
                    logger.debug(f"    -> Linked to previous chunk via NEXT_CHUNK.")
            else:
                logger.error(f"Failed to create/update chunk '{name_str}': No UUID returned from main Cypher operation.")
                return None # Essential: Stop if chunk creation/merge itself failed
        except Exception as e:
            if "Failed to invoke procedure `apoc.do.when`" in str(e):
                logger.error("APOC `apoc.do.when` not found. Ensure APOC plugin is installed.", exc_info=False)
            logger.error(f"Error in main Cypher operation for chunk '{name_str}': {e}", exc_info=True)
            return None # Essential: Stop if chunk creation/merge itself failed
        
        # --- Generate and Store Embedding if chunk was successfully processed ---
        if created_chunk_uuid_from_db and self.embedder:
            try:
                logger.debug(f"    Generating embedding for chunk content of: {created_chunk_uuid_from_db} (Name: '{name_str}')...")
                embedding_vector = await self.embedder.embed_text(text_content_to_embed)
                
                if embedding_vector: 
                    embedding_params = {
                        "chunk_uuid_param": created_chunk_uuid_from_db,
                        "embedding_vector_param": embedding_vector
                    }
                    embed_results, embed_summary, embed_keys = await self.driver.execute_query(
                        cypher_queries.SET_CHUNK_CONTENT_EMBEDDING,
                        embedding_params,
                        database_=self.database
                    )
                    
                    # Now we check for 'uuid_processed' which is the input UUID we returned
                    if embed_results and embed_results[0].get("uuid_processed") == created_chunk_uuid_from_db:
                        # If properties_set > 0, it can be a bit misleading here since setNodeVectorProperty
                        # might not always be counted as a "standard" property set in summary for some drivers/versions.
                        # The fact that the query ran without error and returned the expected UUID is a good sign.
                        logger.debug(f"    Successfully called procedure to store embedding for chunk: {created_chunk_uuid_from_db}")
                    elif embed_results:
                        logger.warning(f"    Storing embedding query returned {embed_results[0].get('uuid_processed')}, expected {created_chunk_uuid_from_db}.")
                    else:
                        logger.warning(f"    Attempted to store embedding for {created_chunk_uuid_from_db}, but query returned no results. Chunk might not have been found for embedding update.")
                else:
                    logger.warning(f"    Embedding vector was empty for chunk {created_chunk_uuid_from_db}. Skipping embedding storage.")
            except Exception as e:
                logger.error(f"    Failed to generate or store embedding for chunk {created_chunk_uuid_from_db}: {e}", exc_info=True)
        elif created_chunk_uuid_from_db and not self.embedder:
            logger.debug(f"    No embedder configured. Skipping embedding for chunk {created_chunk_uuid_from_db}.")

        return created_chunk_uuid_from_db

    async def add_documents_from_source(
        self,
        source_identifier: str,
        documents: list[Document],
        source_dynamic_metadata: dict | None = None,
        allow_same_name_chunks_for_this_source: bool = True
    ) -> tuple[str | None, list[str]]:
        # ... (method remains largely the same)
        logger.info(f"Processing source: [magenta]{source_identifier}[/magenta]")
        source_node_uuid = await self._create_or_merge_source_node(
            source_identifier, source_dynamic_metadata
        )

        if not source_node_uuid:
            logger.error(f"  Failed to create/merge source node for '{source_identifier}'. Aborting chunk processing for this source.")
            return None, []

        added_chunk_uuids: list[str] = []
        for doc_idx, doc in enumerate(documents):
            all_chunk_props_from_doc_meta = doc.metadata.copy() if doc.metadata else {}
            raw_page_content = doc.page_content
            chunk_name_for_log = all_chunk_props_from_doc_meta.get('name', f"Unnamed Chunk {doc_idx+1}")
            chunk_num_for_log = all_chunk_props_from_doc_meta.get('chunk_number', 'N/A (e.g. product)')

            logger.debug(f"  Processing chunk {doc_idx + 1}/{len(documents)}: Name='{chunk_name_for_log}', Number={chunk_num_for_log}")

            created_chunk_uuid = await self._add_single_chunk_and_link(
                raw_content=raw_page_content,
                source_node_uuid=source_node_uuid,
                source_identifier_for_chunk_desc=source_identifier,
                all_chunk_properties_from_doc=all_chunk_props_from_doc_meta,
                allow_same_name_chunks_flag=allow_same_name_chunks_for_this_source
            )
            if created_chunk_uuid:
                added_chunk_uuids.append(created_chunk_uuid)
            else:
                logger.warning(f"    Failed to add chunk: Name='{chunk_name_for_log}'")
        
        logger.info(f"Finished processing source [magenta]{source_identifier}[/magenta]. Added {len(added_chunk_uuids)} chunks.")
        return source_node_uuid, added_chunk_uuids