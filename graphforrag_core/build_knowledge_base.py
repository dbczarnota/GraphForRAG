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
from config.llm_prompts import ExtractedEntity 
from .types import ResolvedEntityInfo 

logger = logging.getLogger("graph_for_rag.build_knowledge_base")

async def _process_single_item_for_kb( 
    item_data: dict, 
    source_node_uuid: str,
    source_name_for_node_linking: str, 
    node_manager: NodeManager,
    embedder: EmbedderClient, 
    entity_extractor: EntityExtractor,
    entity_resolver: EntityResolver,
    relationship_extractor: RelationshipExtractor,
    previous_chunk_content: Optional[str] = None,
    extractable_entity_labels_for_ingestion: Optional[List[str]] = None
) -> Tuple[Optional[str], Usage, Usage]: 
    
    current_item_generative_usage = Usage() 
    current_item_embedding_usage = Usage()  

    node_type = item_data.get("node_type", "chunk").lower() 
    item_name = item_data.get("name", f"Unnamed_{node_type}")
    item_content = item_data.get("content", "") 
    item_specific_metadata = item_data.get("metadata", {}).copy() 
    item_node_uuid_str = str(item_specific_metadata.pop("uuid", item_specific_metadata.pop("chunk_uuid", uuid.uuid4())))
    created_at_ts = datetime.now(timezone.utc)
    final_item_node_uuid: Optional[str] = None

    if node_type == "product":
        # ... (Product processing logic is largely unaffected by this specific change, 
        # as it doesn't directly create MENTIONS relationships from its own definition in this function)
        logger.info(f"    Processing as Product: '{item_name}' (UUID: {item_node_uuid_str})")
        product_sku = item_data.get("sku") 
        product_price = item_data.get("price") 
        product_content_as_string_for_node = item_content 
        dynamic_product_properties = preprocess_metadata_for_neo4j(item_specific_metadata)
        existing_entity_to_promote_uuid: Optional[str] = None
        if entity_resolver:
            logger.debug(f"    Checking if product '{item_name}' matches an existing Entity for promotion.")
            key_attributes_for_match = {
                k: dynamic_product_properties[k] for k in ["brand", "category", "release_year"] 
                if k in dynamic_product_properties and dynamic_product_properties[k] is not None
            }
            matched_uuid, promotion_gen_usage, promotion_embed_usage = await entity_resolver.find_matching_entity_for_product_promotion(
                new_product_name=item_name,
                new_product_description=product_content_as_string_for_node, 
                new_product_attributes=key_attributes_for_match
            )
            if promotion_gen_usage: current_item_generative_usage += promotion_gen_usage
            if promotion_embed_usage: current_item_embedding_usage += promotion_embed_usage
            if matched_uuid:
                existing_entity_to_promote_uuid = matched_uuid
        
        if existing_entity_to_promote_uuid:
            logger.info(f"    Attempting to promote existing Entity '{existing_entity_to_promote_uuid}' to Product '{item_name}' (New Product UUID: {item_node_uuid_str}).")
            properties_for_promotion = dynamic_product_properties.copy()
            final_item_node_uuid = await node_manager.promote_entity_to_product(
                existing_entity_uuid=existing_entity_to_promote_uuid,
                new_product_uuid=item_node_uuid_str, 
                new_product_name=item_name,
                new_product_content=product_content_as_string_for_node, 
                new_product_price=product_price,
                new_product_sku=product_sku,
                new_product_dynamic_properties=properties_for_promotion, 
                promotion_timestamp=created_at_ts
            )
            if not final_item_node_uuid:
                logger.error(f"    Promotion failed for Entity '{existing_entity_to_promote_uuid}'. Will attempt to create Product as new.")
                existing_entity_to_promote_uuid = None 

        if not existing_entity_to_promote_uuid: 
            logger.debug(f"    Creating new Product node for '{item_name}' (UUID: {item_node_uuid_str}).")
            final_item_node_uuid = await node_manager.create_or_merge_product_node(
                product_uuid=item_node_uuid_str, 
                name=item_name,
                content=product_content_as_string_for_node, 
                price=product_price, 
                sku=product_sku,     
                created_at=created_at_ts,
                dynamic_product_properties=dynamic_product_properties 
            )

        if final_item_node_uuid:
            await node_manager.link_product_to_source(final_item_node_uuid, source_node_uuid, created_at_ts)
            if embedder:
                if item_name: 
                    name_embedding, name_embed_usage = await embedder.embed_text(item_name)
                    if name_embed_usage: current_item_embedding_usage += name_embed_usage
                    if name_embedding: await node_manager.set_product_name_embedding(final_item_node_uuid, name_embedding)
                if product_content_as_string_for_node: 
                    content_embedding, content_embed_usage = await embedder.embed_text(product_content_as_string_for_node)
                    if content_embed_usage: current_item_embedding_usage += content_embed_usage
                    if content_embedding: await node_manager.set_product_content_embedding(final_item_node_uuid, content_embedding)
            logger.debug(f"    Product '{item_name}' (UUID: {final_item_node_uuid}) processed.")
        # <<< START OF LOGIC FOR ENTITY EXTRACTION FROM PRODUCT CONTENT (plain text) >>>
        if final_item_node_uuid and entity_extractor and product_content_as_string_for_node: # product_content_as_string_for_node is now plain text
            logger.info(f"    Attempting entity extraction from Product '{item_name}' (UUID: {final_item_node_uuid}) textual content.")
            
            text_to_extract_from = product_content_as_string_for_node # Directly use the product's content string

            if text_to_extract_from.strip():
                # Log the text being sent to the extractor for product content
                logger.debug(f"      Text for entity extraction from Product '{item_name}': \"{text_to_extract_from[:150]}...\"")

                product_extracted_entities_list_model, product_extractor_usage = await entity_extractor.extract_entities(
                    text_content=text_to_extract_from, 
                    context_text=None,
                    extractable_entity_labels=extractable_entity_labels_for_ingestion
                )
                if product_extractor_usage: current_item_generative_usage += product_extractor_usage # Accumulate usage

                if product_extracted_entities_list_model.entities:
                    logger.info(f"      Extracted {len(product_extracted_entities_list_model.entities)} entities from Product '{item_name}' content:")
                    for idx, eee_product in enumerate(product_extracted_entities_list_model.entities):
                        logger.info(f"        {idx+1}. Name: '{eee_product.name}', Label: '{eee_product.label}', Fact: '{eee_product.fact_sentence_about_mention}'")
                    # Storing these extracted entities for future resolution and relationship steps
                    # For now, we just log them. This list would be used in subsequent iterations:
                    # resolved_entities_from_product_content: List[ResolvedEntityInfo] = [] # Placeholder for future
                    resolved_entities_from_product_content: List[ResolvedEntityInfo] = []
                    if product_extracted_entities_list_model.entities:
                        logger.info(f"    --- Starting Entity Resolution for Product '{item_name}' content ---")
                        for extracted_entity_data_model in product_extracted_entities_list_model.entities:
                            entity_data: ExtractedEntity = extracted_entity_data_model
                            
                            resolution_decision, resolver_gen_usage, resolver_embed_usage = await entity_resolver.resolve_entity(entity_data)
                            
                            if resolver_gen_usage: current_item_generative_usage += resolver_gen_usage
                            if resolver_embed_usage: current_item_embedding_usage += resolver_embed_usage
                            
                            canonical_name_from_resolver = resolution_decision.canonical_name
                            fact_sentence_for_mention_rel = entity_data.fact_sentence_about_mention

                            # Self-reference check: if the extracted entity resolves to the product itself
                            if resolution_decision.is_duplicate and resolution_decision.duplicate_of_uuid == final_item_node_uuid:
                                logger.info(f"      Entity mention '{entity_data.name}' from product content resolved to the product itself (UUID: {final_item_node_uuid}). Skipping self-MENTIONS link.")
                                # Add the product itself to the list of resolved entities in its own description,
                                # as it might be part of relationships with other entities mentioned in its description.
                                resolved_entities_from_product_content.append(ResolvedEntityInfo(uuid=final_item_node_uuid, name=item_name, label="Product"))
                                continue # Move to the next extracted entity

                            db_node_uuid_to_link: Optional[str] = None
                            node_type_of_linked_node: Optional[str] = None
                            final_node_name_in_db: str = canonical_name_from_resolver

                            try:
                                if resolution_decision.is_duplicate and resolution_decision.duplicate_of_uuid:
                                    db_node_uuid_to_link = resolution_decision.duplicate_of_uuid
                                    # Determine if the duplicate is an Entity or Product
                                    node_labels_result, _, _ = await node_manager.driver.execute_query(
                                        "MATCH (n {uuid: $uuid}) RETURN labels(n) as node_labels",
                                        uuid=db_node_uuid_to_link, database_=node_manager.database
                                    )
                                    if node_labels_result and node_labels_result[0]["node_labels"]:
                                        labels_list = node_labels_result[0]["node_labels"]
                                        if "Product" in labels_list: node_type_of_linked_node = "Product"
                                        elif "Entity" in labels_list: node_type_of_linked_node = "Entity"
                                    
                                    if node_type_of_linked_node == "Product":
                                        logger.info(f"      Product content entity '{entity_data.name}' resolved as DUPLICATE of existing PRODUCT UUID: '{db_node_uuid_to_link}'.")
                                        # Fetch the Product's actual name
                                        product_details_res, _, _ = await node_manager.driver.execute_query("MATCH (p:Product {uuid: $uuid}) RETURN p.name as name", uuid=db_node_uuid_to_link, database_=node_manager.database) # type: ignore
                                        if product_details_res and product_details_res[0]: final_node_name_in_db = product_details_res[0].get("name", canonical_name_from_resolver)

                                    elif node_type_of_linked_node == "Entity":
                                        logger.info(f"      Product content entity '{entity_data.name}' resolved as DUPLICATE of existing ENTITY UUID: '{db_node_uuid_to_link}'.")
                                        # Potentially update existing Entity's name if resolver suggests a better one
                                        node_details = await node_manager.fetch_entity_details(db_node_uuid_to_link)
                                        current_db_name = None
                                        if node_details: _, current_db_name, _ = node_details
                                        final_node_name_in_db = current_db_name if current_db_name else canonical_name_from_resolver
                                        if canonical_name_from_resolver and current_db_name and \
                                           len(canonical_name_from_resolver) > len(current_db_name) and \
                                           canonical_name_from_resolver != current_db_name:
                                            if await node_manager.update_entity_name(db_node_uuid_to_link, canonical_name_from_resolver, created_at_ts):
                                                final_node_name_in_db = canonical_name_from_resolver
                                        elif not current_db_name and canonical_name_from_resolver:
                                            if await node_manager.update_entity_name(db_node_uuid_to_link, canonical_name_from_resolver, created_at_ts):
                                                final_node_name_in_db = canonical_name_from_resolver
                                        else: # Just update timestamp if name doesn't change or isn't better
                                            await node_manager.driver.execute_query("MATCH (e:Entity {uuid: $uuid}) SET e.updated_at = $ts", uuid=db_node_uuid_to_link, ts=created_at_ts, database_=node_manager.database) # type: ignore
                                    else: # Fallback if type determination failed after claiming duplicate
                                        db_node_uuid_to_link = None; node_type_of_linked_node = None
                                
                                if not db_node_uuid_to_link: # If resolution claimed duplicate but failed to confirm type or UUID
                                    logger.warning(f"      Product content entity '{entity_data.name}' resolution claimed duplicate but target {resolution_decision.duplicate_of_uuid} not found or type indeterminate. Treating as new Entity.")

                                if not db_node_uuid_to_link: # Process as new if not a valid duplicate or if fallback from failed duplicate
                                    node_type_of_linked_node = "Entity" # Default to creating an Entity
                                    new_entity_uuid_val = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{normalize_entity_name(canonical_name_from_resolver)}_{entity_data.label}"))
                                    logger.info(f"      Product content entity '{entity_data.name}' resolved as NEW ENTITY. Name: '{canonical_name_from_resolver}', Target UUID: {new_entity_uuid_val}")
                                    final_node_name_in_db = canonical_name_from_resolver
                                    merge_result = await node_manager.merge_or_create_entity_node(
                                        entity_uuid_to_create_if_new=new_entity_uuid_val, name_for_create=final_node_name_in_db,
                                        normalized_name_for_merge=normalize_entity_name(canonical_name_from_resolver), label_for_merge=entity_data.label,
                                        created_at_ts=created_at_ts
                                    )
                                    if merge_result:
                                        db_node_uuid_to_link = merge_result[0]
                                        final_node_name_in_db = merge_result[1] if merge_result[1] else final_node_name_in_db
                                        # Embed name for new Entity
                                        if embedder and final_node_name_in_db:
                                            name_embedding, name_embed_usage = await embedder.embed_text(final_node_name_in_db)
                                            if name_embed_usage: current_item_embedding_usage += name_embed_usage
                                            if name_embedding: await node_manager.set_entity_name_embedding(db_node_uuid_to_link, name_embedding)
                                    else:
                                        logger.error(f"      Failed to MERGE/CREATE new entity '{canonical_name_from_resolver}' from product content."); continue
                                
                                if db_node_uuid_to_link and node_type_of_linked_node and final_item_node_uuid: # final_item_node_uuid is the Product's UUID

                                    resolved_entities_from_product_content.append(ResolvedEntityInfo(uuid=db_node_uuid_to_link, name=final_node_name_in_db, label=entity_data.label if node_type_of_linked_node == "Entity" else "Product"))
                                    logger.debug(f"      Added '{final_node_name_in_db}' (UUID: {db_node_uuid_to_link}) to list for relationship extraction from product content.")
                                else:
                                    logger.warning(f"      Skipping add to resolved list for entity '{entity_data.name}' from product content as db_node_uuid_to_link or node_type was not established.")
                            except Exception as e_entity_processing_loop_product:
                                logger.error(f"      Error in entity processing loop (from product content) for '{entity_data.name}': {e_entity_processing_loop_product}", exc_info=True)
                        logger.info(f"    --- Finished Entity Resolution for Product '{item_name}' content ---")
                    # Ensure the product itself is in the list for relationship extraction
                    product_itself_info = ResolvedEntityInfo(uuid=final_item_node_uuid, name=item_name, label="Product")
                    if not any(re.uuid == product_itself_info.uuid for re in resolved_entities_from_product_content):
                        resolved_entities_from_product_content.insert(0, product_itself_info) # Add to the beginning
                        logger.debug(f"      Ensured Product '{item_name}' itself is in the context for relationship extraction from its own content.")

                    if final_item_node_uuid and relationship_extractor and resolved_entities_from_product_content: # resolved_entities_from_product_content is populated in the block above
                        logger.info(f"    --- Starting Relationship Extraction for Product '{item_name}' content (based on {len(resolved_entities_from_product_content)} resolved entities) ---")
                        
                        # Prepare entities for relationship extraction (needs name and label)
                        entities_for_rel_extraction_from_product = [
                            ExtractedEntity(name=e.name, label=e.label, fact_sentence_about_mention=None) # fact_sentence not strictly needed by rel_extractor here
                            for e in resolved_entities_from_product_content
                        ]

                        if len(entities_for_rel_extraction_from_product) >= 2: # Need at least two entities for a relationship
                            product_extracted_relationships_list_model, product_rel_extractor_usage = await relationship_extractor.extract_relationships(
                                text_content=text_to_extract_from, # This is the product's textual content
                                entities_in_chunk=entities_for_rel_extraction_from_product
                            )
                            if product_rel_extractor_usage: current_item_generative_usage += product_rel_extractor_usage

                            if product_extracted_relationships_list_model.relationships:
                                logger.info(f"      Extracted {len(product_extracted_relationships_list_model.relationships)} relationships from Product '{item_name}' content.")
                                entity_name_to_uuid_map_for_product_rels: Dict[str, str] = {
                                    entity.name: entity.uuid for entity in resolved_entities_from_product_content
                                }
                                for rel_data in product_extracted_relationships_list_model.relationships:
                                    source_uuid = entity_name_to_uuid_map_for_product_rels.get(rel_data.source_entity_name)
                                    target_uuid = entity_name_to_uuid_map_for_product_rels.get(rel_data.target_entity_name)

                                    if not source_uuid or not target_uuid or source_uuid == target_uuid:
                                        logger.warning(f"        Skipping relationship '{rel_data.relation_label}' due to missing/identical source/target UUIDs from product content map.")
                                        continue
                                    
                                    # The product's UUID (final_item_node_uuid) acts as the 'source_chunk_uuid' for these relationships
                                    relationship_uuid_from_product = await node_manager.create_or_merge_relationship(
                                        source_entity_uuid=source_uuid,
                                        target_entity_uuid=target_uuid,
                                        relation_label=rel_data.relation_label,
                                        fact_sentence=rel_data.fact_sentence,
                                        source_chunk_uuid=final_item_node_uuid, # Product's UUID
                                        created_at_ts=created_at_ts
                                    )
                                    if relationship_uuid_from_product and embedder:
                                        fact_embedding, fact_embed_usage = await embedder.embed_text(rel_data.fact_sentence)
                                        if fact_embed_usage: current_item_embedding_usage += fact_embed_usage
                                        if fact_embedding:
                                            await node_manager.set_relationship_fact_embedding(relationship_uuid_from_product, fact_embedding)
                                            logger.debug(f"        Stored fact_embedding for RELATES_TO {relationship_uuid_from_product} from product content.")
                            else:
                                logger.info(f"      No relationships extracted from Product '{item_name}' content.")
                        else:
                            logger.info(f"      Skipping relationship extraction for Product '{item_name}' content as fewer than 2 entities were resolved from its description.")
                        logger.info(f"    --- Finished Relationship Extraction for Product '{item_name}' content ---")                        
                else:
                    logger.info(f"      No entities extracted from Product '{item_name}' content (text was: '{text_to_extract_from[:150]}...').")
            else:
                logger.info(f"      Skipping entity extraction for Product '{item_name}' as its content string is empty or whitespace.")
        # <<< END OF LOGIC FOR ENTITY EXTRACTION FROM PRODUCT CONTENT >>>

    elif node_type == "chunk": 
        logger.debug(f"    Processing as Chunk: '{item_name}' (UUID: {item_node_uuid_str})")
        chunk_number = item_data.get("chunk_number") 
        dynamic_chunk_properties = preprocess_metadata_for_neo4j(item_specific_metadata)
        chunk_properties_for_cypher = dynamic_chunk_properties.copy()
        chunk_properties_for_cypher['name'] = item_name 
        if chunk_number is not None:
            chunk_properties_for_cypher['chunk_number'] = chunk_number 

        final_item_node_uuid = await node_manager.create_chunk_node_and_link_to_source(
            chunk_uuid=item_node_uuid_str, 
            chunk_content=item_content, 
            source_node_uuid=source_node_uuid, 
            source_name_param=source_name_for_node_linking, 
            created_at=created_at_ts, 
            dynamic_chunk_properties=chunk_properties_for_cypher, 
            chunk_number_for_rel=chunk_number 
        )
        
        if not final_item_node_uuid:
            logger.error(f"Failed to create/link chunk '{item_name}' via NodeManager.")
            return None, current_item_generative_usage, current_item_embedding_usage
        
        resolved_entities_for_chunk: List[ResolvedEntityInfo] = [] 
        if entity_extractor and entity_resolver:
            extracted_entities_list_model, extractor_usage = await entity_extractor.extract_entities(
                text_content=item_content, context_text=previous_chunk_content, extractable_entity_labels=extractable_entity_labels_for_ingestion
            )
            if extractor_usage: current_item_generative_usage += extractor_usage 

            if extracted_entities_list_model.entities:
                logger.info(f"    --- Starting Entity Resolution for Chunk '{item_name}' ---")
                for extracted_entity_data_model in extracted_entities_list_model.entities:
                    entity_data: ExtractedEntity = extracted_entity_data_model 
                    resolution_decision, resolver_gen_usage, resolver_embed_usage = await entity_resolver.resolve_entity(entity_data)
                    
                    if resolver_gen_usage: current_item_generative_usage += resolver_gen_usage 
                    if resolver_embed_usage: current_item_embedding_usage += resolver_embed_usage 
                    
                    canonical_name_from_resolver = resolution_decision.canonical_name
                    fact_sentence_for_mention_rel = entity_data.fact_sentence_about_mention # Use the new field name
                    
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
                                logger.info(f"      Entity mention '{entity_data.name}' resolved as DUPLICATE of existing PRODUCT UUID: '{db_node_uuid_to_link}'.")
                                product_details_res, _, _ = await node_manager.driver.execute_query("MATCH (p:Product {uuid: $uuid}) RETURN p.name as name", uuid=db_node_uuid_to_link, database_=node_manager.database) # type: ignore
                                if product_details_res and product_details_res[0]: final_node_name_in_db = product_details_res[0].get("name", canonical_name_from_resolver)
                            
                            elif node_type_of_linked_node == "Entity":
                                logger.info(f"      Entity mention '{entity_data.name}' resolved as DUPLICATE of existing ENTITY UUID: '{db_node_uuid_to_link}'.")
                                node_details = await node_manager.fetch_entity_details(db_node_uuid_to_link)
                                current_db_name = None
                                if node_details: _, current_db_name, _ = node_details 
                                final_node_name_in_db = current_db_name if current_db_name else canonical_name_from_resolver
                                if canonical_name_from_resolver and current_db_name and \
                                   len(canonical_name_from_resolver) > len(current_db_name) and \
                                   canonical_name_from_resolver != current_db_name:
                                    if await node_manager.update_entity_name(db_node_uuid_to_link, canonical_name_from_resolver, created_at_ts):
                                        final_node_name_in_db = canonical_name_from_resolver
                                elif not current_db_name and canonical_name_from_resolver:
                                     if await node_manager.update_entity_name(db_node_uuid_to_link, canonical_name_from_resolver, created_at_ts):
                                        final_node_name_in_db = canonical_name_from_resolver
                                else: 
                                     await node_manager.driver.execute_query("MATCH (e:Entity {uuid: $uuid}) SET e.updated_at = $ts", uuid=db_node_uuid_to_link, ts=created_at_ts, database_=node_manager.database) # type: ignore
                            else: 
                                db_node_uuid_to_link = None; node_type_of_linked_node = None

                        if not db_node_uuid_to_link: 
                            node_type_of_linked_node = "Entity"
                            new_entity_uuid_val = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{normalize_entity_name(canonical_name_from_resolver)}_{entity_data.label}"))
                            logger.info(f"      Entity mention '{entity_data.name}' resolved as NEW ENTITY. Name: '{canonical_name_from_resolver}', Target UUID: {new_entity_uuid_val}")
                            final_node_name_in_db = canonical_name_from_resolver
                            merge_result = await node_manager.merge_or_create_entity_node(
                                entity_uuid_to_create_if_new=new_entity_uuid_val, name_for_create=final_node_name_in_db,
                                normalized_name_for_merge=normalize_entity_name(canonical_name_from_resolver), label_for_merge=entity_data.label,
                                created_at_ts=created_at_ts 
                            )
                            if merge_result:
                                db_node_uuid_to_link = merge_result[0]
                                final_node_name_in_db = merge_result[1] if merge_result[1] else final_node_name_in_db
                            else: logger.error(f"      Failed to MERGE/CREATE new entity '{canonical_name_from_resolver}'."); continue
                        
                        if db_node_uuid_to_link and node_type_of_linked_node and final_item_node_uuid:
                            if node_type_of_linked_node == "Product":
                                await node_manager.link_chunk_to_product(
                                    chunk_uuid=final_item_node_uuid, 
                                    product_uuid=db_node_uuid_to_link, 
                                    created_at_ts=created_at_ts, 
                                    fact_sentence_on_relationship=fact_sentence_for_mention_rel # Use new param name
                                )
                            elif node_type_of_linked_node == "Entity":
                                await node_manager.link_chunk_to_entity(
                                    chunk_uuid=final_item_node_uuid, 
                                    entity_uuid=db_node_uuid_to_link, 
                                    created_at_ts=created_at_ts, 
                                    fact_sentence_on_relationship=fact_sentence_for_mention_rel # Use new param name
                                )
                            
                            if fact_sentence_for_mention_rel and embedder: # Common embedding logic for MENTIONS fact_sentence
                                fact_embedding_val, fact_embed_usage = await embedder.embed_text(fact_sentence_for_mention_rel)
                                if fact_embed_usage: current_item_embedding_usage += fact_embed_usage
                                if fact_embedding_val:
                                    await node_manager.set_mentions_fact_embedding( # Use renamed method
                                        chunk_uuid=final_item_node_uuid, 
                                        target_node_uuid=db_node_uuid_to_link, 
                                        embedding_vector=fact_embedding_val
                                    )
                                    logger.debug(f"        Stored fact_embedding for MENTIONS between chunk '{final_item_node_uuid}' and node '{db_node_uuid_to_link}'.")

                            resolved_entities_for_chunk.append(ResolvedEntityInfo(uuid=db_node_uuid_to_link, name=final_node_name_in_db, label=entity_data.label if node_type_of_linked_node == "Entity" else "Product"))
                            
                            if node_type_of_linked_node == "Entity" and embedder and final_node_name_in_db: 
                                name_embedding, name_embed_usage = await embedder.embed_text(final_node_name_in_db) 
                                if name_embed_usage: current_item_embedding_usage += name_embed_usage 
                                if name_embedding and await node_manager.set_entity_name_embedding(db_node_uuid_to_link, name_embedding): 
                                    logger.debug(f"        Stored name embedding for Entity '{db_node_uuid_to_link}'.")
                        else: 
                            logger.warning(f"      Skipping link for entity '{entity_data.name}' as db_node_uuid_to_link ({db_node_uuid_to_link}) or node_type_of_linked_node ({node_type_of_linked_node}) or final_item_node_uuid ({final_item_node_uuid}) was not established.")
                    except Exception as e_entity_processing_loop:
                         logger.error(f"      Error in entity processing loop for '{entity_data.name}': {e_entity_processing_loop}", exc_info=True)
                logger.info(f"    --- Finished Entity Resolution for Chunk '{item_name}' ---")

        if final_item_node_uuid and node_type == "chunk" and relationship_extractor and resolved_entities_for_chunk:
            logger.info(f"    --- Starting Relationship Extraction for Chunk '{item_name}' ---")
            # Pass fact_sentence_about_mention=None as it's not directly used by RelationshipExtractor's input model,
            # which expects only name and label for the context entities.
            entities_for_rel_extraction = [ExtractedEntity(name=e.name, label=e.label, fact_sentence_about_mention=None) for e in resolved_entities_for_chunk]
            extracted_relationships_list_model, rel_extractor_usage = await relationship_extractor.extract_relationships(text_content=item_content, entities_in_chunk=entities_for_rel_extraction)
            if rel_extractor_usage: current_item_generative_usage += rel_extractor_usage 
            if extracted_relationships_list_model.relationships:
                entity_name_to_uuid_map: Dict[str, str] = {entity.name: entity.uuid for entity in resolved_entities_for_chunk}
                for rel_data in extracted_relationships_list_model.relationships:
                    source_uuid = entity_name_to_uuid_map.get(rel_data.source_entity_name)
                    target_uuid = entity_name_to_uuid_map.get(rel_data.target_entity_name)
                    if not source_uuid or not target_uuid or source_uuid == target_uuid: continue
                    relationship_uuid = await node_manager.create_or_merge_relationship(source_entity_uuid=source_uuid, target_entity_uuid=target_uuid, relation_label=rel_data.relation_label, fact_sentence=rel_data.fact_sentence, source_chunk_uuid=final_item_node_uuid, created_at_ts=created_at_ts)
                    if relationship_uuid and embedder:
                        fact_embedding, fact_embed_usage = await embedder.embed_text(rel_data.fact_sentence) 
                        if fact_embed_usage: current_item_embedding_usage += fact_embed_usage 
                        if fact_embedding: await node_manager.set_relationship_fact_embedding(relationship_uuid, fact_embedding) 
            else: logger.info(f"    No relationships extracted for chunk '{item_name}'.")
            logger.info(f"    --- Finished Relationship Extraction for Chunk '{item_name}' ---")

        if node_type == "chunk" and final_item_node_uuid and embedder: 
            embedding_vector, chunk_embed_usage = await embedder.embed_text(item_content) 
            if chunk_embed_usage: current_item_embedding_usage += chunk_embed_usage 
            if embedding_vector and await node_manager.set_chunk_content_embedding(final_item_node_uuid, embedding_vector):
                logger.debug(f"    Successfully stored embedding for chunk: {final_item_node_uuid}")
            elif not embedding_vector: 
                logger.warning(f"    Embedding vector was empty for chunk {final_item_node_uuid}.")
    
    else: 
        logger.warning(f"    Unknown node_type: '{node_type}' for item '{item_name}'. Skipping processing.")
        return None, current_item_generative_usage, current_item_embedding_usage

    return final_item_node_uuid, current_item_generative_usage, current_item_embedding_usage

