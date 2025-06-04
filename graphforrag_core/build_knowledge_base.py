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
    item_data: dict, 
    source_node_uuid: str,
    source_identifier_for_chunk_desc: str, 
    node_manager: NodeManager,
    embedder: EmbedderClient, 
    entity_extractor: EntityExtractor,
    entity_resolver: EntityResolver,
    relationship_extractor: RelationshipExtractor,
    allow_same_name_chunks_flag: bool = True, 
    previous_chunk_content: Optional[str] = None
) -> Tuple[Optional[str], Usage, Usage]: 
    
    current_item_generative_usage = Usage() 
    current_item_embedding_usage = Usage()  

    node_type_hint = item_data.get("node_type", "Chunk").lower()
    content_type_hint = item_data.get("content_type", "text").lower()
    item_metadata = item_data.get("metadata", {}).copy()

    item_uuid_str_for_node: Optional[str] = None

    if node_type_hint == "product":
        logger.info(f"    Processing as Product Definition: Name hint '{item_metadata.get('name', 'N/A')}'")
        new_product_uuid_str = str(item_metadata.pop("chunk_uuid", uuid.uuid4())) 
        
        product_name_from_meta = item_metadata.pop("name", "Unknown Product") 
        product_description_from_meta = item_metadata.pop("description", None)
        dynamic_product_properties_from_meta = item_metadata.copy()

        final_product_name = product_name_from_meta
        final_product_description = product_description_from_meta
        all_product_node_properties = dynamic_product_properties_from_meta.copy()

        if content_type_hint == "json":
            try:
                product_data_from_content = json.loads(page_content)
                if isinstance(product_data_from_content, dict):
                    final_product_name = product_data_from_content.get("productName", 
                                           product_data_from_content.get("title", 
                                           product_data_from_content.get("item_name", final_product_name)))
                    final_product_description = product_data_from_content.get("description", final_product_description)
                    for key, value in product_data_from_content.items():
                        all_product_node_properties[key] = value 
                else:
                    logger.warning(f"    Product definition page_content for '{final_product_name}' is not a JSON object.")
            except json.JSONDecodeError:
                logger.warning(f"    Could not parse page_content as JSON for product '{final_product_name}'.")
        elif not final_product_description and isinstance(page_content, str):
                 final_product_description = page_content

        # --- Promotion Check ---
        existing_entity_to_promote_uuid: Optional[str] = None
        if entity_resolver:
            logger.debug(f"    Checking if product '{final_product_name}' matches an existing Entity for promotion.")
            key_attributes_for_match = {
                k: all_product_node_properties[k] for k in ["brand", "sku", "category", "release_year"] 
                if k in all_product_node_properties and all_product_node_properties[k] is not None
            }

            # Call resolver, which now returns (matched_uuid, generative_usage, embedding_usage)
            matched_uuid, promotion_gen_usage, promotion_embed_usage = await entity_resolver.find_matching_entity_for_product_promotion(
                new_product_name=final_product_name,
                new_product_description=final_product_description,
                new_product_attributes=key_attributes_for_match
            )
            if promotion_gen_usage: current_item_generative_usage += promotion_gen_usage
            if promotion_embed_usage: current_item_embedding_usage += promotion_embed_usage
            
            if matched_uuid:
                existing_entity_to_promote_uuid = matched_uuid
        # --- End Promotion Check ---

        created_product_uuid_final: Optional[str] = None
        created_at_ts = datetime.now(timezone.utc)
        
        final_dynamic_product_properties_for_node = preprocess_metadata_for_neo4j(all_product_node_properties)
        # Clean up properties that are explicitly set in Cypher or by params
        for key_to_pop in ["name", "description", "uuid", "created_at", "updated_at", "processed_at"]:
            final_dynamic_product_properties_for_node.pop(key_to_pop, None)

        if existing_entity_to_promote_uuid:
            logger.info(f"    Promoting existing Entity '{existing_entity_to_promote_uuid}' to Product '{final_product_name}' (new Product UUID: {new_product_uuid_str}).")
            created_product_uuid_final = await node_manager.promote_entity_to_product(
                existing_entity_uuid=existing_entity_to_promote_uuid,
                new_product_uuid=new_product_uuid_str, 
                new_product_name=final_product_name,
                new_product_description=final_product_description,
                new_product_dynamic_properties=final_dynamic_product_properties_for_node,
                promotion_timestamp=created_at_ts
            )
            if created_product_uuid_final:
                 item_uuid_str_for_node = created_product_uuid_final
            else:
                logger.error(f"    Promotion failed for Entity '{existing_entity_to_promote_uuid}'. Will attempt to create Product as new.")
                existing_entity_to_promote_uuid = None 

        if not existing_entity_to_promote_uuid and not created_product_uuid_final: 
            logger.debug(f"    Creating new Product node for '{final_product_name}' (UUID: {new_product_uuid_str}).")
            created_product_uuid_final = await node_manager.create_or_merge_product_node(
                product_uuid=new_product_uuid_str, 
                name=final_product_name,
                description=final_product_description,
                created_at=created_at_ts,
                dynamic_product_properties=final_dynamic_product_properties_for_node
            )
            item_uuid_str_for_node = created_product_uuid_final

        if created_product_uuid_final:
            await node_manager.link_product_to_source(created_product_uuid_final, source_node_uuid, created_at_ts)
            if embedder:
                if final_product_name:
                    name_embedding, name_embed_usage = await embedder.embed_text(final_product_name)
                    if name_embed_usage: current_item_embedding_usage += name_embed_usage
                    if name_embedding: await node_manager.set_product_name_embedding(created_product_uuid_final, name_embedding)
                if final_product_description:
                    desc_embedding, desc_embed_usage = await embedder.embed_text(final_product_description)
                    if desc_embed_usage: current_item_embedding_usage += desc_embed_usage
                    if desc_embedding: await node_manager.set_product_description_embedding(created_product_uuid_final, desc_embedding)
            logger.debug(f"    Product '{final_product_name}' (UUID: {created_product_uuid_final}) processed.")
        else:
            logger.error(f"    Failed to create or promote product node for '{final_product_name}'.")
        
    elif node_type_hint == "chunk": 
        chunk_uuid_str = str(item_metadata.pop("chunk_uuid", uuid.uuid4()))
        name_str = item_metadata.pop("name", None)
        chunk_number_for_rel = item_metadata.pop("chunk_number", None)
        
        dynamic_props_for_chunk_from_meta = item_metadata.copy() 
        actual_chunk_content_to_store = page_content
        text_content_to_embed = page_content
        if not name_str: name_str = (page_content[:50] + '...') if len(page_content) > 50 else page_content
        created_at_ts = datetime.now(timezone.utc)

        # Prepare dynamic properties for the Chunk node, excluding explicitly set fields
        final_dynamic_props_for_chunk_node = preprocess_metadata_for_neo4j(dynamic_props_for_chunk_from_meta)
        for key_to_pop in ["name", "chunk_number", "source_description", "content", "uuid", 
                           "created_at", "processed_at", "entity_count", "relationship_count"]:
            final_dynamic_props_for_chunk_node.pop(key_to_pop, None)
        
        # Properties explicitly passed to the Cypher query or set within it
        # The Cypher query `ADD_CHUNK_AND_LINK_TO_SOURCE` needs to be aware of how `name` and `chunk_number` are handled.
        # Currently, it relies on them being in `$dynamic_chunk_properties_param`.
        # For clarity, we ensure they are in the map we pass.
        properties_for_chunk_node_cypher = {"name": name_str}
        if chunk_number_for_rel is not None:
            properties_for_chunk_node_cypher["chunk_number"] = chunk_number_for_rel
        properties_for_chunk_node_cypher.update(final_dynamic_props_for_chunk_node)


        created_chunk_uuid_from_db = await node_manager.create_chunk_node_and_link_to_source(
            chunk_uuid=chunk_uuid_str, 
            chunk_content=actual_chunk_content_to_store,
            source_node_uuid=source_node_uuid, 
            source_identifier_for_chunk_desc=source_identifier_for_chunk_desc,
            created_at=created_at_ts, 
            dynamic_chunk_properties=properties_for_chunk_node_cypher, # Pass the combined map
            chunk_number_for_rel=chunk_number_for_rel 
        )
        
        if not created_chunk_uuid_from_db:
            logger.error(f"Failed to create/link chunk '{name_str}' via NodeManager.")
            return None, current_item_generative_usage, current_item_embedding_usage
        
        item_uuid_str_for_node = created_chunk_uuid_from_db

        resolved_entities_for_chunk: List[ResolvedEntityInfo] = [] 
        if created_chunk_uuid_from_db and entity_extractor and entity_resolver:
            extracted_entities_list_model, extractor_usage = await entity_extractor.extract_entities(
                text_content=page_content, context_text=previous_chunk_content
            )
            if extractor_usage: current_item_generative_usage += extractor_usage 

            if extracted_entities_list_model.entities:
                logger.info(f"    --- Starting Entity Resolution for Chunk '{name_str}' ---")
                for extracted_entity_data_model in extracted_entities_list_model.entities:
                    entity_data: ExtractedEntity = extracted_entity_data_model
                    # resolve_entity returns (decision, gen_usage, embed_usage)
                    resolution_decision, resolver_gen_usage, resolver_embed_usage = await entity_resolver.resolve_entity(entity_data)
                    
                    if resolver_gen_usage: current_item_generative_usage += resolver_gen_usage 
                    if resolver_embed_usage: current_item_embedding_usage += resolver_embed_usage 
                    
                    canonical_name_from_resolver = resolution_decision.canonical_name
                    final_entity_description_to_set = resolution_decision.canonical_description
                    db_node_uuid_to_link: Optional[str] = None
                    node_type_of_linked_node: Optional[str] = None
                    final_node_name_in_db: str = canonical_name_from_resolver

                    try:
                        if resolution_decision.is_duplicate and resolution_decision.duplicate_of_uuid:
                            db_node_uuid_to_link = resolution_decision.duplicate_of_uuid
                            node_labels_result, _, _ = await node_manager.driver.execute_query(
                                "MATCH (n {uuid: $uuid}) RETURN labels(n) as node_labels",
                                uuid=db_node_uuid_to_link, database_=node_manager.database
                            )
                            if node_labels_result and node_labels_result[0]["node_labels"]:
                                labels_list = node_labels_result[0]["node_labels"]
                                if "Product" in labels_list: node_type_of_linked_node = "Product"
                                elif "Entity" in labels_list: node_type_of_linked_node = "Entity"
                            
                            if node_type_of_linked_node == "Product":
                                logger.info(f"      Entity '{entity_data.name}' resolved as DUPLICATE of existing PRODUCT UUID: '{db_node_uuid_to_link}'.")
                                product_details_res, _, _ = await node_manager.driver.execute_query("MATCH (p:Product {uuid: $uuid}) RETURN p.name as name", uuid=db_node_uuid_to_link, database_=node_manager.database) # type: ignore
                                if product_details_res and product_details_res[0]: final_node_name_in_db = product_details_res[0].get("name", canonical_name_from_resolver)
                            
                            elif node_type_of_linked_node == "Entity":
                                logger.info(f"      Entity '{entity_data.name}' resolved as DUPLICATE of existing ENTITY UUID: '{db_node_uuid_to_link}'.")
                                node_details = await node_manager.fetch_entity_details(db_node_uuid_to_link)
                                current_db_name = None; current_db_description = None
                                if node_details: _, current_db_name, current_db_description, _ = node_details
                                final_node_name_in_db = current_db_name if current_db_name else canonical_name_from_resolver
                                name_updated_in_db = False
                                if canonical_name_from_resolver and current_db_name and \
                                   len(canonical_name_from_resolver) > len(current_db_name) and \
                                   canonical_name_from_resolver != current_db_name:
                                    if await node_manager.update_entity_name(db_node_uuid_to_link, canonical_name_from_resolver, created_at_ts):
                                        final_node_name_in_db = canonical_name_from_resolver; name_updated_in_db = True
                                elif not current_db_name and canonical_name_from_resolver:
                                     if await node_manager.update_entity_name(db_node_uuid_to_link, canonical_name_from_resolver, created_at_ts):
                                        final_node_name_in_db = canonical_name_from_resolver; name_updated_in_db = True
                                if final_entity_description_to_set != current_db_description: 
                                    await node_manager.update_entity_description(db_node_uuid_to_link, final_entity_description_to_set, created_at_ts)
                                elif not name_updated_in_db : 
                                     await node_manager.driver.execute_query("MATCH (e:Entity {uuid: $uuid}) SET e.updated_at = $ts", uuid=db_node_uuid_to_link, ts=created_at_ts, database_=node_manager.database) # type: ignore
                            else: 
                                db_node_uuid_to_link = None; node_type_of_linked_node = None

                        if not db_node_uuid_to_link: 
                            node_type_of_linked_node = "Entity"
                            new_entity_uuid_val = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{normalize_entity_name(canonical_name_from_resolver)}_{entity_data.label}"))
                            logger.info(f"      Entity '{entity_data.name}' resolved as NEW ENTITY. Name: '{canonical_name_from_resolver}', Target UUID: {new_entity_uuid_val}")
                            final_node_name_in_db = canonical_name_from_resolver
                            merge_result = await node_manager.merge_or_create_entity_node(
                                entity_uuid_to_create_if_new=new_entity_uuid_val, name_for_create=final_node_name_in_db,
                                normalized_name_for_merge=normalize_entity_name(canonical_name_from_resolver), label_for_merge=entity_data.label,
                                description_for_create=final_entity_description_to_set, created_at_ts=created_at_ts )
                            if merge_result:
                                db_node_uuid_to_link = merge_result[0]
                                final_node_name_in_db = merge_result[1] if merge_result[1] else final_node_name_in_db
                            else: logger.error(f"      Failed to MERGE/CREATE new entity '{canonical_name_from_resolver}'."); continue
                        
                        if db_node_uuid_to_link and node_type_of_linked_node:
                            if node_type_of_linked_node == "Product":
                                await node_manager.link_chunk_to_product(created_chunk_uuid_from_db, db_node_uuid_to_link, created_at_ts)
                                resolved_entities_for_chunk.append(ResolvedEntityInfo(uuid=db_node_uuid_to_link, name=final_node_name_in_db, label="Product")) # Use a generic "Product" or fetch its category for label
                            elif node_type_of_linked_node == "Entity":
                                await node_manager.link_chunk_to_entity(created_chunk_uuid_from_db, db_node_uuid_to_link, created_at_ts)
                                resolved_entities_for_chunk.append(ResolvedEntityInfo(uuid=db_node_uuid_to_link, name=final_node_name_in_db, label=entity_data.label))
                                if embedder: 
                                    if final_node_name_in_db:
                                        name_embedding, name_embed_usage = await embedder.embed_text(final_node_name_in_db) 
                                        if name_embed_usage: current_item_embedding_usage += name_embed_usage 
                                        if name_embedding and await node_manager.set_entity_name_embedding(db_node_uuid_to_link, name_embedding): logger.debug(f"        Stored name embedding for Entity '{db_node_uuid_to_link}'.")
                                    if final_entity_description_to_set:
                                        desc_embedding, desc_embed_usage = await embedder.embed_text(final_entity_description_to_set) 
                                        if desc_embed_usage: current_item_embedding_usage += desc_embed_usage 
                                        if desc_embedding and await node_manager.set_entity_description_embedding(db_node_uuid_to_link, desc_embedding): logger.debug(f"        Stored desc embedding for Entity '{db_node_uuid_to_link}'.")
                        else: logger.warning(f"      Skipping link for entity '{entity_data.name}' as db_node_uuid_to_link was not established.")
                    except Exception as e_entity_processing_loop:
                         logger.error(f"      Error in entity processing loop for '{entity_data.name}': {e_entity_processing_loop}", exc_info=True)
                logger.info(f"    --- Finished Entity Resolution for Chunk '{name_str}' ---")

        if created_chunk_uuid_from_db and relationship_extractor and resolved_entities_for_chunk:
            logger.info(f"    --- Starting Relationship Extraction for Chunk '{name_str}' ---")
            entities_for_rel_extraction = [ExtractedEntity(name=e.name, label=e.label, description=None) for e in resolved_entities_for_chunk]
            extracted_relationships_list_model, rel_extractor_usage = await relationship_extractor.extract_relationships(text_content=page_content, entities_in_chunk=entities_for_rel_extraction)
            if rel_extractor_usage: current_item_generative_usage += rel_extractor_usage 
            if extracted_relationships_list_model.relationships:
                entity_name_to_uuid_map: Dict[str, str] = {entity.name: entity.uuid for entity in resolved_entities_for_chunk}
                for rel_data in extracted_relationships_list_model.relationships:
                    source_uuid = entity_name_to_uuid_map.get(rel_data.source_entity_name)
                    target_uuid = entity_name_to_uuid_map.get(rel_data.target_entity_name)
                    if not source_uuid or not target_uuid or source_uuid == target_uuid: continue
                    relationship_uuid = await node_manager.create_or_merge_relationship(source_entity_uuid=source_uuid, target_entity_uuid=target_uuid, relation_label=rel_data.relation_label, fact_sentence=rel_data.fact_sentence, source_chunk_uuid=created_chunk_uuid_from_db, created_at_ts=created_at_ts)
                    if relationship_uuid and embedder:
                        fact_embedding, fact_embed_usage = await embedder.embed_text(rel_data.fact_sentence) 
                        if fact_embed_usage: current_item_embedding_usage += fact_embed_usage 
                        if fact_embedding: await node_manager.set_relationship_fact_embedding(relationship_uuid, fact_embedding) 
            else: logger.info(f"    No relationships extracted for chunk '{name_str}'.")
            logger.info(f"    --- Finished Relationship Extraction for Chunk '{name_str}' ---")

        if node_type_hint == "chunk" and created_chunk_uuid_from_db and embedder: 
            embedding_vector, chunk_embed_usage = await embedder.embed_text(text_content_to_embed) 
            if chunk_embed_usage: current_item_embedding_usage += chunk_embed_usage 
            if embedding_vector and await node_manager.set_chunk_content_embedding(created_chunk_uuid_from_db, embedding_vector):
                logger.debug(f"    Successfully stored embedding for chunk: {created_chunk_uuid_from_db}")
            elif not embedding_vector: 
                logger.warning(f"    Embedding vector was empty for chunk {created_chunk_uuid_from_db}.")
    
    else: 
        logger.warning(f"    Unknown node_type_hint: '{node_type_hint}'. Skipping processing for this item.")
        return None, current_item_generative_usage, current_item_embedding_usage

    return item_uuid_str_for_node, current_item_generative_usage, current_item_embedding_usage

