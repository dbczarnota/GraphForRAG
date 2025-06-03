# graphforrag_core/graphforrag.py
import logging
import asyncio 
from typing import Optional, Any, List, Tuple, Dict 
import time 
from neo4j import AsyncGraphDatabase, AsyncDriver # type: ignore
from .embedder_client import EmbedderClient
from .openai_embedder import OpenAIEmbedder 
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
    ChunkSearchConfig, ChunkSearchMethod, 
    EntitySearchConfig, EntitySearchMethod, 
    RelationshipSearchConfig, RelationshipSearchMethod,
    SourceSearchConfig, SourceSearchMethod, 
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
        logger.info(f"GraphForRAG initializing for DB '{database}' at '{uri}'.")
        init_start_time = time.perf_counter()
        try:
            self.driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=(user, password)) # type: ignore
            self.database: str = database
            
            if embedder_client:
                self.embedder = embedder_client
            else:
                logger.info("No embedder client provided to GraphForRAG, defaulting to OpenAIEmbedder.")
                from .openai_embedder import OpenAIEmbedderConfig 
                self.embedder = OpenAIEmbedder(OpenAIEmbedderConfig()) 
            
            self._llm_client_input = llm_client
            self._services_llm_client: Optional[Any] = None 

            self._entity_extractor: Optional[EntityExtractor] = None
            self._entity_resolver: Optional[EntityResolver] = None
            self._relationship_extractor: Optional[RelationshipExtractor] = None
            
            self.schema_manager = SchemaManager(self.driver, self.database, self.embedder)
            self.node_manager = NodeManager(self.driver, self.database)
            self.search_manager = SearchManager(self.driver, self.database, self.embedder) 
            
            self.total_llm_usage: Usage = Usage()

            logger.info(f"Using embedder: {self.embedder.config.model_name} with dimension {self.embedder.dimension}")
            if self._llm_client_input:
                model_name_for_log = "Unknown (passed-in client)"
                if hasattr(self._llm_client_input, 'model') and isinstance(self._llm_client_input.model, str):
                    model_name_for_log = self._llm_client_input.model
                elif hasattr(self._llm_client_input, 'model_name') and isinstance(self._llm_client_input.model_name, str):
                    model_name_for_log = self._llm_client_input.model_name
                logger.info(f"GraphForRAG initialized with pre-configured LLM client: {model_name_for_log}")
            else:
                logger.info("GraphForRAG initialized. Services LLM client will be set up on first use if needed.")

            logger.info(f"Successfully initialized Neo4j driver.")
        except Exception as e:
            logger.error(f"Failed to initialize GraphForRAG: {e}", exc_info=True)
            raise
        finally:
            logger.debug(f"GraphForRAG __init__ took {(time.perf_counter() - init_start_time)*1000:.2f} ms")

    def _ensure_services_llm_client(self) -> Any:
        if self._services_llm_client is None:
            if self._llm_client_input:
                self._services_llm_client = self._llm_client_input
                logger.debug("Using pre-configured LLM client for services.")
            else:
                logger.info("Setting up default fallback LLM client for services...")
                llm_setup_start_time = time.perf_counter()
                self._services_llm_client = setup_fallback_model() 
                logger.info(f"Default fallback LLM client setup took {(time.perf_counter() - llm_setup_start_time)*1000:.2f} ms.")
        return self._services_llm_client

    @property
    def entity_extractor(self) -> EntityExtractor:
        if self._entity_extractor is None:
            self._entity_extractor = EntityExtractor(llm_client=self._ensure_services_llm_client())
        return self._entity_extractor

    @property
    def entity_resolver(self) -> EntityResolver:
        if self._entity_resolver is None:
            self._entity_resolver = EntityResolver(
                driver=self.driver,
                database_name=self.database,
                embedder_client=self.embedder,
                llm_client=self._ensure_services_llm_client()
            )
        return self._entity_resolver

    @property
    def relationship_extractor(self) -> RelationshipExtractor:
        if self._relationship_extractor is None:
            self._relationship_extractor = RelationshipExtractor(llm_client=self._ensure_services_llm_client())
        return self._relationship_extractor

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
        _ = self.entity_extractor 
        _ = self.entity_resolver
        _ = self.relationship_extractor
        
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
        search_internal_total_start_time = time.perf_counter()
        if not query_text.strip(): 
            logger.warning("Search query is empty. Returning empty results.")
            return CombinedSearchResults(query_text=query_text)
        
        if config is None: 
            logger.info("No search configuration provided, using default SearchConfig.")
            config = SearchConfig()
        
        query_embedding: Optional[List[float]] = None
        needs_semantic_search = False
        # Determine if any configured search method requires an embedding
        if config.source_config and SourceSearchMethod.SEMANTIC_CONTENT in config.source_config.search_methods: 
            needs_semantic_search = True
        if not needs_semantic_search and config.chunk_config and ChunkSearchMethod.SEMANTIC in config.chunk_config.search_methods: 
            needs_semantic_search = True
        if not needs_semantic_search and config.entity_config:
            if EntitySearchMethod.SEMANTIC_NAME in config.entity_config.search_methods or \
               EntitySearchMethod.SEMANTIC_DESCRIPTION in config.entity_config.search_methods: 
                needs_semantic_search = True
        if not needs_semantic_search and config.relationship_config:
            if RelationshipSearchMethod.SEMANTIC_FACT in config.relationship_config.search_methods: 
                needs_semantic_search = True
                
        embed_duration = 0.0
        if needs_semantic_search:
            embed_start_time = time.perf_counter()
            try:
                logger.debug(f"GRAPHFORRAG.search: Generating embedding for query: '{query_text}'")
                query_embedding = await self.embedder.embed_text(query_text)
                if not query_embedding: 
                    logger.warning(f"GRAPHFORRAG.search: Failed to generate embedding for query: '{query_text}'.")
            except Exception as e:
                logger.error(f"GRAPHFORRAG.search: Error generating query embedding: {e}", exc_info=True)
                query_embedding = None 
            embed_duration = (time.perf_counter() - embed_start_time) * 1000
            logger.info(f"GRAPHFORRAG.search: Query embedding generation took {embed_duration:.2f} ms.")

        all_results_from_methods: List[Optional[List[SearchResultItem]]] = [] 
        sequential_execution_start_time = time.perf_counter()

        # Using sequential execution for profiling clarity
        if config.source_config:
            s_time = time.perf_counter()
            res = await self.search_manager.search_sources(query_text, config.source_config, query_embedding)
            logger.debug(f"GRAPHFORRAG.search (TIMING): search_sources call took {(time.perf_counter() - s_time) * 1000:.2f} ms, found {len(res) if res else 0} items.")
            if res: all_results_from_methods.append(res)
        
        if config.chunk_config:
            s_time = time.perf_counter()
            res = await self.search_manager.search_chunks(query_text, config.chunk_config, query_embedding)
            logger.debug(f"GRAPHFORRAG.search (TIMING): search_chunks call took {(time.perf_counter() - s_time) * 1000:.2f} ms, found {len(res) if res else 0} items.")
            if res: all_results_from_methods.append(res)
        
        if config.entity_config:
            s_time = time.perf_counter()
            res = await self.search_manager.search_entities(query_text, config.entity_config, query_embedding)
            logger.debug(f"GRAPHFORRAG.search (TIMING): search_entities call took {(time.perf_counter() - s_time) * 1000:.2f} ms, found {len(res) if res else 0} items.")
            if res: all_results_from_methods.append(res)
        
        if config.relationship_config:
            s_time = time.perf_counter()
            res = await self.search_manager.search_relationships(query_text, config.relationship_config, query_embedding)
            logger.debug(f"GRAPHFORRAG.search (TIMING): search_relationships call took {(time.perf_counter() - s_time) * 1000:.2f} ms, found {len(res) if res else 0} items.")
            if res: all_results_from_methods.append(res)
        
        sequential_execution_duration = (time.perf_counter() - sequential_execution_start_time) * 1000
        logger.info(f"GRAPHFORRAG.search: All sequential search method calls took {sequential_execution_duration:.2f} ms.")
        
        all_items: List[SearchResultItem] = []
        for result_list_for_type in all_results_from_methods: 
            if result_list_for_type: 
                all_items.extend(result_list_for_type)
        
        sort_start_time = time.perf_counter()
        all_items.sort(key=lambda x: x.score, reverse=True) 
        sort_duration = (time.perf_counter() - sort_start_time) * 1000
        logger.debug(f"GRAPHFORRAG.search: Final sort of {len(all_items)} items took {sort_duration:.2f} ms.")
        
        total_search_internal_duration = (time.perf_counter() - search_internal_total_start_time) * 1000
        logger.info(f"GRAPHFORRAG.search: Total internal execution time {total_search_internal_duration:.2f} ms. Found {len(all_items)} combined items.")
        return CombinedSearchResults(items=all_items, query_text=query_text)