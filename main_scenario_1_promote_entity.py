# main_scenario_1_promote_entity.py
# Objective: Test promotion of an existing :Entity to a :Product with minimal data.
# 1. Ingest ONE text chunk that creates an :Entity (e.g., "Dell XPS 13").
# 2. Ingest ONE product definition for "Dell XPS 13", which should promote the :Entity.

from graphforrag_core.graphforrag import GraphForRAG
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from data.source_data import source_data_sets as all_source_data_sets # Keep access to full data
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
import json # For product page_content

# --- Logging Setup ---
LOG_LEVEL = logging.DEBUG 
logging.getLogger("graph_for_rag").setLevel(LOG_LEVEL)
logging.getLogger("graph_for_rag.build_knowledge_base").setLevel(LOG_LEVEL)
logging.getLogger("graph_for_rag.node_manager").setLevel(LOG_LEVEL)
logging.getLogger("graph_for_rag.entity_resolver").setLevel(LOG_LEVEL)
logging.getLogger("graph_for_rag.entity_extractor").setLevel(LOG_LEVEL)
logging.getLogger("llm_models").setLevel(logging.INFO) 

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s", 
    datefmt="%Y-%m-%d %H:%M:%S", 
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False, log_time_format="[%X.%f]")],
)
logger = logging.getLogger("graph_for_rag_scenario_1_minimal") 
traceback.install()



async def main():
    logger.info("[bold cyan]Scenario 1: Promote Entity & General Ingestion Test - Started[/bold cyan]") # Updated log message
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

        # --- Ingest data from all_source_data_sets (excluding Winnie-the-Pooh) ---
        logger.info("\n--- Ingesting Data from source_data.py ---")
        ingestion_count = 0
        for source_set in all_source_data_sets:
            source_identifier = source_set["identifier"]
            if "Winnie-the-Pooh" in source_identifier:
                logger.info(f"Skipping Winnie-the-Pooh data source: '{source_identifier}'")
                continue

            logger.info(f"Ingesting data source: '{source_identifier}'")
            await graph.add_documents_from_source(
                source_identifier=source_identifier,
                documents_data=source_set["chunks"], # Ensure 'chunks' key exists and matches source_data.py
                source_content=source_set.get("source_content"),
                source_dynamic_metadata=source_set["source_metadata"]
            )
            logger.info(f"Finished ingesting '{source_identifier}'.")
            ingestion_count += 1
        
        if ingestion_count == 0:
            logger.warning("No data sets (other than Pooh) were found or ingested. Check source_data.py.")
        else:
            logger.info(f"All {ingestion_count} selected data sets processed.")
            logger.info("Verify in Neo4j: Entities and Products should be created/promoted as expected based on the ingested data.")
        
        # Log final usage
        gen_usage = graph.get_total_generative_llm_usage()
        embed_usage = graph.get_total_embedding_usage()
        if gen_usage.has_values(): logger.info(f"Total Generative Usage: Tokens={gen_usage.total_tokens}, Requests={gen_usage.requests}")
        if embed_usage.has_values(): logger.info(f"Total Embedding Usage: Tokens={embed_usage.total_tokens}, Requests={embed_usage.requests}")

    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)
    finally:
        if graph:
            await graph.close()
        logger.info(f"Scenario 1 (Promote Entity & General Ingestion Test) finished in {(time.perf_counter() - main_start_time):.2f} seconds.")
        
        
if __name__ == "__main__":
    asyncio.run(main())