async def add_documents_to_knowledge_base(
    source_identifier: str,
    documents_data: List[dict], # Each dict is an "item_data" as defined above
    node_manager: NodeManager,
    embedder: EmbedderClient,
    entity_extractor: EntityExtractor,
    entity_resolver: EntityResolver,
    relationship_extractor: RelationshipExtractor,
    source_content: Optional[str] = None,
    source_dynamic_metadata: Optional[dict] = None,
    allow_same_name_chunks_for_this_source: bool = True # May need rethinking for products
) -> Tuple[Optional[str], List[str], Usage, Usage]: 
    
    total_generative_usage_for_source_set = Usage() 
    total_embedding_usage_for_source_set = Usage()  
    
    # ... (source node creation and embedding remains the same) ...
    logger.info(f"Building knowledge base for source: [magenta]{source_identifier}[/magenta]")
    created_at = datetime.now(timezone.utc)
    processed_metadata = preprocess_metadata_for_neo4j(source_dynamic_metadata)
    source_node_uuid = await node_manager.create_or_merge_source_node(
        identifier=source_identifier, content=source_content,
        dynamic_metadata=processed_metadata, created_at=created_at )
    if not source_node_uuid: # ... (error handling) ...
        return None, [], total_generative_usage_for_source_set, total_embedding_usage_for_source_set
    if source_content and embedder:
        embedding_vector, source_embed_usage = await embedder.embed_text(source_content) 
        if source_embed_usage: total_embedding_usage_for_source_set += source_embed_usage 
        # ... (store source embedding) ...

    added_item_uuids: List[str] = [] # Can be Chunk or Product UUIDs
    previous_chunk_page_content: Optional[str] = None 

    for item_idx, item_data_from_source in enumerate(documents_data): # item_data_from_source is one dict from the list
        page_content = item_data_from_source.get("page_content", "")
        # item_metadata is now explicitly item_data_from_source.get("metadata", {}) inside _process_single_chunk_for_kb
        
        item_name_for_log = item_data_from_source.get("metadata", {}).get('name', f"Unnamed Item {item_idx+1}")
        node_type_for_log = item_data_from_source.get('node_type', 'Chunk')

        logger.debug(f"  Processing item {item_idx + 1}/{len(documents_data)} (as {node_type_for_log}): Name='{item_name_for_log}'")

        # Pass the whole item_data_from_source to _process_single_chunk_for_kb
        created_item_uuid, item_gen_usage, item_embed_usage = await _process_single_chunk_for_kb(
            page_content=page_content, 
            item_data=item_data_from_source, # Pass the whole dict
            source_node_uuid=source_node_uuid,
            source_identifier_for_chunk_desc=source_identifier, # Still relevant for Chunk.source_description
            node_manager=node_manager,
            embedder=embedder,
            entity_extractor=entity_extractor,
            entity_resolver=entity_resolver,
            relationship_extractor=relationship_extractor,
            allow_same_name_chunks_flag=allow_same_name_chunks_for_this_source,
            previous_chunk_content=previous_chunk_page_content 
        )
        if item_gen_usage: total_generative_usage_for_source_set += item_gen_usage 
        if item_embed_usage: total_embedding_usage_for_source_set += item_embed_usage 

        if created_item_uuid:
            added_item_uuids.append(created_item_uuid)
        else:
            logger.warning(f"    Failed to add item: Name='{item_name_for_log}'")
        
        # Only set previous_chunk_content if the current item was a text chunk,
        # as product JSON content isn't useful as context for the next text chunk.
        if item_data_from_source.get("node_type", "Chunk").lower() == "chunk":
            previous_chunk_page_content = page_content 
        else:
            previous_chunk_page_content = None # Reset context if it was a product

    logger.info(f"Finished building knowledge base for source [magenta]{source_identifier}[/magenta]. Added {len(added_item_uuids)} items (Chunks/Products).")
    return source_node_uuid, added_item_uuids, total_generative_usage_for_source_set, total_embedding_usage_for_source_set