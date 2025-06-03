# graphforrag_core/node_manager.py
import logging
import uuid 
from datetime import datetime, timezone
from typing import Optional, Any, Dict, Tuple, List

from neo4j import AsyncDriver # type: ignore

from config import cypher_queries
# Import EmbedderClient to use its type hint, though NodeManager itself won't use it directly here
from .embedder_client import EmbedderClient 

logger = logging.getLogger("graph_for_rag.node_manager")

class NodeManager:
    def __init__(self, driver: AsyncDriver, database_name: str):
        self.driver: AsyncDriver = driver
        self.database: str = database_name

    # ... (create_or_merge_source_node, set_source_content_embedding) ...
    # ... (create_chunk_node_and_link_to_source, set_chunk_content_embedding) ...
    async def create_or_merge_source_node(self, identifier: str, content: Optional[str], dynamic_metadata: Optional[Dict[str, Any]], created_at: datetime) -> Optional[str]:
        source_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, identifier))
        params = {"source_identifier_param": identifier, "source_uuid_param": source_uuid, "source_content_param": content, "created_at_ts_param": created_at, "dynamic_properties_param": dynamic_metadata or {}}
        try:
            results, summary, _ = await self.driver.execute_query(cypher_queries.MERGE_SOURCE_NODE, params, database_=self.database) # type: ignore
            if results and results[0]["source_uuid"]: return results[0]["source_uuid"]
            return None
        except Exception as e:
            logger.error(f"NodeManager: Error merging source node '{identifier}': {e}", exc_info=True)
            return None

    async def set_source_content_embedding(self, source_uuid: str, embedding_vector: List[float]) -> bool:
        try:
            params = {"source_uuid_param": source_uuid, "embedding_vector_param": embedding_vector}
            results, _, _ = await self.driver.execute_query(cypher_queries.SET_SOURCE_CONTENT_EMBEDDING, params, database_=self.database) # type: ignore
            return bool(results and results[0].get("uuid_processed") == source_uuid)
        except Exception as e:
            logger.error(f"NodeManager: Error setting source embedding for '{source_uuid}': {e}", exc_info=True)
            return False

    async def create_chunk_node_and_link_to_source(self, chunk_uuid: str, chunk_content: str, source_node_uuid: str, source_identifier_for_chunk_desc: str, created_at: datetime, dynamic_chunk_properties: Dict[str, Any], chunk_number_for_rel: Optional[int]) -> Optional[str]:
        params = {"source_node_uuid_param": source_node_uuid, "chunk_uuid_param": chunk_uuid, "chunk_content_param": chunk_content, "source_identifier_param": source_identifier_for_chunk_desc, "created_at_ts_param": created_at, "dynamic_chunk_properties_param": dynamic_chunk_properties, "chunk_number_param_for_rel": chunk_number_for_rel if chunk_number_for_rel is not None else 0}
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
        description_for_create: Optional[str],
        created_at_ts: datetime,
        # embedder: Optional[EmbedderClient] = None # Added embedder for description
    ) -> Optional[Tuple[str, Optional[str], Optional[str], bool]]: 
        params = {
            "uuid_param": entity_uuid_to_create_if_new, 
            "name_param": name_for_create, 
            "normalized_name_param": normalized_name_for_merge,
            "label_param": label_for_merge, 
            "description_param": description_for_create,
            "created_at_ts_param": created_at_ts,
        }
        try:
            results, summary, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.MERGE_ENTITY_NODE, params, database_=self.database
            )
            if results and results[0]["entity_uuid"]:
                entity_uuid_result = results[0]["entity_uuid"]
                was_created = summary.counters.nodes_created > 0 # type: ignore
                
                # # Embed description if it was created and description exists
                # if was_created and description_for_create and embedder:
                #     desc_embedding = await embedder.embed_text(description_for_create)
                #     if desc_embedding:
                #         await self.set_entity_description_embedding(entity_uuid_result, desc_embedding)
                #         logger.debug(f"        -> Stored description embedding for NEW Entity '{entity_uuid_result}'.")
                
                return (
                    entity_uuid_result,
                    results[0]["current_entity_name"],
                    results[0]["current_entity_description"],
                    was_created
                )
            logger.warning(f"NodeManager: MERGE_ENTITY_NODE for '{name_for_create}' did not return expected results.")
            return None
        except Exception as e:
            logger.error(f"NodeManager: Error merging/creating entity '{name_for_create}': {e}", exc_info=True)
            return None

    async def fetch_entity_details(self, entity_uuid: str) -> Optional[Tuple[str, Optional[str], Optional[str], str]]:
        # ... (no change) ...
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.GET_ENTITY_DETAILS_FOR_UPDATE, uuid_param=entity_uuid, database_=self.database) # type: ignore
            if results and results[0]:
                record = results[0]
                return (record["entity_uuid"], record["current_entity_name"], record["current_entity_description"], record["entity_label"] )
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

    async def update_entity_description(
        self, 
        entity_uuid: str, 
        new_description: Optional[str], 
        updated_at_ts: datetime,
        # embedder: Optional[EmbedderClient] = None # Added embedder for description
    ) -> bool:
        try:
            params = {"uuid_param": entity_uuid, "new_description_param": new_description, "updated_at_param": updated_at_ts}
            results, _, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.UPDATE_ENTITY_DESCRIPTION, params, database_=self.database
            )
            description_updated_in_db = False
            if results and results[0].get("updated_entity_description") == new_description:
                description_updated_in_db = True
            elif new_description is None and results and results[0].get("updated_entity_description") is None: 
                description_updated_in_db = True
            
            # if description_updated_in_db and new_description and embedder:
            #     desc_embedding = await embedder.embed_text(new_description)
            #     if desc_embedding:
            #         await self.set_entity_description_embedding(entity_uuid, desc_embedding)
            #         logger.debug(f"        -> Updated description embedding for Entity '{entity_uuid}'.")
            # elif description_updated_in_db and new_description is None: # Description removed
            #     # Optionally, remove the description embedding property if desired
            #     # For now, we'll leave it, or you can add a Cypher query to REMOVE e.description_embedding
            #     logger.debug(f"        -> Description removed for Entity '{entity_uuid}'. Description embedding might be stale if not explicitly removed.")


            return description_updated_in_db
        except Exception as e:
            logger.error(f"NodeManager: Error updating entity description for '{entity_uuid}': {e}", exc_info=True)
            return False
    
    async def set_entity_name_embedding(self, entity_uuid: str, embedding_vector: List[float]) -> bool:
        # ... (no change) ...
        try:
            params = {"entity_uuid_param": entity_uuid, "embedding_vector_param": embedding_vector}
            results, _, _ = await self.driver.execute_query(cypher_queries.SET_ENTITY_NAME_EMBEDDING, params, database_=self.database) # type: ignore
            return bool(results and results[0].get("uuid_processed") == entity_uuid)
        except Exception as e:
            logger.error(f"NodeManager: Error setting entity name embedding for '{entity_uuid}': {e}", exc_info=True)
            return False

    async def set_entity_description_embedding(self, entity_uuid: str, embedding_vector: List[float]) -> bool:
        """Sets the description_embedding vector property for a given Entity node."""
        try:
            params = {
                "entity_uuid_param": entity_uuid,
                "embedding_vector_param": embedding_vector
            }
            results, _, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.SET_ENTITY_DESCRIPTION_EMBEDDING, # Use the new query
                params,
                database_=self.database
            )
            return bool(results and results[0].get("uuid_processed") == entity_uuid)
        except Exception as e:
            logger.error(f"NodeManager: Error setting entity description embedding for '{entity_uuid}': {e}", exc_info=True)
            return False

    async def link_chunk_to_entity(self, chunk_uuid: str, entity_uuid: str, created_at_ts: datetime) -> bool:
        # ... (no change) ...
        params = {"chunk_uuid_param": chunk_uuid, "entity_uuid_param": entity_uuid, "created_at_ts_param": created_at_ts}
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.LINK_CHUNK_TO_ENTITY, params, database_=self.database) # type: ignore
            return bool(results and results[0]["relationship_type"] == "MENTIONS_ENTITY")
        except Exception as e:
            logger.error(f"NodeManager: Error linking chunk '{chunk_uuid}' to entity '{entity_uuid}': {e}", exc_info=True)
            return False

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