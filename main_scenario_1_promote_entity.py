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

# --- Minimal Data Setup ---

# Text chunk that mentions "Dell XPS 13"
# Taken from "Navigating the World of Personal Computers: 2024 Edition"
TEXT_CHUNK_FOR_ENTITY_CREATION = {
    "page_content": "Laptops masterfully blend portability with impressive performance, catering to a vast audience. Ultrabooks like the Dell XPS 13 (2024 model) and Apple's MacBook Air with the M3 chip are celebrated for their sleek designs, lightweight construction, and extended battery life, making them ideal for students, writers, and mobile professionals.",
    "metadata": {
        "name": "Minimal Guide - Laptops Excerpt", 
        "chunk_number": 1, 
        "keywords": ["laptops", "ultrabooks", "Dell XPS 13", "MacBook Air M3"]
    }
}

MINIMAL_TEXT_SOURCE = {
    "identifier": "Minimal_PC_Guide_Excerpt_Source",
    "source_content": "A minimal excerpt from a PC guide focusing on laptops.",
    "source_metadata": {"author": "Test Data Generator", "category": "Minimal Test Data"},
    "chunks": [TEXT_CHUNK_FOR_ENTITY_CREATION]
}

# Product definition for "Dell XPS 13"
# Taken from "Q3 2024 Tech Product Showcase"
PRODUCT_DEFINITION_DELL_XPS_13 = {
    "node_type": "product",
    "content_type": "json",
    "page_content": json.dumps({ 
        "productName": "Dell XPS 13 (2024 Model 9340)", 
        "brand": "Dell", "category": "Ultrabook Laptop", "sku": "DEL-XPS13-9340-I716512",
        "release_year": 2024, "price_usd": 1299.00,
        "features": ["Intel Core Ultra 7 processor", "13.4-inch InfinityEdge display"], 
        "description": "The Dell XPS 13 (2024) continues its legacy of premium design and performance...",
        "specifications": { "processor": "Intel Core Ultra 7 155H", "memory_gb_lpddr5x": "16GB" } 
    }),
    "metadata": { 
        "name": "Dell XPS 13 (2024) - Minimal Product Def", 
        "description": "Minimal product definition for Dell XPS 13.", 
        "brand_category": "Dell Laptop", "target_audience": "Professionals"
    }
}

MINIMAL_PRODUCT_SOURCE = {
    "identifier": "Minimal_Product_Showcase_Dell_XPS_13_Source",
    "source_content": "A minimal product definition for Dell XPS 13.",
    "source_metadata": {"catalog_version": "minimal.1.0", "prepared_by": "Test Data Generator"},
    "chunks": [PRODUCT_DEFINITION_DELL_XPS_13]
}


async def main():
    logger.info("[bold cyan]Scenario 1 (Minimal Data): Promote Entity to Product - Test Started[/bold cyan]")
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

        # --- Part 1: Ingest Minimal Text Data to create "Dell XPS 13" as an Entity ---
        logger.info("\n--- Ingesting Minimal Text Data ---")
        await graph.add_documents_from_source(
            source_identifier=MINIMAL_TEXT_SOURCE["identifier"],
            documents_data=MINIMAL_TEXT_SOURCE["chunks"],
            source_content=MINIMAL_TEXT_SOURCE.get("source_content"),
            source_dynamic_metadata=MINIMAL_TEXT_SOURCE["source_metadata"]
        )
        logger.info(f"Finished ingesting '{MINIMAL_TEXT_SOURCE['identifier']}'.")
        logger.info("Verify in Neo4j: An :Entity node for 'Dell XPS 13 (2024 model)' (or similar) should exist.")
        # You can add an input("Press Enter...") here if you want to pause and check Neo4j manually
        # input("Press Enter to continue to Product Ingestion phase...")


        # --- Part 2: Ingest Minimal Product Definition for "Dell XPS 13" ---
        logger.info("\n--- Ingesting Minimal Product Data (Dell XPS 13) ---")
        await graph.add_documents_from_source(
            source_identifier=MINIMAL_PRODUCT_SOURCE["identifier"],
            documents_data=MINIMAL_PRODUCT_SOURCE["chunks"],
            source_content=MINIMAL_PRODUCT_SOURCE.get("source_content"),
            source_dynamic_metadata=MINIMAL_PRODUCT_SOURCE["source_metadata"]
        )
        logger.info("Finished ingesting Dell XPS 13 minimal product definition.")
        logger.info("Verify in Neo4j: The :Entity for 'Dell XPS 13' should be GONE, and a :Product node should exist, with relationships transferred (if any existed).")
        
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
        logger.info(f"Scenario 1 (Minimal Data) finished in {(time.perf_counter() - main_start_time):.2f} seconds.")

if __name__ == "__main__":
    asyncio.run(main())