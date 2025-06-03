# main.py
from graphforrag_core.graphforrag import GraphForRAG
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from data.source_data import source_data_sets 
from graphforrag_core.search_types import (
    SearchConfig, 
    ChunkSearchConfig, ChunkSearchMethod, 
    EntitySearchConfig, EntitySearchMethod, 
    RelationshipSearchConfig, RelationshipSearchMethod, 
    SourceSearchConfig, SourceSearchMethod, 
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
from typing import List, Dict, Any, Optional 
# from files.llm_models import setup_fallback_model # No longer explicitly called from main for service client

# Ensure logging is at DEBUG for search_manager to see detailed logs
logging.getLogger("graph_for_rag.search_manager").setLevel(logging.DEBUG)
logging.getLogger("graph_for_rag.graphforrag").setLevel(logging.DEBUG) 
logging.getLogger("llm_models").setLevel(logging.INFO) # Keep to see if setup_fallback_model is called from GraphForRAG

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s", 
    datefmt="%Y-%m-%d %H:%M:%S", 
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False, log_time_format="[%X.%f]")],
)
logger = logging.getLogger("graph_for_rag_main") 
traceback.install()


def get_current_time_ms() -> str:
    return datetime.now().isoformat(sep=' ', timespec='milliseconds')

async def main():
    logger.info(f"[bold cyan]Main execution started at: {get_current_time_ms()}[/bold cyan]")
    main_start_time = time.perf_counter() 
    timings: Dict[str, float] = {}

    section_start_time = time.perf_counter()
    load_dotenv()
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password')
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    timings["env_setup"] = (time.perf_counter() - section_start_time) * 1000

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found in environment variables. Cannot initialize OpenAIEmbedder.")
        return

    graph = None
    try:
        section_start_time = time.perf_counter()
        embedder_config = OpenAIEmbedderConfig(
            api_key=OPENAI_API_KEY,
            model_name="text-embedding-3-small",
            embedding_dimension=768
        )
        openai_embedder = OpenAIEmbedder(config=embedder_config)
        timings["embedder_init"] = (time.perf_counter() - section_start_time) * 1000

        # --- GraphForRAG Initialization without explicit LLM client ---
        # GraphForRAG will set up its services_llm_client on demand.
        graph_init_overall_start_time = time.perf_counter()
        logger.info("MAIN: Initializing GraphForRAG instance (LLM client will be set up on demand by services)...")
        graph = GraphForRAG(
            NEO4J_URI,
            NEO4J_USER,
            NEO4J_PASSWORD,
            embedder_client=openai_embedder,
            llm_client=None # Pass None, so GraphForRAG uses its internal lazy setup
        )
        timings["graphforrag_init_total"] = (time.perf_counter() - graph_init_overall_start_time) * 1000
        logger.info(f"MAIN: GraphForRAG instance creation took {timings['graphforrag_init_total']:.2f} ms")
        # We no longer have a separate "llm_client_setup (fallback)" here, as it's deferred.
        
        # logger.info("MAIN: Performing DB warm-up query...")
        # warmup_start_time = time.perf_counter()
        # if graph and graph.driver:
        #     try:
        #         await graph.driver.execute_query("RETURN 1", database_=graph.database)
        #     except Exception as e_warmup:
        #          logger.error(f"Error during DB warm-up query: {e_warmup}", exc_info=True)
        # timings["db_warmup_query"] = (time.perf_counter() - warmup_start_time) * 1000
        # logger.info(f"MAIN: DB warm-up query took {timings['db_warmup_query']:.2f} ms")
        
        run_data_setup = False # Set to True to run ingestion, which will trigger LLM setup
        if run_data_setup:
            logger.info(f"Schema/Data setup started at: {get_current_time_ms()}")
            setup_overall_start_time = time.perf_counter()
            
            s_time = time.perf_counter(); await graph.clear_all_known_indexes_and_constraints(); timings["clear_indexes_constraints"] = (time.perf_counter() - s_time) * 1000
            s_time = time.perf_counter(); await graph.clear_all_data(); timings["clear_data"] = (time.perf_counter() - s_time) * 1000
            s_time = time.perf_counter(); await graph.ensure_indices(); timings["ensure_indices"] = (time.perf_counter() - s_time) * 1000
            
            timings["schema_data_setup_total"] = (time.perf_counter() - setup_overall_start_time) * 1000
            logger.info(f"Schema/Data setup finished. Duration: {timings['schema_data_setup_total']:.2f} ms")

            logger.info(f"Data ingestion started at: {get_current_time_ms()}")
            ingestion_overall_start_time = time.perf_counter()
            # This call to add_documents_from_source will trigger LLM setup if not already done
            for i, source_set_info in enumerate(source_data_sets):
                s_time = time.perf_counter()
                await graph.add_documents_from_source(
                    source_identifier=source_set_info["identifier"],
                    documents_data=source_set_info["chunks"],
                    source_content=source_set_info.get("source_content"),
                    source_dynamic_metadata=source_set_info["source_metadata"]
                )
                timings[f"data_ingestion_source_{i+1}"] = (time.perf_counter() - s_time) * 1000
            timings["data_ingestion_total"] = (time.perf_counter() - ingestion_overall_start_time) * 1000
            logger.info(f"Data ingestion finished. Duration: {timings['data_ingestion_total']:.2f} ms")
            logger.info("\n--- All document sets processed ---")
        else:
            logger.info("Skipping schema/data setup and ingestion as `run_data_setup` is False.")

        section_start_time = time.perf_counter()
        data_exists = False
        try:
            if graph and graph.driver:
                query_result = await graph.driver.execute_query("MATCH (c:Chunk) RETURN count(c) > 0 AS chunks_exist", database_=graph.database)
                if query_result and query_result[0] and query_result[0][0]: 
                    data_exists = query_result[0][0].get("chunks_exist", False)
        except Exception as e_db_check:
            logger.error(f"Error checking for data existence: {e_db_check}", exc_info=True)

        if not data_exists and not run_data_setup: # Adjusted condition
             logger.warning("No Chunk data found. Please run ingestion at least once (set run_data_setup=True).")
        timings["data_existence_check"] = (time.perf_counter() - section_start_time) * 1000


        full_search_query = "Pooh Bear stuck in Rabbit's front door eating honey"
        
        # Explicit query embedding in main is removed for this test of deferred LLM setup
        # graph.search() will handle its own embedding if needed.
        timings["query_embedding_generation (explicit_in_main)"] = 0.0 # Placeholder
        logger.info(f"MAIN: Explicit query embedding generation in main is SKIPPED for this test.")
        
        logger.info(f"\n--- Setting up Comprehensive Search Test at: {get_current_time_ms()} ---")
        section_start_time = time.perf_counter()
        comprehensive_search_config = SearchConfig(
            chunk_config=ChunkSearchConfig(
                search_methods=[ChunkSearchMethod.KEYWORD, ChunkSearchMethod.SEMANTIC],
                limit=3, keyword_fetch_limit=10, semantic_fetch_limit=10
            ),
            entity_config=EntitySearchConfig(
                search_methods=[
                    EntitySearchMethod.KEYWORD_NAME_DESC, 
                    EntitySearchMethod.SEMANTIC_NAME, 
                    EntitySearchMethod.SEMANTIC_DESCRIPTION
                ],
                limit=4, keyword_fetch_limit=15, semantic_name_fetch_limit=15, semantic_description_fetch_limit=15
            ),
            relationship_config=RelationshipSearchConfig(
                search_methods=[RelationshipSearchMethod.KEYWORD_FACT, RelationshipSearchMethod.SEMANTIC_FACT],
                limit=3, keyword_fetch_limit=10, semantic_fetch_limit=10
            ),
            source_config=SourceSearchConfig( 
                search_methods=[SourceSearchMethod.KEYWORD_CONTENT, SourceSearchMethod.SEMANTIC_CONTENT],
                limit=2, keyword_fetch_limit=5, semantic_fetch_limit=5
            )
        )
        
        config_dump_str = comprehensive_search_config.model_dump_json(indent=2, exclude_none=True)
        timings["search_config_setup_log"] = (time.perf_counter() - section_start_time) * 1000
        logger.info(f"Using comprehensive search config (setup/log took {timings['search_config_setup_log']:.2f} ms): {config_dump_str}")

        section_start_time = time.perf_counter()
        if graph:
            combined_results: CombinedSearchResults = await graph.search(
                full_search_query, 
                config=comprehensive_search_config
            )
            timings["comprehensive_search_call (graph.search)"] = (time.perf_counter() - section_start_time) * 1000
            logger.info(f"Comprehensive search call (graph.search) finished. Duration: {timings['comprehensive_search_call (graph.search)']:.2f} ms")

            if combined_results.items:
                logger.info(f"Found {len(combined_results.items)} combined results for '{full_search_query}':")
                # (Result printing loop can be re-enabled if desired for output verification)
                # for i, item in enumerate(combined_results.items):
                #     logger.info(f"  --- Result {i+1} ({item.result_type}) ---") # ...
            else:
                logger.info(f"No combined results found for '{full_search_query}'.")
            logger.info(f"Result printing skipped/minimal for this timing test. Found {len(combined_results.items)} items.") # Keep this
        else:
            logger.error("Graph object not initialized, skipping comprehensive search call.")
            timings["comprehensive_search_call (graph.search)"] = 0.0
        
        logger.info(f"--- Comprehensive Search Test Complete at: {get_current_time_ms()} ---")
        
        section_start_time = time.perf_counter()
        if graph: 
            total_usage = graph.get_total_llm_usage()
            if total_usage and total_usage.has_values():
                details = (f"Requests: {total_usage.requests}, Request Tokens: {total_usage.request_tokens or 0}, Response Tokens: {total_usage.response_tokens or 0}, Total Tokens: {total_usage.total_tokens or 0}")
                logger.info(f"[bold magenta]Overall LLM Usage:[/bold magenta] {details}")
            else:
                logger.info("[bold magenta]Overall LLM Usage:[/bold magenta] No usage data reported (or LLM services not used).")
        else:
            logger.info("[bold magenta]Overall LLM Usage:[/bold magenta] Graph object not initialized.")
        timings["get_llm_usage"] = (time.perf_counter() - section_start_time) * 1000

    except Exception as e:
        logger.error(f"An error occurred in main execution: {e}", exc_info=True)
    finally:
        if graph:
            section_start_time = time.perf_counter()
            await graph.close()
            timings["graph_close"] = (time.perf_counter() - section_start_time) * 1000
        
        main_end_time = time.perf_counter()
        timings["total_main_execution"] = (main_end_time - main_start_time) * 1000
        
        logger.info(f"\n[bold cyan]--- TIMING SUMMARY (ms) ---[/bold cyan]")
        sum_of_parts = sum(v for k, v in timings.items() if k != "total_main_execution")
        
        for operation, duration in timings.items():
            if operation == "total_main_execution": continue
            percentage = (duration / timings.get("total_main_execution", 1)) * 100 
            logger.info(f"{operation:<45}: {duration:>10.2f} ms ({percentage:>6.2f}%)")
        
        unaccounted_time = timings.get("total_main_execution", 0) - sum_of_parts
        if abs(unaccounted_time) > 1.0 : 
             percentage_unaccounted = (unaccounted_time / timings.get("total_main_execution", 1)) * 100 
             logger.info(f"{'Unaccounted time':<45}: {unaccounted_time:>10.2f} ms ({percentage_unaccounted:>6.2f}%)")
        
        calculated_total_main_execution = sum_of_parts + (unaccounted_time if abs(unaccounted_time) > 1.0 else 0)
        logger.info(f"{'Total Main Execution (Calculated)':<45}: {calculated_total_main_execution:>10.2f} ms ({(calculated_total_main_execution/timings.get('total_main_execution',1)*100):>6.2f}%)")
        logger.info(f"{'Total Main Execution (Actual)':<45}: {timings.get('total_main_execution', 0):>10.2f} ms (100.00%)")
        logger.info(f"[bold cyan]Main execution finished at: {get_current_time_ms()}. Total duration: {timings.get('total_main_execution',0):.2f} ms[/bold cyan]")

if __name__ == "__main__":
    asyncio.run(main())