async def add_documents_to_knowledge_base(
    source_definition_block: dict, 
    node_manager: NodeManager,
    embedder: EmbedderClient,
    entity_extractor: EntityExtractor,
    entity_resolver: EntityResolver,
    relationship_extractor: RelationshipExtractor,
    extractable_entity_labels_for_ingestion: Optional[List[str]] = None 
) -> Tuple[Optional[str], List[str], Usage, Usage]: 
    
    total_generative_usage_for_source_set = Usage() 
    total_embedding_usage_for_source_set = Usage()  
    
    source_node_type = source_definition_block.get("node_type")
    if source_node_type != "source":
        logger.error(f"Invalid source definition block. Expected node_type 'source', got '{source_node_type}'. Skipping.")
        return None, [], total_generative_usage_for_source_set, total_embedding_usage_for_source_set

    source_name = source_definition_block.get("name", "Unnamed Source")
    source_main_content = source_definition_block.get("content") 
    source_level_metadata = source_definition_block.get("metadata", {})
    items_in_source = source_definition_block.get("chunks", []) 

    logger.info(f"Building knowledge base for source: [magenta]{source_name}[/magenta]")
    created_at = datetime.now(timezone.utc)
    processed_source_metadata = preprocess_metadata_for_neo4j(source_level_metadata)
    
    source_node_uuid = await node_manager.create_or_merge_source_node(
        name=source_name, 
        content=source_main_content, 
        dynamic_metadata=processed_source_metadata, 
        created_at=created_at 
    )
    if not source_node_uuid:
        logger.error(f"Failed to create source node for '{source_name}'. Aborting processing for this source.")
        return None, [], total_generative_usage_for_source_set, total_embedding_usage_for_source_set
    
    if source_main_content and embedder: 
        embedding_vector, source_embed_usage = await embedder.embed_text(source_main_content) 
        if source_embed_usage: total_embedding_usage_for_source_set += source_embed_usage 
        if embedding_vector: 
            await node_manager.set_source_content_embedding(source_node_uuid, embedding_vector)

    added_item_node_uuids: List[str] = []
    previous_chunk_text_content: Optional[str] = None 

    for item_idx, item_data in enumerate(items_in_source):
        item_node_type_for_log = item_data.get('node_type', 'unknown_item_type')
        item_name_for_log = item_data.get('name', f"Unnamed Item {item_idx+1}")

        logger.debug(f"  Processing item {item_idx + 1}/{len(items_in_source)} (as {item_node_type_for_log}): Name='{item_name_for_log}'")

        created_item_uuid, item_gen_usage, item_embed_usage = await _process_single_item_for_kb(
            item_data=item_data, 
            source_node_uuid=source_node_uuid,
            source_name_for_node_linking=source_name, 
            node_manager=node_manager,
            embedder=embedder,
            entity_extractor=entity_extractor,
            entity_resolver=entity_resolver,
            relationship_extractor=relationship_extractor,
            previous_chunk_content=previous_chunk_text_content,
            extractable_entity_labels_for_ingestion=extractable_entity_labels_for_ingestion
        )
        if item_gen_usage: total_generative_usage_for_source_set += item_gen_usage 
        if item_embed_usage: total_embedding_usage_for_source_set += item_embed_usage 

        if created_item_uuid:
            added_item_node_uuids.append(created_item_uuid)
        else:
            logger.warning(f"    Failed to add item: Name='{item_name_for_log}'")
        
        if item_data.get("node_type", "chunk").lower() == "chunk":
            previous_chunk_text_content = item_data.get("content", "")
        else:
            previous_chunk_text_content = None 

    logger.info(f"Finished building knowledge base for source [magenta]{source_name}[/magenta]. Added {len(added_item_node_uuids)} items (Chunks/Products).")
    return source_node_uuid, added_item_node_uuids, total_generative_usage_for_source_set, total_embedding_usage_for_source_set