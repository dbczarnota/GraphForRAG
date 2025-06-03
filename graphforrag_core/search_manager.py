# graphforrag_core/search_manager.py
import logging
import asyncio
from typing import List, Dict, Any, Optional
from neo4j import AsyncDriver # type: ignore
from collections import defaultdict
import time # Import time

from config import cypher_queries
from .embedder_client import EmbedderClient
from .search_types import (
    ChunkSearchConfig, ChunkSearchMethod, ChunkRerankerMethod,
    EntitySearchConfig, EntitySearchMethod, EntityRerankerMethod,
    RelationshipSearchConfig, RelationshipSearchMethod, RelationshipRerankerMethod,
    SearchResultItem
)

logger = logging.getLogger("graph_for_rag.search_manager")

def construct_lucene_query(query: str) -> str:
    """
    Constructs a basic Lucene query string.
    For now, just use the query as is. We can add sanitization/boosting later.
    """
    return query

class SearchManager:
    def __init__(self, driver: AsyncDriver, database_name: str, embedder_client: EmbedderClient):
        self.driver: AsyncDriver = driver
        self.database: str = database_name
        self.embedder: EmbedderClient = embedder_client
        logger.info(f"SearchManager initialized for database '{database_name}'.")

    async def _fetch_chunks_by_keyword(self, query: str, limit: int) -> List[Dict[str, Any]]:
        if not query.strip(): logger.warning("Keyword chunk search query is empty."); return []
        fulltext_index_name = "chunk_content_ft"
        lucene_query_str = construct_lucene_query(query)
        params = {"index_name": fulltext_index_name, "query_string": lucene_query_str, "limit_param": limit}
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.SEARCH_CHUNKS_BY_KEYWORD_FULLTEXT, params, database_=self.database)
            return [dict(record) for record in results]
        except Exception as e:
            logger.error(f"Error during _fetch_chunks_by_keyword: {e}", exc_info=True); return []

    async def _fetch_chunks_by_similarity(self, query_text: str, limit: int, min_score: float, query_embedding_override: Optional[List[float]] = None) -> List[Dict[str, Any]]:
        if not query_text.strip() and not query_embedding_override: logger.warning("Semantic chunk search needs query_text or query_embedding_override."); return []
        query_embedding_to_use = query_embedding_override
        if not query_embedding_to_use:
            try:
                query_embedding_to_use = await self.embedder.embed_text(query_text)
                if not query_embedding_to_use: logger.warning(f"Could not generate embedding for query (chunk sim): '{query_text}'."); return []
            except Exception as e:
                logger.error(f"Error generating embedding for query '{query_text}' in _fetch_chunks_by_similarity: {e}", exc_info=True); return []
        vector_index_name = "chunk_content_embedding_vector"
        params = {"index_name_param": vector_index_name, "top_k_param": limit, "embedding_vector_param": query_embedding_to_use, "min_similarity_score_param": min_score}
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.SEARCH_CHUNKS_BY_SIMILARITY_VECTOR, params, database_=self.database)
            return [dict(record) for record in results]
        except Exception as e:
            logger.error(f"Error during _fetch_chunks_by_similarity: {e}", exc_info=True); return []

    async def _fetch_entities_by_keyword(self, query: str, limit: int) -> List[Dict[str, Any]]:
        if not query.strip(): logger.warning("Keyword entity search query is empty."); return []
        fulltext_index_name = "entity_name_desc_ft"
        lucene_query_str = construct_lucene_query(query)
        params = {"index_name": fulltext_index_name, "query_string": lucene_query_str, "limit_param": limit}
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.SEARCH_ENTITIES_BY_KEYWORD_FULLTEXT, params, database_=self.database)
            return [dict(record) for record in results]
        except Exception as e:
            logger.error(f"Error during _fetch_entities_by_keyword: {e}", exc_info=True); return []

    async def _fetch_entities_by_name_similarity(self, query_text: str, limit: int, min_score: float, query_embedding_override: Optional[List[float]] = None) -> List[Dict[str, Any]]:
        if not query_text.strip() and not query_embedding_override: logger.warning("Semantic entity name search needs query_text or query_embedding_override."); return []
        query_embedding_to_use = query_embedding_override
        if not query_embedding_to_use:
            try:
                query_embedding_to_use = await self.embedder.embed_text(query_text)
                if not query_embedding_to_use: logger.warning(f"Could not generate embedding for query (entity name sim): '{query_text}'."); return []
            except Exception as e:
                logger.error(f"Error generating embedding for query '{query_text}' in _fetch_entities_by_name_similarity: {e}", exc_info=True); return []
        vector_index_name = "entity_name_embedding_vector"
        params = {"index_name_param": vector_index_name, "top_k_param": limit, "embedding_vector_param": query_embedding_to_use, "min_similarity_score_param": min_score}
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.SEARCH_ENTITIES_BY_SIMILARITY_VECTOR, params, database_=self.database)
            return [dict(record) for record in results]
        except Exception as e:
            logger.error(f"Error during _fetch_entities_by_name_similarity: {e}", exc_info=True); return []

    async def _fetch_entities_by_description_similarity(self, query_text: str, limit: int, min_score: float, query_embedding_override: Optional[List[float]] = None) -> List[Dict[str, Any]]:
        if not query_text.strip() and not query_embedding_override: logger.warning("Semantic entity description search needs query_text or query_embedding_override."); return []
        query_embedding_to_use = query_embedding_override
        if not query_embedding_to_use:
            try:
                query_embedding_to_use = await self.embedder.embed_text(query_text)
                if not query_embedding_to_use: logger.warning(f"Could not generate embedding for query (entity desc sim): '{query_text}'."); return []
            except Exception as e:
                logger.error(f"Error generating embedding for query '{query_text}' in _fetch_entities_by_description_similarity: {e}", exc_info=True); return []
        vector_index_name = "entity_description_embedding_vector"
        params = {"index_name_param": vector_index_name, "top_k_param": limit, "embedding_vector_param": query_embedding_to_use, "min_similarity_score_param": min_score}
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.SEARCH_ENTITIES_BY_DESCRIPTION_SIMILARITY_VECTOR, params, database_=self.database)
            return [dict(record) for record in results]
        except Exception as e:
            logger.error(f"Error during _fetch_entities_by_description_similarity: {e}", exc_info=True); return []

    async def _fetch_relationships_by_keyword(self, query: str, limit: int) -> List[Dict[str, Any]]:
        if not query.strip(): logger.warning("Keyword relationship search query is empty."); return []
        fulltext_index_name = "relationship_fact_ft"
        lucene_query_str = construct_lucene_query(query)
        params = {"index_name": fulltext_index_name, "query_string": lucene_query_str, "limit_param": limit}
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.SEARCH_RELATIONSHIPS_BY_KEYWORD_FULLTEXT, params, database_=self.database)
            return [dict(record) for record in results]
        except Exception as e:
            logger.error(f"Error during _fetch_relationships_by_keyword: {e}", exc_info=True); return []

    async def _fetch_relationships_by_similarity(self, query_text: str, limit: int, min_score: float, query_embedding_override: Optional[List[float]] = None) -> List[Dict[str, Any]]:
        if not query_text.strip() and not query_embedding_override: logger.warning("Semantic relationship search needs query_text or query_embedding_override."); return []
        query_embedding_to_use = query_embedding_override
        if not query_embedding_to_use:
            try:
                query_embedding_to_use = await self.embedder.embed_text(query_text)
                if not query_embedding_to_use: logger.warning(f"Could not generate embedding for query (relationship sim): '{query_text}'."); return []
            except Exception as e:
                logger.error(f"Error generating embedding for query '{query_text}' in _fetch_relationships_by_similarity: {e}", exc_info=True); return []
        vector_index_name = "relates_to_fact_embedding_vector"
        params = {"index_name_param": vector_index_name, "top_k_param": limit, "embedding_vector_param": query_embedding_to_use, "min_similarity_score_param": min_score}
        try:
            results, _, _ = await self.driver.execute_query(cypher_queries.SEARCH_RELATIONSHIPS_BY_SIMILARITY_VECTOR, params, database_=self.database)
            return [dict(record) for record in results]
        except Exception as e:
            logger.error(f"Error during _fetch_relationships_by_similarity: {e}", exc_info=True); return []


    def _apply_rrf(self, results_lists: List[List[Dict[str, Any]]], k_val: int, final_limit: int, result_type: str) -> List[SearchResultItem]:
        # ... (no change) ...
        if not results_lists: return []
        rrf_scores: Dict[str, float] = defaultdict(float)
        uuid_to_data_map: Dict[str, Dict[str, Any]] = {} 
        for single_method_results in results_lists:
            if not single_method_results: continue
            for rank, item in enumerate(single_method_results):
                item_uuid = item.get("uuid")
                if not item_uuid: continue
                rrf_scores[item_uuid] += 1.0 / (k_val + rank + 1)
                if item_uuid not in uuid_to_data_map or len(item) > len(uuid_to_data_map[item_uuid]): uuid_to_data_map[item_uuid] = item
        if not rrf_scores: return []
        sorted_uuids = sorted(rrf_scores.keys(), key=lambda u: rrf_scores[u], reverse=True)
        final_results: List[SearchResultItem] = []
        for uuid_str in sorted_uuids[:final_limit]:
            data = uuid_to_data_map[uuid_str]
            item_data_for_pydantic = {"uuid": uuid_str,"name": data.get("name"),"score": rrf_scores[uuid_str],"result_type": result_type, "metadata": {"original_search_score": data.get("score")}} # type: ignore
            if result_type == "Chunk": item_data_for_pydantic["content"] = data.get("content"); item_data_for_pydantic["metadata"].update({"source_description": data.get("source_description"),"chunk_number": data.get("chunk_number")})
            elif result_type == "Entity": item_data_for_pydantic["description"] = data.get("description"); item_data_for_pydantic["label"] = data.get("label")
            elif result_type == "Relationship": item_data_for_pydantic["fact_sentence"] = data.get("fact_sentence"); item_data_for_pydantic["source_entity_uuid"] = data.get("source_entity_uuid"); item_data_for_pydantic["target_entity_uuid"] = data.get("target_entity_uuid")
            final_results.append(SearchResultItem(**item_data_for_pydantic))
        return final_results

    async def search_chunks(self, query_text: str, config: ChunkSearchConfig, query_embedding: Optional[List[float]] = None) -> List[SearchResultItem]:
        start_time = time.perf_counter()
        logger.info(f"Searching chunks for: '{query_text}'") # Removed config from this line for brevity
        
        tasks_to_run = []
        # ... (task appending logic as before) ...
        if ChunkSearchMethod.KEYWORD in config.search_methods:
            tasks_to_run.append(self._fetch_chunks_by_keyword(query_text, config.keyword_fetch_limit))
        if ChunkSearchMethod.SEMANTIC in config.search_methods:
            tasks_to_run.append(self._fetch_chunks_by_similarity(
                query_text, config.semantic_fetch_limit, config.min_similarity_score, query_embedding
            ))
        if not tasks_to_run: logger.info("No search methods configured for chunks."); return []
        
        gathered_results_from_methods = await asyncio.gather(*tasks_to_run)
        all_method_results: List[List[Dict[str, Any]]] = [res for res in gathered_results_from_methods if res]
        if not all_method_results: logger.info("No results from any search method for chunks."); return []
        
        final_items: List[SearchResultItem]
        if config.reranker == ChunkRerankerMethod.RRF:
            final_items = self._apply_rrf(all_method_results, config.rrf_k, config.limit, "Chunk")
        else: 
            combined_deduped_results: Dict[str, Dict[str, Any]] = {item["uuid"]: item for res_list in all_method_results for item in res_list}
            sorted_items = sorted(combined_deduped_results.values(), key=lambda x: x.get('score', 0.0), reverse=True)
            final_items = [SearchResultItem(uuid=data["uuid"], name=data.get("name"), content=data.get("content"), score=data.get("score", 0.0), result_type="Chunk", metadata={"source_description": data.get("source_description"),"chunk_number": data.get("chunk_number")}) for data in sorted_items[:config.limit]]
        
        duration = (time.perf_counter() - start_time) * 1000
        logger.info(f"Chunk search completed in {duration:.2f} ms, found {len(final_items)} items.")
        return final_items

    async def search_entities(self, query_text: str, config: EntitySearchConfig, query_embedding: Optional[List[float]] = None) -> List[SearchResultItem]:
        start_time = time.perf_counter()
        logger.info(f"Searching entities for: '{query_text}'")
        
        tasks_to_run = []
        # ... (task appending logic as before) ...
        if EntitySearchMethod.KEYWORD_NAME_DESC in config.search_methods:
            tasks_to_run.append(self._fetch_entities_by_keyword(query_text, config.keyword_fetch_limit))
        if EntitySearchMethod.SEMANTIC_NAME in config.search_methods:
            tasks_to_run.append(self._fetch_entities_by_name_similarity(query_text, config.semantic_name_fetch_limit, config.min_similarity_score_name, query_embedding))
        if EntitySearchMethod.SEMANTIC_DESCRIPTION in config.search_methods:
            tasks_to_run.append(self._fetch_entities_by_description_similarity(query_text, config.semantic_description_fetch_limit, config.min_similarity_score_description, query_embedding))
        if not tasks_to_run: logger.info("No search methods configured for entities."); return []

        gathered_results_from_methods = await asyncio.gather(*tasks_to_run)
        all_method_results: List[List[Dict[str, Any]]] = [res for res in gathered_results_from_methods if res]
        if not all_method_results: logger.info("No results from any search method for entities."); return []

        final_items: List[SearchResultItem]
        if config.reranker == EntityRerankerMethod.RRF:
            final_items = self._apply_rrf(all_method_results, config.rrf_k, config.limit, "Entity")
        else: 
            combined_deduped_results: Dict[str, Dict[str, Any]] = {item["uuid"]: item for res_list in all_method_results for item in res_list}
            sorted_items = sorted(combined_deduped_results.values(), key=lambda x: x.get('score', 0.0), reverse=True)
            final_items = [SearchResultItem(uuid=data["uuid"], name=data.get("name"), description=data.get("description"), label=data.get("label"), score=data.get("score", 0.0), result_type="Entity", metadata={}) for data in sorted_items[:config.limit]]
        
        duration = (time.perf_counter() - start_time) * 1000
        logger.info(f"Entity search completed in {duration:.2f} ms, found {len(final_items)} items.")
        return final_items

    async def search_relationships(self, query_text: str, config: RelationshipSearchConfig, query_embedding: Optional[List[float]] = None) -> List[SearchResultItem]:
        start_time = time.perf_counter()
        logger.info(f"Searching relationships for: '{query_text}'")
        
        tasks_to_run = []
        # ... (task appending logic as before) ...
        if RelationshipSearchMethod.KEYWORD_FACT in config.search_methods:
            tasks_to_run.append(self._fetch_relationships_by_keyword(query_text, config.keyword_fetch_limit))
        if RelationshipSearchMethod.SEMANTIC_FACT in config.search_methods:
            tasks_to_run.append(self._fetch_relationships_by_similarity(query_text, config.semantic_fetch_limit, config.min_similarity_score, query_embedding))
        if not tasks_to_run: logger.info("No search methods configured for relationships."); return []
            
        gathered_results_from_methods = await asyncio.gather(*tasks_to_run)
        all_method_results: List[List[Dict[str, Any]]] = [res for res in gathered_results_from_methods if res]
        if not all_method_results: logger.info("No results from any search method for relationships."); return []

        final_items: List[SearchResultItem]
        if config.reranker == RelationshipRerankerMethod.RRF:
            final_items = self._apply_rrf(all_method_results, config.rrf_k, config.limit, "Relationship")
        else: 
            combined_deduped_results: Dict[str, Dict[str, Any]] = {item["uuid"]: item for res_list in all_method_results for item in res_list}
            sorted_items = sorted(combined_deduped_results.values(), key=lambda x: x.get('score', 0.0), reverse=True)
            final_simple_results: List[SearchResultItem] = []
            for data in sorted_items[:config.limit]:
                final_simple_results.append(SearchResultItem(uuid=data["uuid"],name=data.get("name"), fact_sentence=data.get("fact_sentence"),source_entity_uuid=data.get("source_entity_uuid"),target_entity_uuid=data.get("target_entity_uuid"),score=data.get("score", 0.0), result_type="Relationship", metadata={"original_search_score": data.get("score")}))
            final_items = final_simple_results
        
        duration = (time.perf_counter() - start_time) * 1000
        logger.info(f"Relationship search completed in {duration:.2f} ms, found {len(final_items)} items.")
        return final_items