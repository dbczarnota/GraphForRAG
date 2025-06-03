# main.py
from graphforrag_core.graphforrag import GraphForRAG
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from data.source_data import source_data_sets 
from graphforrag_core.search_types import (
    SearchConfig, 
    ChunkSearchConfig, ChunkSearchMethod, ChunkRerankerMethod, 
    EntitySearchConfig, EntitySearchMethod, EntityRerankerMethod, 
    RelationshipSearchConfig, RelationshipSearchMethod, RelationshipRerankerMethod,
    CombinedSearchResults, SearchResultItem
)
from dotenv import load_dotenv
import os
import logging
from rich import traceback
from rich.logging import RichHandler
from datetime import datetime # Import datetime
import time # Import time for performance measurement

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d - %(message)s", # Added milliseconds to asctime
    datefmt="%Y-%m-%d %H:%M:%S", # Kept datefmt simple, as asctime now handles ms
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False)],
)
logger = logging.getLogger("graph_for_rag_main")
traceback.install()

def get_current_time_ms() -> str:
    """Returns current time as a string with milliseconds."""
    return datetime.now().isoformat(sep=' ', timespec='milliseconds')

async def main():
    logger.info(f"[bold cyan]Main execution started at: {get_current_time_ms()}[/bold cyan]")
    main_start_time = time.perf_counter() # For overall duration

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
        
        # --- Schema and Data Setup (Uncomment if needed) ---
        logger.info(f"Schema/Data setup started at: {get_current_time_ms()}")
        setup_start_time = time.perf_counter()
        await graph.clear_all_known_indexes_and_constraints()
        await graph.clear_all_data()                        
        await graph.ensure_indices()
        setup_end_time = time.perf_counter()
        logger.info(f"Schema/Data setup finished at: {get_current_time_ms()}. Duration: {(setup_end_time - setup_start_time):.4f} seconds")

        # --- Data Ingestion (Uncomment if needed) ---
        logger.info(f"Data ingestion started at: {get_current_time_ms()}")
        ingestion_start_time = time.perf_counter()
        for source_set_info in source_data_sets:
            source_id = source_set_info["identifier"]
            source_content_for_node = source_set_info.get("source_content")
            chunks_for_source = source_set_info["chunks"] 
            dynamic_metadata_for_source = source_set_info["source_metadata"]
            await graph.add_documents_from_source(
                source_identifier=source_id,
                documents_data=chunks_for_source,
                source_content=source_content_for_node,
                source_dynamic_metadata=dynamic_metadata_for_source
            )
        ingestion_end_time = time.perf_counter()
        logger.info(f"Data ingestion finished at: {get_current_time_ms()}. Duration: {(ingestion_end_time - ingestion_start_time):.4f} seconds")
        logger.info("\n--- All document sets processed ---")
        
        # --- Combined Chunk, Entity, AND Relationship Search Test ---
        logger.info(f"\n--- Starting Full Combined Search Test at: {get_current_time_ms()} ---")
        search_op_start_time = time.perf_counter()
        
        full_search_query = "Pooh Bear stuck in Rabbit's front door eating honey" 
        
        my_overall_search_config = SearchConfig(
            chunk_config=ChunkSearchConfig(
                search_methods=[ChunkSearchMethod.KEYWORD, ChunkSearchMethod.SEMANTIC],
                limit=3, min_similarity_score=0.5, keyword_fetch_limit=10, semantic_fetch_limit=10, rrf_k=60
            ),
            entity_config=EntitySearchConfig(
                search_methods=[EntitySearchMethod.KEYWORD_NAME_DESC, EntitySearchMethod.SEMANTIC_NAME, EntitySearchMethod.SEMANTIC_DESCRIPTION],
                limit=4, min_similarity_score_name=0.6, min_similarity_score_description=0.5, keyword_fetch_limit=10, semantic_name_fetch_limit=10, semantic_description_fetch_limit=10, rrf_k=60
            ),
            relationship_config=RelationshipSearchConfig(
                search_methods=[RelationshipSearchMethod.KEYWORD_FACT, RelationshipSearchMethod.SEMANTIC_FACT],
                limit=3, min_similarity_score=0.6, keyword_fetch_limit=10, semantic_fetch_limit=10, rrf_k=60
            )
        )
        
        logger.info(f"Executing full combined search for: '{full_search_query}' with config: {my_overall_search_config.model_dump_json(indent=2, exclude_none=True)}")
        combined_results: CombinedSearchResults = await graph.search(
            full_search_query, 
            config=my_overall_search_config
        )
        
        search_op_end_time = time.perf_counter()
        logger.info(f"Search operation finished at: {get_current_time_ms()}. Duration: {(search_op_end_time - search_op_start_time):.4f} seconds")

        if combined_results.items:
            logger.info(f"Found {len(combined_results.items)} combined results for '{full_search_query}':")
            for i, item in enumerate(combined_results.items):
                logger.info(f"  --- Result {i+1} ---")
                logger.info(f"    Type: {item.result_type}")
                logger.info(f"    UUID: {item.uuid}")
                logger.info(f"    Name/Label: {item.name if item.name else 'N/A'}")
                logger.info(f"    Score (RRF): {item.score:.4f}")
                if item.result_type == "Chunk":
                    logger.info(f"      Chunk Content Preview: {item.content[:100] if item.content else 'N/A'}...")
                    logger.info(f"      Chunk Source: {item.metadata.get('source_description', 'N/A')}")
                    logger.info(f"      Chunk Number: {item.metadata.get('chunk_number', 'N/A')}")
                elif item.result_type == "Entity":
                    logger.info(f"      Entity Description: {item.description[:100] if item.description else 'N/A'}...")
                    logger.info(f"      Entity Neo4j Label: {item.label if item.label else 'N/A'}")
                elif item.result_type == "Relationship":
                    logger.info(f"      Fact Sentence: {item.fact_sentence if item.fact_sentence else 'N/A'}")
                    logger.info(f"      Source Entity UUID: {item.source_entity_uuid if item.source_entity_uuid else 'N/A'}")
                    logger.info(f"      Target Entity UUID: {item.target_entity_uuid if item.target_entity_uuid else 'N/A'}")
                # logger.info(f"    Original Search Score (Metadata): {item.metadata.get('original_search_score', 'N/A')}") # Can be verbose
        else:
            logger.info(f"No combined results found for '{full_search_query}'.")

        logger.info(f"--- Full Combined Search Test Complete at: {get_current_time_ms()} ---")
        
        
        # Log total usage (as before)
        total_usage = graph.get_total_llm_usage()
        if total_usage and total_usage.has_values():
            details = (f"Requests: {total_usage.requests}, Request Tokens: {total_usage.request_tokens or 0}, Response Tokens: {total_usage.response_tokens or 0}, Total Tokens: {total_usage.total_tokens or 0}")
            logger.info(f"[bold magenta]Overall LLM Usage:[/bold magenta] {details}")
        else:
            logger.info("[bold magenta]Overall LLM Usage:[/bold magenta] No usage data reported.")

    except Exception as e:
        logger.error(f"An error occurred in main execution: {e}", exc_info=True)
    finally:
        if graph:
            await graph.close()
        main_end_time = time.perf_counter()
        logger.info(f"[bold cyan]Main execution finished at: {get_current_time_ms()}. Total duration: {(main_end_time - main_start_time):.4f} seconds[/bold cyan]")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())