# graphforrag_core/build_knowledge_base.py
import logging
import uuid
from datetime import datetime, timezone
import json
from typing import Optional, Any, List, Tuple, Dict

from neo4j import AsyncDriver # type: ignore
from pydantic_ai.usage import Usage

from config import cypher_queries 
from .embedder_client import EmbedderClient
from .utils import preprocess_metadata_for_neo4j, normalize_entity_name
from .entity_extractor import EntityExtractor
from .entity_resolver import EntityResolver
from .relationship_extractor import RelationshipExtractor
from .node_manager import NodeManager
from config.llm_prompts import ExtractedEntity, EntityDeduplicationDecision 
from .types import ResolvedEntityInfo 

logger = logging.getLogger("graph_for_rag.build_knowledge_base")

async def _process_single_chunk_for_kb(
    page_content: str,
    chunk_metadata: dict,
    source_node_uuid: str,
    source_identifier_for_chunk_desc: str,
    node_manager: NodeManager,
    embedder: EmbedderClient, 
    entity_extractor: EntityExtractor,
    entity_resolver: EntityResolver,
    relationship_extractor: RelationshipExtractor,
    allow_same_name_chunks_flag: bool = True,
    previous_chunk_content: Optional[str] = None
) -> Tuple[Optional[str], Usage, Usage]: # MODIFIED: Returns (chunk_uuid, generative_usage, embedding_usage)
    
    current_chunk_generative_usage = Usage() # For LLM calls related to this chunk (extraction, resolution, etc.)
    current_chunk_embedding_usage = Usage()  # For embedding calls related to this chunk

    # --- Chunk Preparation & DB Operation ---
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
                for key, value in json_data.items(): dynamic_props_for_chunk[key] = value
                name_override_keys = ["productName", "title", "item_name", "name"]
                derived_name = name_from_meta
                for key in name_override_keys:
                    if key in json_data and isinstance(json_data[key], str) and json_data[key]:
                        derived_name = json_data[key]; break
                name_str = derived_name
        except json.JSONDecodeError:
            logger.warning(f"    Could not parse JSON for chunk, treating as text. Name hint: '{name_from_meta or chunk_uuid_str}'")
    
    if not name_str: name_str = (page_content[:50] + '...') if len(page_content) > 50 else page_content
    
    dynamic_props_for_chunk["name"] = name_str
    if chunk_number_for_rel is not None: dynamic_props_for_chunk["chunk_number"] = chunk_number_for_rel
    
    final_dynamic_props_for_chunk = preprocess_metadata_for_neo4j(dynamic_props_for_chunk)
    created_at_ts = datetime.now(timezone.utc)

    created_chunk_uuid_from_db = await node_manager.create_chunk_node_and_link_to_source(
        chunk_uuid=chunk_uuid_str, chunk_content=actual_chunk_content_to_store,
        source_node_uuid=source_node_uuid, source_identifier_for_chunk_desc=source_identifier_for_chunk_desc,
        created_at=created_at_ts, dynamic_chunk_properties=final_dynamic_props_for_chunk,
        chunk_number_for_rel=chunk_number_for_rel
    )
    if not created_chunk_uuid_from_db:
        logger.error(f"Failed to create/link chunk '{name_str}' via NodeManager.")
        return None, current_chunk_generative_usage, current_chunk_embedding_usage


    # --- Entity Processing ---
    resolved_entities_for_chunk: List[ResolvedEntityInfo] = [] 
    if created_chunk_uuid_from_db and entity_extractor and entity_resolver:
        extracted_entities_list_model, extractor_usage = await entity_extractor.extract_entities(
            text_content=page_content, context_text=previous_chunk_content
        )
        if extractor_usage: current_chunk_generative_usage += extractor_usage # type: ignore

        if extracted_entities_list_model.entities:
            logger.info(f"    --- Starting Entity Resolution for Chunk '{name_str}' ---")
            for extracted_entity_data_model in extracted_entities_list_model.entities:
                entity_data: ExtractedEntity = extracted_entity_data_model
                resolution_decision, resolver_usage = await entity_resolver.resolve_entity(entity_data)
                if resolver_usage: current_chunk_generative_usage += resolver_usage # type: ignore
                
                canonical_name_from_resolver = resolution_decision.canonical_name
                normalized_name_for_key = normalize_entity_name(canonical_name_from_resolver)
                label_for_key = entity_data.label
                final_entity_description_to_set = resolution_decision.canonical_description 
                
                db_entity_uuid: Optional[str] = None
                final_entity_name_in_db: str = canonical_name_from_resolver

                try:
                    if resolution_decision.is_duplicate and resolution_decision.duplicate_of_uuid:
                        db_entity_uuid = resolution_decision.duplicate_of_uuid
                        node_details = await node_manager.fetch_entity_details(db_entity_uuid)
                        current_db_name = None
                        current_db_description = None
                        if node_details: _, current_db_name, current_db_description, _ = node_details
                        
                        final_entity_name_in_db = current_db_name if current_db_name else canonical_name_from_resolver
                        name_updated_in_db = False

                        if canonical_name_from_resolver and current_db_name and \
                           len(canonical_name_from_resolver) > len(current_db_name) and \
                           canonical_name_from_resolver != current_db_name:
                            if await node_manager.update_entity_name(db_entity_uuid, canonical_name_from_resolver, created_at_ts):
                                final_entity_name_in_db = canonical_name_from_resolver
                                name_updated_in_db = True
                        elif not current_db_name and canonical_name_from_resolver:
                             if await node_manager.update_entity_name(db_entity_uuid, canonical_name_from_resolver, created_at_ts):
                                final_entity_name_in_db = canonical_name_from_resolver
                                name_updated_in_db = True
                        
                        if final_entity_description_to_set != current_db_description: 
                            await node_manager.update_entity_description(
                                db_entity_uuid, 
                                final_entity_description_to_set, 
                                created_at_ts
                            )
                        elif not name_updated_in_db : 
                             await node_manager.driver.execute_query("MATCH (e:Entity {uuid: $uuid}) SET e.updated_at = $ts", uuid=db_entity_uuid, ts=created_at_ts, database_=node_manager.database) # type: ignore
                    else: 
                        new_entity_uuid_val = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{normalized_name_for_key}_{label_for_key}"))
                        final_entity_name_in_db = canonical_name_from_resolver
                        
                        merge_result = await node_manager.merge_or_create_entity_node(
                            entity_uuid_to_create_if_new=new_entity_uuid_val,
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
                            logger.error(f"      Failed to MERGE/CREATE new entity '{canonical_name_from_resolver}' via NodeManager.")
                            continue
                    
                    if db_entity_uuid:
                        resolved_entities_for_chunk.append(ResolvedEntityInfo(uuid=db_entity_uuid, name=final_entity_name_in_db, label=label_for_key))
                        await node_manager.link_chunk_to_entity(created_chunk_uuid_from_db, db_entity_uuid, created_at_ts)
                        
                        if embedder: 
                            if final_entity_name_in_db:
                                name_embedding, name_embed_usage = await embedder.embed_text(final_entity_name_in_db) 
                                if name_embed_usage: current_chunk_embedding_usage += name_embed_usage 
                                if name_embedding: 
                                    if await node_manager.set_entity_name_embedding(db_entity_uuid, name_embedding):
                                        logger.debug(f"        -> Stored name embedding for Entity '{db_entity_uuid}'.")
                            
                            if final_entity_description_to_set:
                                desc_embedding, desc_embed_usage = await embedder.embed_text(final_entity_description_to_set) 
                                if desc_embed_usage: current_chunk_embedding_usage += desc_embed_usage 
                                if desc_embedding: 
                                    await node_manager.set_entity_description_embedding(db_entity_uuid, desc_embedding) 
                                    logger.debug(f"        -> Stored description embedding for Entity '{db_entity_uuid}'.")
                    else:
                        logger.warning(f"      Skipping link and embed for entity '{entity_data.name}' as db_entity_uuid was not established.")
                except Exception as e_entity_processing:
                    logger.error(f"      Error processing resolved entity '{entity_data.name}': {e_entity_processing}", exc_info=True)
            logger.info(f"    --- Finished Entity Resolution for Chunk '{name_str}' ---")
            
    if created_chunk_uuid_from_db and relationship_extractor and resolved_entities_for_chunk:
        logger.info(f"    --- Starting Relationship Extraction for Chunk '{name_str}' ---")
        entities_for_rel_extraction = [ExtractedEntity(name=e.name, label=e.label, description=None) for e in resolved_entities_for_chunk]
        extracted_relationships_list_model, rel_extractor_usage = await relationship_extractor.extract_relationships(text_content=page_content, entities_in_chunk=entities_for_rel_extraction)
        if rel_extractor_usage: current_chunk_generative_usage += rel_extractor_usage # type: ignore
        if extracted_relationships_list_model.relationships:
            entity_name_to_uuid_map: Dict[str, str] = {entity.name: entity.uuid for entity in resolved_entities_for_chunk}
            for rel_data in extracted_relationships_list_model.relationships:
                source_uuid = entity_name_to_uuid_map.get(rel_data.source_entity_name)
                target_uuid = entity_name_to_uuid_map.get(rel_data.target_entity_name)
                if not source_uuid or not target_uuid:
                    continue
                if source_uuid == target_uuid: continue
                relationship_uuid = await node_manager.create_or_merge_relationship(source_entity_uuid=source_uuid, target_entity_uuid=target_uuid, relation_label=rel_data.relation_label, fact_sentence=rel_data.fact_sentence, source_chunk_uuid=created_chunk_uuid_from_db, created_at_ts=created_at_ts)
                if relationship_uuid and embedder:
                    fact_embedding, fact_embed_usage = await embedder.embed_text(rel_data.fact_sentence) 
                    if fact_embed_usage: current_chunk_embedding_usage += fact_embed_usage 
                    if fact_embedding: 
                        await node_manager.set_relationship_fact_embedding(relationship_uuid, fact_embedding) 
        else: logger.info(f"    No relationships extracted for chunk '{name_str}'.")
        logger.info(f"    --- Finished Relationship Extraction for Chunk '{name_str}' ---")

    if created_chunk_uuid_from_db and embedder:
        embedding_vector, chunk_embed_usage = await embedder.embed_text(text_content_to_embed) 
        if chunk_embed_usage: current_chunk_embedding_usage += chunk_embed_usage 
        if embedding_vector: 
            if await node_manager.set_chunk_content_embedding(created_chunk_uuid_from_db, embedding_vector):
                logger.debug(f"    Successfully stored embedding for chunk: {created_chunk_uuid_from_db}")
        else: logger.warning(f"    Embedding vector was empty for chunk {created_chunk_uuid_from_db}. Skipping embedding storage.")
    
    return created_chunk_uuid_from_db, current_chunk_generative_usage, current_chunk_embedding_usage

async def add_documents_to_knowledge_base(
    source_identifier: str,
    documents_data: List[dict], 
    node_manager: NodeManager,
    embedder: EmbedderClient,
    entity_extractor: EntityExtractor,
    entity_resolver: EntityResolver,
    relationship_extractor: RelationshipExtractor,
    source_content: Optional[str] = None,
    source_dynamic_metadata: Optional[dict] = None,
    allow_same_name_chunks_for_this_source: bool = True
) -> Tuple[Optional[str], List[str], Usage, Usage]: # MODIFIED: Returns (source_uuid, chunk_uuids, total_gen_usage, total_embed_usage)
    
    total_generative_usage_for_source_set = Usage() # For generative LLM calls
    total_embedding_usage_for_source_set = Usage()  # For embedding calls
    
    logger.info(f"Building knowledge base for source: [magenta]{source_identifier}[/magenta]")
    
    created_at = datetime.now(timezone.utc)
    processed_metadata = preprocess_metadata_for_neo4j(source_dynamic_metadata)
    source_node_uuid = await node_manager.create_or_merge_source_node(
        identifier=source_identifier,
        content=source_content,
        dynamic_metadata=processed_metadata,
        created_at=created_at
    )

    if not source_node_uuid:
        logger.error(f"  Failed to create/merge source node for '{source_identifier}'. Aborting chunk processing for this source.")
        return None, [], total_generative_usage_for_source_set, total_embedding_usage_for_source_set

    logger.debug(f"Source node processed by NodeManager: UUID '{source_node_uuid}', Identifier: '{source_identifier}'.")
    if source_content and embedder:
        embedding_vector, source_embed_usage = await embedder.embed_text(source_content) 
        if source_embed_usage: total_embedding_usage_for_source_set += source_embed_usage 
        if embedding_vector:
            if await node_manager.set_source_content_embedding(source_node_uuid, embedding_vector):
                logger.debug(f"  Successfully stored embedding for Source node: {source_node_uuid}")
            else:
                logger.warning(f"  Failed to store embedding for Source node: {source_node_uuid}")
        else:
            logger.warning(f"  Source content embedding vector was empty for {source_node_uuid}. Skipping storage.")


    added_chunk_uuids: List[str] = []
    previous_chunk_page_content: Optional[str] = None 

    for doc_idx, chunk_data in enumerate(documents_data):
        page_content = chunk_data.get("page_content", "")
        chunk_metadata = chunk_data.get("metadata", {})

        chunk_name_for_log = chunk_metadata.get('name', f"Unnamed Chunk {doc_idx+1}")
        chunk_num_for_log = chunk_metadata.get('chunk_number', 'N/A (e.g. product)')

        logger.debug(f"  Processing chunk {doc_idx + 1}/{len(documents_data)}: Name='{chunk_name_for_log}', Number={chunk_num_for_log}")

        # Now _process_single_chunk_for_kb returns three items
        created_chunk_uuid, chunk_gen_usage, chunk_embed_usage = await _process_single_chunk_for_kb(
            page_content=page_content, 
            chunk_metadata=chunk_metadata, 
            source_node_uuid=source_node_uuid,
            source_identifier_for_chunk_desc=source_identifier,
            node_manager=node_manager,
            embedder=embedder,
            entity_extractor=entity_extractor,
            entity_resolver=entity_resolver,
            relationship_extractor=relationship_extractor,
            allow_same_name_chunks_flag=allow_same_name_chunks_for_this_source,
            previous_chunk_content=previous_chunk_page_content 
        )
        if chunk_gen_usage: total_generative_usage_for_source_set += chunk_gen_usage # type: ignore
        if chunk_embed_usage: total_embedding_usage_for_source_set += chunk_embed_usage # type: ignore

        if created_chunk_uuid:
            added_chunk_uuids.append(created_chunk_uuid)
        else:
            logger.warning(f"    Failed to add chunk: Name='{chunk_name_for_log}'")
        
        previous_chunk_page_content = page_content 

    logger.info(f"Finished building knowledge base for source [magenta]{source_identifier}[/magenta]. Added {len(added_chunk_uuids)} chunks.")
    return source_node_uuid, added_chunk_uuids, total_generative_usage_for_source_set, total_embedding_usage_for_source_set