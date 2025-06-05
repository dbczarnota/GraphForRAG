# graphforrag_core/node_manager.py
import logging
import uuid 
from datetime import datetime, timezone
from typing import Optional, Any, Dict, Tuple, List

from neo4j import AsyncDriver # type: ignore

from config import cypher_queries
from .embedder_client import EmbedderClient 
from .utils import preprocess_metadata_for_neo4j # ADDED IMPORT

logger = logging.getLogger("graph_for_rag.node_manager")

class NodeManager:
    def __init__(self, driver: AsyncDriver, database_name: str):
        self.driver: AsyncDriver = driver
        self.database: str = database_name

    # ... (create_or_merge_source_node, set_source_content_embedding) ...
    # ... (create_chunk_node_and_link_to_source, set_chunk_content_embedding) ...
    async def create_or_merge_source_node(self, name: str, content: Optional[str], dynamic_metadata: Optional[Dict[str, Any]], created_at: datetime) -> Optional[str]: # identifier -> name
        source_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, name)) # Use name for UUID generation
        params = {
            "name_param": name, # Used for MERGE key and setting source.name
            "source_uuid_param": source_uuid, 
            "source_content_param": content, 
            "created_at_ts_param": created_at, 
            "dynamic_properties_param": dynamic_metadata or {}
        }
        try:
            results, summary, _ = await self.driver.execute_query(cypher_queries.MERGE_SOURCE_NODE, params, database_=self.database) # type: ignore
            if results and results[0]["source_uuid"]: return results[0]["source_uuid"]
            return None
        except Exception as e:
            logger.error(f"NodeManager: Error merging source node '{name}': {e}", exc_info=True)
            return None

    async def set_source_content_embedding(self, source_uuid: str, embedding_vector: List[float]) -> bool:
        try:
            params = {"source_uuid_param": source_uuid, "embedding_vector_param": embedding_vector}
            results, _, _ = await self.driver.execute_query(cypher_queries.SET_SOURCE_CONTENT_EMBEDDING, params, database_=self.database) # type: ignore
            return bool(results and results[0].get("uuid_processed") == source_uuid)
        except Exception as e:
            logger.error(f"NodeManager: Error setting source embedding for '{source_uuid}': {e}", exc_info=True)
            return False

    async def create_chunk_node_and_link_to_source(self, chunk_uuid: str, chunk_content: str, source_node_uuid: str, source_name_param: str, created_at: datetime, dynamic_chunk_properties: Dict[str, Any], chunk_number_for_rel: Optional[int]) -> Optional[str]: # source_identifier_for_chunk_desc -> source_name_param
        params = {
            "source_node_uuid_param": source_node_uuid, 
            "chunk_uuid_param": chunk_uuid, 
            "chunk_content_param": chunk_content, # Explicitly for chunk.content
            "source_name_param": source_name_param, # For chunk.source_description and APOC subquery
            "created_at_ts_param": created_at, 
            "dynamic_chunk_properties_param": dynamic_chunk_properties, # Should contain name, chunk_number etc.
            "chunk_number_param_for_rel": chunk_number_for_rel if chunk_number_for_rel is not None else 0
        }
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.ADD_CHUNK_AND_LINK_TO_SOURCE, params, database_=self.database) # type: ignore
            if results and results[0]["chunk_uuid"]: return results[0]["chunk_uuid"]
            return None
        except Exception as e:
            if "Failed to invoke procedure `apoc.do.when`" in str(e): logger.error("NodeManager: APOC `apoc.do.when` not found. Ensure APOC plugin is installed.", exc_info=False)
            logger.error(f"NodeManager: Error creating/linking chunk '{dynamic_chunk_properties.get('name', chunk_uuid)}': {e}", exc_info=True)
            return None
        
        
    async def set_chunk_content_embedding(self, chunk_uuid: str, embedding_vector: List[float]) -> bool:
        try:
            params = { "chunk_uuid_param": chunk_uuid, "embedding_vector_param": embedding_vector }
            results, _, _ = await self.driver.execute_query(cypher_queries.SET_CHUNK_CONTENT_EMBEDDING, params, database_=self.database) # type: ignore
            return bool(results and results[0].get("uuid_processed") == chunk_uuid)
        except Exception as e:
            logger.error(f"NodeManager: Error setting chunk embedding for '{chunk_uuid}': {e}", exc_info=True)
            return False

    async def merge_or_create_entity_node(
        self,
        entity_uuid_to_create_if_new: str, 
        name_for_create: str,        
        normalized_name_for_merge: str,
        label_for_merge: str,
        # description_for_create: Optional[str], -- REMOVED
        created_at_ts: datetime,
    ) -> Optional[Tuple[str, Optional[str], str, bool]]: # Corrected return tuple type
        params = {
            "uuid_param": entity_uuid_to_create_if_new, 
            "name_param": name_for_create, 
            "normalized_name_param": normalized_name_for_merge,
            "label_param": label_for_merge, 
            # "description_param": description_for_create, -- REMOVED
            "created_at_ts_param": created_at_ts,
        }
        try:
            results, summary, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.MERGE_ENTITY_NODE, params, database_=self.database
            )
            if results and results[0]["entity_uuid"]:
                entity_uuid_result = results[0]["entity_uuid"]
                was_created = summary.counters.nodes_created > 0 # type: ignore
                
                return (
                    entity_uuid_result,
                    results[0]["current_entity_name"],
                    results[0]["entity_label"], # This is from the Cypher query
                    was_created
                )
            logger.warning(f"NodeManager: MERGE_ENTITY_NODE for '{name_for_create}' did not return expected results.")
            return None
        except Exception as e:
            logger.error(f"NodeManager: Error merging/creating entity '{name_for_create}': {e}", exc_info=True)
            return None

    async def fetch_entity_details(self, entity_uuid: str) -> Optional[Tuple[str, Optional[str], str]]: # Return type changed
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.GET_ENTITY_DETAILS_FOR_UPDATE, uuid_param=entity_uuid, database_=self.database) # type: ignore
            if results and results[0]:
                record = results[0]
                return (
                    record["entity_uuid"], 
                    record["current_entity_name"], 
                    # record["current_entity_description"], -- REMOVED
                    record["entity_label"]
                )
            return None
        except Exception as e:
            logger.error(f"NodeManager: Error fetching entity details for UUID '{entity_uuid}': {e}", exc_info=True)
            return None

    async def update_entity_name(self, entity_uuid: str, new_name: str, updated_at_ts: datetime) -> bool:
        # ... (no change) ...
        try:
            params = {"uuid_param": entity_uuid, "new_name_param": new_name, "updated_at_param": updated_at_ts}
            results, _, _ = await self.driver.execute_query(cypher_queries.UPDATE_ENTITY_NAME, params, database_=self.database) # type: ignore
            return bool(results and results[0].get("updated_entity_name") == new_name)
        except Exception as e:
            logger.error(f"NodeManager: Error updating entity name for '{entity_uuid}': {e}", exc_info=True)
            return False

    # async def update_entity_description(
    #     self, 
    #     entity_uuid: str, 
    #     new_description: Optional[str], 
    #     updated_at_ts: datetime,
    #     # embedder: Optional[EmbedderClient] = None # Added embedder for description
    # ) -> bool:
    #     try:
    #         params = {"uuid_param": entity_uuid, "new_description_param": new_description, "updated_at_param": updated_at_ts}
    #         results, _, _ = await self.driver.execute_query( # type: ignore
    #             cypher_queries.UPDATE_ENTITY_DESCRIPTION, params, database_=self.database
    #         )
    #         description_updated_in_db = False
    #         if results and results[0].get("updated_entity_description") == new_description:
    #             description_updated_in_db = True
    #         elif new_description is None and results and results[0].get("updated_entity_description") is None: 
    #             description_updated_in_db = True
            
    #         # if description_updated_in_db and new_description and embedder:
    #         #     desc_embedding = await embedder.embed_text(new_description)
    #         #     if desc_embedding:
    #         #         await self.set_entity_description_embedding(entity_uuid, desc_embedding)
    #         #         logger.debug(f"        -> Updated description embedding for Entity '{entity_uuid}'.")
    #         # elif description_updated_in_db and new_description is None: # Description removed
    #         #     # Optionally, remove the description embedding property if desired
    #         #     # For now, we'll leave it, or you can add a Cypher query to REMOVE e.description_embedding
    #         #     logger.debug(f"        -> Description removed for Entity '{entity_uuid}'. Description embedding might be stale if not explicitly removed.")


    #         return description_updated_in_db
    #     except Exception as e:
    #         logger.error(f"NodeManager: Error updating entity description for '{entity_uuid}': {e}", exc_info=True)
    #         return False
    
    async def set_entity_name_embedding(self, entity_uuid: str, embedding_vector: List[float]) -> bool:
        # ... (no change) ...
        try:
            params = {"entity_uuid_param": entity_uuid, "embedding_vector_param": embedding_vector}
            results, _, _ = await self.driver.execute_query(cypher_queries.SET_ENTITY_NAME_EMBEDDING, params, database_=self.database) # type: ignore
            return bool(results and results[0].get("uuid_processed") == entity_uuid)
        except Exception as e:
            logger.error(f"NodeManager: Error setting entity name embedding for '{entity_uuid}': {e}", exc_info=True)
            return False

    # async def set_entity_description_embedding(self, entity_uuid: str, embedding_vector: List[float]) -> bool:
    #     """Sets the description_embedding vector property for a given Entity node."""
    #     try:
    #         params = {
    #             "entity_uuid_param": entity_uuid,
    #             "embedding_vector_param": embedding_vector
    #         }
    #         results, _, _ = await self.driver.execute_query( # type: ignore
    #             cypher_queries.SET_ENTITY_DESCRIPTION_EMBEDDING, # Use the new query
    #             params,
    #             database_=self.database
    #         )
    #         return bool(results and results[0].get("uuid_processed") == entity_uuid)
    #     except Exception as e:
    #         logger.error(f"NodeManager: Error setting entity description embedding for '{entity_uuid}': {e}", exc_info=True)
    #         return False



    async def create_or_merge_relationship(self, source_entity_uuid: str, target_entity_uuid: str, relation_label: str, fact_sentence: str, source_chunk_uuid: str, created_at_ts: datetime, relationship_uuid: Optional[str] = None) -> Optional[str]:
        # ... (no change) ...
        if not relationship_uuid: relationship_uuid = str(uuid.uuid4())
        params = {"source_entity_uuid_param": source_entity_uuid, "target_entity_uuid_param": target_entity_uuid, "relation_label_param": relation_label, "fact_sentence_param": fact_sentence, "relationship_uuid_param": relationship_uuid, "source_chunk_uuid_param": source_chunk_uuid, "created_at_ts_param": created_at_ts}
        try:
            results, summary, _ = await self.driver.execute_query(cypher_queries.MERGE_RELATIONSHIP, params, database_=self.database) # type: ignore
            if results and results[0]["relationship_uuid"]:
                action = "created" if summary.counters.relationships_created > 0 else "merged (or updated last_seen_at)" # type: ignore
                logger.debug(f"NodeManager: Relationship '{relation_label}' {action} between '{source_entity_uuid}' and '{target_entity_uuid}'. Fact: '{fact_sentence[:50]}...'. UUID: {results[0]['relationship_uuid']}")
                return results[0]["relationship_uuid"]
            return None
        except Exception as e:
            logger.error(f"NodeManager: Error merging relationship '{relation_label}' between '{source_entity_uuid}' and '{target_entity_uuid}': {e}", exc_info=True)
            return None

    async def set_relationship_fact_embedding(self, relationship_uuid: str, embedding_vector: List[float]) -> bool:
        # ... (no change) ...
        try:
            params = {"relationship_uuid_param": relationship_uuid, "embedding_vector_param": embedding_vector}
            results, _, _ = await self.driver.execute_query(cypher_queries.SET_RELATIONSHIP_FACT_EMBEDDING, params, database_=self.database) # type: ignore
            return bool(results and results[0].get("uuid_processed") == relationship_uuid)
        except Exception as e:
            logger.error(f"NodeManager: Error setting fact embedding for relationship '{relationship_uuid}': {e}", exc_info=True)
            return False
        
    async def create_or_merge_product_node(
        self,
        product_uuid: str,
        name: str,
        content: Optional[str], # NEW - for product's raw JSON content
        price: Optional[Any],   # NEW
        sku: Optional[str],     # NEW
        created_at: datetime,
        dynamic_product_properties: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Creates or merges a Product node."""
        params = {
            "product_uuid_param": product_uuid,
            "name_param": name,
            "content_param": content, # NEW
            "price_param": price,     # NEW
            "sku_param": sku,         # NEW
            "created_at_ts_param": created_at,
            "dynamic_product_properties_param": dynamic_product_properties or {}
        }
        try:
            results, _, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.MERGE_PRODUCT_NODE, 
                params, 
                database_=self.database
            )
            if results and results[0]["product_uuid"]:
                logger.debug(f"NodeManager: Product node '{name}' (UUID: {results[0]['product_uuid']}) merged/created.")
                return results[0]["product_uuid"]
            logger.warning(f"NodeManager: MERGE_PRODUCT_NODE for '{name}' did not return expected results.")
            return None
        except Exception as e:
            logger.error(f"NodeManager: Error merging/creating product node '{name}': {e}", exc_info=True)
            return None

    async def link_product_to_source(
        self,
        product_uuid: str,
        source_node_uuid: str,
        created_at: datetime
    ) -> bool:
        """Links a Product node to its Source node using BELONGS_TO_SOURCE."""
        params = {
            "product_uuid_param": product_uuid,
            "source_node_uuid_param": source_node_uuid,
            "created_at_ts_param": created_at
        }
        try:
            results, _, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.LINK_PRODUCT_TO_SOURCE, 
                params, 
                database_=self.database
            )
            # Expect BELONGS_TO_SOURCE now
            return bool(results and results[0]["relationship_type"] == "BELONGS_TO_SOURCE")
        except Exception as e:
            logger.error(f"NodeManager: Error linking product '{product_uuid}' to source '{source_node_uuid}': {e}", exc_info=True)
            return False

    async def set_product_name_embedding(self, product_uuid: str, embedding_vector: List[float]) -> bool:
        """Sets the name_embedding vector property for a given Product node."""
        try:
            params = {
                "product_uuid_param": product_uuid,
                "embedding_vector_param": embedding_vector
            }
            results, _, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.SET_PRODUCT_NAME_EMBEDDING,
                params,
                database_=self.database
            )
            return bool(results and results[0].get("uuid_processed") == product_uuid)
        except Exception as e:
            logger.error(f"NodeManager: Error setting product name embedding for '{product_uuid}': {e}", exc_info=True)
            return False

    async def set_product_content_embedding(self, product_uuid: str, embedding_vector: List[float]) -> bool: # Renamed
        """Sets the content_embedding vector property for a given Product node.""" # Docstring updated
        try:
            params = {
                "product_uuid_param": product_uuid,
                "embedding_vector_param": embedding_vector
            }
            results, _, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.SET_PRODUCT_CONTENT_EMBEDDING, # THIS IS THE USAGE
                params,
                database_=self.database
            )
            return bool(results and results[0].get("uuid_processed") == product_uuid)
        except Exception as e:
            logger.error(f"NodeManager: Error setting product content embedding for '{product_uuid}': {e}", exc_info=True) # Log message updated
            return False
        
        
    async def link_chunk_to_entity(self, chunk_uuid: str, entity_uuid: str, created_at_ts: datetime, fact_sentence_on_relationship: Optional[str] = None, mention_uuid: Optional[str] = None) -> Optional[str]:
        if not mention_uuid:
            mention_uuid = str(uuid.uuid4()) # Generate UUID if not provided

        params = {
            "chunk_uuid_param": chunk_uuid, 
            "entity_uuid_param": entity_uuid, 
            "created_at_ts_param": created_at_ts,
            "fact_sentence_param": fact_sentence_on_relationship, # Corrected from mention_context_param
            "mention_uuid_param": mention_uuid 
        }
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.LINK_CHUNK_TO_ENTITY, params, database_=self.database) # type: ignore
            if results and results[0]["relationship_type"] == "MENTIONS" and results[0]["relationship_uuid"]:
                return results[0]["relationship_uuid"]
            return None
        except Exception as e:
            logger.error(f"NodeManager: Error linking chunk '{chunk_uuid}' to entity '{entity_uuid}': {e}", exc_info=True)
            return None
        
           
    async def link_chunk_to_product(self, chunk_uuid: str, product_uuid: str, created_at_ts: datetime, fact_sentence_on_relationship: Optional[str] = None, mention_uuid: Optional[str] = None) -> Optional[str]: # Added mention_uuid, changed return
        """Links a Chunk node to a Product node using MENTIONS."""
        if not mention_uuid:
            mention_uuid = str(uuid.uuid4()) # Generate UUID if not provided

        params = {
            "chunk_uuid_param": chunk_uuid,
            "product_uuid_param": product_uuid, 
            "created_at_ts_param": created_at_ts,
            "fact_sentence_param": fact_sentence_on_relationship,
            "mention_uuid_param": mention_uuid # Pass UUID to Cypher
        }
        try:
            results, _, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.LINK_CHUNK_TO_PRODUCT, 
                params, 
                database_=self.database
            )
            if results and results[0]["relationship_type"] == "MENTIONS" and results[0]["relationship_uuid"]:
                return results[0]["relationship_uuid"]
            return None # Return None if creation/match failed or UUID not returned
        except Exception as e:
            logger.error(f"NodeManager: Error linking chunk '{chunk_uuid}' to product '{product_uuid}': {e}", exc_info=True)
            return None

    async def promote_entity_to_product(
        self,
        existing_entity_uuid: str,
        new_product_uuid: str, 
        new_product_name: str,
        new_product_content: Optional[str], # CHANGED from new_product_description
        new_product_price: Optional[Any],   # NEW
        new_product_sku: Optional[str],     # NEW
        new_product_dynamic_properties: Dict[str, Any],
        promotion_timestamp: datetime
    ) -> Optional[str]:
        
        processed_dynamic_props = preprocess_metadata_for_neo4j(new_product_dynamic_properties)
        params = {
            "existing_entity_uuid_param": existing_entity_uuid,
            "new_product_uuid_param": new_product_uuid,
            "new_product_name_param": new_product_name,
            "new_product_content_param": new_product_content, # CHANGED
            "new_product_price_param": new_product_price,     # NEW
            "new_product_sku_param": new_product_sku,         # NEW
            "new_product_properties_param": processed_dynamic_props, 
            "created_at_ts_param": promotion_timestamp
        }
        try:
            logger.info(f"NodeManager: Attempting to promote Entity '{existing_entity_uuid}' to Product '{new_product_name}' (new UUID: {new_product_uuid}).")
            logger.debug(f"NodeManager: Promotion FULL PARAMS being sent: {params}")

            current_query_text = cypher_queries.PROMOTE_ENTITY_TO_PRODUCT
            logger.debug(f"NodeManager: EXECUTING CYPHER for promotion:\n{current_query_text}\nWith PARAMS:\n{params}")

            results, summary, _ = await self.driver.execute_query( # type: ignore
                current_query_text,
                params,
                database_=self.database
            )

            if summary:
                logger.debug(f"NodeManager: Promotion query summary: "
                             f"nodes_created={summary.counters.nodes_created}, "
                             f"nodes_deleted={summary.counters.nodes_deleted}, "
                             f"rels_created={summary.counters.relationships_created}, "
                             f"rels_deleted={summary.counters.relationships_deleted}, "
                             f"props_set={summary.counters.properties_set}")
            else:
                logger.warning("NodeManager: Promotion query did not return a summary object.")

            if results and results[0].get("new_product_uuid"):
                new_puuid = results[0]["new_product_uuid"]
                inc_copied = results[0].get("incoming_rels_copied", -1) 
                out_copied = results[0].get("outgoing_rels_copied", -1)
                logger.info(f"NodeManager: Successfully processed promotion for Entity '{existing_entity_uuid}'. New Product UUID: '{new_puuid}'. Rel stats: In={inc_copied}, Out={out_copied}.")
                return new_puuid
            else:
                logger.error(f"NodeManager: Promotion of Entity '{existing_entity_uuid}' to Product failed to return new product UUID from results. Results list might be empty or record malformed.")
                if results: 
                    logger.error(f"NodeManager: Actual Result content from DB: {results[0]}")
                else:
                    logger.error("NodeManager: Results list from DB was empty.")
                return None
        except Exception as e:
            logger.error(f"NodeManager: EXCEPTION during promotion of Entity '{existing_entity_uuid}' to Product: {e}", exc_info=True)
            return None
        
    async def set_mentions_fact_embedding(self, chunk_uuid: str, target_node_uuid: str, embedding_vector: List[float]) -> bool: # Renamed method
        """Sets the fact_embedding on the MENTIONS relationship between a chunk and a target node (Entity or Product).""" # Updated docstring
        try:
            params = {
                "chunk_uuid_param": chunk_uuid,
                "target_node_uuid_param": target_node_uuid, 
                "embedding_vector_param": embedding_vector
            }
            results, _, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.SET_MENTIONS_FACT_EMBEDDING, # Use renamed Cypher query
                params,
                database_=self.database
            )
            return bool(results and results[0].get("relationships_updated", 0) > 0)
        except Exception as e:
            logger.error(f"NodeManager: Error setting fact_embedding for MENTIONS between chunk '{chunk_uuid}' and target node '{target_node_uuid}': {e}", exc_info=True) # Updated log
            return False

    async def delete_source_and_derived_data(self, source_uuid: str) -> Dict[str, int]:
        logger.info(f"NodeManager: Initiating deletion for Source UUID: {source_uuid}")
        deleted_counts = {
            "sources": 0, "chunks": 0, "products": 0, "products_demoted": 0,
            "mentions_rels": 0, "relates_to_rels": 0, "entities": 0,
        }

        async with self.driver.session(database=self.database) as session:
            tx = await session.begin_transaction()
            try:
                # 1. Get Chunk and Product UUIDs belonging to this source
                cursor = await tx.run(cypher_queries.GET_CHUNKS_FOR_SOURCE, source_uuid=source_uuid)
                chunk_uuids_of_source = [r["node_uuid"] async for r in cursor]
                await cursor.consume()
                logger.debug(f"  Found {len(chunk_uuids_of_source)} chunks for source {source_uuid}.")

                cursor = await tx.run(cypher_queries.GET_PRODUCTS_FOR_SOURCE, source_uuid=source_uuid)
                product_uuids_of_source = [r["node_uuid"] async for r in cursor]
                await cursor.consume()
                logger.debug(f"  Found {len(product_uuids_of_source)} products for source {source_uuid}.")

                all_origin_nodes_from_source = list(set(chunk_uuids_of_source + product_uuids_of_source))
                if not all_origin_nodes_from_source: logger.info(f"  No chunks or products linked to source {source_uuid}.")
                else: logger.debug(f"  Total origin nodes from source {source_uuid}: {len(all_origin_nodes_from_source)}")

                # Pre-fetch potential orphans
                potential_orphan_details = []
                if all_origin_nodes_from_source:
                    cursor = await tx.run(cypher_queries.GET_POTENTIAL_ORPHANS_CONNECTED_TO_ORIGINS, origin_uuids=all_origin_nodes_from_source)
                    potential_orphan_details = [{"uuid": r["node_uuid"], "name": r["node_name"], "labels": r["node_labels"]} async for r in cursor]
                    await cursor.consume()
                    logger.debug(f"  Identified {len(potential_orphan_details)} potential orphan candidates.")

                # 2. Delete RELATES_TO relationships from these origins
                if all_origin_nodes_from_source:
                    cursor = await tx.run(cypher_queries.DELETE_RELATES_TO_BY_SOURCE_CHUNK_UUIDS, origin_uuids=all_origin_nodes_from_source)
                    rec = await cursor.single(); deleted_counts["relates_to_rels"] = rec["deleted_count"] if rec else 0; await cursor.consume()
                    logger.info(f"  Deleted {deleted_counts['relates_to_rels']} RELATES_TO relationships from source origins.")

                # 3. Delete MENTIONS relationships from these origins
                if all_origin_nodes_from_source:
                    cursor = await tx.run(cypher_queries.DELETE_MENTIONS_BY_ORIGIN_UUIDS, origin_uuids=all_origin_nodes_from_source)
                    rec = await cursor.single(); deleted_counts["mentions_rels"] = rec["total_deleted"] if rec else 0; await cursor.consume()
                    logger.info(f"  Deleted {deleted_counts['mentions_rels']} MENTIONS relationships from source origins.")

                # 4. Identify and delete orphaned Entities
                entities_to_fully_delete = []
                if potential_orphan_details:
                    for target_detail in potential_orphan_details:
                        if "Entity" not in target_detail["labels"]: continue
                        entity_uuid = target_detail["uuid"]
                        
                        cursor = await tx.run(cypher_queries.CHECK_ENTITY_MENTIONED_BY_OTHERS, entity_uuid=entity_uuid, deleted_origin_uuids=all_origin_nodes_from_source)
                        rec = await cursor.single(); is_mentioned = rec["is_mentioned_by_others"] if rec else False; await cursor.consume()
                        
                        cursor = await tx.run(cypher_queries.CHECK_ENTITY_HAS_OTHER_RELATIONSHIPS, entity_uuid=entity_uuid, deleted_origin_uuids=all_origin_nodes_from_source)
                        rec = await cursor.single(); has_other_rels = rec["has_other_relationships"] if rec else False; await cursor.consume()
                        
                        if not is_mentioned and not has_other_rels:
                            entities_to_fully_delete.append(entity_uuid)
                            logger.debug(f"    Entity '{target_detail['name']}' ({entity_uuid}) marked as orphan.")
                        else:
                            logger.debug(f"    Entity '{target_detail['name']}' ({entity_uuid}) kept. External mentions: {is_mentioned}, Other rels: {has_other_rels}.")
                
                if entities_to_fully_delete:
                    cursor = await tx.run(cypher_queries.DELETE_ENTITIES_BY_UUIDS, entity_uuids=entities_to_fully_delete)
                    rec = await cursor.single(); deleted_counts["entities"] = rec["deleted_count"] if rec else 0; await cursor.consume()
                    logger.info(f"  Deleted {deleted_counts['entities']} orphaned Entities.")

                # 5. Handle Products (Demotion or Deletion)
                products_to_delete_fully = []
                if product_uuids_of_source:
                    for product_uuid in product_uuids_of_source:
                        cursor = await tx.run(cypher_queries.GET_PRODUCT_DETAILS_FOR_DEMOTION, uuid=product_uuid)
                        prod_rec = await cursor.single(); await cursor.consume()
                        prod_name = prod_rec["name"] if prod_rec else "Unknown Product"
                        prod_cat = prod_rec["category"] if prod_rec and prod_rec["category"] else "Product"

                        cursor = await tx.run(cypher_queries.CHECK_PRODUCT_MENTIONED_EXTERNALLY, product_uuid=product_uuid, deleted_origin_uuids=all_origin_nodes_from_source)
                        rec = await cursor.single(); mentioned_ext = rec["is_mentioned_externally"] if rec else False; await cursor.consume()
                        
                        cursor = await tx.run(cypher_queries.CHECK_PRODUCT_RELATED_EXTERNALLY_AS_TARGET, product_uuid=product_uuid, deleted_origin_uuids=all_origin_nodes_from_source)
                        rec = await cursor.single(); related_ext = rec["is_related_to_as_target_externally"] if rec else False; await cursor.consume()

                        if mentioned_ext or related_ext:
                            logger.info(f"    Product '{prod_name}' ({product_uuid}) referenced externally. Demoting.")
                            new_entity_uuid = str(uuid.uuid4())
                            demotion_label = prod_cat if prod_cat.strip() else "DemotedProduct"
                            await tx.run(cypher_queries.CREATE_DEMOTED_ENTITY_FROM_PRODUCT, new_uuid=new_entity_uuid, name=prod_name, label=demotion_label, original_uuid=product_uuid)
                            deleted_counts["products_demoted"] += 1
                            
                            params_relink = {"original_product_uuid": product_uuid, "new_demoted_entity_uuid": new_entity_uuid, "deleted_origin_uuids": all_origin_nodes_from_source}
                            cursor = await tx.run(cypher_queries.RELINK_MENTIONS_TO_DEMOTED_ENTITY, params_relink); rec = await cursor.single(); await cursor.consume()
                            if rec and rec["relinked_count"] > 0: logger.debug(f"      Re-linked {rec['relinked_count']} MENTIONS to demoted {new_entity_uuid}.")
                            
                            cursor = await tx.run(cypher_queries.RELINK_INCOMING_RELATES_TO_TO_DEMOTED_ENTITY, params_relink); rec = await cursor.single(); await cursor.consume()
                            if rec and rec["relinked_count"] > 0: logger.debug(f"      Re-linked {rec['relinked_count']} incoming RELATES_TO to demoted {new_entity_uuid}.")

                            cursor = await tx.run(cypher_queries.RELINK_OUTGOING_RELATES_TO_FROM_DEMOTED_ENTITY, original_product_uuid=product_uuid, new_demoted_entity_uuid=new_entity_uuid); rec = await cursor.single(); await cursor.consume()
                            if rec and rec["relinked_count"] > 0: logger.debug(f"      Re-linked {rec['relinked_count']} outgoing RELATES_TO from demoted {new_entity_uuid}.")
                            
                            cursor = await tx.run(cypher_queries.DELETE_PRODUCT_BY_UUID_DETACH, uuid=product_uuid); await cursor.consume() # Deletes original product
                            logger.debug(f"      Original Product {product_uuid} deleted after demotion.")
                        else:
                            products_to_delete_fully.append(product_uuid)
                            logger.info(f"    Product '{prod_name}' ({product_uuid}) not referenced externally. Marking for full deletion.")
                
                if products_to_delete_fully:
                    cursor = await tx.run(cypher_queries.DELETE_PRODUCTS_BY_UUIDS_DETACH, product_uuids=products_to_delete_fully)
                    rec = await cursor.single(); deleted_counts["products"] = rec["deleted_count"] if rec else 0; await cursor.consume()
                    logger.info(f"  Deleted {deleted_counts['products']} non-demoted Products.")
                
                # 6. Delete Chunks
                if chunk_uuids_of_source:
                    cursor = await tx.run(cypher_queries.DELETE_CHUNKS_BY_UUIDS_DETACH, chunk_uuids=chunk_uuids_of_source)
                    rec = await cursor.single(); deleted_counts["chunks"] = rec["deleted_count"] if rec else 0; await cursor.consume()
                    logger.info(f"  Deleted {deleted_counts['chunks']} Chunks.")

                # 7. Delete Source
                cursor = await tx.run(cypher_queries.DELETE_SOURCE_BY_UUID_DETACH, source_uuid=source_uuid)
                rec = await cursor.single(); deleted_counts["sources"] = rec["deleted_count"] if rec else 0; await cursor.consume()
                if deleted_counts["sources"] > 0: logger.info(f"  Deleted Source {source_uuid}.")
                else: logger.warning(f"  Source {source_uuid} not found for deletion.")

                await tx.commit()
                logger.info(f"NodeManager: Source deletion for {source_uuid} committed. Counts: {deleted_counts}")
            except Exception as e:
                logger.error(f"NodeManager: Error during deletion for Source {source_uuid}. Rolling back. Error: {e}", exc_info=True)
                if not tx.closed(): await tx.rollback()
                raise
            finally:
                if not tx.closed(): await tx.rollback()
        return deleted_counts
    
    
    async def delete_orphaned_entities(self) -> int:
        """
        Deletes :Entity nodes that have no incoming :MENTIONS relationships
        and no :RELATES_TO relationships (either incoming or outgoing).
        This is intended as a cleanup step after ingestion or major deletions.
        Returns the count of deleted orphaned entities.
        """
        logger.info("NodeManager: Attempting to delete orphaned :Entity nodes...")
        
        deleted_count = 0
        try:
            async with self.driver.session(database=self.database) as session:
                # Use the imported Cypher query
                result_cursor = await session.run(cypher_queries.DELETE_ORPHANED_ENTITIES)
                record = await result_cursor.single()
                await result_cursor.consume() # Ensure the result is fully consumed
                if record and record["deleted_count"] is not None:
                    deleted_count = record["deleted_count"]
            
            if deleted_count > 0:
                logger.info(f"NodeManager: Successfully deleted {deleted_count} orphaned :Entity nodes.")
            else:
                logger.info("NodeManager: No orphaned :Entity nodes found to delete.")
            return deleted_count
        except Exception as e:
            logger.error(f"NodeManager: Error during orphaned entity deletion: {e}", exc_info=True)
            return 0 # Return 0 or raise, depending on desired error handling