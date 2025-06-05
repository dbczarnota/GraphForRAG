# main_delete_source.py
import asyncio
import os
from dotenv import load_dotenv
import logging
from rich import traceback
from rich.logging import RichHandler
from datetime import datetime
import time
from typing import Optional, Dict # Added Dict

from graphforrag_core.graphforrag import GraphForRAG
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from data.source_data import source_data_sets # Assuming this is your main data source

# --- Logging Setup ---
LOG_LEVEL = logging.DEBUG # Set to DEBUG to see detailed NodeManager logs
logging.getLogger("graph_for_rag").setLevel(LOG_LEVEL)
logging.getLogger("graph_for_rag.node_manager").setLevel(LOG_LEVEL)
# Add other loggers if needed
logging.getLogger("llm_models").setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False, log_time_format="[%X.%f]")],
)
logger = logging.getLogger("graph_for_rag_delete_source_main")
traceback.install()

def get_current_time_ms() -> str:
    return datetime.now().isoformat(sep=' ', timespec='milliseconds')

async def main():
    logger.info(f"[bold cyan]Source Deletion Test - Main execution started at: {get_current_time_ms()}[/bold cyan]")
    main_start_time = time.perf_counter()
    timings: Dict[str, float] = {}

    load_dotenv()
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password')
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found in environment variables.")
        return

    graph: Optional[GraphForRAG] = None

    # --- Test Configuration ---
    run_data_ingestion_before_delete = False  # Set to False if data already exists and is in the desired state
    
    # --- CHOOSE WHICH SOURCE TO DELETE ---
    # Scenario 1: Source with only Chunks and general Entities
    # source_name_to_delete = "Winnie-the-Pooh: A Tight Spot at Rabbit's House (Chapter II Excerpt)"
    
    # Scenario 2: Source with Products (which might mention entities also found in chunks from other sources)
    source_name_to_delete = "Q3 2024 Tech Product Showcase"
    
    # Scenario 3: Source with Chunks that mention Products from the "Product Showcase"
    # source_name_to_delete = "Navigating the World of Personal Computers: 2024 Edition"
    
    logger.info(f"--- CONFIGURATION ---")
    logger.info(f"Run Ingestion: {run_data_ingestion_before_delete}")
    logger.info(f"Source to Delete: '{source_name_to_delete}'")
    logger.info(f"--- END CONFIGURATION ---\n")

    try:
        s_time = time.perf_counter()
        embedder_config = OpenAIEmbedderConfig(api_key=OPENAI_API_KEY)
        openai_embedder = OpenAIEmbedder(config=embedder_config)
        timings["embedder_init"] = (time.perf_counter() - s_time) * 1000

        s_time = time.perf_counter()
        graph = GraphForRAG(
            NEO4J_URI,
            NEO4J_USER,
            NEO4J_PASSWORD,
            embedder_client=openai_embedder,
            llm_client=None
        )
        timings["graphforrag_init"] = (time.perf_counter() - s_time) * 1000
        logger.info(f"GraphForRAG instance initialized in {timings['graphforrag_init']:.2f} ms")

        if run_data_ingestion_before_delete:
            logger.info(f"Schema/Data setup started at: {get_current_time_ms()}")
            s_time = time.perf_counter()
            await graph.clear_all_known_indexes_and_constraints()
            await graph.clear_all_data()
            await graph.ensure_indices()
            input("\n[bold yellow]Press Enter to proceed to Data ingestion phase...[/bold yellow]")
            timings["schema_setup"] = (time.perf_counter() - s_time) * 1000
            logger.info(f"Schema setup finished. Duration: {timings['schema_setup']:.2f} ms")

            logger.info(f"Data ingestion started at: {get_current_time_ms()}")
            ingestion_start_time = time.perf_counter()
            for i, source_set_info in enumerate(source_data_sets):
                current_source_name = source_set_info.get("name", f"unknown_source_{i+1}")
                logger.info(f"Ingesting source: {current_source_name}")
                s_item_time = time.perf_counter()
                await graph.add_documents_from_source(source_data_block=source_set_info)
                timings[f"ingestion_{current_source_name}"] = (time.perf_counter() - s_item_time) * 1000
            timings["data_ingestion_total"] = (time.perf_counter() - ingestion_start_time) * 1000
            logger.info(f"Data ingestion finished. Duration: {timings['data_ingestion_total']:.2f} ms")
            logger.info("\n--- All document sets processed for ingestion ---")
            input("\n[bold yellow]Data ingestion complete. Press Enter to proceed to DELETION phase...[/bold yellow]")
        else:
            logger.info("Skipping data ingestion as `run_data_ingestion_before_delete` is False.")
            s_time = time.perf_counter()
            await graph.ensure_indices() # Still ensure indices are up-to-date
            timings["ensure_indices_standalone"] = (time.perf_counter() - s_time) * 1000
            logger.info(f"Ensured indices (standalone). Duration: {timings['ensure_indices_standalone']:.2f} ms")


        # --- Deletion Phase ---
        logger.info(f"\n--- Attempting to delete source: '{source_name_to_delete}' ---")
        s_time = time.perf_counter()
        
        source_node_result_cursor = await graph.driver.execute_query( # Use execute_query which handles result processing
            "MATCH (s:Source {name: $name}) RETURN s.uuid AS uuid LIMIT 1",
            parameters_={"name": source_name_to_delete}, # Use parameters_
            database_=graph.database
        )
        timings["fetch_source_uuid"] = (time.perf_counter() - s_time) * 1000

        source_records = source_node_result_cursor[0] # Records list
        if not source_records or not source_records[0] or not source_records[0].get("uuid"):
            logger.error(f"Source '{source_name_to_delete}' not found. Cannot proceed with deletion.")
            # Log LLM Usage if any occurred during setup
            if graph:
                gen_usage = graph.get_total_generative_llm_usage()
                embed_usage = graph.get_total_embedding_usage()
                if gen_usage.has_values(): logger.info(f"Total Generative Usage: Tokens={gen_usage.total_tokens}, Requests={gen_usage.requests}")
                if embed_usage.has_values(): logger.info(f"Total Embedding Usage: Tokens={embed_usage.total_tokens}, Requests={embed_usage.requests}")
            return
        
        source_uuid_to_delete = source_records[0]["uuid"]
        logger.info(f"Found Source UUID '{source_uuid_to_delete}' for name '{source_name_to_delete}'.")

        s_time = time.perf_counter()
        deletion_summary: Optional[Dict[str, int]] = None
        try:
            # Using the GraphForRAG method which calls NodeManager
            deletion_summary = await graph.delete_source(source_uuid_to_delete) 
            
            timings["delete_source_operation"] = (time.perf_counter() - s_time) * 1000
            logger.info(f"Deletion operation for source '{source_name_to_delete}' (UUID: {source_uuid_to_delete}) completed in {timings['delete_source_operation']:.2f} ms.")
            if deletion_summary:
                logger.info(f"Deletion summary: {deletion_summary}")
            else:
                logger.warning("Deletion operation did not return a summary.")


            logger.info("Verify in Neo4j Browser that the source and its derived data are gone or correctly handled.")
            logger.info("Check for orphaned nodes or unexpected remaining relationships.")

        except Exception as e_delete:
            timings["delete_source_operation_error"] = (time.perf_counter() - s_time) * 1000
            logger.error(f"Error during source deletion: {e_delete}", exc_info=True)
            logger.error(f"Deletion operation for source '{source_name_to_delete}' failed after {timings.get('delete_source_operation_error', 0):.2f} ms.")


        # Log LLM Usage
        gen_usage = graph.get_total_generative_llm_usage()
        embed_usage = graph.get_total_embedding_usage()
        if gen_usage.has_values(): logger.info(f"Total Generative Usage: Tokens={gen_usage.total_tokens}, Requests={gen_usage.requests}")
        if embed_usage.has_values(): logger.info(f"Total Embedding Usage: Tokens={embed_usage.total_tokens}, Requests={embed_usage.requests}")


    except Exception as e:
        logger.error(f"An error occurred in main execution: {e}", exc_info=True)
    finally:
        if graph:
            s_time = time.perf_counter()
            await graph.close()
            timings["graph_close"] = (time.perf_counter() - s_time) * 1000
        
        main_end_time = time.perf_counter()
        timings["total_main_execution"] = (main_end_time - main_start_time) * 1000
        logger.info(f"\n[bold cyan]--- TIMING SUMMARY (ms) ---[/bold cyan]")
        for operation, duration in timings.items():
            logger.info(f"{operation:<45}: {duration:>10.2f} ms")
        logger.info(f"Source Deletion Test - Main execution finished at: {get_current_time_ms()}. Total duration: {timings['total_main_execution']:.2f} ms")

if __name__ == "__main__":
    asyncio.run(main())