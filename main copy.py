# main.py
from graphforrag_core.graphforrag import GraphForRAG
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from data.source_data import source_data_sets 
from graphforrag_core.search_types import (
    SearchConfig, 
    ChunkSearchConfig, ChunkSearchMethod, ChunkRerankerMethod, 
    EntitySearchConfig, EntitySearchMethod, EntityRerankerMethod, 
    RelationshipSearchConfig, RelationshipSearchMethod, RelationshipRerankerMethod,
    SourceSearchConfig, SourceSearchMethod, SourceRerankerMethod, 
    CombinedSearchResults, SearchResultItem
)
from dotenv import load_dotenv
import os
import logging
from rich import traceback
from rich.logging import RichHandler
from datetime import datetime 
import time 
import asyncio
from typing import List, Dict, Any, Optional # Added Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d - %(message)s", 
    datefmt="%Y-%m-%d %H:%M:%S", 
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False)],
)
logger = logging.getLogger("graph_for_rag_main")
traceback.install()

def get_current_time_ms() -> str:
    """Returns current time as a string with milliseconds."""
    return datetime.now().isoformat(sep=' ', timespec='milliseconds')

# Helper to mimic the "old" search_chunks behavior for direct comparison
async def run_old_search_chunks_logic(
    search_manager, 
    query_text: str, 
    config: ChunkSearchConfig, 
    query_embedding: Optional[List[float]]
) -> List[SearchResultItem]:
    logger.info(f"[OLD METHOD] Searching chunks for: '{query_text}'")
    tasks_to_run = []
    if ChunkSearchMethod.KEYWORD in config.search_methods:
        tasks_to_run.append(search_manager._fetch_chunks_by_keyword(query_text, config.keyword_fetch_limit))
    if ChunkSearchMethod.SEMANTIC in config.search_methods and query_embedding:
        tasks_to_run.append(search_manager._fetch_chunks_by_similarity(
            query_text, config.semantic_fetch_limit, config.min_similarity_score, query_embedding
        ))
    
    if not tasks_to_run:
        logger.info("[OLD METHOD] No search methods configured for chunks.")
        return []
        
    gathered_results_from_methods = await asyncio.gather(*tasks_to_run)
    all_method_results: List[List[Dict[str, Any]]] = [res for res in gathered_results_from_methods if res]
    
    if not all_method_results:
        logger.info("[OLD METHOD] No results from any search method for chunks.")
        return []
    
    final_items: List[SearchResultItem]
    if config.reranker == ChunkRerankerMethod.RRF:
        final_items = search_manager._apply_rrf(all_method_results, config.rrf_k, config.limit, "Chunk")
    else:
        # Simplified fallback for non-RRF - adapt if other rerankers were used in old method
        combined_deduped_results: Dict[str, Dict[str, Any]] = {item["uuid"]: item for res_list in all_method_results for item in res_list}
        sorted_items = sorted(combined_deduped_results.values(), key=lambda x: x.get('score', 0.0), reverse=True)
        final_items = [SearchResultItem(uuid=data["uuid"], name=data.get("name"), content=data.get("content"), score=data.get("score", 0.0), result_type="Chunk", metadata={"source_description": data.get("source_description"),"chunk_number": data.get("chunk_number")}) for data in sorted_items[:config.limit]]
    
    logger.info(f"[OLD METHOD] Chunk search completed, found {len(final_items)} items.")
    return final_items


