# graphforrag_core/graphforrag.py
import logging
import asyncio 
from typing import Optional, Any, List, Tuple, Dict
from collections import defaultdict
import time 
import json 
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
from .types import IngestionConfig
from .types import IngestionConfig, FlaggedPropertiesConfig
from .cypher_generator import CypherGenerator

logger = logging.getLogger("graph_for_rag")

class GraphForRAG:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        embedder_client: Optional[EmbedderClient] = None,
        # llm_client: Optional[Any] = None, # --- REMOVED PARAMETER ---
        ingestion_config: Optional[IngestionConfig] = None,
        default_schema_flagged_properties_config: Optional[FlaggedPropertiesConfig] = None
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
            
            # self._llm_client_input = llm_client # --- REMOVED ---
            self.ingestion_config = ingestion_config if ingestion_config else IngestionConfig() 
            self._services_llm_client: Optional[Any] = None 

            self._entity_extractor: Optional[EntityExtractor] = None
            self._entity_resolver: Optional[EntityResolver] = None
            self._relationship_extractor: Optional[RelationshipExtractor] = None
            self._multi_query_generator: Optional[MultiQueryGenerator] = None
            self._cypher_generator: Optional[CypherGenerator] = None # New private attribute
            
            self.schema_manager = SchemaManager(self.driver, self.database, self.embedder, default_schema_flagged_properties_config) # Use new config name
            self.node_manager = NodeManager(self.driver, self.database)
            self.search_manager = SearchManager(self.driver, self.database, self.embedder) 
            
            self.total_generative_llm_usage: Usage = Usage() 
            self.total_embedding_usage: Usage = Usage() 

            logger.info(f"Using embedder: {self.embedder.config.model_name} with dimension {self.embedder.dimension}")
            if self.ingestion_config.ingestion_llm_models is not None:
                 logger.info(f"GraphForRAG: Ingestion services will use specific LLM config: {self.ingestion_config.ingestion_llm_models if self.ingestion_config.ingestion_llm_models else 'setup_fallback_model defaults'}")
            else:
                 logger.info("GraphForRAG: Ingestion services will use default LLM setup (via setup_fallback_model).")

            logger.info(f"Successfully initialized Neo4j driver.")
        except Exception as e:
            logger.error(f"Failed to initialize GraphForRAG: {e}", exc_info=True)
            raise
        finally:
            logger.debug(f"GraphForRAG __init__ took {(time.perf_counter() - init_start_time)*1000:.2f} ms")
            

    
    
    def _ensure_services_llm_client(self) -> Any:
        if self._services_llm_client is None:
            if self.ingestion_config and self.ingestion_config.ingestion_llm_models is not None:
                models_for_ingestion_setup = self.ingestion_config.ingestion_llm_models
                log_msg_model_source = models_for_ingestion_setup if models_for_ingestion_setup else "internal defaults of setup_fallback_model for ingestion"
                logger.info(f"INGESTION: Setting up specific LLM client for ingestion services using models: {log_msg_model_source}.")
                llm_setup_start_time = time.perf_counter()
                self._services_llm_client = setup_fallback_model(models_for_ingestion_setup)
                logger.info(f"INGESTION: Specific LLM client for ingestion setup took {(time.perf_counter() - llm_setup_start_time)*1000:.2f} ms.")
            else: # This now becomes the default if ingestion_config.ingestion_llm_models is None
                logger.info("INGESTION: No specific ingestion models configured. Setting up default fallback LLM client for ingestion services...")
            # --- End of modification ---
                llm_setup_start_time = time.perf_counter()
                self._services_llm_client = setup_fallback_model() 
                logger.info(f"INGESTION: Default fallback LLM client for ingestion setup took {(time.perf_counter() - llm_setup_start_time)*1000:.2f} ms.")
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
    
    @property
    def cypher_generator(self) -> Optional[CypherGenerator]: # Optional, as it depends on search_config
        """
        Provides an instance of CypherGenerator.
        The LLM client and flagged_properties_config for this generator
        are determined by the CypherSearchConfig passed during a search operation.
        This property might seem to initialize with a default LLM, but its actual
        LLM and schema config will be set/overridden per search call if CypherSearch is enabled.
        Consider this a placeholder or default instance. The real configuration happens in `search()`.
        Alternatively, CypherGenerator instantiation could be entirely within the search() method.
        For now, let's allow a default instantiation here.
        """
        if self._cypher_generator is None:
            # This default instantiation might use a general LLM.
            # The `search` method will need to pass the specific config from `SearchConfig`
            # to a method of `CypherGenerator` or re-initialize it.
            # For simplicity of this property, let's use _ensure_services_llm_client,
            # but acknowledge that the search method will drive the actual config.
            logger.debug("GraphForRAG: Initializing default CypherGenerator instance.")
            self._cypher_generator = CypherGenerator(
                llm_client=self._ensure_services_llm_client(), # Default LLM for now
                driver=self.driver,
                database_name=self.database,
                embedder_client=self.embedder,
                flagged_properties_config=None # Default schema config for this instance
            )
        return self._cypher_generator
    
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
        source_data_block: dict, 
    ) -> Tuple[Optional[str], List[str]]:
        # Ensure LLM services are ready if they'll be needed during ingestion
        _ = self.entity_extractor 
        _ = self.entity_resolver
        _ = self.relationship_extractor
        
        labels_for_extraction: Optional[List[str]] = None
        
        if self.ingestion_config and self.ingestion_config.extractable_entity_labels:
            labels_for_extraction = self.ingestion_config.extractable_entity_labels
            logger.info(f"GraphForRAG: Using specific entity labels for ingestion: {labels_for_extraction}")
        else:
            logger.info("GraphForRAG: Using general entity extraction for ingestion (no specific labels configured).")        
            
        # Correctly unpack the return values from add_documents_to_knowledge_base
        source_node_uuid, processed_item_node_uuids, gen_usage_for_set, embed_usage_for_set = await add_documents_to_knowledge_base(
            source_definition_block=source_data_block, 
            node_manager=self.node_manager,
            embedder=self.embedder,
            entity_extractor=self.entity_extractor, 
            entity_resolver=self.entity_resolver,   
            relationship_extractor=self.relationship_extractor,
            extractable_entity_labels_for_ingestion=labels_for_extraction
        )
        self._accumulate_generative_usage(gen_usage_for_set)
        self._accumulate_embedding_usage(embed_usage_for_set)
        
        # Use the correctly named variable for the condition
        if source_node_uuid or processed_item_node_uuids: # Only run cleanup if something was potentially added/changed
            logger.info(f"GraphForRAG: Running orphaned entity cleanup after ingesting source: {source_data_block.get('name', 'Unknown Source')}")
            await self.cleanup_orphaned_entities()
            
        return source_node_uuid, processed_item_node_uuids # Return the correctly named variable
    
    
    # Inside GraphForRAG class in graphforrag_core/graphforrag.py
    async def delete_source(self, source_uuid: str) -> Dict[str, int]:
        logger.info(f"GraphForRAG: Request to delete source UUID: {source_uuid}")
        # Optional: Add pre-checks here, e.g., confirm source_uuid exists.
        # For example:
        # source_exists_res, _, _ = await self.driver.execute_query(
        #     "MATCH (s:Source {uuid: $uuid}) RETURN count(s) > 0 AS exists",
        #     uuid=source_uuid, database_=self.database
        # )
        # if not (source_exists_res and source_exists_res[0]["exists"]):
        #     logger.warning(f"Source with UUID {source_uuid} not found. Skipping deletion.")
        #     return {} # Or raise an error

        deletion_summary = await self.node_manager.delete_source_and_derived_data(source_uuid)
        logger.info(f"GraphForRAG: Deletion process for source {source_uuid} completed. Summary: {deletion_summary}")
        if deletion_summary.get("sources", 0) > 0 or \
           deletion_summary.get("chunks", 0) > 0 or \
           deletion_summary.get("products", 0) > 0 or \
           deletion_summary.get("products_demoted", 0) > 0: # Only run cleanup if significant nodes were affected
            logger.info(f"GraphForRAG: Running orphaned entity cleanup after deleting source: {source_uuid}")
            await self.cleanup_orphaned_entities()
        else:
            logger.info(f"GraphForRAG: Skipping orphaned entity cleanup as no primary nodes seem to have been deleted for source: {source_uuid}")
        
        return deletion_summary
    
    async def cleanup_orphaned_entities(self) -> int:
        """
        Calls the NodeManager to delete any truly orphaned Entity nodes.
        """
        logger.info("GraphForRAG: Initiating cleanup of orphaned entities...")
        deleted_count = await self.node_manager.delete_orphaned_entities()
        logger.info(f"GraphForRAG: Orphaned entity cleanup complete. Deleted {deleted_count} entities.")
        return deleted_count
    
    async def get_schema(self) -> str:
        """
        Retrieves and formats the database schema string using the SchemaManager.
        """
        if not self.schema_manager:
            logger.error("SchemaManager not initialized in GraphForRAG. Cannot get schema.")
            return "Error: SchemaManager not available."
        return await self.schema_manager.get_schema_string()    
    
    
    async def search(
        self, 
        query_text: str, 
        config: Optional[SearchConfig] = None
    ) -> CombinedSearchResults:
        _original_user_query_for_report = query_text # Store the absolute original quer
        search_internal_total_start_time = time.perf_counter()
        if not query_text.strip(): 
            logger.warning("Search query is empty. Returning empty results.")
            return CombinedSearchResults(query_text=_original_user_query_for_report)
        
        if config is None: 
            logger.info("No search configuration provided, using default SearchConfig.")
            config = SearchConfig()
        all_queries_to_process: List[str] = [] 
        total_mqr_generation_duration = 0.0
        generated_cypher_query: Optional[str] = None # To store the LLM-generated Cypher
        cypher_generation_duration = 0.0         # To store its generation time
        cypher_generation_usage: Optional[Usage] = None # To store its LLM usage

        # --- Parallel Task Preparation: MQR and Cypher Generation ---
        parallel_tasks = []
        mqr_task_idx = -1 # To identify MQR results later
        cypher_gen_task_idx = -1 # To identify Cypher gen results later

        if config.mqr_config and config.mqr_config.enabled:
            logger.info(f"MQR enabled. Config: {config.mqr_config.model_dump_json(indent=2, exclude_none=True)}")
            
            async def mqr_generation_wrapper(): # Wrapper to easily add to gather
                mq_generator_for_this_search: MultiQueryGenerator
                if config.mqr_config.mqr_llm_models is not None:
                    models_for_mqr_setup = config.mqr_config.mqr_llm_models
                    log_msg_model_source = models_for_mqr_setup if models_for_mqr_setup else "internal defaults of setup_fallback_model"
                    logger.info(f"MQR: Setting up specific LLM client for MQR generation using models: {log_msg_model_source}.")
                    mqr_specific_llm_client = setup_fallback_model(models_for_mqr_setup) 
                    mq_generator_for_this_search = MultiQueryGenerator(llm_client=mqr_specific_llm_client)
                else: 
                    logger.info("MQR: Using default service LLM for MQR generation (via self.multi_query_generator property).")
                    mq_generator_for_this_search = self.multi_query_generator
                
                return await mq_generator_for_this_search.generate_alternative_queries(
                    original_query=query_text,
                    max_alternative_questions=config.mqr_config.max_alternative_questions
                )
            parallel_tasks.append(mqr_generation_wrapper())
            mqr_task_idx = len(parallel_tasks) - 1
        else:
            logger.info(f"MQR not enabled or no MQR config. Original query will be processed: '{query_text}'")

        if config.cypher_search_config and config.cypher_search_config.enabled:
            logger.info(f"Cypher Search enabled. Config: {config.cypher_search_config.model_dump_json(indent=2, exclude_none=True)}")

            async def cypher_generation_wrapper(): # Wrapper for Cypher generation
                # Instantiate CypherGenerator specifically for this search call
                cypher_gen_llm_models = config.cypher_search_config.llm_models # May be None
                cypher_gen_flagged_props_config = config.cypher_search_config.flagged_properties_config # May be None
                
                llm_for_cypher_gen = setup_fallback_model(cypher_gen_llm_models) if cypher_gen_llm_models else self._ensure_services_llm_client()
                
                cypher_gen_instance = CypherGenerator(
                    llm_client=llm_for_cypher_gen,
                    driver=self.driver,
                    database_name=self.database,
                    embedder_client=self.embedder,
                    flagged_properties_config=cypher_gen_flagged_props_config
                )
                return await cypher_gen_instance.generate_cypher_query(
                    question=query_text,
                    custom_schema_string=config.cypher_search_config.custom_schema_string if config.cypher_search_config else None
                )
            
            parallel_tasks.append(cypher_generation_wrapper())
            cypher_gen_task_idx = len(parallel_tasks) - 1
        else:
            logger.info("Cypher Search not enabled.")

        # --- Execute MQR and Cypher Generation Concurrently (if any tasks) ---
        if parallel_tasks:
            logger.info(f"GraphForRAG.search: Running {len(parallel_tasks)} generation tasks concurrently (MQR and/or Cypher Gen).")
            parallel_start_time = time.perf_counter()
            gathered_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
            parallel_duration = (time.perf_counter() - parallel_start_time) * 1000
            logger.info(f"GraphForRAG.search: Concurrent generation tasks finished in {parallel_duration:.2f} ms.")

            # Process MQR results
            if mqr_task_idx != -1:
                mqr_result_or_exc = gathered_results[mqr_task_idx]
                if isinstance(mqr_result_or_exc, Exception):
                    logger.error(f"MQR generation failed: {mqr_result_or_exc}", exc_info=mqr_result_or_exc)
                    alternative_queries_list = []
                elif isinstance(mqr_result_or_exc, tuple) and len(mqr_result_or_exc) == 2:
                    alternative_queries_list, mqr_usage = mqr_result_or_exc
                    self._accumulate_generative_usage(mqr_usage)
                    # total_mqr_generation_duration is now part of parallel_duration, can log specific if needed
                    logger.info(f"MQR: Found {len(alternative_queries_list)} alternatives from concurrent execution.")
                else:
                    logger.error(f"Unexpected result from MQR generation wrapper: {type(mqr_result_or_exc)}")
                    alternative_queries_list = []
                
                if config.mqr_config and config.mqr_config.include_original_query:
                    all_queries_to_process.append(query_text)
                if alternative_queries_list: # Check if list is not empty
                    all_queries_to_process.extend(alternative_queries_list)

            # Process Cypher generation results
            if cypher_gen_task_idx != -1:
                cypher_result_or_exc = gathered_results[cypher_gen_task_idx]
                if isinstance(cypher_result_or_exc, Exception):
                    logger.error(f"Cypher query generation failed: {cypher_result_or_exc}", exc_info=cypher_result_or_exc)
                    generated_cypher_query = None
                elif isinstance(cypher_result_or_exc, tuple) and len(cypher_result_or_exc) == 2:
                    generated_cypher_query, cypher_generation_usage = cypher_result_or_exc
                    self._accumulate_generative_usage(cypher_generation_usage)
                    # cypher_generation_duration is now part of parallel_duration
                    if generated_cypher_query:
                        logger.info(f"Cypher Search: Generated Cypher query from concurrent execution:\n{generated_cypher_query}")
                    else:
                        logger.info("Cypher Search: No Cypher query was generated by the LLM.")
                else:
                     logger.error(f"Unexpected result from Cypher generation wrapper: {type(cypher_result_or_exc)}")
                     generated_cypher_query = None
        
        # If no MQR was run but original query should be processed
        if not all_queries_to_process and (not config.mqr_config or not config.mqr_config.enabled or not config.mqr_config.include_original_query):
            all_queries_to_process.append(query_text) # Ensure original query is processed if MQR didn't add it
        elif not all_queries_to_process and config.mqr_config and config.mqr_config.enabled and config.mqr_config.include_original_query:
             all_queries_to_process.append(query_text) # Ensure original query if MQR ran but somehow yielded no queries for processing including original
        elif not all_queries_to_process and not (config.mqr_config and config.mqr_config.enabled): # Case where MQR is off
             all_queries_to_process.append(query_text)


        if not all_queries_to_process and not generated_cypher_query:
            logger.warning("MQR/Standard search resulted in no queries, and Cypher search yielded no query. Search will be skipped.")
            return CombinedSearchResults(query_text=_original_user_query_for_report)
        
        logger.info(f"Total keyword/semantic queries to process: {len(all_queries_to_process)}")
        if generated_cypher_query:
             logger.info(f"LLM-Generated Cypher query will also be processed.")
             
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

        raw_results_by_type_query_method: Dict[str, Dict[str, Dict[str, List[Dict[str, Any]]]]] = defaultdict(lambda: defaultdict(dict))
        llm_cypher_execution_results: List[Dict[str, Any]] = [] # To store results from LLM Cypher
        total_llm_cypher_execution_duration = 0.0

        # --- Execute LLM-Generated Cypher Query (if available) ---
        # This happens *before* the loop over all_queries_to_process for standard search,
        # as the Cypher query is based on the *original* user query.
        # We need the embedding of the *original* user query for potential binding.
        original_query_embedding: Optional[List[float]] = None
        if query_text in query_to_embedding_map: # Ensure original query's embedding exists if needed
            original_query_embedding = query_to_embedding_map[query_text]
        
        if generated_cypher_query and config.cypher_search_config and config.cypher_search_config.enabled:
            cypher_exec_start_time = time.perf_counter()
            llm_cypher_execution_results = await self.search_manager.execute_llm_generated_cypher(
                generated_cypher_query=generated_cypher_query,
                original_query_text=_original_user_query_for_report, # Pass the absolute original query
                query_embedding=original_query_embedding # Pass embedding of the original query
            )
            total_llm_cypher_execution_duration = (time.perf_counter() - cypher_exec_start_time) * 1000
            logger.info(f"GraphForRAG.search: LLM-generated Cypher execution completed in {total_llm_cypher_execution_duration:.2f} ms. Found {len(llm_cypher_execution_results)} items.")
            # These results are raw list of dicts. We'll add them to CombinedSearchResults later.
        
        total_sequential_search_calls_duration = 0.0

        for i, current_query_text_for_processing in enumerate(all_queries_to_process):
            is_original_query = (i == 0)
            query_log_prefix = "Original Query" if is_original_query else f"MQR Query {i+1}" # Corrected from i to i+1 for MQR Query
            logger.info(f"--- {query_log_prefix}: '{current_query_text_for_processing}' ---")
            current_query_embedding = query_to_embedding_map.get(current_query_text_for_processing)
            
            sequential_execution_start_time = time.perf_counter()
            
            # --- Collect results for each type for the current query ---
            if config.source_config:
                s_time = time.perf_counter()
                # SearchManager.search_sources now returns Dict[str, List[Dict[str, Any]]]
                source_method_results: Dict[str, List[Dict[str, Any]]] = await self.search_manager.search_sources(
                    current_query_text_for_processing, config.source_config, current_query_embedding
                )
                raw_results_by_type_query_method["Source"][current_query_text_for_processing] = source_method_results
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_sources raw fetch took {(time.perf_counter() - s_time) * 1000:.2f} ms. Method counts: {{m: len(r) for m, r in source_method_results.items()}}")

            if config.chunk_config:
                s_time = time.perf_counter()
                chunk_method_results: Dict[str, List[Dict[str, Any]]] = await self.search_manager.search_chunks(
                    current_query_text_for_processing, config.chunk_config, current_query_embedding
                )
                raw_results_by_type_query_method["Chunk"][current_query_text_for_processing] = chunk_method_results
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_chunks raw fetch took {(time.perf_counter() - s_time) * 1000:.2f} ms. Method counts: {{m: len(r) for m, r in chunk_method_results.items()}}")

            if config.entity_config:
                s_time = time.perf_counter()
                entity_method_results: Dict[str, List[Dict[str, Any]]] = await self.search_manager.search_entities(
                    current_query_text_for_processing, config.entity_config, current_query_embedding
                )
                raw_results_by_type_query_method["Entity"][current_query_text_for_processing] = entity_method_results
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_entities raw fetch took {(time.perf_counter() - s_time) * 1000:.2f} ms. Method counts: {{m: len(r) for m, r in entity_method_results.items()}}")

            if config.relationship_config:
                s_time = time.perf_counter()
                relationship_method_results: Dict[str, List[Dict[str, Any]]] = await self.search_manager.search_relationships(
                    current_query_text_for_processing, config.relationship_config, current_query_embedding
                )
                raw_results_by_type_query_method["Relationship"][current_query_text_for_processing] = relationship_method_results
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_relationships raw fetch took {(time.perf_counter() - s_time) * 1000:.2f} ms. Method counts: {{m: len(r) for m, r in relationship_method_results.items()}}")

            if config.product_config: 
                s_time = time.perf_counter()
                product_method_results: Dict[str, List[Dict[str, Any]]] = await self.search_manager.search_products(
                    current_query_text_for_processing, config.product_config, current_query_embedding
                )
                raw_results_by_type_query_method["Product"][current_query_text_for_processing] = product_method_results
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_products raw fetch took {(time.perf_counter() - s_time) * 1000:.2f} ms. Method counts: {{m: len(r) for m, r in product_method_results.items()}}")

            if config.mention_config: 
                s_time = time.perf_counter()
                mention_method_results: Dict[str, List[Dict[str, Any]]] = await self.search_manager.search_mentions(
                    current_query_text_for_processing, config.mention_config, current_query_embedding
                )
                raw_results_by_type_query_method["Mention"][current_query_text_for_processing] = mention_method_results
                logger.debug(f"GRAPHFORRAG.search ({query_log_prefix}, TIMING): search_mentions raw fetch took {(time.perf_counter() - s_time) * 1000:.2f} ms. Method counts: {{m: len(r) for m, r in mention_method_results.items()}}")
            
            current_query_sequential_search_duration = (time.perf_counter() - sequential_execution_start_time) * 1000
            total_sequential_search_calls_duration += current_query_sequential_search_duration
            logger.info(f"GRAPHFORRAG.search ({query_log_prefix}): Raw data fetching for this query took {current_query_sequential_search_duration:.2f} ms.")
            logger.info(f"--- Finished fetching data for {query_log_prefix} ---")

        logger.info(f"GRAPHFORRAG.search: MQR generation took {total_mqr_generation_duration:.2f} ms.")
        logger.info(f"GRAPHFORRAG.search: Total (batch) embedding generation time across all queries: {total_embedding_generation_duration:.2f} ms.")
        logger.info(f"GRAPHFORRAG.search: Total time for all raw data fetching calls across all queries: {total_sequential_search_calls_duration:.2f} ms.")
        
        # The old deduplication and sorting logic is removed from here.
        # It will be replaced by the new two-stage RRF and final blending.
        # For now, let's just log the structure we've built.
        logger.debug(f"GRAPHFORRAG.search: Raw results collected. Structure summary (Type -> Query -> Method -> Count):")
        for res_type, queries_data in raw_results_by_type_query_method.items():
            for q_text, methods_data in queries_data.items():
                for method_src, res_list in methods_data.items():
                    logger.debug(f"  - {res_type} | Query: '{q_text[:30]}...' | Method: {method_src} | Count: {len(res_list)}")

            # New structure: Dict[ResultType, Dict[MethodSource, List[MQR_Enhanced_ResultDict]]]
        mqr_enhanced_lists_by_type_method: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(dict)
        inter_query_rrf_processing_start_time = time.perf_counter()

        logger.info("GRAPHFORRAG.search: Starting Inter-Query RRF processing...")

        for result_type, queries_data in raw_results_by_type_query_method.items():
            # Determine rrf_k and fetch_limit based on the result_type's config
            # This requires accessing parts of the original search config.
            # We'll need to make sure the config object is accessible here.
            # For now, let's use a placeholder or a default rrf_k.
            # The fetch_limit for the method will determine how many items went into each list.
            
            current_type_config: Any = None
            if result_type == "Chunk" and config.chunk_config: current_type_config = config.chunk_config
            elif result_type == "Entity" and config.entity_config: current_type_config = config.entity_config
            elif result_type == "Relationship" and config.relationship_config: current_type_config = config.relationship_config
            elif result_type == "Source" and config.source_config: current_type_config = config.source_config
            elif result_type == "Product" and config.product_config: current_type_config = config.product_config
            elif result_type == "Mention" and config.mention_config: current_type_config = config.mention_config
            
            # Get all method sources used for this result_type across all queries
            all_method_sources_for_type: set[str] = set()
            for query_specific_methods_data in queries_data.values():
                all_method_sources_for_type.update(query_specific_methods_data.keys())

            for method_source in all_method_sources_for_type:
                lists_for_this_method_across_queries: List[List[Dict[str, Any]]] = []
                for query_text in all_queries_to_process: # Iterate in the original query order
                    if query_text in queries_data and method_source in queries_data[query_text]:
                        lists_for_this_method_across_queries.append(queries_data[query_text][method_source])
                
                if lists_for_this_method_across_queries:
                    # Determine rrf_k for this specific method/type combination if different configs exist per method
                    # For now, assume rrf_k is from the top-level type config.
                    rrf_k_for_inter_query = 60 # Default
                    if current_type_config and hasattr(current_type_config, 'rrf_k'):
                        rrf_k_for_inter_query = current_type_config.rrf_k
                    
                    logger.debug(f"  Applying Inter-Query RRF for Type: {result_type}, Method: {method_source} across {len(lists_for_this_method_across_queries)} query lists.")
                    mqr_enhanced_list = self._apply_inter_query_rrf(
                        query_results_for_method=lists_for_this_method_across_queries,
                        rrf_k=rrf_k_for_inter_query,
                        method_source_tag=method_source,
                        result_type_tag=result_type
                    )
                    mqr_enhanced_lists_by_type_method[result_type][method_source] = mqr_enhanced_list
                    logger.debug(f"    MQR-enhanced list for Type: {result_type}, Method: {method_source} contains {len(mqr_enhanced_list)} items.")
                else:
                    logger.debug(f"  No query results found for Type: {result_type}, Method: {method_source} to apply Inter-Query RRF.")
                    mqr_enhanced_lists_by_type_method[result_type][method_source] = []


        inter_query_rrf_duration = (time.perf_counter() - inter_query_rrf_processing_start_time) * 1000
        logger.info(f"GRAPHFORRAG.search: Inter-Query RRF processing completed in {inter_query_rrf_duration:.2f} ms.")
        logger.debug(f"GRAPHFORRAG.search: MQR-enhanced lists structure summary (Type -> Method -> Count):")
        for res_type, methods_data in mqr_enhanced_lists_by_type_method.items():
            for method_src, res_list in methods_data.items():
                logger.debug(f"  - {res_type} | Method: {method_src} | MQR-Enhanced Count: {len(res_list)}")
        # --- Start of modification (Step 3.1 - Intra-Type RRF) ---
        # This part will take mqr_enhanced_lists_by_type_method and process it further.
        # logger.warning("GRAPHFORRAG.search: Intra-type RRF and final blending steps not yet implemented. Returning empty results for now.") # Old placeholder
        # final_results_list: List[SearchResultItem] = [] # Old placeholder
        
        all_fully_ranked_results_by_type: Dict[str, List[SearchResultItem]] = defaultdict(list)
        intra_type_rrf_processing_start_time = time.perf_counter()
        logger.info("GRAPHFORRAG.search: Starting Intra-Type RRF processing...")

        for result_type, methods_data in mqr_enhanced_lists_by_type_method.items():
            logger.debug(f"  Processing Intra-Type RRF for: {result_type}")
            
            # Prepare lists for SearchManager._apply_rrf
            # It expects List[List[Dict[str, Any]]]
            # The inner lists are the MQR-enhanced results for each method of this result_type.
            # The items in these lists already have "inter_query_rrf_score".
            # _apply_rrf will use "inter_query_rrf_score" as the "original_score" for its RRF calculation.
            
            lists_for_intra_type_rrf: List[List[Dict[str, Any]]] = []
            for method_source, mqr_enhanced_list in methods_data.items():
                if mqr_enhanced_list:
                    # _apply_rrf expects items to have a 'score' field for its internal ranking.
                    # We need to ensure our 'inter_query_rrf_score' is presented as 'score'.
                    # And we also need to carry forward the method_source from this MQR-enhanced list.
                    # The mqr_enhanced_list items are dicts like:
                    # {'uuid': ..., 'name': ..., 'score': <original_db_score>, 'method_source': <original_method>, 'inter_query_rrf_score': ...}
                    
                    # We'll rename 'inter_query_rrf_score' to 'score' for _apply_rrf,
                    # and 'method_source' will be the source of this MQR-enhanced list (e.g. "keyword_mqr_enhanced")
                    
                    current_method_input_for_final_rrf: List[Dict[str, Any]] = []
                    for item in mqr_enhanced_list:
                        item_copy = item.copy()
                        item_copy["score"] = item_copy.pop("inter_query_rrf_score", 0.0) # Use inter_query_rrf_score as input score
                        # The 'method_source' in item_copy is from the *original* fetch (e.g. "keyword", "semantic").
                        # This is fine, _apply_rrf will use this to group if needed (though less relevant now as lists are already method-specific)
                        # or store it in `contributing_methods` metadata by _apply_rrf.
                        # For clarity, the method source for _apply_rrf's input list is the MQR-enhanced method.
                        item_copy["method_source_for_intra_type_rrf"] = method_source # e.g. "keyword", "semantic_name"
                        current_method_input_for_final_rrf.append(item_copy)
                    lists_for_intra_type_rrf.append(current_method_input_for_final_rrf)
            
            if not lists_for_intra_type_rrf:
                logger.debug(f"    No MQR-enhanced lists to process for Intra-Type RRF for {result_type}. Skipping.")
                all_fully_ranked_results_by_type[result_type] = []
                continue

            # Determine RRF config for this result_type
            type_specific_config_obj: Optional[Any] = None
            type_specific_reranker_method: Optional[Any] = None # e.g., ChunkRerankerMethod.RRF
            type_specific_limit = 10 # Default final limit per type
            type_specific_rrf_k = 60 # Default RRF K

            if result_type == "Chunk" and config.chunk_config:
                type_specific_config_obj = config.chunk_config
                type_specific_reranker_method = config.chunk_config.reranker
                type_specific_limit = config.chunk_config.limit
                type_specific_rrf_k = config.chunk_config.rrf_k
            elif result_type == "Entity" and config.entity_config:
                type_specific_config_obj = config.entity_config
                type_specific_reranker_method = config.entity_config.reranker
                type_specific_limit = config.entity_config.limit
                type_specific_rrf_k = config.entity_config.rrf_k
            elif result_type == "Relationship" and config.relationship_config:
                type_specific_config_obj = config.relationship_config
                type_specific_reranker_method = config.relationship_config.reranker
                type_specific_limit = config.relationship_config.limit
                type_specific_rrf_k = config.relationship_config.rrf_k
            elif result_type == "Source" and config.source_config:
                type_specific_config_obj = config.source_config
                type_specific_reranker_method = config.source_config.reranker
                type_specific_limit = config.source_config.limit
                type_specific_rrf_k = config.source_config.rrf_k
            elif result_type == "Product" and config.product_config:
                type_specific_config_obj = config.product_config
                type_specific_reranker_method = config.product_config.reranker
                type_specific_limit = config.product_config.limit
                type_specific_rrf_k = config.product_config.rrf_k
            elif result_type == "Mention" and config.mention_config:
                type_specific_config_obj = config.mention_config
                type_specific_reranker_method = config.mention_config.reranker
                type_specific_limit = config.mention_config.limit
                type_specific_rrf_k = config.mention_config.rrf_k
            
            ranked_items_for_type: List[SearchResultItem] = []
            if type_specific_reranker_method == "reciprocal_rank_fusion" and lists_for_intra_type_rrf: # Check actual enum value string
                logger.debug(f"    Applying Intra-Type RRF for {result_type} using {len(lists_for_intra_type_rrf)} MQR-enhanced method lists.")
                ranked_items_for_type = self.search_manager._apply_rrf( # Call SearchManager's _apply_rrf
                    lists_for_intra_type_rrf, 
                    type_specific_rrf_k, 
                    type_specific_limit, # This limit is per type
                    result_type
                )
            elif lists_for_intra_type_rrf: # If RRF not configured, or only one list, do simple sort of the first list
                logger.debug(f"    Applying simple sort for {result_type} (RRF not configured or single MQR-enhanced list).")
                # Flatten all items from lists_for_intra_type_rrf, as they are already MQR-enhanced.
                # Then sort them by their 'score' (which is the inter_query_rrf_score).
                flat_list_to_sort: List[Dict[str, Any]] = []
                for mqr_method_list in lists_for_intra_type_rrf:
                    flat_list_to_sort.extend(mqr_method_list)
                
                # Deduplicate by UUID, keeping the one with the highest 'score' (inter_query_rrf_score)
                deduped_for_simple_sort: Dict[str, Dict[str, Any]] = {}
                for item in flat_list_to_sort:
                    uid = item.get("uuid")
                    if uid:
                        if uid not in deduped_for_simple_sort or item.get("score", 0.0) > deduped_for_simple_sort[uid].get("score", 0.0):
                            deduped_for_simple_sort[uid] = item
                
                sorted_items_for_type = sorted(deduped_for_simple_sort.values(), key=lambda x: x.get('score', 0.0), reverse=True)
                
                # Construct SearchResultItem from these sorted items
                # Note: The `_apply_rrf` method handles SearchResultItem construction internally.
                # Here, for the non-RRF path of this stage, we need to do it.
                for data in sorted_items_for_type[:type_specific_limit]:
                    # data here is a dict like {'uuid': ..., 'name': ..., 'score': <inter_query_rrf_score>, 'method_source': <original_method_source>}
                    item_metadata = {"inter_query_rrf_score": data.get("score"), 
                                     "original_method_source_before_mqr_enhancement": data.get("method_source")}
                    
                    # Populate type-specific fields
                    pydantic_item_data = {"uuid": data["uuid"], "name": data.get("name"), "score": data.get("score",0.0), "result_type": result_type, "metadata": item_metadata}
                    if result_type == "Chunk": pydantic_item_data["content"] = data.get("content"); item_metadata.update({"source_description": data.get("source_description"), "chunk_number": data.get("chunk_number")})
                    elif result_type == "Entity": pydantic_item_data["label"] = data.get("label")
                    elif result_type == "Relationship": pydantic_item_data["fact_sentence"] = data.get("fact_sentence"); item_metadata.update({"source_entity_uuid": data.get("source_entity_uuid"), "target_entity_uuid": data.get("target_entity_uuid")})
                    elif result_type == "Source": pydantic_item_data["content"] = data.get("content")
                    elif result_type == "Product": pydantic_item_data["content"] = data.get("content"); item_metadata.update({"sku": data.get("sku"), "price": data.get("price")})
                    elif result_type == "Mention": 
                        pydantic_item_data["fact_sentence"] = data.get("fact_sentence")
                        item_metadata.update({"source_node_uuid": data.get("source_node_uuid"), "target_node_uuid": data.get("target_node_uuid")})
                        target_labels = data.get("target_node_labels", [])
                        item_metadata["target_node_type"] = "Product" if "Product" in target_labels else ("Entity" if "Entity" in target_labels else "Unknown")
                    
                    ranked_items_for_type.append(SearchResultItem(**pydantic_item_data))
            
            all_fully_ranked_results_by_type[result_type] = ranked_items_for_type
            logger.debug(f"    Intra-Type RRF/Sort for {result_type} produced {len(ranked_items_for_type)} items.")

        intra_type_rrf_duration = (time.perf_counter() - intra_type_rrf_processing_start_time) * 1000
        logger.info(f"GRAPHFORRAG.search: Intra-Type RRF processing completed in {intra_type_rrf_duration:.2f} ms.")
        logger.debug("GRAPHFORRAG.search: Intra-Type RRF results (Type -> Count):")
        for res_type, res_list in all_fully_ranked_results_by_type.items():
            logger.debug(f"  - {res_type} | Count: {len(res_list)}")
        # --- Start of new code (Normalization Step based on Strategy 1) ---
        normalization_start_time = time.perf_counter()
        logger.info("GRAPHFORRAG.search: Normalizing scores for each result type...")

        # We need to know how many MQR-enhanced method lists contributed to the intra-type RRF for each result type.
        # This information was available when we prepared `lists_for_intra_type_rrf`.
        # Let's re-construct that count or ensure it was stored.
        # For simplicity in this step, we can re-derive N_methods by checking `mqr_enhanced_lists_by_type_method`

        for result_type, items_for_this_type in all_fully_ranked_results_by_type.items():
            if not items_for_this_type: # Skip if no items for this type after intra-type RRF
                logger.debug(f"  No items to normalize for type: {result_type}")
                continue

            # Determine N_methods_contributed_to_intra_type_rrf for this result_type
            # These are the MQR-enhanced lists that were non-empty and fed into the intra-type RRF
            n_methods_contributed = 0
            if result_type in mqr_enhanced_lists_by_type_method:
                for method_list in mqr_enhanced_lists_by_type_method[result_type].values():
                    if method_list: # If the MQR-enhanced list for this method was not empty
                        n_methods_contributed += 1
            
            if n_methods_contributed == 0:
                logger.warning(f"  Normalization: N_methods_contributed is 0 for type {result_type}, though items exist. Skipping normalization for this type.")
                # Scores will remain unnormalized for this type if this unlikely case happens.
                for item in items_for_this_type: # Still ensure metadata field exists
                    if 'unnormalized_score' not in item.metadata: # Store only if not already (e.g. from a previous partial run)
                         item.metadata['unnormalized_score'] = item.score
                    item.metadata['normalization_applied'] = False
                continue

            # Get k_intra_type (rrf_k used for the intra-type RRF for this result_type)
            k_intra_type = 60 # Default
            if result_type == "Chunk" and config.chunk_config: k_intra_type = config.chunk_config.rrf_k
            elif result_type == "Entity" and config.entity_config: k_intra_type = config.entity_config.rrf_k
            elif result_type == "Relationship" and config.relationship_config: k_intra_type = config.relationship_config.rrf_k
            elif result_type == "Source" and config.source_config: k_intra_type = config.source_config.rrf_k
            elif result_type == "Product" and config.product_config: k_intra_type = config.product_config.rrf_k
            elif result_type == "Mention" and config.mention_config: k_intra_type = config.mention_config.rrf_k
            
            max_possible_score_for_type = n_methods_contributed * (1.0 / (k_intra_type + 1.0)) # Ensure float division

            logger.debug(f"  Normalizing type '{result_type}': N_methods_contributed={n_methods_contributed}, k_intra_type={k_intra_type}, max_possible_score={max_possible_score_for_type:.4f}")

            if max_possible_score_for_type > 0:
                for item in items_for_this_type:
                    unnormalized_score = item.score
                    item.metadata['unnormalized_score'] = unnormalized_score
                    item.metadata['normalization_N_methods'] = n_methods_contributed
                    item.metadata['normalization_max_score'] = max_possible_score_for_type
                    
                    normalized_score = unnormalized_score / max_possible_score_for_type
                    item.score = min(normalized_score, 1.0) # Clamp to 1.0, scores shouldn't exceed this.
                    item.metadata['normalization_applied'] = True
                    logger.debug(f"    UUID: {item.uuid}, Orig_RRF_Score: {unnormalized_score:.4f}, Norm_Score: {item.score:.4f}")
            else:
                logger.warning(f"  Max possible score for type {result_type} is 0 or less. Skipping normalization for its items.")
                for item in items_for_this_type: # Still ensure metadata field exists
                    if 'unnormalized_score' not in item.metadata:
                        item.metadata['unnormalized_score'] = item.score
                    item.metadata['normalization_applied'] = False


        normalization_duration = (time.perf_counter() - normalization_start_time) * 1000
        logger.info(f"GRAPHFORRAG.search: Score normalization completed in {normalization_duration:.2f} ms.")
        # --- End of new code (Normalization Step) ---

        # --- Step 3.2: Final Aggregation, Min Results, Overall Limit ---
        # This part will use `all_fully_ranked_results_by_type` where item.score is now normalized
        final_results_aggregation_start_time = time.perf_counter()
        logger.info("GRAPHFORRAG.search: Starting final aggregation and limiting of results...")

        # Consolidate all SearchResultItems into one list first for easier processing
        all_processed_items: List[SearchResultItem] = []
        for type_name, items_for_type in all_fully_ranked_results_by_type.items():
            all_processed_items.extend(items_for_type)

        # Deduplicate by UUID across all types, keeping the item with the highest score.
        # This handles cases where, theoretically, an item might appear in multiple type-specific lists
        # (e.g., a node could be both an Entity and somehow returned by another search type if logic allowed).
        # The scores are now the final RRF scores from the two-stage process.
        deduplicated_overall_map: Dict[str, SearchResultItem] = {}
        for item in all_processed_items:
            if item.uuid not in deduplicated_overall_map or item.score > deduplicated_overall_map[item.uuid].score:
                deduplicated_overall_map[item.uuid] = item
        
        # Sort all unique items by their final RRF score
        globally_sorted_unique_items = sorted(deduplicated_overall_map.values(), key=lambda x: x.score, reverse=True)
        logger.debug(f"  Globally sorted unique items before min_results: {len(globally_sorted_unique_items)}")

        final_results_list: List[SearchResultItem] = []
        added_uuids_for_final_list: set[str] = set()

        # 1. Guarantee min_results for each type
        # Rebuild result_type_configs to access min_results
        # (This was defined in the original version of the search method)
        current_result_type_configs = []
        if config.chunk_config and config.chunk_config.min_results > 0:
            current_result_type_configs.append({"type": "Chunk", "min": config.chunk_config.min_results})
        if config.entity_config and config.entity_config.min_results > 0:
            current_result_type_configs.append({"type": "Entity", "min": config.entity_config.min_results})
        if config.relationship_config and config.relationship_config.min_results > 0:
            current_result_type_configs.append({"type": "Relationship", "min": config.relationship_config.min_results})
        if config.source_config and config.source_config.min_results > 0:
            current_result_type_configs.append({"type": "Source", "min": config.source_config.min_results})
        if config.product_config and config.product_config.min_results > 0: 
            current_result_type_configs.append({"type": "Product", "min": config.product_config.min_results})
        if config.mention_config and config.mention_config.min_results > 0: 
            current_result_type_configs.append({"type": "Mention", "min": config.mention_config.min_results})

        logger.debug(f"  Applying min_results logic. Type configs for min_results: {current_result_type_configs}")
        for type_info in current_result_type_configs:
            current_type_str = type_info["type"]
            min_to_add = type_info["min"]
            count_for_type_added = 0
            
            # Iterate through the globally_sorted_unique_items to pick for this type
            for item in globally_sorted_unique_items:
                if count_for_type_added >= min_to_add:
                    break # Met minimum for this type
                if item.result_type == current_type_str and item.uuid not in added_uuids_for_final_list:
                    final_results_list.append(item)
                    added_uuids_for_final_list.add(item.uuid)
                    count_for_type_added += 1
            logger.debug(f"    Guaranteed {count_for_type_added}/{min_to_add} for type '{current_type_str}'. Total in final_results_list: {len(final_results_list)}")

        # 2. Fill up to overall_results_limit from remaining globally sorted items
        overall_limit = config.overall_results_limit if config.overall_results_limit is not None else float('inf')
        
        if len(final_results_list) < overall_limit:
            logger.debug(f"  Attempting to fill up to overall_results_limit ({overall_limit}). Current count: {len(final_results_list)}")
            for item in globally_sorted_unique_items:
                if len(final_results_list) >= overall_limit:
                    break
                if item.uuid not in added_uuids_for_final_list:
                    final_results_list.append(item)
                    added_uuids_for_final_list.add(item.uuid)
            logger.debug(f"    After fill attempt, total in final_results_list: {len(final_results_list)}")

        # 3. Final sort of the collected list (items are already SearchResultItem with final RRF scores)
        final_results_list.sort(key=lambda x: x.score, reverse=True)
        
        # 4. Apply overall_results_limit strictly if specified
        if config.overall_results_limit is not None and len(final_results_list) > config.overall_results_limit:
            logger.info(f"  Applying final overall_results_limit ({config.overall_results_limit}). Truncating from {len(final_results_list)}.")
            final_results_list = final_results_list[:config.overall_results_limit]
        
        final_aggregation_duration = (time.perf_counter() - final_results_aggregation_start_time) * 1000
        logger.info(f"GRAPHFORRAG.search: Final aggregation, min_results, and limiting completed in {final_aggregation_duration:.2f} ms.")
        snippet_generation_start_time = time.perf_counter()
        snippet_parts: List[str] = []
        seen_facts_for_snippet: set[str] = set()

        if final_results_list:
            # snippet_parts.append(f"Here is some context retrieved from the knowledge graph based on your query: '{_original_user_query_for_report}'.\n")
            pass
            # Group results by type for structured output
            results_by_type: Dict[str, List[SearchResultItem]] = defaultdict(list)
            for item in final_results_list:
                results_by_type[item.result_type].append(item)

            # 1. Chunks
            if results_by_type["Chunk"]:
                snippet_parts.append("\nRelevant text passages (from Chunks):")
                for item in results_by_type["Chunk"]:
                    if item.content:
                        content_full = item.content # Use full content              
                        chunk_details = [f"- Chunk Content: \"{content_full}\""]
                        # Display all non-technical metadata for Chunks
                        for key, value in item.metadata.items():
                            # More targeted exclusion list for snippet
                            if key.lower() not in ['uuid', 'contributing_methods', 'unnormalized_score', 
                                                 'normalization_applied', 'normalization_n_methods', 
                                                 'normalization_max_score', 
                                                 'original_method_source_before_mqr_enhancement', 
                                                 'inter_query_rrf_score',
                                                 'name', 'content', 'source_description', 'chunk_number',
                                                 'entity_count', 'relationship_count', 'created_at', 'updated_at', 'processed_at']: # Added new exclusions
                                chunk_details.append(f"  - {key.replace('_', ' ').title()}: {value}")
                        snippet_parts.extend(chunk_details)
                        # --- End of modification ---
                snippet_parts.append("") # Add a blank line for spacing

            # 1.5. Sources (Added new section)
            if results_by_type["Source"]:
                snippet_parts.append("\nRelevant sources:")
                for item in results_by_type["Source"]:
                    if item.name: 
                        # --- Start of modification ---
                        source_details = [f"- Source Document: {item.name}"]
                        if item.content:
                            source_details.append(f"  - Summary/Content: \"{item.content}\"")
                        
                        # Display all non-technical metadata for Sources
                        for key, value in item.metadata.items():
                             if key.lower() not in ['uuid', 'contributing_methods', 'unnormalized_score', 
                                                  'normalization_applied', 'normalization_n_methods', 
                                                  'normalization_max_score', 
                                                  'original_method_source_before_mqr_enhancement', 
                                                  'inter_query_rrf_score',
                                                  'name', 'content',
                                                  'created_at', 'updated_at', 'processed_at']: # Added new exclusions
                                source_details.append(f"  - {key.replace('_', ' ').title()}: {value}")
                        snippet_parts.extend(source_details)
                snippet_parts.append("") # Add a blank line for spacing

            # 2. Entities and Products (with their connected facts)
            # Section for Entities
            entities_added_to_snippet = False
            if results_by_type["Entity"]:
                snippet_parts.append("\nKey entities and related information:")
                entities_added_to_snippet = True
                for item in results_by_type["Entity"]:
                    item_label_display = f" ({item.label})" if item.label else ""
                    snippet_parts.append(f"*   Entity: {item.name}{item_label_display}")
                    
                    if item.metadata:
                        entity_meta_added_subheader = False
                        for key, value in item.metadata.items():
                            if key.lower() not in ['uuid', 'name', 'label', 'contributing_methods', 'unnormalized_score', 'normalization_applied', 'normalization_n_methods', 'normalization_max_score', 'original_method_source_before_mqr_enhancement', 'inter_query_rrf_score', 'created_at', 'updated_at', 'processed_at'] and not key.endswith('_embedding'):
                                if not entity_meta_added_subheader:
                                    snippet_parts.append("    *   Additional Metadata:")
                                    entity_meta_added_subheader = True
                                snippet_parts.append(f"        - {key.replace('_', ' ').title()}: {value}")
                                
                    facts_for_this_item_added = False # Reset for each item
                    if item.connected_facts:
                        for fact_data in item.connected_facts:
                            if fact_data is None: continue
                            # --- Start of modification ---
                            fact_text_for_snippet = None
                            # Unified way to get fact_sentence for snippet from relationship_properties
                            rel_props = fact_data.get('relationship_properties')
                            if isinstance(rel_props, dict):
                                fact_text_for_snippet = rel_props.get('fact_sentence')
                            # --- End of modification ---

                            if fact_text_for_snippet and fact_text_for_snippet not in seen_facts_for_snippet:
                                snippet_parts.append(f"    *   Fact: {fact_text_for_snippet}")
                                seen_facts_for_snippet.add(fact_text_for_snippet)
                                facts_for_this_item_added = True
                    
                    # This logic is for the snippet, if no specific facts were added above for THIS entity item.
                    # And no other "Additional Metadata" was added.
                    if not facts_for_this_item_added and not (item.metadata and any(
                        k.lower() not in ['uuid', 'name', 'label', 'contributing_methods', 'unnormalized_score', 'normalization_applied', 'normalization_n_methods', 'normalization_max_score', 'original_method_source_before_mqr_enhancement', 'inter_query_rrf_score', 'created_at', 'updated_at', 'processed_at'] and not k.endswith('_embedding') 
                        for k in item.metadata.keys()
                    )):
                         snippet_parts.append(f"    *   (No additional connected facts or metadata found for this entity in the current search results)")
                if entities_added_to_snippet:
                    snippet_parts.append("")

            # Section for Products
            products_added_to_snippet = False
            if results_by_type["Product"]:
                snippet_parts.append("\nKey products and related information:")
                products_added_to_snippet = True
                for item in results_by_type["Product"]:
                    product_category_from_metadata = item.metadata.get('category', 'N/A') if item.metadata else 'N/A'
                    item_label_display = f" (Category: {product_category_from_metadata})"
                    snippet_parts.append(f"*   Product: {item.name}{item_label_display}")

                    if item.content: 
                        snippet_parts.append(f"    *   Description: \"{item.content}\"")
                    
                    if item.metadata:
                        product_meta_added_subheader = False
                        for key, value in item.metadata.items():
                            if key.lower() not in ['uuid', 'name', 'content', 'category', 'contributing_methods', 'unnormalized_score', 'normalization_applied', 'normalization_n_methods', 'normalization_max_score', 'original_method_source_before_mqr_enhancement', 'inter_query_rrf_score', 'created_at', 'updated_at', 'processed_at'] and not key.endswith('_embedding'):
                                if not product_meta_added_subheader:
                                    snippet_parts.append("    *   Additional Details/Metadata:")
                                    product_meta_added_subheader = True
                                snippet_parts.append(f"        - {key.replace('_', ' ').title()}: {value}")
                    
                    facts_for_this_item_added = False # Reset for each item
                    if item.connected_facts:
                        for fact_data in item.connected_facts:
                            if fact_data is None: continue
                            # --- Start of modification ---
                            fact_text_for_snippet = None
                            # Unified way to get fact_sentence for snippet from relationship_properties
                            rel_props = fact_data.get('relationship_properties')
                            if isinstance(rel_props, dict):
                                fact_text_for_snippet = rel_props.get('fact_sentence')
                            # --- End of modification ---

                            if fact_text_for_snippet and fact_text_for_snippet not in seen_facts_for_snippet:
                                snippet_parts.append(f"    *   Fact: {fact_text_for_snippet}")
                                seen_facts_for_snippet.add(fact_text_for_snippet)
                                facts_for_this_item_added = True
                                
                    # This logic is for the snippet, if no specific facts were added for THIS product item.
                    # And no "Additional Details/Metadata" or "Description" was added.
                    if not facts_for_this_item_added and not (item.metadata and any(
                        k.lower() not in ['uuid', 'name', 'content', 'category', 'contributing_methods', 'unnormalized_score', 'normalization_applied', 'normalization_n_methods', 'normalization_max_score', 'original_method_source_before_mqr_enhancement', 'inter_query_rrf_score', 'created_at', 'updated_at', 'processed_at'] and not k.endswith('_embedding')
                        for k in item.metadata.keys()
                    )) and not item.content:
                         snippet_parts.append(f"    *   (No additional description, connected facts or metadata found for this product in the current search results)")
                if products_added_to_snippet:
                    snippet_parts.append("")
            # 3. Standalone Relationships and Mentions
            additional_facts_added = False
            temp_additional_facts_list: List[str] = [] # Store potential facts here first
            
            for item_type in ["Relationship", "Mention"]: # Iterate through Relationship then Mention items
                for item in results_by_type[item_type]:
                    # These items have a direct .fact_sentence attribute
                    if item.fact_sentence and item.fact_sentence not in seen_facts_for_snippet:
                        temp_additional_facts_list.append(f"- Fact: {item.fact_sentence}")
                        seen_facts_for_snippet.add(item.fact_sentence) # Add to seen to avoid duplicates from here too
            
            if temp_additional_facts_list: # Only add headline and facts if any were found
                snippet_parts.append("\nAdditional relevant facts (from direct Relationships/Mentions):")
                snippet_parts.extend(temp_additional_facts_list)
                additional_facts_added = True # Set flag as we added something
            
            if additional_facts_added:
                snippet_parts.append("")
                
        # --- NEW: Add LLM-generated Cypher query and its results to the snippet ---
        if generated_cypher_query and llm_cypher_execution_results: # Check if query was generated AND executed AND returned results
            snippet_parts.append("\n--- Results from LLM-Generated Cypher Query ---")
            snippet_parts.append(f"Executed Cypher Query:\n{generated_cypher_query.strip()}")
            if llm_cypher_execution_results:
                snippet_parts.append("\nQuery Results:")
                for i, res_item in enumerate(llm_cypher_execution_results):
                    if i < 5: # Limit to first 5 results for snippet brevity
                        # Convert dict to a more readable string format for the snippet
                        try:
                            res_item_str = json.dumps(res_item, indent=2, default=str) # Use default=str for non-serializable types
                            snippet_parts.append(f"  - Result {i+1}: {res_item_str}")
                        except TypeError: # Fallback if json.dumps fails with default=str
                            snippet_parts.append(f"  - Result {i+1}: {str(res_item)} (Note: complex data types)")
                    elif i == 5:
                        snippet_parts.append(f"  ... (and {len(llm_cypher_execution_results) - 5} more items from Cypher query)")
                        break
            else: # Query was executed but returned no results
                snippet_parts.append("Query Results: No data returned from this query.")
            snippet_parts.append("") # Add a blank line for spacing
        elif generated_cypher_query and not llm_cypher_execution_results and config.cypher_search_config and config.cypher_search_config.enabled:
            # Case where query was generated but execution yielded empty list (e.g., query ran fine but found nothing, or error during exec returned [])
            snippet_parts.append("\n--- LLM-Generated Cypher Query ---")
            snippet_parts.append(f"Executed Cypher Query:\n{generated_cypher_query.strip()}")
            snippet_parts.append("Query Results: No data returned or execution failed.")
            snippet_parts.append("")
        elif config.cypher_search_config and config.cypher_search_config.enabled and not generated_cypher_query:
            # Case where Cypher search was enabled but LLM failed to generate a query
             snippet_parts.append("\n--- LLM-Generated Cypher Query ---")
             snippet_parts.append("Note: Cypher query generation was enabled, but no query was successfully generated by the LLM.")
             snippet_parts.append("")
             
        generated_context_snippet = "\n".join(snippet_parts) if snippet_parts else None
        snippet_generation_duration = (time.perf_counter() - snippet_generation_start_time) * 1000
        logger.info(f"GRAPHFORRAG.search: Context snippet generation took {snippet_generation_duration:.2f} ms.")
        # --- Step 5: Collect and Format Source Data References ---
        source_data_collection_start_time = time.perf_counter()
        referenced_chunk_uuids: set[str] = set()
        referenced_product_uuids: set[str] = set()
        referenced_source_uuids: set[str] = set() # To store UUIDs of sources

        # Helper to add source UUID from a chunk or product UUID
        async def get_source_uuid_for_item(item_uuid: str, item_label: str) -> Optional[str]:
            # Product and Chunk nodes have a BELONGS_TO_SOURCE relationship
            # Source nodes are identified directly.
            if item_label == "Source": return item_uuid

            query = f"""
            MATCH (item:{item_label} {{uuid: $item_uuid}})-[:BELONGS_TO_SOURCE]->(s:Source)
            RETURN s.uuid AS source_uuid
            UNION
            MATCH (item:Chunk {{uuid: $item_uuid}})-[:BELONGS_TO_SOURCE]->(s:Source)
            RETURN s.uuid AS source_uuid
            """ # Ensures we cover chunks linked by entities/rels if item_label is not Chunk
            if item_label not in ["Chunk", "Product"]: # Fallback for other types if needed, though less direct
                # This might be needed if a relationship's source_chunk_uuid points to something other than a Chunk
                # but for now, assume BELONGS_TO_SOURCE is the primary way.
                 logger.debug(f"Attempting to find source for non-Chunk/Product item: {item_uuid} with label {item_label}")


            db_results, _, _ = await self.driver.execute_query(query, item_uuid=item_uuid, database_=self.database)
            if db_results and db_results[0] and db_results[0]["source_uuid"]:
                return db_results[0]["source_uuid"]
            logger.warning(f"Could not find Source UUID for {item_label} item {item_uuid}")
            return None

        for item in final_results_list:
            if item.result_type == "Chunk":
                referenced_chunk_uuids.add(item.uuid)
                source_uuid_for_chunk = await get_source_uuid_for_item(item.uuid, "Chunk")
                if source_uuid_for_chunk: referenced_source_uuids.add(source_uuid_for_chunk)

            elif item.result_type == "Product":
                referenced_product_uuids.add(item.uuid)
                source_uuid_for_product = await get_source_uuid_for_item(item.uuid, "Product")
                if source_uuid_for_product: referenced_source_uuids.add(source_uuid_for_product)
            
            elif item.result_type == "Source": # Direct source result
                referenced_source_uuids.add(item.uuid)

            elif item.result_type == "Entity":
                if item.connected_facts:
                    for fact in item.connected_facts:
                        if fact.get("type") == "MENTIONED_IN_CHUNK" and fact.get("mentioning_chunk_uuid"):
                            chunk_uuid = fact["mentioning_chunk_uuid"]
                            referenced_chunk_uuids.add(chunk_uuid)
                            source_uuid_for_chunk = await get_source_uuid_for_item(chunk_uuid, "Chunk")
                            if source_uuid_for_chunk: referenced_source_uuids.add(source_uuid_for_chunk)
            
            elif item.result_type == "Relationship": # RELATES_TO
                # metadata might contain source_chunk_uuid
                source_chunk_uuid_from_rel = item.metadata.get("source_chunk_uuid") # source_chunk_uuid on RELATES_TO
                if not source_chunk_uuid_from_rel and item.source_node_uuid: # Fallback if source_node_uuid is chunk-like for some reason
                    # This is less likely for RELATES_TO, usually source_node_uuid is an Entity/Product
                    pass
                if source_chunk_uuid_from_rel:
                    referenced_chunk_uuids.add(source_chunk_uuid_from_rel)
                    source_uuid_for_chunk = await get_source_uuid_for_item(source_chunk_uuid_from_rel, "Chunk")
                    if source_uuid_for_chunk: referenced_source_uuids.add(source_uuid_for_chunk)


            elif item.result_type == "Mention": # MENTIONS relationship
                if item.source_node_uuid: # This is the Chunk UUID for MENTIONS
                    referenced_chunk_uuids.add(item.source_node_uuid)
                    source_uuid_for_chunk = await get_source_uuid_for_item(item.source_node_uuid, "Chunk")
                    if source_uuid_for_chunk: referenced_source_uuids.add(source_uuid_for_chunk)
        
        source_data_references_list: List[SearchResultItem] = []
        
        # Fetch and format Source nodes
        if referenced_source_uuids:
            # Query to fetch full Source nodes
            source_nodes_query = "MATCH (s:Source) WHERE s.uuid IN $uuids RETURN properties(s) as props, s.uuid as uuid, s.name as name, s.content as content"
            source_db_results, _, _ = await self.driver.execute_query(source_nodes_query, uuids=list(referenced_source_uuids), database_=self.database)
            for record in source_db_results:
                props = record["props"]
                source_data_references_list.append(SearchResultItem(
                    uuid=record["uuid"], name=record["name"], content=record["content"],
                    score=1.0, result_type="Source", metadata=props
                ))

        # Fetch and format Chunk nodes
        if referenced_chunk_uuids:
            chunk_nodes_query = "MATCH (c:Chunk) WHERE c.uuid IN $uuids RETURN properties(c) as props, c.uuid as uuid, c.name as name, c.content as content"
            chunk_db_results, _, _ = await self.driver.execute_query(chunk_nodes_query, uuids=list(referenced_chunk_uuids), database_=self.database)
            for record in chunk_db_results:
                props = record["props"]
                source_data_references_list.append(SearchResultItem(
                    uuid=record["uuid"], name=record["name"], content=record["content"],
                    score=1.0, result_type="Chunk", metadata=props
                ))

        # Fetch and format Product nodes
        if referenced_product_uuids:
            product_nodes_query = "MATCH (p:Product) WHERE p.uuid IN $uuids RETURN properties(p) as props, p.uuid as uuid, p.name as name, p.content as content" # content is description
            product_db_results, _, _ = await self.driver.execute_query(product_nodes_query, uuids=list(referenced_product_uuids), database_=self.database)
            for record in product_db_results:
                props = record["props"]
                source_data_references_list.append(SearchResultItem(
                    uuid=record["uuid"], name=record["name"], content=record["content"], # Product's text description
                    score=1.0, result_type="Product", metadata=props # All other props in metadata
                ))
        
        # Deduplicate source_data_references_list just in case (though UUID sets should handle most of it)
        final_source_data_references_map: Dict[str, SearchResultItem] = {}
        for s_item in source_data_references_list:
            if s_item.uuid not in final_source_data_references_map:
                 final_source_data_references_map[s_item.uuid] = s_item
        
        final_source_data_references = list(final_source_data_references_map.values())

        # Generate source_data_snippet
        source_snippet_parts: List[str] = []
        if final_source_data_references:
            source_snippet_parts.append("Detailed Source Data References:\n")
            
            sources_in_snippet = [item for item in final_source_data_references if item.result_type == "Source"]
            chunks_in_snippet = [item for item in final_source_data_references if item.result_type == "Chunk"]
            products_in_snippet = [item for item in final_source_data_references if item.result_type == "Product"]

            if sources_in_snippet:
                source_snippet_parts.append("\nReferenced Sources:")
                for item in sorted(list(sources_in_snippet), key=lambda x: x.name or ""):
                    source_details = [f"- Source Document: {item.name}"]
                    if item.content: source_details.append(f"  - Summary/Content: \"{item.content}\"")
                    for key, value in item.metadata.items():
                        if key.lower() not in ['uuid', 'name', 'content', 'created_at', 'updated_at', 'processed_at'] and not key.endswith('_embedding'):
                            source_details.append(f"  - {key.replace('_', ' ').title()}: {value}")
                    source_snippet_parts.extend(source_details)
                source_snippet_parts.append("")

            if chunks_in_snippet:
                source_snippet_parts.append("\nReferenced Chunks:")
                for item in sorted(list(chunks_in_snippet), key=lambda x: (x.metadata.get('source_description', ""), x.metadata.get('chunk_number', 0))):
                    chunk_details = [f"- Chunk: {item.name or item.uuid}"]
                    if item.content: chunk_details.append(f"  - Content: \"{item.content}\"")
                    for key, value in item.metadata.items():
                         if key.lower() not in ['uuid', 'name', 'content', 'created_at', 'updated_at', 'processed_at', 'entity_count', 'relationship_count'] and not key.endswith('_embedding'):
                            chunk_details.append(f"  - {key.replace('_', ' ').title()}: {value}")
                    source_snippet_parts.extend(chunk_details)
                source_snippet_parts.append("")
            
            if products_in_snippet:
                source_snippet_parts.append("\nReferenced Products:")
                for item in sorted(list(products_in_snippet), key=lambda x: x.name or ""):
                    prod_details = [f"- Product: {item.name}"]
                    if item.content: prod_details.append(f"  - Description: \"{item.content}\"") # Product.content is textual description
                    for key, value in item.metadata.items():
                        if key.lower() not in ['uuid', 'name', 'content', 'created_at', 'updated_at', 'processed_at'] and not key.endswith('_embedding'):
                            prod_details.append(f"  - {key.replace('_', ' ').title()}: {value}")
                    source_snippet_parts.extend(prod_details)
                source_snippet_parts.append("")

        generated_source_data_snippet = "\n".join(source_snippet_parts) if source_snippet_parts else None
        source_data_collection_duration = (time.perf_counter() - source_data_collection_start_time) * 1000
        logger.info(f"GRAPHFORRAG.search: Source data reference collection & snippet generation took {source_data_collection_duration:.2f} ms. Found {len(final_source_data_references)} unique source items.")
        
        total_search_internal_duration = (time.perf_counter() - search_internal_total_start_time) * 1000
        logger.info(f"GRAPHFORRAG.search: Total internal execution time {total_search_internal_duration:.2f} ms. Found {len(final_results_list)} combined items.")

        return CombinedSearchResults(
            items=final_results_list, 
            query_text=_original_user_query_for_report, 
               context_snippet=generated_context_snippet,
            source_data_references=final_source_data_references, 
            source_data_snippet=generated_source_data_snippet,
            executed_llm_cypher_query=generated_cypher_query if (config.cypher_search_config and config.cypher_search_config.enabled and generated_cypher_query) else None,
            # Populate with empty list if enabled & query generated but no results, else None
            raw_llm_cypher_query_results=llm_cypher_execution_results if (config.cypher_search_config and config.cypher_search_config.enabled and generated_cypher_query) else None
        )
    
    
    def _apply_inter_query_rrf(
        self,
        query_results_for_method: List[List[Dict[str, Any]]],
        rrf_k: int,
        # We might want a specific limit for this stage, or derive it.
        # For now, let's assume we process all and limit later, or use a passed limit.
        # For simplicity in this step, let's not apply a limit here, the next stage will.
        # inter_query_limit: int, 
        method_source_tag: str,
        result_type_tag: str
    ) -> List[Dict[str, Any]]:
        """
        Applies Reciprocal Rank Fusion across multiple lists of results,
        where each list comes from a different query (original or MQR alternative)
        for the SAME search method and SAME result type.

        Returns a single list of items, ranked by their inter-query RRF score.
        Each item dictionary in the output will have an added 'inter_query_rrf_score'.
        """
        if not query_results_for_method or not any(query_results_for_method):
            logger.debug(f"_apply_inter_query_rrf ({result_type_tag} - {method_source_tag}): No results to process.")
            return []

        inter_query_rrf_scores: Dict[str, float] = defaultdict(float)
        # Store the primary data for each UUID encountered, preferring data from earlier query lists
        # or ones with higher original scores if necessary, though this is less critical here
        # as the main data (name, content) should be consistent for the same UUID.
        uuid_primary_data_store: Dict[str, Dict[str, Any]] = {}
        # Track which original query and rank led to an item for enrichment/logging
        uuid_contributions_across_queries: Dict[str, List[Dict[str, Any]]] = defaultdict(list)


        for query_idx, single_query_result_list in enumerate(query_results_for_method):
            if not single_query_result_list:
                continue
            for rank, item in enumerate(single_query_result_list):
                item_uuid = item.get("uuid")
                if not item_uuid:
                    continue
                
                rank_contribution = 1.0 / (rrf_k + rank + 1)
                inter_query_rrf_scores[item_uuid] += rank_contribution

                # Store data if not already stored, or from the first query encountered
                if item_uuid not in uuid_primary_data_store:
                    uuid_primary_data_store[item_uuid] = item.copy() # Store a copy

                uuid_contributions_across_queries[item_uuid].append({
                    "query_index": query_idx, # 0 for original, 1+ for alternatives
                    "original_rank_in_query_list": rank + 1,
                    "original_score_in_query_list": item.get("score", 0.0),
                    "rrf_part": rank_contribution
                })
        
        if not inter_query_rrf_scores:
            return []

        # Create a list of dictionaries, each containing the primary data and the new inter_query_rrf_score
        mqr_enhanced_list: List[Dict[str, Any]] = []
        for uuid_str, iq_rrf_score in inter_query_rrf_scores.items():
            if uuid_str in uuid_primary_data_store:
                item_data_copy = uuid_primary_data_store[uuid_str].copy() # Work with a copy
                item_data_copy["inter_query_rrf_score"] = iq_rrf_score
                # Optionally, add the detailed contributions to the item if needed for later stages
                # item_data_copy["inter_query_contributions"] = uuid_contributions_across_queries[uuid_str]
                mqr_enhanced_list.append(item_data_copy)
            else:
                # This case should ideally not happen if logic is correct
                logger.warning(f"_apply_inter_query_rrf: UUID '{uuid_str}' has RRF score but no primary data stored. Skipping.")

        # Sort by the new inter_query_rrf_score
        mqr_enhanced_list.sort(key=lambda x: x["inter_query_rrf_score"], reverse=True)
        
        logger.debug(f"_apply_inter_query_rrf ({result_type_tag} - {method_source_tag}): Produced MQR-enhanced list of {len(mqr_enhanced_list)} items.")
        # We are not applying a limit here; the next RRF stage or final blending will.
        return mqr_enhanced_list