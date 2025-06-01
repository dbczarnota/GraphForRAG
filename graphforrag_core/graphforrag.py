# graphforrag_core/graphforrag.py
# ... (imports remain the same) ...
import logging
import uuid
from datetime import datetime, timezone, date
import json
from typing import Optional, Any, List, Tuple 

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncResult, ResultSummary # type: ignore

from config import cypher_queries
from .embedder_client import EmbedderClient
from .openai_embedder import OpenAIEmbedder
from .utils import preprocess_metadata_for_neo4j, normalize_entity_name 
from .schema_manager import SchemaManager
from .entity_extractor import EntityExtractor
from config.llm_prompts import ExtractedEntity 
from files.llm_models import setup_fallback_model


logger = logging.getLogger("graph_for_rag")

class GraphForRAG:
    # ... (__init__, close, schema methods, _create_or_merge_source_node remain the same) ...
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        embedder_client: Optional[EmbedderClient] = None,
        llm_client: Optional[Any] = None 
    ):
        try:
            self.driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=(user, password)) # type: ignore
            self.database: str = database
            
            if embedder_client:
                self.embedder = embedder_client
            else:
                logger.info("No embedder client provided to GraphForRAG, defaulting to OpenAIEmbedder.")
                self.embedder = OpenAIEmbedder()
            
            if llm_client:
                self.entity_extractor = EntityExtractor(llm_client=llm_client)
            else:
                logger.info("No LLM client provided to GraphForRAG for entity extraction, EntityExtractor will use its default.")
                self.entity_extractor = EntityExtractor() 
            
            self.schema_manager = SchemaManager(self.driver, self.database, self.embedder)

            logger.info(f"Using embedder: {self.embedder.config.model_name} with dimension {self.embedder.dimension}")
            
            entity_extractor_model_name = "Unknown"
            if hasattr(self.entity_extractor.llm_client, 'model') and isinstance(self.entity_extractor.llm_client.model, str):
                entity_extractor_model_name = self.entity_extractor.llm_client.model
            elif hasattr(self.entity_extractor.llm_client, 'model_name') and isinstance(self.entity_extractor.llm_client.model_name, str):
                entity_extractor_model_name = self.entity_extractor.llm_client.model_name

            logger.info(f"GraphForRAG initialized. Entity Extractor LLM: {entity_extractor_model_name}")
            logger.info(f"Successfully initialized Neo4j driver for database '{database}' at '{uri}'")
        except Exception as e:
            logger.error(f"Failed to initialize GraphForRAG: {e}", exc_info=True)
            raise

    async def close(self):
        if self.driver:
            await self.driver.close()
            logger.info("Neo4j driver closed.")

    async def ensure_indices(self):
        await self.schema_manager.ensure_indices_and_constraints()

    async def clear_all_data(self):
        await self.schema_manager.clear_all_data()

    async def clear_all_known_indexes_and_constraints(self):
        await self.schema_manager.clear_all_known_indexes_and_constraints()
    
    async def _create_or_merge_source_node(
        self,
        source_identifier: str,
        source_content: str | None = None,
        source_dynamic_metadata: dict | None = None
    ) -> str | None:
        source_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, source_identifier))
        created_at = datetime.now(timezone.utc)
        dynamic_props_for_cypher = preprocess_metadata_for_neo4j(source_dynamic_metadata)
        params = {
            "source_identifier_param": source_identifier,
            "source_uuid_param": source_uuid,
            "source_content_param": source_content, 
            "created_at_ts_param": created_at,
            "dynamic_properties_param": dynamic_props_for_cypher
        }
        returned_uuid = None
        try:
            results, summary, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.MERGE_SOURCE_NODE, params, database_=self.database
            )
            if results and results[0]["source_uuid"]:
                returned_uuid = results[0]["source_uuid"]
                action = "created" if summary.counters.nodes_created > 0 else "merged" # type: ignore
                if summary.counters.nodes_created == 0 and summary.counters.properties_set > 0 and (source_dynamic_metadata or source_content): # type: ignore
                    action = "updated properties for"
                elif summary.counters.nodes_created == 0 and summary.counters.properties_set == 0: # type: ignore
                    action = "matched (no changes to)"
                
                log_content_snippet = f", Content: '{source_content[:30]}...'" if source_content else ""
                logger.debug(f"Source node {action}: [green]{returned_uuid}[/green] (Identifier: '[magenta]{source_identifier}[/magenta]'{log_content_snippet}).")
                
                if returned_uuid and source_content and self.embedder:
                    try:
                        logger.debug(f"  Generating embedding for Source content of: {returned_uuid} (Identifier: '{source_identifier}')...")
                        embedding_vector = await self.embedder.embed_text(source_content)
                        if embedding_vector:
                            embedding_params = {
                                "source_uuid_param": returned_uuid,
                                "embedding_vector_param": embedding_vector
                            }
                            embed_results, _, _ = await self.driver.execute_query( # type: ignore
                                cypher_queries.SET_SOURCE_CONTENT_EMBEDDING,
                                embedding_params,
                                database_=self.database
                            )
                            if embed_results and embed_results[0].get("uuid_processed") == returned_uuid:
                                logger.debug(f"  Successfully stored embedding for Source node: {returned_uuid}")
                            else:
                                logger.warning(f"  Storing Source content embedding query for {returned_uuid} did not confirm processing.")
                        else:
                            logger.warning(f"  Source content embedding vector was empty for {returned_uuid}. Skipping storage.")
                    except Exception as e_embed:
                        logger.error(f"  Failed to generate or store Source content embedding for {returned_uuid}: {e_embed}", exc_info=True)
                elif returned_uuid and source_content and not self.embedder:
                     logger.debug(f"  No embedder configured. Skipping embedding for Source content of {returned_uuid}.")
                return returned_uuid
            return None 
        except Exception as e:
            logger.error(f"Error in _create_or_merge_source_node for '{source_identifier}': {e}", exc_info=True)
            return None


    async def _add_single_chunk_and_link(
        self,
        page_content: str,
        chunk_metadata: dict,
        source_node_uuid: str,
        source_identifier_for_chunk_desc: str,
        allow_same_name_chunks_flag: bool = True,
        previous_chunk_content: Optional[str] = None
    ) -> str | None:
        # ... (chunk property preparation and pre-check logic - NO CHANGES HERE) ...
        chunk_uuid_str = str(chunk_metadata.pop("chunk_uuid", uuid.uuid4()))
        name_from_meta = chunk_metadata.pop("name", None)
        chunk_number_for_rel = chunk_metadata.pop("chunk_number", None)
        dynamic_props_for_chunk = chunk_metadata.copy()
        content_type = dynamic_props_for_chunk.pop("content_type", "text").lower()
        actual_chunk_content_to_store = page_content
        text_content_to_embed = page_content
        name_str = name_from_meta
        if content_type == "json":
            try:
                json_data = json.loads(page_content)
                if isinstance(json_data, dict):
                    for key, value in json_data.items():
                        dynamic_props_for_chunk[key] = value
                    name_override_keys = ["productName", "title", "item_name", "name"]
                    derived_name = name_from_meta
                    for key in name_override_keys:
                        if key in json_data and isinstance(json_data[key], str) and json_data[key]:
                            derived_name = json_data[key]
                            logger.debug(f"    Derived chunk name '{derived_name}' from JSON key '{key}'.")
                            break
                    name_str = derived_name
                else:
                    logger.warning(f"    Chunk content for '{name_from_meta or chunk_uuid_str}' was marked JSON but not a dict. Storing as text, embedding raw content.")
            except json.JSONDecodeError:
                logger.warning(f"    Failed to parse JSON content for '{name_from_meta or chunk_uuid_str}'. Storing as raw text, embedding raw content.")
        if not name_str: 
            name_str = (page_content[:50] + '...') if len(page_content) > 50 else page_content
        dynamic_props_for_chunk["name"] = name_str
        if chunk_number_for_rel is not None:
            dynamic_props_for_chunk["chunk_number"] = chunk_number_for_rel
        final_dynamic_props_for_chunk = preprocess_metadata_for_neo4j(dynamic_props_for_chunk)
        created_at_ts = datetime.now(timezone.utc)
        if not allow_same_name_chunks_flag: # Pre-check
            try:
                check_params = {"name": name_str}
                existing_chunk_records, _, _ = await self.driver.execute_query(cypher_queries.CHECK_CHUNK_EXISTS_BY_NAME, check_params, database_=self.database) # type: ignore
                if existing_chunk_records:
                    found_uuid = existing_chunk_records[0]["uuid"]
                    if found_uuid != chunk_uuid_str:
                        logger.warning(f"Operation on chunk (target UUID: [yellow]{chunk_uuid_str}[/yellow]) with name '[cyan]{name_str}[/cyan]' blocked. Another chunk (UUID: [yellow]{found_uuid}[/yellow]) already has this name. 'allow_same_name_chunks' is False.")
                        return None
            except Exception as e:
                logger.error(f"Error during pre-check for chunk name '{name_str}': {e}", exc_info=True)
                return None
        
        parameters_for_chunk_creation = {
            "source_node_uuid_param": source_node_uuid,
            "chunk_uuid_param": chunk_uuid_str,
            "chunk_content_param": actual_chunk_content_to_store, 
            "source_identifier_param": source_identifier_for_chunk_desc, 
            "created_at_ts_param": created_at_ts,
            "dynamic_chunk_properties_param": final_dynamic_props_for_chunk,
            "chunk_number_param_for_rel": chunk_number_for_rel if chunk_number_for_rel is not None else 0,
        }
        
        created_chunk_uuid_from_db = None 
        try:
            results, summary, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.ADD_CHUNK_AND_LINK_TO_SOURCE, 
                parameters_for_chunk_creation, 
                database_=self.database
            )
            if results and results[0]["chunk_uuid"]:
                created_chunk_uuid_from_db = results[0]["chunk_uuid"]
                # ... (logging for chunk add/update)
            else:
                logger.error(f"Failed to create/update chunk '{name_str}': No UUID returned from main Cypher operation.")
                return None 
        except Exception as e:
            # ... (error handling for chunk creation)
            if "Failed to invoke procedure `apoc.do.when`" in str(e):
                logger.error("APOC `apoc.do.when` not found. Ensure APOC plugin is installed.", exc_info=False)
            logger.error(f"Error in main Cypher operation for chunk '{name_str}': {e}", exc_info=True)
            return None
        
        # --- Entity Extraction and Linking ---
        if created_chunk_uuid_from_db and self.entity_extractor:
            logger.debug(f"    Attempting entity extraction for chunk: {created_chunk_uuid_from_db} (Name: '{name_str}')")
            extracted_entities_list_model = await self.entity_extractor.extract_entities(
                text_content=page_content, 
                context_text=previous_chunk_content
            )
            if extracted_entities_list_model.entities:
                logger.info(f"    [bold green]Entities Extracted for chunk '{name_str}' ({created_chunk_uuid_from_db}):[/bold green]")
                for extracted_entity_data in extracted_entities_list_model.entities:
                    entity_data: ExtractedEntity = extracted_entity_data
                    
                    normalized_name = normalize_entity_name(entity_data.name)
                    if not normalized_name:
                        logger.warning(f"      Skipping entity with empty normalized name (original: '{entity_data.name}')")
                        continue

                    entity_uuid_val = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{normalized_name}_{entity_data.label}"))
                    
                    entity_params_merge = { # Parameters for the MERGE query
                        "uuid_param": entity_uuid_val,
                        "name_param": entity_data.name, 
                        "normalized_name_param": normalized_name,
                        "label_param": entity_data.label,
                        "description_param": entity_data.description,
                        "created_at_ts_param": created_at_ts,
                    }
                    try:
                        # Execute MERGE_ENTITY_NODE
                        entity_results, entity_summary, _ = await self.driver.execute_query( # type: ignore
                            cypher_queries.MERGE_ENTITY_NODE,
                            entity_params_merge,
                            database_=self.database
                        )
                        if entity_results and entity_results[0]["entity_uuid"]:
                            db_entity_uuid = entity_results[0]["entity_uuid"]
                            current_db_name = entity_results[0]["current_entity_name"] # Get current name from DB
                            action = "created" if entity_summary.counters.nodes_created > 0 else "merged/updated" # type: ignore
                            
                            final_entity_name_to_log = entity_data.name # Default to new name

                            # Python logic to decide if name needs a separate update
                            if action == "merged/updated" and current_db_name and entity_data.name:
                                if len(entity_data.name) > len(current_db_name):
                                    logger.debug(f"      New name '{entity_data.name}' is longer than existing '{current_db_name}'. Updating.")
                                    await self.driver.execute_query(
                                        cypher_queries.UPDATE_ENTITY_NAME,
                                        {"uuid_param": db_entity_uuid, "new_name_param": entity_data.name},
                                        database_=self.database
                                    )
                                    final_entity_name_to_log = entity_data.name
                                else:
                                    final_entity_name_to_log = current_db_name # Log the name that's now in DB
                            elif action == "created":
                                final_entity_name_to_log = entity_data.name


                            logger.debug(f"      Entity node {action}: [cyan]{db_entity_uuid}[/cyan] (Name: '{final_entity_name_to_log}', NormName: '{normalized_name}', Label: '{entity_data.label}')")

                            link_params = {
                                "chunk_uuid_param": created_chunk_uuid_from_db,
                                "entity_uuid_param": db_entity_uuid,
                                "created_at_ts_param": created_at_ts,
                            }
                            await self.driver.execute_query( # type: ignore
                                cypher_queries.LINK_CHUNK_TO_ENTITY,
                                link_params,
                                database_=self.database
                            )
                            logger.debug(f"        -> Linked Chunk '{created_chunk_uuid_from_db}' to Entity '{db_entity_uuid}' via MENTIONS_ENTITY.")

                            if self.embedder:
                                try:
                                    entity_name_embedding = await self.embedder.embed_text(final_entity_name_to_log) # Embed the name that's in DB
                                    if entity_name_embedding:
                                        await self.driver.execute_query( # type: ignore
                                            cypher_queries.SET_ENTITY_NAME_EMBEDDING,
                                            {"entity_uuid_param": db_entity_uuid, "embedding_vector_param": entity_name_embedding},
                                            database_=self.database
                                        )
                                        logger.debug(f"        -> Stored name embedding for Entity '{db_entity_uuid}'.")
                                except Exception as e_embed_entity:
                                     logger.error(f"      Error embedding or storing entity name embedding for {db_entity_uuid}: {e_embed_entity}", exc_info=True)
                        else:
                            logger.warning(f"      Failed to create/merge entity: {entity_data.name}")
                    except Exception as e_entity:
                        logger.error(f"      Error processing extracted entity '{entity_data.name}': {e_entity}", exc_info=True)
            else:
                logger.info(f"    No entities extracted for chunk '{name_str}' ({created_chunk_uuid_from_db}).")
        
        # ... (chunk embedding logic - NO CHANGES HERE) ...
        if created_chunk_uuid_from_db and self.embedder:
            try:
                logger.debug(f"    Generating embedding for chunk content of: {created_chunk_uuid_from_db} (Name: '{name_str}')...")
                embedding_vector = await self.embedder.embed_text(text_content_to_embed)
                if embedding_vector: 
                    embedding_params = {
                        "chunk_uuid_param": created_chunk_uuid_from_db,
                        "embedding_vector_param": embedding_vector
                    }
                    embed_results, embed_summary, embed_keys = await self.driver.execute_query( # type: ignore
                        cypher_queries.SET_CHUNK_CONTENT_EMBEDDING,
                        embedding_params,
                        database_=self.database
                    )
                    if embed_results and embed_results[0].get("uuid_processed") == created_chunk_uuid_from_db:
                        logger.debug(f"    Successfully called procedure to store embedding for chunk: {created_chunk_uuid_from_db}")
                    else:
                        logger.warning(f"    Storing embedding query returned an unexpected UUID or no result for chunk {created_chunk_uuid_from_db}.")
                else:
                    logger.warning(f"    Embedding vector was empty for chunk {created_chunk_uuid_from_db}. Skipping embedding storage.")
            except Exception as e:
                logger.error(f"    Failed to generate or store embedding for chunk {created_chunk_uuid_from_db}: {e}", exc_info=True)
        elif created_chunk_uuid_from_db and not self.embedder:
            logger.debug(f"    No embedder configured. Skipping embedding for chunk {created_chunk_uuid_from_db}.")


        return created_chunk_uuid_from_db

    # ... (add_documents_from_source remains the same) ...
    async def add_documents_from_source(
        self,
        source_identifier: str,
        documents_data: List[dict], 
        source_content: Optional[str] = None,
        source_dynamic_metadata: Optional[dict] = None,
        allow_same_name_chunks_for_this_source: bool = True
    ) -> Tuple[Optional[str], List[str]]:
        logger.info(f"Processing source: [magenta]{source_identifier}[/magenta]")
        source_node_uuid = await self._create_or_merge_source_node( 
            source_identifier, source_content, source_dynamic_metadata
        )

        if not source_node_uuid:
            logger.error(f"  Failed to create/merge source node for '{source_identifier}'. Aborting chunk processing for this source.")
            return None, []

        added_chunk_uuids: List[str] = []
        previous_chunk_page_content: Optional[str] = None 

        for doc_idx, chunk_data in enumerate(documents_data):
            page_content = chunk_data.get("page_content", "")
            chunk_metadata = chunk_data.get("metadata", {})

            chunk_name_for_log = chunk_metadata.get('name', f"Unnamed Chunk {doc_idx+1}")
            chunk_num_for_log = chunk_metadata.get('chunk_number', 'N/A (e.g. product)')

            logger.debug(f"  Processing chunk {doc_idx + 1}/{len(documents_data)}: Name='{chunk_name_for_log}', Number={chunk_num_for_log}")

            created_chunk_uuid = await self._add_single_chunk_and_link(
                page_content=page_content, 
                chunk_metadata=chunk_metadata, 
                source_node_uuid=source_node_uuid,
                source_identifier_for_chunk_desc=source_identifier,
                allow_same_name_chunks_flag=allow_same_name_chunks_for_this_source,
                previous_chunk_content=previous_chunk_page_content 
            )
            if created_chunk_uuid:
                added_chunk_uuids.append(created_chunk_uuid)
            else:
                logger.warning(f"    Failed to add chunk: Name='{chunk_name_for_log}'")
            
            previous_chunk_page_content = page_content 

        logger.info(f"Finished processing source [magenta]{source_identifier}[/magenta]. Added {len(added_chunk_uuids)} chunks.")
        return source_node_uuid, added_chunk_uuids