async def main():
    logger.info(f"[bold cyan]Main execution started at: {get_current_time_ms()}[/bold cyan]")
    main_start_time = time.perf_counter() 

    load_dotenv()
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password')
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found in environment variables. Cannot initialize OpenAIEmbedder.")
        return

    graph = None
    try:
        embedder_config = OpenAIEmbedderConfig(
            api_key=OPENAI_API_KEY,
            model_name="text-embedding-3-small",
            embedding_dimension=768
        )
        openai_embedder = OpenAIEmbedder(config=embedder_config)

        graph = GraphForRAG(
            NEO4J_URI,
            NEO4J_USER,
            NEO4J_PASSWORD,
            embedder_client=openai_embedder
        )
        
        # --- Schema and Data Setup (Run once, then comment out for tests) ---
        # logger.info(f"Schema/Data setup started at: {get_current_time_ms()}")
        # setup_start_time = time.perf_counter()
        # await graph.clear_all_known_indexes_and_constraints() 
        # await graph.clear_all_data()                        
        # await graph.ensure_indices()
        # setup_end_time = time.perf_counter()
        # logger.info(f"Schema/Data setup finished at: {get_current_time_ms()}. Duration: {(setup_end_time - setup_start_time):.4f} seconds")

        # logger.info(f"Data ingestion started at: {get_current_time_ms()}")
        # ingestion_start_time = time.perf_counter()
        # for source_set_info in source_data_sets:
        #     source_id = source_set_info["identifier"]
        #     source_content_for_node = source_set_info.get("source_content")
        #     chunks_for_source = source_set_info["chunks"] 
        #     dynamic_metadata_for_source = source_set_info["source_metadata"]
        #     await graph.add_documents_from_source(
        #         source_identifier=source_id,
        #         documents_data=chunks_for_source,
        #         source_content=source_content_for_node,
        #         source_dynamic_metadata=dynamic_metadata_for_source
        #     )
        # ingestion_end_time = time.perf_counter()
        # logger.info(f"Data ingestion finished at: {get_current_time_ms()}. Duration: {(ingestion_end_time - ingestion_start_time):.4f} seconds")
        # logger.info("\n--- All document sets processed ---")

        if not (await graph.driver.execute_query("MATCH (n:Chunk) RETURN count(n) > 0 AS chunks_exist", database_=graph.database))[0][0].get("chunks_exist"):
             logger.warning("No data found. Please run ingestion at least once before testing search.")
             return

        full_search_query = "Pooh Bear stuck in Rabbit's front door eating honey"
        
        # --- Generate Query Embedding Once ---
        query_embedding_for_tests: Optional[List[float]] = None
        embed_start_time_main = time.perf_counter()
        try:
            logger.debug(f"Generating query embedding for: '{full_search_query}' for all tests")
            query_embedding_for_tests = await graph.embedder.embed_text(full_search_query)
        except Exception as e:
            logger.error(f"Error generating query embedding for tests: {e}", exc_info=True)
        embed_duration_main = (time.perf_counter() - embed_start_time_main) * 1000
        logger.info(f"MAIN: Query embedding generation for all tests took {embed_duration_main:.2f} ms.")
        if not query_embedding_for_tests:
            logger.error("Failed to generate query embedding. Cannot proceed with semantic search tests.")
            return


        # --- Test Configuration for Chunks ---
        chunk_test_config = ChunkSearchConfig(
            search_methods=[ChunkSearchMethod.KEYWORD, ChunkSearchMethod.SEMANTIC],
            limit=3, min_similarity_score=0.5, keyword_fetch_limit=10, semantic_fetch_limit=10, rrf_k=60
        )
        logger.info(f"\n--- Test Config for Chunks: {chunk_test_config.model_dump_json(indent=2)} ---")

        # --- Test OLD search_chunks logic ---
        logger.info(f"\n--- Testing OLD Chunk Search Logic at: {get_current_time_ms()} ---")
        old_chunk_search_start_time = time.perf_counter()
        old_chunk_results = await run_old_search_chunks_logic(
            graph.search_manager, 
            full_search_query, 
            chunk_test_config, 
            query_embedding_for_tests
        )
        old_chunk_search_duration = (time.perf_counter() - old_chunk_search_start_time) * 1000
        logger.info(f"[bold yellow]MAIN: OLD search_chunks logic took {old_chunk_search_duration:.2f} ms. Found {len(old_chunk_results)} items.[/bold yellow]")
        # for item in old_chunk_results: logger.info(f"  OLD Result: {item.name} - Score: {item.score:.4f}")


        # --- Test NEW (Refactored) search_chunks logic ---
        logger.info(f"\n--- Testing NEW Chunk Search Logic (Combined Query) at: {get_current_time_ms()} ---")
        new_chunk_search_start_time = time.perf_counter()
        # Directly call the SearchManager's refactored method
        new_chunk_results = await graph.search_manager.search_chunks(
            full_search_query, 
            chunk_test_config, 
            query_embedding_for_tests
        )
        new_chunk_search_duration = (time.perf_counter() - new_chunk_search_start_time) * 1000
        logger.info(f"[bold green]MAIN: NEW search_chunks logic (Combined Query) took {new_chunk_search_duration:.2f} ms. Found {len(new_chunk_results)} items.[/bold green]")
        # for item in new_chunk_results: logger.info(f"  NEW Result: {item.name} - Score: {item.score:.4f}")


        # --- Full Combined Search (using the new method implicitly for chunks) ---
        logger.info(f"\n--- Running Full Combined Search (which uses NEW chunk logic) at: {get_current_time_ms()} ---")
        overall_search_config = SearchConfig(
            chunk_config=chunk_test_config, # Use the same chunk config
            entity_config=EntitySearchConfig(limit=4), # Example
            relationship_config=RelationshipSearchConfig(limit=3), # Example
            source_config=SourceSearchConfig(limit=2) # Example
        )
        
        full_search_start_time = time.perf_counter()
        combined_results_with_new_chunk_logic: CombinedSearchResults = await graph.search(
            full_search_query, 
            config=overall_search_config
            # query_embedding is handled internally by graph.search now
        )
        full_search_duration = (time.perf_counter() - full_search_start_time) * 1000
        logger.info(f"Full combined search (with new chunk logic) took {full_search_duration:.2f} ms.")

        if combined_results_with_new_chunk_logic.items:
            logger.info(f"Found {len(combined_results_with_new_chunk_logic.items)} combined results for '{full_search_query}':")
            # (Your existing detailed logging for combined_results can go here)
        else:
            logger.info(f"No combined results found for '{full_search_query}'.")
        
        total_usage = graph.get_total_llm_usage() # LLM usage is not relevant to DB query performance test
        # ... (LLM usage logging) ...

    except Exception as e:
        logger.error(f"An error occurred in main execution: {e}", exc_info=True)
    finally:
        if graph:
            await graph.close()
        main_end_time = time.perf_counter()
        logger.info(f"[bold cyan]Main execution finished at: {get_current_time_ms()}. Total duration: {(main_end_time - main_start_time):.4f} seconds[/bold cyan]")

if __name__ == "__main__":
    asyncio.run(main())