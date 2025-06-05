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
from config import cypher_queries # ADD THIS IMPORT
from .build_knowledge_base import add_documents_to_knowledge_base 
from .types import ResolvedEntityInfo
from .search_manager import SearchManager
from .search_types import (
    SearchConfig, 
    ChunkSearchConfig, ChunkSearchMethod, 
    EntitySearchConfig, EntitySearchMethod, 
    RelationshipSearchConfig, RelationshipSearchMethod,
    SourceSearchConfig, SourceSearchMethod, 
    ProductSearchConfig, ProductSearchMethod,
    MentionSearchConfig, MentionSearchMethod, # ADDED MentionSearchMethod
    CombinedSearchResults, 
    SearchResultItem,
    MultiQueryConfig
)
from .multi_query_generator import MultiQueryGenerator


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
            self._multi_query_generator: Optional[MultiQueryGenerator] = None
            
            self.schema_manager = SchemaManager(self.driver, self.database, self.embedder)
            self.node_manager = NodeManager(self.driver, self.database)
            self.search_manager = SearchManager(self.driver, self.database, self.embedder) 
            
            self.total_generative_llm_usage: Usage = Usage() # RENAMED
            self.total_embedding_usage: Usage = Usage() # ADDED

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

    @property
    def multi_query_generator(self) -> MultiQueryGenerator:
        if self._multi_query_generator is None:
            self._multi_query_generator = MultiQueryGenerator(llm_client=self._ensure_services_llm_client())
        return self._multi_query_generator

    def _accumulate_generative_usage(self, new_usage: Optional[Usage]): # RENAMED
        if new_usage and hasattr(new_usage, 'has_values') and new_usage.has_values():
            self.total_generative_llm_usage = self.total_generative_llm_usage + new_usage # type: ignore
    
    def _accumulate_embedding_usage(self, new_usage: Optional[Usage]): # ADDED
        if new_usage and hasattr(new_usage, 'has_values') and new_usage.has_values():
            self.total_embedding_usage = self.total_embedding_usage + new_usage # type: ignore

    def get_total_llm_usage(self) -> Usage: 
        # Combines generative and embedding usage for an overall picture
        # Pydantic's Usage object supports addition
        return self.total_generative_llm_usage + self.total_embedding_usage # type: ignore

    def get_total_generative_llm_usage(self) -> Usage: # ADDED getter
        return self.total_generative_llm_usage
        
    def get_total_embedding_usage(self) -> Usage: # ADDED getter
        return self.total_embedding_usage

    async def close(self):
        if self.driver:
            await self.driver.close()
            logger.info("Neo4j driver closed.")

    async def ensure_indices(self):
        await self.schema_manager.ensure_indices_and_constraints()

    async def clear_all_data(self):
            # await self.schema_manager.clear_all_data() # Original problematic line
            logger.warning("GraphForRAG: Attempting to delete ALL nodes and relationships from the database directly...")
            try:
                # Directly use the driver and cypher query, similar to how SchemaManager does it
                async with self.driver.session(database=self.database) as session:
                    await session.run(cypher_queries.CLEAR_ALL_NODES_AND_RELATIONSHIPS)
                logger.info("GraphForRAG: Successfully cleared all data directly.")
            except Exception as e:
                logger.error(f"GraphForRAG: Error clearing all data directly: {e}", exc_info=True)
                raise

    async def clear_all_known_indexes_and_constraints(self):
        await self.schema_manager.clear_all_known_indexes_and_constraints()
    
    async def add_documents_from_source(
        self,
        source_data_block: dict, # CHANGED: was source_identifier, documents_data, etc.
        # source_identifier: str, # REMOVED
        # documents_data: List[dict],  # REMOVED
        # source_content: Optional[str] = None, # REMOVED
        # source_dynamic_metadata: Optional[dict] = None, # REMOVED
        allow_same_name_chunks_for_this_source: bool = True # This can probably be removed too if not used
    ) -> Tuple[Optional[str], List[str]]:
        # Ensure LLM services are ready if they'll be needed during ingestion
        _ = self.entity_extractor 
        _ = self.entity_resolver
        _ = self.relationship_extractor
        
        # add_documents_to_knowledge_base now expects the whole source_definition_block
        source_node_uuid, added_chunk_uuids, gen_usage_for_set, embed_usage_for_set = await add_documents_to_knowledge_base(
            source_definition_block=source_data_block, # PASS THE WHOLE BLOCK
            node_manager=self.node_manager,
            embedder=self.embedder,
            entity_extractor=self.entity_extractor, 
            entity_resolver=self.entity_resolver,   
            relationship_extractor=self.relationship_extractor
            # source_content and source_dynamic_metadata are now inside source_data_block
            # allow_same_name_chunks_for_this_source is not used by add_documents_to_knowledge_base
        )
        self._accumulate_generative_usage(gen_usage_for_set)
        self._accumulate_embedding_usage(embed_usage_for_set)
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
        
        all_queries_to_process: List[str] = [query_text]
        total_mqr_generation_duration = 0.0

        if config.mqr_config and config.mqr_config.enabled:
            logger.info(f"MQR enabled. Generating alternative queries for: '{query_text}'")
            mqr_start_time = time.perf_counter()
            alternative_queries_list, mqr_usage = await self.multi_query_generator.generate_alternative_queries(
                original_query=query_text,
                max_alternative_questions=config.mqr_config.max_alternative_questions
            )
            self._accumulate_generative_usage(mqr_usage)
            total_mqr_generation_duration = (time.perf_counter() - mqr_start_time) * 1000
            logger.info(f"MQR: Generation took {total_mqr_generation_duration:.2f} ms. Found {len(alternative_queries_list)} alternatives.")
            if alternative_queries_list:
                all_queries_to_process.extend(alternative_queries_list)
                logger.info(f"MQR: Total queries to process: {len(all_queries_to_process)} (Original + {len(alternative_queries_list)} alternatives)")
        
        query_to_embedding_map: Dict[str, Optional[List[float]]] = {}
        total_embedding_generation_duration = 0.0
        
        queries_requiring_embedding: List[str] = []
        for q_text in all_queries_to_process:
            needs_embedding = False
            if config.source_config and SourceSearchMethod.SEMANTIC_CONTENT in config.source_config.search_methods: needs_embedding = True
            if not needs_embedding and config.chunk_config and ChunkSearchMethod.SEMANTIC in config.chunk_config.search_methods: needs_embedding = True
            if not needs_embedding and config.entity_config and EntitySearchMethod.SEMANTIC_NAME in config.entity_config.search_methods: needs_embedding = True 
            if not needs_embedding and config.relationship_config and RelationshipSearchMethod.SEMANTIC_FACT in config.relationship_config.search_methods: needs_embedding = True
            if not needs_embedding and config.product_config: 
                if ProductSearchMethod.SEMANTIC_NAME in config.product_config.search_methods or \
                   ProductSearchMethod.SEMANTIC_CONTENT in config.product_config.search_methods:
                    needs_embedding = True
            if not needs_embedding and config.mention_config and MentionSearchMethod.SEMANTIC_FACT in config.mention_config.search_methods: # ADDED check for mention semantic search
                needs_embedding = True
            
            if needs_embedding:
                queries_requiring_embedding.append(q_text)
            query_to_embedding_map[q_text] = None 

        if queries_requiring_embedding:
            logger.info(f"GRAPHFORRAG.search: Generating embeddings concurrently for {len(queries_requiring_embedding)} queries.")
            embed_batch_start_time = time.perf_counter()
            embedding_tasks = [self.embedder.embed_text(q) for q in queries_requiring_embedding]
            
            try:
                results_or_exceptions = await asyncio.gather(*embedding_tasks, return_exceptions=True)
                for i, res_or_exc in enumerate(results_or_exceptions):
                    query_for_this_embedding = queries_requiring_embedding[i]
                    if isinstance(res_or_exc, Exception):
                        logger.error(f"GRAPHFORRAG.search: Error generating embedding for query '{query_for_this_embedding}': {res_or_exc}", exc_info=False)
                        query_to_embedding_map[query_for_this_embedding] = None
                    elif isinstance(res_or_exc, tuple) and len(res_or_exc) == 2:
                        embedding_vector, usage_info = res_or_exc
                        query_to_embedding_map[query_for_this_embedding] = embedding_vector
                        self._accumulate_embedding_usage(usage_info) 
                        if embedding_vector is None: 
                             logger.warning(f"GRAPHFORRAG.search: Embedding for query '{query_for_this_embedding}' was None despite no exception.")
                    else: 
                        logger.error(f"GRAPHFORRAG.search: Unexpected result type from embed_text for query '{query_for_this_embedding}': {type(res_or_exc)}")
                        query_to_embedding_map[query_for_this_embedding] = None
            except Exception as e_gather: 
                logger.error(f"GRAPHFORRAG.search: asyncio.gather for embeddings failed: {e_gather}", exc_info=True)
            total_embedding_generation_duration = (time.perf_counter() - embed_batch_start_time) * 1000
            logger.info(f"GRAPHFORRAG.search: Batch query embedding generation took {total_embedding_generation_duration:.2f} ms.")
        else:
            logger.info("GRAPHFORRAG.search: No queries required semantic embeddings.")

        all_raw_results_from_search_manager: List[SearchResultItem] = []
        total_sequential_search_calls_duration = 0.0

        for i, current_query_text_for_processing in enumerate(all_queries_to_process):
            is_original_query = (i == 0)
            query_log_prefix = "Original Query" if is_original_query else f"MQR Query {i+1}"
            logger.info(f"--- {query_log_prefix}: '{current_query_text_for_processing}' ---")
            current_query_embedding = query_to_embedding_map.get(current_query_text_for_processing)
            
            sequential_execution_start_time = time.perf_counter()
            if config.source_config:
                s_time = time.perf_counter(); res = await self.search_manager.search_sources(current_query_text_for_processing, config.source_config, current_query_embedding)
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_sources call took {(time.perf_counter() - s_time) * 1000:.2f} ms, found {len(res) if res else 0} items.")
                if res: all_raw_results_from_search_manager.extend(res)
            if config.chunk_config:
                s_time = time.perf_counter(); res = await self.search_manager.search_chunks(current_query_text_for_processing, config.chunk_config, current_query_embedding)
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_chunks call took {(time.perf_counter() - s_time) * 1000:.2f} ms, found {len(res) if res else 0} items.")
                if res: all_raw_results_from_search_manager.extend(res)
            if config.entity_config:
                s_time = time.perf_counter(); res = await self.search_manager.search_entities(current_query_text_for_processing, config.entity_config, current_query_embedding)
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_entities call took {(time.perf_counter() - s_time) * 1000:.2f} ms, found {len(res) if res else 0} items.")
                if res: all_raw_results_from_search_manager.extend(res)
            if config.relationship_config:
                s_time = time.perf_counter(); res = await self.search_manager.search_relationships(current_query_text_for_processing, config.relationship_config, current_query_embedding)
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_relationships call took {(time.perf_counter() - s_time) * 1000:.2f} ms, found {len(res) if res else 0} items.")
                if res: all_raw_results_from_search_manager.extend(res)
            if config.product_config: 
                s_time = time.perf_counter(); res = await self.search_manager.search_products(current_query_text_for_processing, config.product_config, current_query_embedding)
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_products call took {(time.perf_counter() - s_time) * 1000:.2f} ms, found {len(res) if res else 0} items.")
                if res: all_raw_results_from_search_manager.extend(res)
            if config.mention_config: # ADDED mention search call
                s_time = time.perf_counter(); res = await self.search_manager.search_mentions(current_query_text_for_processing, config.mention_config, current_query_embedding)
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_mentions call took {(time.perf_counter() - s_time) * 1000:.2f} ms, found {len(res) if res else 0} items.")
                if res: all_raw_results_from_search_manager.extend(res)
            
            current_query_sequential_search_duration = (time.perf_counter() - sequential_execution_start_time) * 1000
            total_sequential_search_calls_duration += current_query_sequential_search_duration
            logger.info(f"GRAPHFORRAG.search ({query_log_prefix}): Sequential search method calls for this query took {current_query_sequential_search_duration:.2f} ms.")
            logger.info(f"--- Finished processing {query_log_prefix} ---")

        logger.info(f"GRAPHFORRAG.search: MQR generation took {total_mqr_generation_duration:.2f} ms.")
        logger.info(f"GRAPHFORRAG.search: Total (batch) embedding generation time across all queries: {total_embedding_generation_duration:.2f} ms.")
        logger.info(f"GRAPHFORRAG.search: Total time for all sequential search calls across all queries: {total_sequential_search_calls_duration:.2f} ms.")
        
        deduplicated_scored_items_map: Dict[str, SearchResultItem] = {}
        if all_raw_results_from_search_manager:
            for item in all_raw_results_from_search_manager:
                if item.uuid not in deduplicated_scored_items_map or item.score > deduplicated_scored_items_map[item.uuid].score:
                    deduplicated_scored_items_map[item.uuid] = item
        
        deduplicated_and_sorted_items = sorted(deduplicated_scored_items_map.values(), key=lambda x: x.score, reverse=True)
        logger.debug(f"GRAPHFORRAG.search: After initial deduplication, {len(deduplicated_and_sorted_items)} unique items sorted by score.")

        final_results_list: List[SearchResultItem] = []
        added_uuids_for_final_list: set[str] = set()

        result_type_configs = []
        if config.chunk_config and config.chunk_config.min_results > 0:
            result_type_configs.append({"type": "Chunk", "min": config.chunk_config.min_results, "cfg": config.chunk_config})
        if config.entity_config and config.entity_config.min_results > 0:
            result_type_configs.append({"type": "Entity", "min": config.entity_config.min_results, "cfg": config.entity_config})
        if config.relationship_config and config.relationship_config.min_results > 0:
            result_type_configs.append({"type": "Relationship", "min": config.relationship_config.min_results, "cfg": config.relationship_config})
        if config.source_config and config.source_config.min_results > 0:
            result_type_configs.append({"type": "Source", "min": config.source_config.min_results, "cfg": config.source_config})
        if config.product_config and config.product_config.min_results > 0: 
            result_type_configs.append({"type": "Product", "min": config.product_config.min_results, "cfg": config.product_config})
        if config.mention_config and config.mention_config.min_results > 0: # ADDED Mention min_results check
            result_type_configs.append({"type": "Mention", "min": config.mention_config.min_results, "cfg": config.mention_config})


        for type_info in result_type_configs:
            current_type = type_info["type"]
            min_to_add = type_info["min"]
            count_for_type = 0
            for item in deduplicated_and_sorted_items:
                if item.result_type == current_type and item.uuid not in added_uuids_for_final_list:
                    if count_for_type < min_to_add:
                        final_results_list.append(item)
                        added_uuids_for_final_list.add(item.uuid)
                        count_for_type += 1
                    else:
                        break 
            logger.debug(f"Guaranteed {count_for_type}/{min_to_add} for type '{current_type}'. Total guaranteed: {len(final_results_list)}")

        if config.overall_results_limit is None or len(final_results_list) < config.overall_results_limit:
            limit_for_fill = config.overall_results_limit if config.overall_results_limit is not None else float('inf')
            
            for item in deduplicated_and_sorted_items:
                if len(final_results_list) >= limit_for_fill:
                    break
                if item.uuid not in added_uuids_for_final_list:
                    final_results_list.append(item)
                    added_uuids_for_final_list.add(item.uuid)
            logger.debug(f"Filled remaining. Total items before final sort: {len(final_results_list)}")

        final_results_list.sort(key=lambda x: x.score, reverse=True)
        
        if config.overall_results_limit is not None and len(final_results_list) > config.overall_results_limit:
            logger.info(f"Applying final overall_results_limit ({config.overall_results_limit}). Truncating from {len(final_results_list)}.")
            final_results_list = final_results_list[:config.overall_results_limit]
        
        total_search_internal_duration = (time.perf_counter() - search_internal_total_start_time) * 1000
        logger.info(f"GRAPHFORRAG.search: Total internal execution time {total_search_internal_duration:.2f} ms. Found {len(final_results_list)} combined items.")
        return CombinedSearchResults(items=final_results_list, query_text=query_text)