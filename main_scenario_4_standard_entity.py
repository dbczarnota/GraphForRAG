# main_scenario_4_standard_entity.py
# Objective: Test standard :Entity creation from text when no product definitions match.

from graphforrag_core.graphforrag import GraphForRAG
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from data.source_data import source_data_sets as all_source_data_sets 
from graphforrag_core.search_types import (
    SearchConfig, ChunkSearchConfig, EntitySearchConfig, 
    RelationshipSearchConfig, SourceSearchConfig, MultiQueryConfig
)
from dotenv import load_dotenv
import os
import logging
from rich import traceback
from rich.logging import RichHandler
from datetime import datetime 
import time 
import asyncio

# --- Logging Setup ---
LOG_LEVEL = logging.DEBUG
logging.getLogger("graph_for_rag").setLevel(LOG_LEVEL)
# ... other loggers ...

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s", 
    datefmt="%Y-%m-%d %H:%M:%S", 
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False, log_time_format="[%X.%f]")],
)
logger = logging.getLogger("graph_for_rag_scenario_4") 
traceback.install()

def get_source_by_identifier(identifier_substring: str):
    for source_set in all_source_data_sets:
        if identifier_substring.lower() in source_set["identifier"].lower():
            return source_set
    return None

async def main():
    logger.info("[bold cyan]Scenario 4: Standard Entity Creation - Test Started[/bold cyan]")
    main_start_time = time.perf_counter() 

    load_dotenv()
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password')
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found.")
        return

    graph = None
    try:
        embedder_config = OpenAIEmbedderConfig(api_key=OPENAI_API_KEY)
        openai_embedder = OpenAIEmbedder(config=embedder_config)
        graph = GraphForRAG(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, embedder_client=openai_embedder)

        logger.info("Clearing all data and ensuring schema for a clean test run...")
        await graph.clear_all_known_indexes_and_constraints()
        await graph.clear_all_data()
        await graph.ensure_indices()
        logger.info("Data cleared and schema ensured.")

        # --- Ingest Text Data (Winnie the Pooh) ---
        logger.info("\n--- Ingesting Text Data (Winnie the Pooh) ---")
        pooh_data = get_source_by_identifier("Winnie-the-Pooh")
        if pooh_data:
            await graph.add_documents_from_source(
                source_identifier=pooh_data["identifier"],
                documents_data=pooh_data["chunks"],
                source_content=pooh_data.get("source_content"),
                source_dynamic_metadata=pooh_data["source_metadata"]
            )
            logger.info(f"Finished ingesting '{pooh_data['identifier']}'.")
            logger.info("Verify in Neo4j: :Entity nodes (e.g., 'Winnie-the-Pooh', 'Rabbit') should be created and linked to chunks via :MENTIONS.")
        else:
            logger.error("Winnie the Pooh source data not found. Aborting.")
            return
            
        gen_usage = graph.get_total_generative_llm_usage()
        embed_usage = graph.get_total_embedding_usage()
        if gen_usage.has_values(): logger.info(f"Total Generative Usage: {gen_usage.total_tokens} tokens")
        if embed_usage.has_values(): logger.info(f"Total Embedding Usage: {embed_usage.total_tokens} tokens")

    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)
    finally:
        if graph:
            await graph.close()
        logger.info(f"Scenario 4 finished in {(time.perf_counter() - main_start_time):.2f} seconds.")

if __name__ == "__main__":
    asyncio.run(main())