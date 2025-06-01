# graphforrag_core/graphforrag.py
import logging
import uuid
from datetime import datetime, timezone
import json
from typing import Optional, Any, List, Tuple, Dict # Added Dict


from neo4j import AsyncGraphDatabase, AsyncDriver # type: ignore
from config import cypher_queries
from .embedder_client import EmbedderClient
from .openai_embedder import OpenAIEmbedder
from .utils import preprocess_metadata_for_neo4j, normalize_entity_name
from .schema_manager import SchemaManager
from .entity_extractor import EntityExtractor
from .entity_resolver import EntityResolver
from .relationship_extractor import RelationshipExtractor # <-- IMPORTED RelationshipExtractor
from .node_manager import NodeManager
from config.llm_prompts import ExtractedEntity, EntityDeduplicationDecision, ExtractedRelationship # Added ExtractedRelationship
from files.llm_models import setup_fallback_model
from pydantic_ai.usage import Usage
from pydantic import BaseModel


logger = logging.getLogger("graph_for_rag")

# Simple Pydantic model to hold resolved entity info for relationship mapping
class ResolvedEntityInfo(BaseModel):
    uuid: str
    name: str # This should be the canonical/final name in DB
    label: str


class GraphForRAG:
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
            
            _llm_for_services = llm_client if llm_client else setup_fallback_model()

            self.entity_extractor = EntityExtractor(llm_client=_llm_for_services)
            self.entity_resolver = EntityResolver( 
                driver=self.driver,
                database_name=self.database,
                embedder_client=self.embedder,
                llm_client=_llm_for_services
            )
            self.relationship_extractor = RelationshipExtractor(llm_client=_llm_for_services) # <-- INITIALIZE
            
            self.schema_manager = SchemaManager(self.driver, self.database, self.embedder)
            self.node_manager = NodeManager(self.driver, self.database)
            
            self.total_llm_usage: Usage = Usage()

            logger.info(f"Using embedder: {self.embedder.config.model_name} with dimension {self.embedder.dimension}")
            
            services_llm_model_name = "Unknown"
            if hasattr(_llm_for_services, 'model') and isinstance(_llm_for_services.model, str):
                services_llm_model_name = _llm_for_services.model
            elif hasattr(_llm_for_services, 'model_name') and isinstance(_llm_for_services.model_name, str):
                services_llm_model_name = _llm_for_services.model_name
            logger.info(f"GraphForRAG initialized. LLM for Entity/Relationship Services: {services_llm_model_name}")
            logger.info(f"Successfully initialized Neo4j driver for database '{database}' at '{uri}'")
        except Exception as e:
            logger.error(f"Failed to initialize GraphForRAG: {e}", exc_info=True)
            raise

    # ... (_accumulate_usage, get_total_llm_usage, close, schema methods, _create_or_merge_source_node remain the same)
    def _accumulate_usage(self, new_usage: Optional[Usage]):
        if new_usage and hasattr(new_usage, 'has_values') and new_usage.has_values():
            self.total_llm_usage = self.total_llm_usage + new_usage # type: ignore
    
    def get_total_llm_usage(self) -> Usage: # type: ignore
        return self.total_llm_usage

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
        source_content: Optional[str] = None,
        source_dynamic_metadata: Optional[dict] = None
    ) -> Optional[str]:
        created_at = datetime.now(timezone.utc)
        processed_metadata = preprocess_metadata_for_neo4j(source_dynamic_metadata)

        returned_uuid = await self.node_manager.create_or_merge_source_node(
            identifier=source_identifier,
            content=source_content,
            dynamic_metadata=processed_metadata,
            created_at=created_at
        )

        if returned_uuid:
            logger.debug(f"Source node processed by NodeManager: UUID '{returned_uuid}', Identifier: '{source_identifier}'.")
            if source_content and self.embedder:
                embedding_vector = await self.embedder.embed_text(source_content)
                if embedding_vector:
                    if await self.node_manager.set_source_content_embedding(returned_uuid, embedding_vector):
                        logger.debug(f"  Successfully stored embedding for Source node: {returned_uuid}")
                    else:
                        logger.warning(f"  Failed to store embedding for Source node: {returned_uuid}")
                else:
                    logger.warning(f"  Source content embedding vector was empty for {returned_uuid}. Skipping storage.")
        return returned_uuid

    async def _add_single_chunk_and_link(
        self,
        page_content: str,
        chunk_metadata: dict,
        source_node_uuid: str,
        source_identifier_for_chunk_desc: str,
        allow_same_name_chunks_flag: bool = True,
        previous_chunk_content: Optional[str] = None
    ) -> Optional[str]:
        
        # --- Chunk Preparation & DB Operation ---
        # (This part remains the same - creating/merging the chunk node)
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
                            break
                    name_str = derived_name
            except json.JSONDecodeError:
                logger.warning(f"    Could not parse JSON for chunk, treating as text. Name hint: '{name_from_meta or chunk_uuid_str}'")
        if not name_str: 
            name_str = (page_content[:50] + '...') if len(page_content) > 50 else page_content
        dynamic_props_for_chunk["name"] = name_str
        if chunk_number_for_rel is not None:
            dynamic_props_for_chunk["chunk_number"] = chunk_number_for_rel
        final_dynamic_props_for_chunk = preprocess_metadata_for_neo4j(dynamic_props_for_chunk)
        created_at_ts = datetime.now(timezone.utc)

        if not allow_same_name_chunks_flag:
            existing_chunk_records, _, _ = await self.driver.execute_query("MATCH (c:Chunk {name: $name}) RETURN c.uuid AS uuid LIMIT 1", name=name_str, database_=self.database) # type: ignore
            if existing_chunk_records and existing_chunk_records[0]["uuid"] != chunk_uuid_str:
                logger.warning(f"Chunk name '{name_str}' already exists. Skipping due to allow_same_name_chunks_flag=False.")
                return None
        
        created_chunk_uuid_from_db = await self.node_manager.create_chunk_node_and_link_to_source(
            chunk_uuid=chunk_uuid_str, chunk_content=actual_chunk_content_to_store,
            source_node_uuid=source_node_uuid, source_identifier_for_chunk_desc=source_identifier_for_chunk_desc,
            created_at=created_at_ts, dynamic_chunk_properties=final_dynamic_props_for_chunk,
            chunk_number_for_rel=chunk_number_for_rel
        )
        if not created_chunk_uuid_from_db:
            logger.error(f"Failed to create/link chunk '{name_str}' via NodeManager.")
            return None
        logger.debug(f"  Chunk processed by NodeManager: UUID '{created_chunk_uuid_from_db}', Name: '{name_str}'")

        # --- Entity Processing ---
        resolved_entities_for_chunk: List[ResolvedEntityInfo] = [] 

        if created_chunk_uuid_from_db and self.entity_extractor and self.entity_resolver:
            extracted_entities_list_model, extractor_usage = await self.entity_extractor.extract_entities(
                text_content=page_content, context_text=previous_chunk_content
            )
            self._accumulate_usage(extractor_usage)

            if extracted_entities_list_model.entities:
                logger.info(f"    --- Starting Entity Resolution for Chunk '{name_str}' ---")
                for extracted_entity_data in extracted_entities_list_model.entities:
                    entity_data: ExtractedEntity = extracted_entity_data
                    
                    resolution_decision, resolver_usage = await self.entity_resolver.resolve_entity(entity_data)
                    self._accumulate_usage(resolver_usage)
                    
                    canonical_name_from_resolver = resolution_decision.canonical_name
                    normalized_name_for_key = normalize_entity_name(canonical_name_from_resolver)
                    label_for_key = entity_data.label 
                    description_from_extraction = entity_data.description
                    
                    db_entity_uuid: Optional[str] = None
                    final_entity_name_in_db: str = canonical_name_from_resolver
                    final_entity_description_to_set: Optional[str] = description_from_extraction # Default for new

                    try:
                        if resolution_decision.is_duplicate and resolution_decision.duplicate_of_uuid:
                            db_entity_uuid = resolution_decision.duplicate_of_uuid
                            # ... (logic for updating existing entity as in the previous correct step)
                            logger.info(f"      Entity '{entity_data.name}' resolved as DUPLICATE of existing Entity UUID: '{db_entity_uuid}'. Canonical name: '{canonical_name_from_resolver}'")
                            node_details = await self.node_manager.fetch_entity_details(db_entity_uuid)
                            current_db_name = None
                            current_db_description = None
                            if node_details:
                                _, current_db_name, current_db_description, _ = node_details
                            
                            final_entity_name_in_db = current_db_name if current_db_name else canonical_name_from_resolver
                            name_updated_in_db = False # Flag to track if name was explicitly updated

                            if canonical_name_from_resolver and current_db_name and \
                               len(canonical_name_from_resolver) > len(current_db_name) and \
                               canonical_name_from_resolver != current_db_name:
                                if await self.node_manager.update_entity_name(db_entity_uuid, canonical_name_from_resolver, created_at_ts):
                                    final_entity_name_in_db = canonical_name_from_resolver
                                    name_updated_in_db = True
                                    logger.debug(f"        Updated name for Entity '{db_entity_uuid}' to '{final_entity_name_in_db}'.")
                            elif not current_db_name and canonical_name_from_resolver:
                                 if await self.node_manager.update_entity_name(db_entity_uuid, canonical_name_from_resolver, created_at_ts):
                                    final_entity_name_in_db = canonical_name_from_resolver
                                    name_updated_in_db = True
                                    logger.debug(f"        Set name for Entity '{db_entity_uuid}' to '{final_entity_name_in_db}'.")
                            
                            if description_from_extraction:
                                if current_db_description and description_from_extraction not in current_db_description:
                                    final_entity_description_to_set = f"{current_db_description} | {description_from_extraction}"
                            else:
                                final_entity_description_to_set = current_db_description
                            
                            if final_entity_description_to_set != current_db_description:
                                await self.node_manager.update_entity_description(db_entity_uuid, final_entity_description_to_set, created_at_ts)
                                logger.debug(f"        Updated description for Entity '{db_entity_uuid}'.")
                            elif not name_updated_in_db : # If neither name nor description specifically updated, still touch updated_at
                                 await self.driver.execute_query("MATCH (e:Entity {uuid: $uuid}) SET e.updated_at = $ts", uuid=db_entity_uuid, ts=created_at_ts, database_=self.database) # type: ignore
                                 logger.debug(f"        Touched updated_at for Entity '{db_entity_uuid}'.")

                        else: # Not a duplicate, create a new entity
                            new_entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{normalized_name_for_key}_{label_for_key}"))
                            logger.info(f"      Entity '{entity_data.name}' resolved as NEW. Name: '{canonical_name_from_resolver}', Desc: '{description_from_extraction}', Target UUID: {new_entity_uuid}")
                            
                            final_entity_name_in_db = canonical_name_from_resolver
                            final_entity_description_to_set = description_from_extraction
                            
                            # Use the correct method name from NodeManager
                            merge_result = await self.node_manager.merge_or_create_entity_node( # <-- CORRECTED METHOD NAME
                                entity_uuid_to_create_if_new=new_entity_uuid,
                                name_for_create=final_entity_name_in_db,
                                normalized_name_for_merge=normalized_name_for_key,
                                label_for_merge=label_for_key,
                                description_for_create=final_entity_description_to_set,
                                created_at_ts=created_at_ts
                            )
                            if merge_result:
                                db_entity_uuid = merge_result[0]
                                final_entity_name_in_db = merge_result[1] if merge_result[1] else final_entity_name_in_db 
                            else:
                                logger.error(f"      Failed to MERGE/CREATE new entity '{canonical_name_from_resolver}' using NodeManager.")
                                continue 
                        
                        if db_entity_uuid:
                            # ... (rest of linking and embedding logic)
                            resolved_entities_for_chunk.append(ResolvedEntityInfo(uuid=db_entity_uuid, name=final_entity_name_in_db, label=label_for_key))
                            await self.node_manager.link_chunk_to_entity(created_chunk_uuid_from_db, db_entity_uuid, created_at_ts)
                            logger.debug(f"        -> Linked Chunk to Entity '{db_entity_uuid}'.")
                            if self.embedder and final_entity_name_in_db:
                                if await self.node_manager.set_entity_name_embedding(db_entity_uuid, await self.embedder.embed_text(final_entity_name_in_db)):
                                    logger.debug(f"        -> Stored name embedding for Entity '{db_entity_uuid}'.")
                        else:
                            logger.warning(f"      Skipping link and embed for entity '{entity_data.name}' as db_entity_uuid was not established.")
                    
                    except Exception as e_entity_processing:
                        logger.error(f"      Error processing resolved entity '{entity_data.name}': {e_entity_processing}", exc_info=True)
                logger.info(f"    --- Finished Entity Resolution for Chunk '{name_str}' ---")

        # ... (Relationship Extraction and Chunk Embedding logic remains the same) ...
        if created_chunk_uuid_from_db and self.relationship_extractor and resolved_entities_for_chunk:
            logger.info(f"    --- Starting Relationship Extraction for Chunk '{name_str}' ---")
            extracted_relationships_list_model, rel_extractor_usage = await self.relationship_extractor.extract_relationships(
                text_content=page_content, 
                entities_in_chunk=resolved_entities_for_chunk 
            )
            self._accumulate_usage(rel_extractor_usage)

            if extracted_relationships_list_model.relationships:
                entity_name_to_uuid_map: Dict[str, str] = {
                    entity.name: entity.uuid for entity in resolved_entities_for_chunk 
                }
                for rel_data in extracted_relationships_list_model.relationships:
                    source_uuid = entity_name_to_uuid_map.get(rel_data.source_entity_name)
                    target_uuid = entity_name_to_uuid_map.get(rel_data.target_entity_name)

                    if not source_uuid or not target_uuid:
                        logger.warning(f"      Could not map source '{rel_data.source_entity_name}' or target '{rel_data.target_entity_name}' to UUIDs for relationship. Skipping.")
                        continue
                    if source_uuid == target_uuid:
                        logger.debug(f"      Skipping self-relationship for entity '{rel_data.source_entity_name}'.")
                        continue
                    
                    relationship_uuid = await self.node_manager.create_or_merge_relationship(
                        source_entity_uuid=source_uuid, target_entity_uuid=target_uuid,
                        relation_label=rel_data.relation_label, fact_sentence=rel_data.fact_sentence,
                        source_chunk_uuid=created_chunk_uuid_from_db, created_at_ts=created_at_ts
                    )
                    if relationship_uuid and self.embedder:
                        fact_embedding = await self.embedder.embed_text(rel_data.fact_sentence)
                        if fact_embedding:
                            await self.node_manager.set_relationship_fact_embedding(relationship_uuid, fact_embedding)
                            logger.debug(f"        -> Stored fact embedding for relationship '{relationship_uuid}'.")
            else:
                logger.info(f"    No relationships extracted for chunk '{name_str}'.")
            logger.info(f"    --- Finished Relationship Extraction for Chunk '{name_str}' ---")
        
        if created_chunk_uuid_from_db and self.embedder:
            embedding_vector = await self.embedder.embed_text(text_content_to_embed)
            if embedding_vector: 
                if await self.node_manager.set_chunk_content_embedding(created_chunk_uuid_from_db, embedding_vector):
                    logger.debug(f"    Successfully stored embedding for chunk: {created_chunk_uuid_from_db}")
            else:
                logger.warning(f"    Embedding vector was empty for chunk {created_chunk_uuid_from_db}. Skipping embedding storage.")
        
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