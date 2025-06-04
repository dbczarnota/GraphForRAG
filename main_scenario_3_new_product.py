# main_scenario_3_new_product.py
# Objective: Test creation of a new :Product node when no matching :Entity exists.

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
logging.getLogger("graph_for_rag.build_knowledge_base").setLevel(LOG_LEVEL)
# ... other loggers ...

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s", 
    datefmt="%Y-%m-%d %H:%M:%S", 
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False, log_time_format="[%X.%f]")],
)
logger = logging.getLogger("graph_for_rag_scenario_3") 
traceback.install()

def get_source_by_identifier(identifier_substring: str):
    for source_set in all_source_data_sets:
        if identifier_substring.lower() in source_set["identifier"].lower():
            return source_set
    return None

async def main():
    logger.info("[bold cyan]Scenario 3: New Product Creation - Test Started[/bold cyan]")
    main_start_time = time.perf_counter() 

    load_dotenv() # Ensure .env is loaded
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

        # --- Ingest a unique Product Definition ---
        logger.info("\n--- Ingesting Unique Product Data (e.g., Surface Pro 9) ---")
        product_showcase_data = get_source_by_identifier("Product Showcase")
        surface_pro_item = None
        if product_showcase_data:
            for item in product_showcase_data["chunks"]:
                if item.get("node_type") == "product" and \
                   "Surface Pro 9" in item.get("metadata", {}).get("name", ""):
                    surface_pro_item = item
                    break
        
        if product_showcase_data and surface_pro_item:
            temp_product_source = {
                "identifier": f"{product_showcase_data['identifier']} - Surface Pro 9 Only",
                "source_content": product_showcase_data.get("source_content"),
                "source_metadata": product_showcase_data["source_metadata"],
                "chunks": [surface_pro_item]
            }
            await graph.add_documents_from_source(
                source_identifier=temp_product_source["identifier"],
                documents_data=temp_product_source["chunks"],
                source_content=temp_product_source.get("source_content"),
                source_dynamic_metadata=temp_product_source["source_metadata"]
            )
            logger.info("Finished ingesting Surface Pro 9 product definition.")
            logger.info("Verify in Neo4j: A :Product node for 'Microsoft Surface Pro 9' should exist. EntityResolver logs should show no existing entity candidate was found for promotion.")
        else:
            logger.error("Product Showcase data or specific Surface Pro 9 product item not found. Aborting.")
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
        logger.info(f"Scenario 3 finished in {(time.perf_counter() - main_start_time):.2f} seconds.")

if __name__ == "__main__":
    asyncio.run(main())