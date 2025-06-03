# graphforrag_core/search_manager.py
import logging
import asyncio 
from typing import List, Dict, Any, Optional
from neo4j import AsyncDriver # type: ignore
from collections import defaultdict
import time 
import re 

from config import cypher_queries # Now imports the refactored queries
from .embedder_client import EmbedderClient
from .search_types import (
    ChunkSearchConfig, ChunkSearchMethod, ChunkRerankerMethod,
    EntitySearchConfig, EntitySearchMethod, EntityRerankerMethod,
    RelationshipSearchConfig, RelationshipSearchMethod, RelationshipRerankerMethod,
    SourceSearchConfig, SourceSearchMethod, SourceRerankerMethod, 
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
    ) -> List[Dict[str, Any]]:
        cypher_parts = []
        params: Dict[str, Any] = {}
        keyword_part_included = False
        semantic_part_included = False

        if ChunkSearchMethod.KEYWORD in config.search_methods and query_text.strip():
            lucene_query_str = construct_lucene_query(query_text)
            if lucene_query_str: 
                params["keyword_query_string_chunk"] = lucene_query_str
                params["keyword_limit_param_chunk"] = config.keyword_fetch_limit
                params["index_name_keyword_chunk"] = "chunk_content_ft"
                cypher_parts.append(cypher_queries.CHUNK_SEARCH_KEYWORD_PART)
                keyword_part_included = True
            else:
                logger.debug("_fetch_chunks_combined: Keyword part skipped due to empty Lucene query.")

        if ChunkSearchMethod.SEMANTIC in config.search_methods and query_embedding:
            params["semantic_embedding_vector_param_chunk"] = query_embedding
            params["semantic_top_k_param_chunk"] = config.semantic_fetch_limit
            params["semantic_min_similarity_score_param_chunk"] = config.min_similarity_score
            params["index_name_semantic_chunk"] = "chunk_content_embedding_vector"
            cypher_parts.append(cypher_queries.CHUNK_SEARCH_SEMANTIC_PART)
            semantic_part_included = True
        else:
            logger.debug("_fetch_chunks_combined: Semantic part skipped (no embedding or not in config).")
        
        if not cypher_parts:
            logger.info("_fetch_chunks_combined: No search parts to execute.")
            return []

        final_query = " UNION ALL ".join(cypher_parts)
        
        try:
            param_keys_for_log = {k: (type(v).__name__ if not isinstance(v, list) else f"list_len_{len(v)}") for k,v in params.items()}
            logger.debug(f"_fetch_chunks_combined: Executing with {len(cypher_parts)} part(s) (K: {keyword_part_included}, S: {semantic_part_included}). Query:\n{final_query}\nParams (keys and types/lengths): {param_keys_for_log}")
            
            fetch_start_time = time.perf_counter()
            results, summary, _ = await self.driver.execute_query(final_query, params, database_=self.database)
            fetch_duration = (time.perf_counter() - fetch_start_time) * 1000
            num_rows_returned = len(results)
            logger.debug(f"_fetch_chunks_combined: DB query took {fetch_duration:.2f} ms. Rows returned: {num_rows_returned}")
            
            return [dict(record) for record in results]
        except Exception as e:
            logger.error(f"Error during _fetch_chunks_combined: {e}", exc_info=True)
            return []

    async def _fetch_entities_combined(
        self,
        query_text: str,
        config: EntitySearchConfig,
        query_embedding: Optional[List[float]]
    ) -> List[Dict[str, Any]]:
        cypher_parts = []
        params: Dict[str, Any] = {}
        keyword_part_included = False
        semantic_name_part_included = False
        semantic_desc_part_included = False
        
        if EntitySearchMethod.KEYWORD_NAME_DESC in config.search_methods and query_text.strip():
            lucene_query_str = construct_lucene_query(query_text)
            if lucene_query_str:
                params["keyword_query_string_entity"] = lucene_query_str
                params["keyword_limit_param_entity"] = config.keyword_fetch_limit
                params["index_name_keyword_entity"] = "entity_name_desc_ft"
                cypher_parts.append(cypher_queries.ENTITY_SEARCH_KEYWORD_PART)
                keyword_part_included = True
            else:
                logger.debug("_fetch_entities_combined: Keyword part skipped due to empty Lucene query.")

        if EntitySearchMethod.SEMANTIC_NAME in config.search_methods and query_embedding:
            params["semantic_embedding_entity_name"] = query_embedding
            params["semantic_limit_entity_name"] = config.semantic_name_fetch_limit
            params["semantic_min_score_entity_name"] = config.min_similarity_score_name
            params["index_name_semantic_entity_name"] = "entity_name_embedding_vector"
            cypher_parts.append(cypher_queries.ENTITY_SEARCH_SEMANTIC_NAME_PART)
            semantic_name_part_included = True
        else:
            logger.debug("_fetch_entities_combined: Semantic Name part skipped.")

        if EntitySearchMethod.SEMANTIC_DESCRIPTION in config.search_methods and query_embedding:
            params["semantic_embedding_entity_desc"] = query_embedding
            params["semantic_limit_entity_desc"] = config.semantic_description_fetch_limit
            params["semantic_min_score_entity_desc"] = config.min_similarity_score_description
            params["index_name_semantic_entity_desc"] = "entity_description_embedding_vector"
            cypher_parts.append(cypher_queries.ENTITY_SEARCH_SEMANTIC_DESCRIPTION_PART)
            semantic_desc_part_included = True
        else:
            logger.debug("_fetch_entities_combined: Semantic Description part skipped.")
            
        if not cypher_parts:
            logger.info("_fetch_entities_combined: No search parts to execute.")
            return []

        final_query = " UNION ALL ".join(cypher_parts)
        try:
            param_keys_for_log = {k: (type(v).__name__ if not isinstance(v, list) else f"list_len_{len(v)}") for k,v in params.items()}
            logger.debug(f"_fetch_entities_combined: Executing with {len(cypher_parts)} part(s) (K: {keyword_part_included}, SN: {semantic_name_part_included}, SD: {semantic_desc_part_included}). Query:\n{final_query}\nParams (keys and types/lengths): {param_keys_for_log}")
            fetch_start_time = time.perf_counter()
            results, summary, _ = await self.driver.execute_query(final_query, params, database_=self.database)
            fetch_duration = (time.perf_counter() - fetch_start_time) * 1000
            num_rows_returned = len(results)
            logger.debug(f"_fetch_entities_combined: DB query took {fetch_duration:.2f} ms. Rows returned: {num_rows_returned}")
            return [dict(record) for record in results]
        except Exception as e:
            logger.error(f"Error during _fetch_entities_combined: {e}", exc_info=True); return []
    
    async def _fetch_relationships_combined(
        self,
        query_text: str,
        config: RelationshipSearchConfig,
        query_embedding: Optional[List[float]]
    ) -> List[Dict[str, Any]]:
        cypher_parts = []
        params: Dict[str, Any] = {}
        keyword_part_included = False
        semantic_part_included = False

        if RelationshipSearchMethod.KEYWORD_FACT in config.search_methods and query_text.strip():
            lucene_query_str = construct_lucene_query(query_text)
            if lucene_query_str:
                params["keyword_query_string_rel"] = lucene_query_str
                params["keyword_limit_param_rel"] = config.keyword_fetch_limit
                params["index_name_keyword_rel"] = "relationship_fact_ft"
                cypher_parts.append(cypher_queries.RELATIONSHIP_SEARCH_KEYWORD_PART)
                keyword_part_included = True
            else:
                logger.debug("_fetch_relationships_combined: Keyword part skipped due to empty Lucene query.")

        if RelationshipSearchMethod.SEMANTIC_FACT in config.search_methods and query_embedding:
            params["semantic_embedding_rel_fact"] = query_embedding
            params["semantic_limit_rel_fact"] = config.semantic_fetch_limit
            params["semantic_min_score_rel_fact"] = config.min_similarity_score
            params["index_name_semantic_rel_fact"] = "relates_to_fact_embedding_vector"
            cypher_parts.append(cypher_queries.RELATIONSHIP_SEARCH_SEMANTIC_PART)
            semantic_part_included = True
        else:
            logger.debug("_fetch_relationships_combined: Semantic part skipped.")
            
        if not cypher_parts: 
            logger.info("_fetch_relationships_combined: No search parts to execute.")
            return []
            
        final_query = " UNION ALL ".join(cypher_parts)
        try:
            param_keys_for_log = {k: (type(v).__name__ if not isinstance(v, list) else f"list_len_{len(v)}") for k,v in params.items()}
            logger.debug(f"_fetch_relationships_combined: Executing with {len(cypher_parts)} part(s) (K: {keyword_part_included}, S: {semantic_part_included}). Query:\n{final_query}\nParams (keys and types/lengths): {param_keys_for_log}")
            fetch_start_time = time.perf_counter()
            results, summary, _ = await self.driver.execute_query(final_query, params, database_=self.database)
            fetch_duration = (time.perf_counter() - fetch_start_time) * 1000
            num_rows_returned = len(results)
            logger.debug(f"_fetch_relationships_combined: DB query took {fetch_duration:.2f} ms. Rows returned: {num_rows_returned}")
            return [dict(record) for record in results]
        except Exception as e:
            logger.error(f"Error during _fetch_relationships_combined: {e}", exc_info=True); return []

    async def _fetch_sources_combined(
        self,
        query_text: str,
        config: SourceSearchConfig,
        query_embedding: Optional[List[float]]
    ) -> List[Dict[str, Any]]:
        cypher_parts = []
        params: Dict[str, Any] = {}
        keyword_part_included = False
        semantic_part_included = False

        if SourceSearchMethod.KEYWORD_CONTENT in config.search_methods and query_text.strip():
            lucene_query_str = construct_lucene_query(query_text)
            if lucene_query_str:
                params["keyword_query_string_source"] = lucene_query_str
                params["keyword_limit_param_source"] = config.keyword_fetch_limit
                params["index_name_keyword_source"] = "source_content_ft"
                cypher_parts.append(cypher_queries.SOURCE_SEARCH_KEYWORD_PART)
                keyword_part_included = True
            else:
                logger.debug("_fetch_sources_combined: Keyword part skipped due to empty Lucene query.")
        
        if SourceSearchMethod.SEMANTIC_CONTENT in config.search_methods and query_embedding:
            params["semantic_embedding_source_content"] = query_embedding
            params["semantic_limit_source_content"] = config.semantic_fetch_limit
            params["semantic_min_score_source_content"] = config.min_similarity_score
            params["index_name_semantic_source_content"] = "source_content_embedding_vector"
            cypher_parts.append(cypher_queries.SOURCE_SEARCH_SEMANTIC_PART)
            semantic_part_included = True
        else:
            logger.debug("_fetch_sources_combined: Semantic part skipped.")
            
        if not cypher_parts: 
            logger.info("_fetch_sources_combined: No search parts to execute.")
            return []
            
        final_query = " UNION ALL ".join(cypher_parts)
        try:
            param_keys_for_log = {k: (type(v).__name__ if not isinstance(v, list) else f"list_len_{len(v)}") for k,v in params.items()}
            logger.debug(f"_fetch_sources_combined: Executing with {len(cypher_parts)} part(s) (K: {keyword_part_included}, S: {semantic_part_included}). Query:\n{final_query}\nParams (keys and types/lengths): {param_keys_for_log}")
            fetch_start_time = time.perf_counter()
            results, summary, _ = await self.driver.execute_query(final_query, params, database_=self.database)
            fetch_duration = (time.perf_counter() - fetch_start_time) * 1000
            num_rows_returned = len(results)
            logger.debug(f"_fetch_sources_combined: DB query took {fetch_duration:.2f} ms. Rows returned: {num_rows_returned}")
            return [dict(record) for record in results]
        except Exception as e:
            logger.error(f"Error during _fetch_sources_combined: {e}", exc_info=True); return []
            
    def _apply_rrf(self, results_lists: List[List[Dict[str, Any]]], k_val: int, final_limit: int, result_type: str) -> List[SearchResultItem]:
        if not results_lists: return []
        rrf_scores: Dict[str, float] = defaultdict(float)
        uuid_to_data_map: Dict[str, Dict[str, Any]] = {} 
        for single_method_results in results_lists:
            if not single_method_results: continue
            for rank, item in enumerate(single_method_results):
                item_uuid = item.get("uuid")
                if not item_uuid: continue
                item_original_score = item.get("score", 0.0)
                if not isinstance(item_original_score, (int, float)):
                    item_original_score = 0.0
                
                rrf_scores[item_uuid] += 1.0 / (k_val + rank + 1)
                
                if item_uuid not in uuid_to_data_map or \
                   item_original_score > uuid_to_data_map[item_uuid].get("score", -1.0) or \
                   (item_original_score == uuid_to_data_map[item_uuid].get("score", -1.0) and len(item) > len(uuid_to_data_map[item_uuid])):
                    uuid_to_data_map[item_uuid] = item 
        
        if not rrf_scores: return []
        
        sorted_uuids = sorted(rrf_scores.keys(), key=lambda u: rrf_scores[u], reverse=True)
        
        final_results: List[SearchResultItem] = []
        for uuid_str in sorted_uuids[:final_limit]:
            data = uuid_to_data_map[uuid_str]
            item_name = data.get("name")
            item_final_score = rrf_scores[uuid_str] 
            original_search_score = data.get("score") 
            method_source = data.get("method_source") 

            item_data_for_pydantic: Dict[str, Any] = {
                "uuid": uuid_str,
                "name": item_name,
                "score": item_final_score, 
                "result_type": result_type, 
                "metadata": {"original_search_score": original_search_score}
            }
            if method_source: 
                item_data_for_pydantic["metadata"]["method_source"] = method_source
            
            if result_type == "Chunk":
                item_data_for_pydantic["content"] = data.get("content")
                item_data_for_pydantic["metadata"].update({
                    "source_description": data.get("source_description"),
                    "chunk_number": data.get("chunk_number")
                })
            elif result_type == "Entity":
                item_data_for_pydantic["description"] = data.get("description")
                item_data_for_pydantic["label"] = data.get("label")
            elif result_type == "Relationship":
                item_data_for_pydantic["fact_sentence"] = data.get("fact_sentence")
                item_data_for_pydantic["source_entity_uuid"] = data.get("source_entity_uuid")
                item_data_for_pydantic["target_entity_uuid"] = data.get("target_entity_uuid")
            elif result_type == "Source": 
                item_data_for_pydantic["content"] = data.get("content")
            
            final_results.append(SearchResultItem(**item_data_for_pydantic))
        return final_results

    # --- Public Search Methods (Now using combined fetch internally) ---
    async def search_chunks(self, query_text: str, config: ChunkSearchConfig, query_embedding: Optional[List[float]] = None) -> List[SearchResultItem]:
        start_time = time.perf_counter()
        logger.info(f"Searching chunks for: '{query_text}'")
        
        combined_method_results: List[Dict[str, Any]] = await self._fetch_chunks_combined(
            query_text, config, query_embedding
        )
        
        if not combined_method_results:
            logger.info("No results from combined fetch for chunks.")
            duration_empty = (time.perf_counter() - start_time) * 1000
            logger.info(f"Chunk search (empty results) completed in {duration_empty:.2f} ms.")
            return []

        all_method_results_for_rrf: List[List[Dict[str, Any]]] = []
        if config.reranker == ChunkRerankerMethod.RRF:
            grouped_by_method: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for res in combined_method_results: 
                grouped_by_method[res.get("method_source", "unknown")].append(res)
            all_method_results_for_rrf = list(grouped_by_method.values())
        
        final_items: List[SearchResultItem]
        if config.reranker == ChunkRerankerMethod.RRF and all_method_results_for_rrf:
            final_items = self._apply_rrf(all_method_results_for_rrf, config.rrf_k, config.limit, "Chunk")
        elif combined_method_results: 
            logger.debug("Applying simple sort for chunks as RRF is not configured or results could not be split by method.")
            combined_method_results.sort(key=lambda x: x.get('score', 0.0), reverse=True)
            final_items = [
                SearchResultItem(
                    uuid=data["uuid"], 
                    name=data.get("name"), 
                    content=data.get("content"), 
                    score=data.get("score", 0.0), 
                    result_type="Chunk", 
                    metadata={
                        "source_description": data.get("source_description"),
                        "chunk_number": data.get("chunk_number"),
                        "method_source": data.get("method_source", "unknown") 
                    }
                ) for data in combined_method_results[:config.limit]
            ]
        else:
            final_items = []
        
        duration = (time.perf_counter() - start_time) * 1000
        logger.info(f"Chunk search completed in {duration:.2f} ms, found {len(final_items)} items.")
        return final_items

    async def search_entities(self, query_text: str, config: EntitySearchConfig, query_embedding: Optional[List[float]] = None) -> List[SearchResultItem]:
        start_time = time.perf_counter()
        logger.info(f"Searching entities for: '{query_text}'")
        
        combined_method_results: List[Dict[str, Any]] = await self._fetch_entities_combined(
            query_text, config, query_embedding
        )

        if not combined_method_results:
            logger.info("No results from combined fetch for entities.")
            duration_empty = (time.perf_counter() - start_time) * 1000
            logger.info(f"Entity search (empty results) completed in {duration_empty:.2f} ms.")
            return []

        all_method_results_for_rrf: List[List[Dict[str, Any]]] = []
        if config.reranker == EntityRerankerMethod.RRF:
            grouped_by_method: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for res in combined_method_results:
                grouped_by_method[res.get("method_source", "unknown")].append(res)
            all_method_results_for_rrf = list(grouped_by_method.values())

        final_items: List[SearchResultItem]
        if config.reranker == EntityRerankerMethod.RRF and all_method_results_for_rrf:
            final_items = self._apply_rrf(all_method_results_for_rrf, config.rrf_k, config.limit, "Entity")
        elif combined_method_results:
            logger.debug("Applying simple sort for entities as RRF is not configured or results could not be split.")
            combined_method_results.sort(key=lambda x: x.get('score', 0.0), reverse=True)
            final_items = [
                SearchResultItem(
                    uuid=data["uuid"], name=data.get("name"), description=data.get("description"),
                    label=data.get("label"), score=data.get("score", 0.0), result_type="Entity",
                    metadata={"method_source": data.get("method_source", "unknown")}
                ) for data in combined_method_results[:config.limit]
            ]
        else:
            final_items = []
        
        duration = (time.perf_counter() - start_time) * 1000
        logger.info(f"Entity search completed in {duration:.2f} ms, found {len(final_items)} items.")
        return final_items

    async def search_relationships(self, query_text: str, config: RelationshipSearchConfig, query_embedding: Optional[List[float]] = None) -> List[SearchResultItem]:
        start_time = time.perf_counter()
        logger.info(f"Searching relationships for: '{query_text}'")
        
        combined_method_results: List[Dict[str, Any]] = await self._fetch_relationships_combined(
            query_text, config, query_embedding
        )

        if not combined_method_results:
            logger.info("No results from combined fetch for relationships.")
            duration_empty = (time.perf_counter() - start_time) * 1000
            logger.info(f"Relationship search (empty results) completed in {duration_empty:.2f} ms.")
            return []

        all_method_results_for_rrf: List[List[Dict[str, Any]]] = []
        if config.reranker == RelationshipRerankerMethod.RRF:
            grouped_by_method: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for res in combined_method_results:
                grouped_by_method[res.get("method_source", "unknown")].append(res)
            all_method_results_for_rrf = list(grouped_by_method.values())
            
        final_items: List[SearchResultItem]
        if config.reranker == RelationshipRerankerMethod.RRF and all_method_results_for_rrf:
            final_items = self._apply_rrf(all_method_results_for_rrf, config.rrf_k, config.limit, "Relationship")
        elif combined_method_results:
            logger.debug("Applying simple sort for relationships as RRF is not configured or results could not be split.")
            combined_method_results.sort(key=lambda x: x.get('score', 0.0), reverse=True)
            final_items = [
                SearchResultItem(
                    uuid=data["uuid"],name=data.get("name"), fact_sentence=data.get("fact_sentence"),
                    source_entity_uuid=data.get("source_entity_uuid"),target_entity_uuid=data.get("target_entity_uuid"),
                    score=data.get("score", 0.0), result_type="Relationship",
                    metadata={"method_source": data.get("method_source", "unknown")}
                ) for data in combined_method_results[:config.limit]
            ]
        else:
            final_items = []
        
        duration = (time.perf_counter() - start_time) * 1000
        logger.info(f"Relationship search completed in {duration:.2f} ms, found {len(final_items)} items.")
        return final_items

    async def search_sources(self, query_text: str, config: SourceSearchConfig, query_embedding: Optional[List[float]] = None) -> List[SearchResultItem]:
        start_time = time.perf_counter()
        logger.info(f"Searching sources for: '{query_text}'")
        
        combined_method_results: List[Dict[str, Any]] = await self._fetch_sources_combined(
            query_text, config, query_embedding
        )

        if not combined_method_results:
            logger.info("No results from combined fetch for sources.")
            duration_empty = (time.perf_counter() - start_time) * 1000
            logger.info(f"Source search (empty results) completed in {duration_empty:.2f} ms.")
            return []

        all_method_results_for_rrf: List[List[Dict[str, Any]]] = []
        if config.reranker == SourceRerankerMethod.RRF:
            grouped_by_method: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for res in combined_method_results:
                grouped_by_method[res.get("method_source", "unknown")].append(res)
            all_method_results_for_rrf = list(grouped_by_method.values())

        final_items: List[SearchResultItem]
        if config.reranker == SourceRerankerMethod.RRF and all_method_results_for_rrf:
            final_items = self._apply_rrf(all_method_results_for_rrf, config.rrf_k, config.limit, "Source")
        elif combined_method_results:
            logger.debug("Applying simple sort for sources as RRF is not configured or results could not be split.")
            combined_method_results.sort(key=lambda x: x.get('score', 0.0), reverse=True)
            final_items = [
                SearchResultItem(
                    uuid=data["uuid"], name=data.get("name"), content=data.get("content"), 
                    score=data.get("score", 0.0), result_type="Source",
                    metadata={"method_source": data.get("method_source", "unknown")}
                ) for data in combined_method_results[:config.limit]
            ]
        else:
            final_items = []
        
        duration = (time.perf_counter() - start_time) * 1000
        logger.info(f"Source search completed in {duration:.2f} ms, found {len(final_items)} items.")
        return final_items