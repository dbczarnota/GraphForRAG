# graphforrag_core/search_manager.py
import logging
import asyncio 
from typing import List, Dict, Any, Optional
from neo4j import AsyncDriver # type: ignore
from collections import defaultdict
import time 
import re 

from config import cypher_queries 
from .embedder_client import EmbedderClient
from .search_types import (
    ChunkSearchConfig, ChunkSearchMethod, ChunkRerankerMethod,
    EntitySearchConfig, EntitySearchMethod, EntityRerankerMethod,
    RelationshipSearchConfig, RelationshipSearchMethod, RelationshipRerankerMethod,
    SourceSearchConfig, SourceSearchMethod, SourceRerankerMethod, 
    ProductSearchConfig, ProductSearchMethod, ProductRerankerMethod,
    MentionSearchConfig, MentionSearchMethod, MentionRerankerMethod, # ADDED Mention... types
    SearchResultItem
)

logger = logging.getLogger("graph_for_rag.search_manager")

def construct_lucene_query(query: str) -> str:
    pattern = r'([+\-&|!(){}\[\]^"~*?:\\\/])'
    stripped_query = query.strip()
    if not stripped_query:
        return "" 
    return re.sub(pattern, r'\\\1', stripped_query)


class SearchManager:
    def __init__(self, driver: AsyncDriver, database_name: str, embedder_client: EmbedderClient):
        self.driver: AsyncDriver = driver
        self.database: str = database_name
        self.embedder: EmbedderClient = embedder_client
        logger.info(f"SearchManager initialized for database '{database_name}'.")

    async def _fetch_chunks_combined(
        self, 
        query_text: str, 
        config: ChunkSearchConfig, 
        query_embedding: Optional[List[float]]
    # ) -> List[Dict[str, Any]]: # Old
    ) -> Dict[str, List[Dict[str, Any]]]: # New return type
        # --- Start of modification ---
        # cypher_parts = [] # Old: Not needed for separate queries
        # params: Dict[str, Any] = {} # Old: Params will be per query
        # keyword_part_included = False # Old
        # semantic_part_included = False # Old
        results_by_method: Dict[str, List[Dict[str, Any]]] = {}


        if ChunkSearchMethod.KEYWORD in config.search_methods and query_text.strip():
            lucene_query_str = construct_lucene_query(query_text)
            if lucene_query_str:
                keyword_params = {
                    "keyword_query_string_chunk": lucene_query_str,
                    "keyword_limit_param_chunk": config.keyword_fetch_limit,
                    "index_name_keyword_chunk": "chunk_content_ft"
                }
                # cypher_parts.append(cypher_queries.CHUNK_SEARCH_KEYWORD_PART) # Old
                # keyword_part_included = True # Old
                try:
                    logger.debug(f"_fetch_chunks_combined (Keyword): Executing. Query:\n{cypher_queries.CHUNK_SEARCH_KEYWORD_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in keyword_params.items()} }")
                    fetch_start_time_kw = time.perf_counter()
                    keyword_db_results, _, _ = await self.driver.execute_query(
                        cypher_queries.CHUNK_SEARCH_KEYWORD_PART, keyword_params, database_=self.database
                    )
                    fetch_duration_kw = (time.perf_counter() - fetch_start_time_kw) * 1000
                    logger.debug(f"_fetch_chunks_combined (Keyword): DB query took {fetch_duration_kw:.2f} ms. Rows: {len(keyword_db_results)}")
                    results_by_method["keyword"] = [dict(record) for record in keyword_db_results]
                except Exception as e_kw:
                    logger.error(f"Error during _fetch_chunks_combined (Keyword): {e_kw}", exc_info=True)
                    results_by_method["keyword"] = [] # Ensure key exists even on error for consistency downstream if needed
            else:
                logger.debug("_fetch_chunks_combined (Keyword): Skipped due to empty Lucene query.")
                results_by_method["keyword"] = []


        if ChunkSearchMethod.SEMANTIC in config.search_methods and query_embedding:
            semantic_params = {
                "semantic_embedding_vector_param_chunk": query_embedding,
                "semantic_top_k_param_chunk": config.semantic_fetch_limit,
                "semantic_min_similarity_score_param_chunk": config.min_similarity_score,
                "index_name_semantic_chunk": "chunk_content_embedding_vector"
            }
            # cypher_parts.append(cypher_queries.CHUNK_SEARCH_SEMANTIC_PART) # Old
            # semantic_part_included = True # Old
            try:
                logger.debug(f"_fetch_chunks_combined (Semantic): Executing. Query:\n{cypher_queries.CHUNK_SEARCH_SEMANTIC_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in semantic_params.items()} }")
                fetch_start_time_sem = time.perf_counter()
                semantic_db_results, _, _ = await self.driver.execute_query(
                    cypher_queries.CHUNK_SEARCH_SEMANTIC_PART, semantic_params, database_=self.database
                )
                fetch_duration_sem = (time.perf_counter() - fetch_start_time_sem) * 1000
                logger.debug(f"_fetch_chunks_combined (Semantic): DB query took {fetch_duration_sem:.2f} ms. Rows: {len(semantic_db_results)}")
                results_by_method["semantic"] = [dict(record) for record in semantic_db_results]
            except Exception as e_sem:
                logger.error(f"Error during _fetch_chunks_combined (Semantic): {e_sem}", exc_info=True)
                results_by_method["semantic"] = []
        else:
            logger.debug("_fetch_chunks_combined (Semantic): Skipped (no embedding or not in config).")
            if ChunkSearchMethod.SEMANTIC in config.search_methods: # Add empty list if method was configured but skipped
                 results_by_method["semantic"] = []
        
        # if not cypher_parts: # Old
        #     logger.info("_fetch_chunks_combined: No search parts to execute.")
        #     return []

        # final_query = " UNION ALL ".join(cypher_parts) # Old
        
        # try: # Old
            # param_keys_for_log = {k: (type(v).__name__ if not isinstance(v, list) else f"list_len_{len(v)}") for k,v in params.items()}
            # logger.debug(f"_fetch_chunks_combined: Executing with {len(cypher_parts)} part(s) (K: {keyword_part_included}, S: {semantic_part_included}). Query:\n{final_query}\nParams (keys and types/lengths): {param_keys_for_log}")
            
            # fetch_start_time = time.perf_counter()
            # results, summary, _ = await self.driver.execute_query(final_query, params, database_=self.database)
            # fetch_duration = (time.perf_counter() - fetch_start_time) * 1000
            # num_rows_returned = len(results)
            # logger.debug(f"_fetch_chunks_combined: DB query took {fetch_duration:.2f} ms. Rows returned: {num_rows_returned}")
            
            # return [dict(record) for record in results] # Old
        # except Exception as e: # Old
            # logger.error(f"Error during _fetch_chunks_combined: {e}", exc_info=True)
            # return [] # Old
        
        logger.debug(f"_fetch_chunks_combined: Returning results by method: { {k: len(v) for k,v in results_by_method.items()} }")
        return results_by_method


    async def _fetch_entities_combined(
        self,
        query_text: str,
        config: EntitySearchConfig,
        query_embedding: Optional[List[float]]
    # ) -> List[Dict[str, Any]]: # Old
    ) -> Dict[str, List[Dict[str, Any]]]: # New return type
        # --- Start of modification ---
        results_by_method: Dict[str, List[Dict[str, Any]]] = {}

        if EntitySearchMethod.KEYWORD_NAME in config.search_methods and query_text.strip():
            lucene_query_str = construct_lucene_query(query_text)
            if lucene_query_str:
                keyword_params = {
                    "keyword_query_string_entity": lucene_query_str,
                    "keyword_limit_param_entity": config.keyword_fetch_limit,
                    "index_name_keyword_entity": "entity_name_ft"
                }
                try:
                    logger.debug(f"_fetch_entities_combined (KeywordName): Executing. Query:\n{cypher_queries.ENTITY_SEARCH_KEYWORD_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in keyword_params.items()} }")
                    fetch_start_time_kw = time.perf_counter()
                    keyword_db_results, _, _ = await self.driver.execute_query(
                        cypher_queries.ENTITY_SEARCH_KEYWORD_PART, keyword_params, database_=self.database
                    )
                    fetch_duration_kw = (time.perf_counter() - fetch_start_time_kw) * 1000
                    logger.debug(f"_fetch_entities_combined (KeywordName): DB query took {fetch_duration_kw:.2f} ms. Rows: {len(keyword_db_results)}")
                    # The key here should match the method_source in the Cypher query
                    results_by_method["keyword_name"] = [dict(record) for record in keyword_db_results]
                except Exception as e_kw:
                    logger.error(f"Error during _fetch_entities_combined (KeywordName): {e_kw}", exc_info=True)
                    results_by_method["keyword_name"] = []
            else:
                logger.debug("_fetch_entities_combined (KeywordName): Skipped due to empty Lucene query.")
                results_by_method["keyword_name"] = []

        if EntitySearchMethod.SEMANTIC_NAME in config.search_methods and query_embedding:
            semantic_name_params = {
                "semantic_embedding_entity_name": query_embedding,
                "semantic_limit_entity_name": config.semantic_name_fetch_limit,
                "semantic_min_score_entity_name": config.min_similarity_score_name,
                "index_name_semantic_entity_name": "entity_name_embedding_vector"
            }
            try:
                logger.debug(f"_fetch_entities_combined (SemanticName): Executing. Query:\n{cypher_queries.ENTITY_SEARCH_SEMANTIC_NAME_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in semantic_name_params.items()} }")
                fetch_start_time_sem_name = time.perf_counter()
                semantic_name_db_results, _, _ = await self.driver.execute_query(
                    cypher_queries.ENTITY_SEARCH_SEMANTIC_NAME_PART, semantic_name_params, database_=self.database
                )
                fetch_duration_sem_name = (time.perf_counter() - fetch_start_time_sem_name) * 1000
                logger.debug(f"_fetch_entities_combined (SemanticName): DB query took {fetch_duration_sem_name:.2f} ms. Rows: {len(semantic_name_db_results)}")
                results_by_method["semantic_name"] = [dict(record) for record in semantic_name_db_results]
            except Exception as e_sem_name:
                logger.error(f"Error during _fetch_entities_combined (SemanticName): {e_sem_name}", exc_info=True)
                results_by_method["semantic_name"] = []
        else:
            logger.debug("_fetch_entities_combined (SemanticName): Skipped (no embedding or not in config).")
            if EntitySearchMethod.SEMANTIC_NAME in config.search_methods:
                 results_by_method["semantic_name"] = []
            

        logger.debug(f"_fetch_entities_combined: Returning results by method: { {k: len(v) for k,v in results_by_method.items()} }")
        return results_by_method
    
    async def _fetch_relationships_combined(
        self,
        query_text: str,
        config: RelationshipSearchConfig,
        query_embedding: Optional[List[float]]
    # ) -> List[Dict[str, Any]]: # Old
    ) -> Dict[str, List[Dict[str, Any]]]: # New return type
        # --- Start of modification ---
        results_by_method: Dict[str, List[Dict[str, Any]]] = {}

        if RelationshipSearchMethod.KEYWORD_FACT in config.search_methods and query_text.strip():
            lucene_query_str = construct_lucene_query(query_text)
            if lucene_query_str:
                keyword_params = {
                    "keyword_query_string_rel": lucene_query_str,
                    "keyword_limit_param_rel": config.keyword_fetch_limit,
                    "index_name_keyword_rel": "relationship_fact_ft"
                }
                try:
                    logger.debug(f"_fetch_relationships_combined (KeywordFact): Executing. Query:\n{cypher_queries.RELATIONSHIP_SEARCH_KEYWORD_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in keyword_params.items()} }")
                    fetch_start_time_kw = time.perf_counter()
                    keyword_db_results, _, _ = await self.driver.execute_query(
                        cypher_queries.RELATIONSHIP_SEARCH_KEYWORD_PART, keyword_params, database_=self.database
                    )
                    fetch_duration_kw = (time.perf_counter() - fetch_start_time_kw) * 1000
                    logger.debug(f"_fetch_relationships_combined (KeywordFact): DB query took {fetch_duration_kw:.2f} ms. Rows: {len(keyword_db_results)}")
                    results_by_method["keyword_fact"] = [dict(record) for record in keyword_db_results]
                except Exception as e_kw:
                    logger.error(f"Error during _fetch_relationships_combined (KeywordFact): {e_kw}", exc_info=True)
                    results_by_method["keyword_fact"] = []
            else:
                logger.debug("_fetch_relationships_combined (KeywordFact): Skipped due to empty Lucene query.")
                results_by_method["keyword_fact"] = []

        if RelationshipSearchMethod.SEMANTIC_FACT in config.search_methods and query_embedding:
            semantic_params = {
                "semantic_embedding_rel_fact": query_embedding,
                "semantic_limit_rel_fact": config.semantic_fetch_limit,
                "semantic_min_score_rel_fact": config.min_similarity_score,
                "index_name_semantic_rel_fact": "relates_to_fact_embedding_vector"
            }
            try:
                logger.debug(f"_fetch_relationships_combined (SemanticFact): Executing. Query:\n{cypher_queries.RELATIONSHIP_SEARCH_SEMANTIC_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in semantic_params.items()} }")
                fetch_start_time_sem = time.perf_counter()
                semantic_db_results, _, _ = await self.driver.execute_query(
                    cypher_queries.RELATIONSHIP_SEARCH_SEMANTIC_PART, semantic_params, database_=self.database
                )
                fetch_duration_sem = (time.perf_counter() - fetch_start_time_sem) * 1000
                logger.debug(f"_fetch_relationships_combined (SemanticFact): DB query took {fetch_duration_sem:.2f} ms. Rows: {len(semantic_db_results)}")
                results_by_method["semantic_fact"] = [dict(record) for record in semantic_db_results]
            except Exception as e_sem:
                logger.error(f"Error during _fetch_relationships_combined (SemanticFact): {e_sem}", exc_info=True)
                results_by_method["semantic_fact"] = []
        else:
            logger.debug("_fetch_relationships_combined (SemanticFact): Skipped (no embedding or not in config).")
            if RelationshipSearchMethod.SEMANTIC_FACT in config.search_methods:
                 results_by_method["semantic_fact"] = []
            
        logger.debug(f"_fetch_relationships_combined: Returning results by method: { {k: len(v) for k,v in results_by_method.items()} }")
        return results_by_method

    async def _fetch_sources_combined(
        self,
        query_text: str,
        config: SourceSearchConfig,
        query_embedding: Optional[List[float]]
    # ) -> List[Dict[str, Any]]: # Old
    ) -> Dict[str, List[Dict[str, Any]]]: # New return type
        # --- Start of modification ---
        results_by_method: Dict[str, List[Dict[str, Any]]] = {}

        if SourceSearchMethod.KEYWORD_CONTENT in config.search_methods and query_text.strip():
            lucene_query_str = construct_lucene_query(query_text)
            if lucene_query_str:
                keyword_params = {
                    "keyword_query_string_source": lucene_query_str,
                    "keyword_limit_param_source": config.keyword_fetch_limit,
                    "index_name_keyword_source": "source_content_ft"
                }
                try:
                    logger.debug(f"_fetch_sources_combined (KeywordContent): Executing. Query:\n{cypher_queries.SOURCE_SEARCH_KEYWORD_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in keyword_params.items()} }")
                    fetch_start_time_kw = time.perf_counter()
                    keyword_db_results, _, _ = await self.driver.execute_query(
                        cypher_queries.SOURCE_SEARCH_KEYWORD_PART, keyword_params, database_=self.database
                    )
                    fetch_duration_kw = (time.perf_counter() - fetch_start_time_kw) * 1000
                    logger.debug(f"_fetch_sources_combined (KeywordContent): DB query took {fetch_duration_kw:.2f} ms. Rows: {len(keyword_db_results)}")
                    results_by_method["keyword_content"] = [dict(record) for record in keyword_db_results]
                except Exception as e_kw:
                    logger.error(f"Error during _fetch_sources_combined (KeywordContent): {e_kw}", exc_info=True)
                    results_by_method["keyword_content"] = []
            else:
                logger.debug("_fetch_sources_combined (KeywordContent): Skipped due to empty Lucene query.")
                results_by_method["keyword_content"] = []
        
        if SourceSearchMethod.SEMANTIC_CONTENT in config.search_methods and query_embedding:
            semantic_params = {
                "semantic_embedding_source_content": query_embedding,
                "semantic_limit_source_content": config.semantic_fetch_limit,
                "semantic_min_score_source_content": config.min_similarity_score,
                "index_name_semantic_source_content": "source_content_embedding_vector"
            }
            try:
                logger.debug(f"_fetch_sources_combined (SemanticContent): Executing. Query:\n{cypher_queries.SOURCE_SEARCH_SEMANTIC_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in semantic_params.items()} }")
                fetch_start_time_sem = time.perf_counter()
                semantic_db_results, _, _ = await self.driver.execute_query(
                    cypher_queries.SOURCE_SEARCH_SEMANTIC_PART, semantic_params, database_=self.database
                )
                fetch_duration_sem = (time.perf_counter() - fetch_start_time_sem) * 1000
                logger.debug(f"_fetch_sources_combined (SemanticContent): DB query took {fetch_duration_sem:.2f} ms. Rows: {len(semantic_db_results)}")
                results_by_method["semantic_content"] = [dict(record) for record in semantic_db_results]
            except Exception as e_sem:
                logger.error(f"Error during _fetch_sources_combined (SemanticContent): {e_sem}", exc_info=True)
                results_by_method["semantic_content"] = []
        else:
            logger.debug("_fetch_sources_combined (SemanticContent): Skipped (no embedding or not in config).")
            if SourceSearchMethod.SEMANTIC_CONTENT in config.search_methods:
                 results_by_method["semantic_content"] = []

        logger.debug(f"_fetch_sources_combined: Returning results by method: { {k: len(v) for k,v in results_by_method.items()} }")
        return results_by_method


    async def _fetch_mentions_combined(
        self,
        query_text: str,
        config: MentionSearchConfig, 
        query_embedding: Optional[List[float]]
    # ) -> List[Dict[str, Any]]: # Old
    ) -> Dict[str, List[Dict[str, Any]]]: # New return type
        # --- Start of modification ---
        results_by_method: Dict[str, List[Dict[str, Any]]] = {}
        # keyword_part_included = False # Old
        # semantic_part_included = False # Old

        if MentionSearchMethod.KEYWORD_FACT in config.search_methods and query_text.strip():
            lucene_query_str = construct_lucene_query(query_text)
            if lucene_query_str:
                keyword_params = {
                    "keyword_query_string_mention_fact": lucene_query_str,
                    "keyword_limit_param_mention_fact": config.keyword_fetch_limit,
                    "index_name_keyword_mention_fact": "mentions_fact_sentence_ft"
                }
                try:
                    logger.debug(f"_fetch_mentions_combined (KeywordFact): Executing. Query:\n{cypher_queries.MENTION_SEARCH_KEYWORD_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in keyword_params.items()} }")
                    fetch_start_time_kw = time.perf_counter()
                    keyword_db_results, _, _ = await self.driver.execute_query(
                        cypher_queries.MENTION_SEARCH_KEYWORD_PART, keyword_params, database_=self.database
                    )
                    fetch_duration_kw = (time.perf_counter() - fetch_start_time_kw) * 1000
                    logger.debug(f"_fetch_mentions_combined (KeywordFact): DB query took {fetch_duration_kw:.2f} ms. Rows: {len(keyword_db_results)}")
                    results_by_method["keyword_fact"] = [dict(record) for record in keyword_db_results]
                except Exception as e_kw:
                    logger.error(f"Error during _fetch_mentions_combined (KeywordFact): {e_kw}", exc_info=True)
                    results_by_method["keyword_fact"] = []
            else:
                logger.debug("_fetch_mentions_combined (KeywordFact): Skipped due to empty Lucene query.")
                results_by_method["keyword_fact"] = []


        if MentionSearchMethod.SEMANTIC_FACT in config.search_methods and query_embedding:
            semantic_params = {
                "semantic_embedding_mention_fact": query_embedding,
                "semantic_limit_mention_fact": config.semantic_fetch_limit,
                "semantic_min_score_mention_fact": config.min_similarity_score,
                "index_name_semantic_mention_fact": "mentions_fact_embedding_vector"
            }
            try:
                logger.debug(f"_fetch_mentions_combined (SemanticFact): Executing. Query:\n{cypher_queries.MENTION_SEARCH_SEMANTIC_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in semantic_params.items()} }")
                fetch_start_time_sem = time.perf_counter()
                semantic_db_results, _, _ = await self.driver.execute_query(
                    cypher_queries.MENTION_SEARCH_SEMANTIC_PART, semantic_params, database_=self.database
                )
                fetch_duration_sem = (time.perf_counter() - fetch_start_time_sem) * 1000
                logger.debug(f"_fetch_mentions_combined (SemanticFact): DB query took {fetch_duration_sem:.2f} ms. Rows: {len(semantic_db_results)}")
                results_by_method["semantic_fact"] = [dict(record) for record in semantic_db_results]
            except Exception as e_sem:
                logger.error(f"Error during _fetch_mentions_combined (SemanticFact): {e_sem}", exc_info=True)
                results_by_method["semantic_fact"] = []
        else:
            logger.debug("_fetch_mentions_combined (SemanticFact): Skipped (no embedding or not in config).")
            if MentionSearchMethod.SEMANTIC_FACT in config.search_methods:
                 results_by_method["semantic_fact"] = []


        logger.debug(f"_fetch_mentions_combined: Returning results by method: { {k: len(v) for k,v in results_by_method.items()} }")
        return results_by_method
        
                    
    def _apply_rrf(self, results_lists: List[List[Dict[str, Any]]], k_val: int, final_limit: int, result_type: str) -> List[SearchResultItem]:
        # --- Start of modification ---
        if not results_lists:
            logger.debug(f"_apply_rrf ({result_type}): Received empty results_lists. Returning empty list.")
            return []

        rrf_scores: Dict[str, float] = defaultdict(float)
        # Stores the actual data (name, content, etc.) for each UUID.
        # We'll pick the one from the highest original score or first encountered.
        uuid_to_primary_data_map: Dict[str, Dict[str, Any]] = {}
        # Stores detailed contributions from each method for each UUID
        uuid_contributions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        logger.debug(f"_apply_rrf ({result_type}): Processing {len(results_lists)} result list(s). k_val={k_val}, final_limit={final_limit}")

        for method_idx, single_method_results in enumerate(results_lists):
            if not single_method_results:
                logger.debug(f"_apply_rrf ({result_type}): Method list {method_idx} is empty. Skipping.")
                continue
            
            current_method_source = "unknown_method"
            if single_method_results and single_method_results[0].get("method_source"):
                 current_method_source = single_method_results[0]["method_source"]
            logger.debug(f"_apply_rrf ({result_type}): Processing method '{current_method_source}' (list {method_idx}) with {len(single_method_results)} items.")

            for rank, item in enumerate(single_method_results):
                item_uuid = item.get("uuid")
                if not item_uuid:
                    logger.warning(f"_apply_rrf ({result_type}): Item at rank {rank} in method list {method_idx} has no UUID. Skipping.")
                    continue
                
                item_original_score = item.get("score", 0.0)
                if not isinstance(item_original_score, (int, float)):
                    logger.warning(f"_apply_rrf ({result_type}): Item UUID '{item_uuid}' has non-numeric score '{item_original_score}'. Defaulting to 0.0.")
                    item_original_score = 0.0
                
                rank_contribution = 1.0 / (k_val + rank + 1)
                rrf_scores[item_uuid] += rank_contribution

                # Store contribution details
                uuid_contributions[item_uuid].append({
                    "method": current_method_source,
                    "rank": rank + 1, # 1-based rank
                    "original_score": item_original_score,
                    "rrf_contribution": rank_contribution
                })
                
                # Update primary data map (for name, content etc.)
                # This logic keeps the data from the item with the highest original score,
                # or if scores are equal, the one most recently processed if it has more fields.
                if item_uuid not in uuid_to_primary_data_map or \
                   item_original_score > uuid_to_primary_data_map[item_uuid].get("score", -1.0) or \
                   (item_original_score == uuid_to_primary_data_map[item_uuid].get("score", -1.0) and len(item) > len(uuid_to_primary_data_map[item_uuid])):
                    uuid_to_primary_data_map[item_uuid] = item
        
        if not rrf_scores:
            logger.debug(f"_apply_rrf ({result_type}): No RRF scores generated. Returning empty list.")
            return []
        
        sorted_uuids = sorted(rrf_scores.keys(), key=lambda u: rrf_scores[u], reverse=True)
        
        final_results: List[SearchResultItem] = []
        logger.debug(f"_apply_rrf ({result_type}): RRF scores calculated for {len(sorted_uuids)} unique UUIDs. Applying limit {final_limit}.")

        for i, uuid_str in enumerate(sorted_uuids[:final_limit]):
            primary_data = uuid_to_primary_data_map[uuid_str]
            item_final_rrf_score = rrf_scores[uuid_str]
            contributions = uuid_contributions[uuid_str]

            logger.debug(f"  RRF Result ({result_type}) #{i+1}: UUID: {uuid_str}, Final RRF Score: {item_final_rrf_score:.6f}")
            for contrib in contributions:
                logger.debug(f"    - Contributed by: {contrib['method']}, Rank: {contrib['rank']}, Orig. Score: {contrib['original_score']:.4f}, RRF Part: {contrib['rrf_contribution']:.6f}")

            # Initialize metadata from all_node_properties if available
            base_metadata = primary_data.get("all_node_properties", {}).copy()
            
            # Add RRF contribution details to metadata
            base_metadata["contributing_methods"] = contributions
            
            # Define keys that are either top-level SearchResultItem fields or internal/technical
            # These will be removed from base_metadata if they came from all_node_properties,
            # as they are handled separately or shouldn't be in the user-facing metadata.
            explicit_or_technical_keys = {
                "uuid", "name", "content", "score", "result_type", "label", 
                "fact_sentence", "source_node_uuid", "target_node_uuid",
                "connected_facts", # This is handled at SearchResultItem top level
                "name_embedding", "content_embedding", "description_embedding", "fact_embedding", # Embeddings
                "all_node_properties", # The key itself
                "method_source", # Handled by contributing_methods
                # Keys specific to Chunk/Source that are already explicitly returned/handled
                "source_description", "chunk_number", 
                # Keys specific to Product that are already explicitly returned/handled
                "sku", "price",
                # RRF/normalization metadata added later by GraphForRAG.search
                "unnormalized_score", "normalization_applied", "normalization_N_methods", 
                "normalization_max_score", "original_method_source_before_mqr_enhancement", 
                "inter_query_rrf_score"
            }

            # Clean base_metadata
            cleaned_metadata = {
                k: v for k, v in base_metadata.items() if k not in explicit_or_technical_keys
            }
            
            item_data_for_pydantic: Dict[str, Any] = {
                "uuid": uuid_str,
                "name": primary_data.get("name"), # Get from primary_data, which might be from node properties
                "score": item_final_rrf_score, 
                "result_type": result_type,
                "metadata": cleaned_metadata # Use the cleaned metadata
            }
            
            # Type-specific fields (ensure these are taken from primary_data which now contains all_node_properties)
            if result_type == "Chunk":
                item_data_for_pydantic["content"] = primary_data.get("content")
                # source_description and chunk_number are often explicit in RETURN, but also in all_node_properties.
                # If they are in cleaned_metadata, they will appear. If not, SearchResultItem allows them to be None.
                # For consistency, let's ensure they are in metadata if primary_data has them.
                if primary_data.get("source_description") is not None: # Check if it was returned by cypher
                     item_data_for_pydantic["metadata"]["source_description"] = primary_data.get("source_description")
                if primary_data.get("chunk_number") is not None:
                     item_data_for_pydantic["metadata"]["chunk_number"] = primary_data.get("chunk_number")

            elif result_type == "Entity":
                item_data_for_pydantic["label"] = primary_data.get("label")
                if primary_data.get("connected_facts"): # connected_facts is directly from Cypher, not all_node_properties
                    item_data_for_pydantic["connected_facts"] = primary_data.get("connected_facts")
            elif result_type == "Relationship":
                item_data_for_pydantic["fact_sentence"] = primary_data.get("fact_sentence")
                item_data_for_pydantic["source_node_uuid"] = primary_data.get("source_entity_uuid") 
                item_data_for_pydantic["target_node_uuid"] = primary_data.get("target_entity_uuid") 
            elif result_type == "Source": 
                item_data_for_pydantic["content"] = primary_data.get("content")
            elif result_type == "Product":
                item_data_for_pydantic["content"] = primary_data.get("content") 
                if primary_data.get("sku") is not None:
                    item_data_for_pydantic["metadata"]["sku"] = primary_data.get("sku")
                if primary_data.get("price") is not None:
                    item_data_for_pydantic["metadata"]["price"] = primary_data.get("price")
                if primary_data.get("connected_facts"): # connected_facts is directly from Cypher
                    item_data_for_pydantic["connected_facts"] = primary_data.get("connected_facts")
            elif result_type == "Mention":
                item_data_for_pydantic["fact_sentence"] = primary_data.get("fact_sentence")
                item_data_for_pydantic["source_node_uuid"] = primary_data.get("source_node_uuid") 
                item_data_for_pydantic["target_node_uuid"] = primary_data.get("target_node_uuid") 
                
                target_node_type_str = "Unknown"
                target_labels = primary_data.get("target_node_labels", [])
                if "Product" in target_labels: target_node_type_str = "Product"
                elif "Entity" in target_labels: target_node_type_str = "Entity"
                item_data_for_pydantic["metadata"]["target_node_type"] = target_node_type_str

            final_results.append(SearchResultItem(**item_data_for_pydantic))
        
        logger.debug(f"_apply_rrf ({result_type}): Final list contains {len(final_results)} items.")
        return final_results
    
    # --- Public Search Methods (Now using combined fetch internally) ---
    async def search_mentions(self, query_text: str, config: MentionSearchConfig, query_embedding: Optional[List[float]] = None) -> Dict[str, List[Dict[str, Any]]]: # MODIFIED return type
        start_time = time.perf_counter()
        logger.info(f"SearchManager: Fetching mention data for query: '{query_text}' (will be RRF'd later if applicable)")
        
        # --- Start of modification ---
        fetched_results_by_method: Dict[str, List[Dict[str, Any]]] = await self._fetch_mentions_combined(
            query_text, config, query_embedding
        )

        # RRF logic and SearchResultItem creation removed.

        duration = (time.perf_counter() - start_time) * 1000
        method_counts = {method: len(results) for method, results in fetched_results_by_method.items()}
        logger.info(f"SearchManager: Mention data fetching for '{query_text}' completed in {duration:.2f} ms. Results per method: {method_counts}")
        
        return fetched_results_by_method
    
    async def search_chunks(self, query_text: str, config: ChunkSearchConfig, query_embedding: Optional[List[float]] = None) -> Dict[str, List[Dict[str, Any]]]: # MODIFIED return type
        start_time = time.perf_counter()
        logger.info(f"SearchManager: Fetching chunk data for query: '{query_text}' (will be RRF'd later if applicable)")
        
        # --- Start of modification ---
        fetched_results_by_method: Dict[str, List[Dict[str, Any]]] = await self._fetch_chunks_combined(
            query_text, config, query_embedding
        )

        # The RRF logic and SearchResultItem creation is removed from here.
        # It will be handled in GraphForRAG.search after inter-query RRF.

        duration = (time.perf_counter() - start_time) * 1000
        # Log the counts of raw results fetched per method
        method_counts = {method: len(results) for method, results in fetched_results_by_method.items()}
        logger.info(f"SearchManager: Chunk data fetching for '{query_text}' completed in {duration:.2f} ms. Results per method: {method_counts}")
        
        return fetched_results_by_method

    async def search_entities(self, query_text: str, config: EntitySearchConfig, query_embedding: Optional[List[float]] = None) -> Dict[str, List[Dict[str, Any]]]: # MODIFIED return type
        start_time = time.perf_counter()
        logger.info(f"SearchManager: Fetching entity data for query: '{query_text}' (will be RRF'd later if applicable)")
        
        # --- Start of modification ---
        fetched_results_by_method: Dict[str, List[Dict[str, Any]]] = await self._fetch_entities_combined(
            query_text, config, query_embedding
        )

        # RRF logic and SearchResultItem creation removed.
        
        duration = (time.perf_counter() - start_time) * 1000
        method_counts = {method: len(results) for method, results in fetched_results_by_method.items()}
        logger.info(f"SearchManager: Entity data fetching for '{query_text}' completed in {duration:.2f} ms. Results per method: {method_counts}")
        
        return fetched_results_by_method

    async def search_relationships(self, query_text: str, config: RelationshipSearchConfig, query_embedding: Optional[List[float]] = None) -> Dict[str, List[Dict[str, Any]]]: # MODIFIED return type
        start_time = time.perf_counter()
        logger.info(f"SearchManager: Fetching relationship data for query: '{query_text}' (will be RRF'd later if applicable)")
        
        # --- Start of modification ---
        fetched_results_by_method: Dict[str, List[Dict[str, Any]]] = await self._fetch_relationships_combined(
            query_text, config, query_embedding
        )

        # RRF logic and SearchResultItem creation removed.

        duration = (time.perf_counter() - start_time) * 1000
        method_counts = {method: len(results) for method, results in fetched_results_by_method.items()}
        logger.info(f"SearchManager: Relationship data fetching for '{query_text}' completed in {duration:.2f} ms. Results per method: {method_counts}")
        
        return fetched_results_by_method

    async def search_sources(self, query_text: str, config: SourceSearchConfig, query_embedding: Optional[List[float]] = None) -> Dict[str, List[Dict[str, Any]]]: # MODIFIED return type
        start_time = time.perf_counter()
        logger.info(f"SearchManager: Fetching source data for query: '{query_text}' (will be RRF'd later if applicable)")
        
        # --- Start of modification ---
        fetched_results_by_method: Dict[str, List[Dict[str, Any]]] = await self._fetch_sources_combined(
            query_text, config, query_embedding
        )

        # RRF logic and SearchResultItem creation removed.

        duration = (time.perf_counter() - start_time) * 1000
        method_counts = {method: len(results) for method, results in fetched_results_by_method.items()}
        logger.info(f"SearchManager: Source data fetching for '{query_text}' completed in {duration:.2f} ms. Results per method: {method_counts}")
        
        return fetched_results_by_method
    
    async def _fetch_products_combined(
        self,
        query_text: str,
        config: ProductSearchConfig,
        query_embedding: Optional[List[float]]
    # ) -> List[Dict[str, Any]]: # Old
    ) -> Dict[str, List[Dict[str, Any]]]: # New return type
        # --- Start of modification ---
        results_by_method: Dict[str, List[Dict[str, Any]]] = {}
        # keyword_part_included = False # Old
        # semantic_name_part_included = False # Old
        # semantic_content_part_included = False # Old

        if ProductSearchMethod.KEYWORD_NAME_CONTENT in config.search_methods and query_text.strip():
            
            # lucene_query_str = query_text # TEMPORARY: Use raw query_text
            # logger.warning(f"TEMP DEBUG: Using RAW query text for Lucene: '{lucene_query_str}'")
            escaped_query_text = construct_lucene_query(query_text)
            lucene_query_str_for_product: str
            if " " in query_text.strip() or any(c in query_text for c in "()[]{}<>/"): # Add more chars if needed
                 # Ensure internal quotes within the escaped_query_text are themselves escaped for the outer phrase quotes
                 # For example, if escaped_query_text becomes 'Product \"X\"', for phrase it should be '"Product \\"X\\""'
                 # However, construct_lucene_query already escapes double quotes to \\"
                 # So, simply wrapping should be fine if construct_lucene_query handles internal quotes correctly for Lucene.
                 lucene_query_str_for_product = f"\"{escaped_query_text}\""
                 logger.debug(f"Product Keyword Search: Using PHRASE query for '{query_text[:50]}...': {lucene_query_str_for_product}")
            else:
                 lucene_query_str_for_product = escaped_query_text
                 logger.debug(f"Product Keyword Search: Using standard Lucene query for '{query_text[:50]}...': {lucene_query_str_for_product}")
            if lucene_query_str_for_product:
                keyword_params = {
                    "keyword_query_string_product": lucene_query_str_for_product,
                    "keyword_limit_param_product": config.keyword_fetch_limit,
                    "index_name_keyword_product": "product_name_content_ft"
                }
                try:
                    logger.debug(f"_fetch_products_combined (KeywordNameContent) for query '{query_text[:50]}...': Executing. Query:\n{cypher_queries.PRODUCT_SEARCH_KEYWORD_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in keyword_params.items()} }") # Log query
                    fetch_start_time_kw = time.perf_counter()
                    keyword_db_results, _, _ = await self.driver.execute_query(
                        cypher_queries.PRODUCT_SEARCH_KEYWORD_PART, keyword_params, database_=self.database
                    )
                    fetch_duration_kw = (time.perf_counter() - fetch_start_time_kw) * 1000
                    results_by_method["keyword_name_content"] = [dict(record) for record in keyword_db_results]
                    # --- Start of new code ---
                    kw_found_products = [(r.get('uuid'), r.get('name'), r.get('score')) for r in results_by_method["keyword_name_content"]]
                    logger.info(f"DEBUG ProductFetch: Keyword for '{query_text[:50]}...' FOUND: {len(kw_found_products)} products. Details: {kw_found_products}")
                    # --- End of new code ---
                    logger.debug(f"_fetch_products_combined (KeywordNameContent): DB query took {fetch_duration_kw:.2f} ms. Rows: {len(keyword_db_results)}")
                except Exception as e_kw:
                    logger.error(f"Error during _fetch_products_combined (KeywordNameContent) for query '{query_text[:50]}...': {e_kw}", exc_info=True) # Log query
                    results_by_method["keyword_name_content"] = []
            else:
                logger.debug("_fetch_products_combined (KeywordNameContent): Skipped due to empty Lucene query.")
                results_by_method["keyword_name_content"] = []


        if ProductSearchMethod.SEMANTIC_NAME in config.search_methods and query_embedding:
            logger.info(f"DEBUG ProductFetch: SemanticName for '{query_text[:50]}...' using query_embedding (first 5 dims): {query_embedding[:5] if query_embedding else 'None'}")
            semantic_name_params = {
                "semantic_embedding_product_name": query_embedding,
                "semantic_limit_product_name": config.semantic_name_fetch_limit,
                "semantic_min_score_product_name": config.min_similarity_score_name,
                "index_name_semantic_product_name": "product_name_embedding_vector"
            }
            try:
                logger.debug(f"_fetch_products_combined (SemanticName) for query '{query_text[:50]}...': Executing. Query:\n{cypher_queries.PRODUCT_SEARCH_SEMANTIC_NAME_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in semantic_name_params.items()} }") # Log query
                fetch_start_time_sem_name = time.perf_counter()
                semantic_name_db_results, _, _ = await self.driver.execute_query(
                    cypher_queries.PRODUCT_SEARCH_SEMANTIC_NAME_PART, semantic_name_params, database_=self.database
                )
                fetch_duration_sem_name = (time.perf_counter() - fetch_start_time_sem_name) * 1000
                results_by_method["semantic_name"] = [dict(record) for record in semantic_name_db_results]
                # --- Start of new code ---
                sem_name_found_products = [(r.get('uuid'), r.get('name'), r.get('score')) for r in results_by_method["semantic_name"]]
                logger.info(f"DEBUG ProductFetch: SemanticName for '{query_text[:50]}...' FOUND: {len(sem_name_found_products)} products. Details: {sem_name_found_products}")
                # --- End of new code ---
                logger.debug(f"_fetch_products_combined (SemanticName): DB query took {fetch_duration_sem_name:.2f} ms. Rows: {len(semantic_name_db_results)}")
            except Exception as e_sem_name:
                logger.error(f"Error during _fetch_products_combined (SemanticName) for query '{query_text[:50]}...': {e_sem_name}", exc_info=True) # Log query
                results_by_method["semantic_name"] = []
        else:
            logger.debug(f"_fetch_products_combined (SemanticName) for query '{query_text[:50]}...': Skipped (no embedding or not in config).") # Log query
            if ProductSearchMethod.SEMANTIC_NAME in config.search_methods:
                 results_by_method["semantic_name"] = []


        if ProductSearchMethod.SEMANTIC_CONTENT in config.search_methods and query_embedding:
            semantic_content_params = {
                "semantic_embedding_product_content": query_embedding,
                "semantic_limit_product_content": config.semantic_content_fetch_limit,
                "semantic_min_score_product_content": config.min_similarity_score_content,
                "index_name_semantic_product_content": "product_content_embedding_vector"
            }
            try:
                logger.debug(f"_fetch_products_combined (SemanticContent) for query '{query_text[:50]}...': Executing. Query:\n{cypher_queries.PRODUCT_SEARCH_SEMANTIC_CONTENT_PART}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in semantic_content_params.items()} }") # Log query
                fetch_start_time_sem_content = time.perf_counter()
                semantic_content_db_results, _, _ = await self.driver.execute_query(
                    cypher_queries.PRODUCT_SEARCH_SEMANTIC_CONTENT_PART, semantic_content_params, database_=self.database
                )
                fetch_duration_sem_content = (time.perf_counter() - fetch_start_time_sem_content) * 1000
                results_by_method["semantic_content"] = [dict(record) for record in semantic_content_db_results]
                # --- Start of new code ---
                sem_content_found_products = [(r.get('uuid'), r.get('name'), r.get('score')) for r in results_by_method["semantic_content"]]
                logger.info(f"DEBUG ProductFetch: SemanticContent for '{query_text[:50]}...' FOUND: {len(sem_content_found_products)} products. Details: {sem_content_found_products}")
                # --- End of new code ---
                logger.debug(f"_fetch_products_combined (SemanticContent): DB query took {fetch_duration_sem_content:.2f} ms. Rows: {len(semantic_content_db_results)}")
            except Exception as e_sem_content:
                logger.error(f"Error during _fetch_products_combined (SemanticContent) for query '{query_text[:50]}...': {e_sem_content}", exc_info=True) # Log query
                results_by_method["semantic_content"] = []
        else:
            logger.debug(f"_fetch_products_combined (SemanticContent) for query '{query_text[:50]}...': Skipped (no embedding or not in config).") # Log query
            if ProductSearchMethod.SEMANTIC_CONTENT in config.search_methods:
                 results_by_method["semantic_content"] = []

        logger.debug(f"_fetch_products_combined for query '{query_text[:50]}...': Returning results by method: { {k: len(v) for k,v in results_by_method.items()} }") # Log query
        return results_by_method
    
    async def search_products(self, query_text: str, config: ProductSearchConfig, query_embedding: Optional[List[float]] = None) -> Dict[str, List[Dict[str, Any]]]:
        start_time = time.perf_counter()
        logger.info(f"SearchManager: Fetching product data for query: '{query_text}' (will be RRF'd later if applicable)")
        
        fetched_results_by_method: Dict[str, List[Dict[str, Any]]] = await self._fetch_products_combined(
            query_text, config, query_embedding
        )

        duration = (time.perf_counter() - start_time) * 1000
        method_counts = {method: len(results) for method, results in fetched_results_by_method.items()}
        logger.info(f"SearchManager: Product data fetching for '{query_text}' completed in {duration:.2f} ms. Results per method: {method_counts}")
        
        return fetched_results_by_method
    async def execute_llm_generated_cypher(
        self,
        generated_cypher_query: str,
        original_query_text: str, # For potential parameter binding or context
        query_embedding: Optional[List[float]] # For binding $query_embedding
    ) -> List[Dict[str, Any]]:
        """
        Executes an LLM-generated Cypher query and returns the raw results.
        Handles basic parameter binding for $query_embedding.
        """
        if not generated_cypher_query.strip():
            logger.warning("SearchManager.execute_llm_generated_cypher: Received empty Cypher query. Skipping execution.")
            return []

        params: Dict[str, Any] = {}
        if "$query_embedding" in generated_cypher_query:
            if query_embedding:
                params["query_embedding"] = query_embedding
                logger.debug("Bound $query_embedding for LLM-generated Cypher.")
            else:
                logger.warning("LLM-generated Cypher contains $query_embedding, but no embedding was provided. Query might fail or return unexpected results.")
        
        # Placeholder for other potential parameters if LLM starts generating them
        # For example, if LLM generates a query like "MATCH (n) WHERE n.name = $name_param RETURN n"
        # We would need a mechanism to extract $name_param from original_query_text or have LLM provide it.
        # For now, we only explicitly handle $query_embedding.

        logger.info(f"SearchManager: Executing LLM-generated Cypher for original query '{original_query_text[:50]}...'.")
        logger.debug(f"Generated Cypher:\n{generated_cypher_query}\nParams: { {k: (type(v).__name__ if not isinstance(v, list) else f'list_len_{len(v)}') for k,v in params.items()} }")
        
        try:
            fetch_start_time = time.perf_counter()
            results, _, _ = await self.driver.execute_query(
                generated_cypher_query,
                parameters_=params, # Use parameters_ argument
                database_=self.database
            )
            fetch_duration = (time.perf_counter() - fetch_start_time) * 1000
            logger.info(f"SearchManager: LLM-generated Cypher execution took {fetch_duration:.2f} ms. Returned {len(results)} rows.")
            return [dict(record) for record in results]
        except Exception as e:
            # Log the specific Cypher query that failed along with the error.
            logger.error(f"SearchManager: Error executing LLM-generated Cypher. Query: \n{generated_cypher_query}\nParams: {params}\nError: {e}", exc_info=True)
            # Return an empty list to indicate failure but allow the overall search to continue.
            # Optionally, you could return a specific error marker if the calling code needs to distinguish
            # between "no results found" and "query execution failed". For now, empty list is simple.
            return []