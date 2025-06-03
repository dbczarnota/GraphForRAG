# graphforrag_core/graphforrag.py
import logging
import asyncio # Make sure asyncio is imported
from typing import Optional, Any, List, Tuple, Dict 
import time # Import time
from neo4j import AsyncGraphDatabase, AsyncDriver # type: ignore
from .embedder_client import EmbedderClient
from .openai_embedder import OpenAIEmbedder # Assuming default if not provided
from .schema_manager import SchemaManager
from .entity_extractor import EntityExtractor
from .entity_resolver import EntityResolver
from .relationship_extractor import RelationshipExtractor
from .node_manager import NodeManager
from files.llm_models import setup_fallback_model
from pydantic_ai.usage import Usage

from .build_knowledge_base import add_documents_to_knowledge_base 
from .types import ResolvedEntityInfo
from .search_manager import SearchManager
from .search_types import (
    SearchConfig, 
    ChunkSearchConfig, ChunkSearchMethod, # Keep if needed for default config creation
    EntitySearchConfig, EntitySearchMethod, # <-- Ensure EntitySearchMethod is here
    RelationshipSearchConfig, RelationshipSearchMethod, # <-- Ensure RelationshipSearchMethod is here
    CombinedSearchResults, 
    SearchResultItem
)

logger = logging.getLogger("graph_for_rag")

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
                # Assuming OpenAIEmbedderConfig can be default or you have env vars for it
                from .openai_embedder import OpenAIEmbedderConfig 
                self.embedder = OpenAIEmbedder(OpenAIEmbedderConfig()) 
            
            self.services_llm_client = llm_client if llm_client else setup_fallback_model()

            self.entity_extractor = EntityExtractor(llm_client=self.services_llm_client)
            self.entity_resolver = EntityResolver( 
                driver=self.driver,
                database_name=self.database,
                embedder_client=self.embedder,
                llm_client=self.services_llm_client
            )
            self.relationship_extractor = RelationshipExtractor(llm_client=self.services_llm_client)
            
            self.schema_manager = SchemaManager(self.driver, self.database, self.embedder)
            self.node_manager = NodeManager(self.driver, self.database)
            # Ensure SearchManager is initialized
            self.search_manager = SearchManager(self.driver, self.database, self.embedder) 
            
            self.total_llm_usage: Usage = Usage()

            logger.info(f"Using embedder: {self.embedder.config.model_name} with dimension {self.embedder.dimension}")
            
            services_llm_model_name = "Unknown"
            # ... (LLM model name logging as before) ...
            if hasattr(self.services_llm_client, 'model') and isinstance(self.services_llm_client.model, str):
                services_llm_model_name = self.services_llm_client.model
            elif hasattr(self.services_llm_client, 'model_name') and isinstance(self.services_llm_client.model_name, str):
                services_llm_model_name = self.services_llm_client.model_name
            elif hasattr(self.services_llm_client, 'models') and isinstance(self.services_llm_client.models, list) and self.services_llm_client.models: 
                first_model_in_fallback = self.services_llm_client.models[0]
                if hasattr(first_model_in_fallback, 'model') and isinstance(first_model_in_fallback.model, str):
                    services_llm_model_name = f"Fallback starting with: {first_model_in_fallback.model}"
                elif hasattr(first_model_in_fallback, 'model_name') and isinstance(first_model_in_fallback.model_name, str):
                    services_llm_model_name = f"Fallback starting with: {first_model_in_fallback.model_name}"
                else: services_llm_model_name = "Fallback (model name unretrievable)"


            logger.info(f"GraphForRAG initialized. LLM for Entity/Relationship Services: {services_llm_model_name}")
            logger.info(f"Successfully initialized Neo4j driver for database '{database}' at '{uri}'")
        except Exception as e:
            logger.error(f"Failed to initialize GraphForRAG: {e}", exc_info=True)
            raise

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
    
    async def add_documents_from_source(
        self,
        source_identifier: str,
        documents_data: List[dict], 
        source_content: Optional[str] = None,
        source_dynamic_metadata: Optional[dict] = None,
        allow_same_name_chunks_for_this_source: bool = True
    ) -> Tuple[Optional[str], List[str]]:
        source_node_uuid, added_chunk_uuids, usage_for_set = await add_documents_to_knowledge_base(
            source_identifier=source_identifier,
            documents_data=documents_data,
            node_manager=self.node_manager,
            embedder=self.embedder,
            entity_extractor=self.entity_extractor,
            entity_resolver=self.entity_resolver,
            relationship_extractor=self.relationship_extractor,
            source_content=source_content,
            source_dynamic_metadata=source_dynamic_metadata,
            allow_same_name_chunks_for_this_source=allow_same_name_chunks_for_this_source
        )
        self._accumulate_usage(usage_for_set)
        return source_node_uuid, added_chunk_uuids

    async def search(
        self, 
        query_text: str, 
        config: Optional[SearchConfig] = None
    ) -> CombinedSearchResults:
        # ... (query_text check, config default, query_embedding logic as before) ...
        if not query_text.strip(): logger.warning("Search query is empty. Returning empty results."); return CombinedSearchResults(query_text=query_text)
        if config is None: logger.info("No search configuration provided, using default SearchConfig."); config = SearchConfig()
        query_embedding: Optional[List[float]] = None
        needs_semantic_search = False
        if config.chunk_config and ChunkSearchMethod.SEMANTIC in config.chunk_config.search_methods: needs_semantic_search = True
        if not needs_semantic_search and config.entity_config:
            if EntitySearchMethod.SEMANTIC_NAME in config.entity_config.search_methods or \
               EntitySearchMethod.SEMANTIC_DESCRIPTION in config.entity_config.search_methods: needs_semantic_search = True
        if not needs_semantic_search and config.relationship_config:
            if RelationshipSearchMethod.SEMANTIC_FACT in config.relationship_config.search_methods: needs_semantic_search = True
        if needs_semantic_search:
            embed_start_time = time.perf_counter()
            try:
                logger.debug(f"Generating embedding for query: '{query_text}'")
                query_embedding = await self.embedder.embed_text(query_text)
                if not query_embedding: logger.warning(f"Failed to generate embedding for query: '{query_text}'.")
            except Exception as e:
                logger.error(f"Error generating query embedding: {e}", exc_info=True); query_embedding = None
            embed_duration = (time.perf_counter() - embed_start_time) * 1000
            logger.info(f"Query embedding generation took {embed_duration:.2f} ms.")


        search_tasks = []
        task_map = {} 
        task_idx_counter = 0

        if config.chunk_config:
            # logger.info(f"Queueing chunk search for query: '{query_text}'") # Can be verbose
            search_tasks.append(self.search_manager.search_chunks(query_text, config.chunk_config, query_embedding))
            task_map[task_idx_counter] = "chunk"
            task_idx_counter += 1
        if config.entity_config:
            # logger.info(f"Queueing entity search for query: '{query_text}'")
            search_tasks.append(self.search_manager.search_entities(query_text, config.entity_config, query_embedding))
            task_map[task_idx_counter] = "entity"
            task_idx_counter += 1
        if config.relationship_config:
            # logger.info(f"Queueing relationship search for query: '{query_text}'")
            search_tasks.append(self.search_manager.search_relationships(query_text, config.relationship_config, query_embedding))
            task_map[task_idx_counter] = "relationship"
            task_idx_counter += 1

        if not search_tasks:
            logger.info("No search types configured. Returning empty results.")
            return CombinedSearchResults(items=[], query_text=query_text)

        logger.debug(f"Executing {len(search_tasks)} search type tasks concurrently...")
        gather_start_time = time.perf_counter()
        list_of_item_lists_from_gather = await asyncio.gather(*search_tasks)
        gather_duration = (time.perf_counter() - gather_start_time) * 1000
        logger.info(f"Concurrent search type execution (asyncio.gather) took {gather_duration:.2f} ms.")
        
        all_items: List[SearchResultItem] = []
        # ... (logic to combine results from list_of_item_lists_from_gather) ...
        for i, result_list_for_type in enumerate(list_of_item_lists_from_gather):
            search_type = task_map.get(i)
            if result_list_for_type: 
                logger.debug(f"Received {len(result_list_for_type)} items from {search_type} search.")
                all_items.extend(result_list_for_type)
            else: logger.debug(f"Received no items from {search_type} search.")
        
        all_items.sort(key=lambda x: x.score, reverse=True)
        
        logger.info(f"Search completed for '{query_text}'. Total combined items after sorting: {len(all_items)}")
        return CombinedSearchResults(items=all_items, query_text=query_text)