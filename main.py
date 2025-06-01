# main.py
from graphforrag_core.graphforrag import GraphForRAG
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from data.source_data import source_data_sets # <-- MODIFIED: Import from new data file

from dotenv import load_dotenv
import os
import logging
from rich import traceback
from rich.logging import RichHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False)],
)
logger = logging.getLogger("graph_for_rag_main")
traceback.install()

async def main():
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
        
        await graph.clear_all_known_indexes_and_constraints()
        await graph.clear_all_data()                        
        
        await graph.ensure_indices()

        for source_set_info in source_data_sets:
            source_id = source_set_info["identifier"]
            source_content_for_node = source_set_info.get("source_content")
            # Directly use the list of chunk dictionaries
            chunks_for_source = source_set_info["chunks"] # <-- MODIFIED: This is now a list of dicts
            dynamic_metadata_for_source = source_set_info["source_metadata"]

            await graph.add_documents_from_source( # Method name is now a bit of a misnomer, but we can refactor later
                source_identifier=source_id,
                # documents parameter now expects list of dicts
                documents_data=chunks_for_source, # <-- MODIFIED: Pass the list of dicts
                source_content=source_content_for_node,
                source_dynamic_metadata=dynamic_metadata_for_source
            )

        logger.info("\n--- All document sets processed ---")

    except Exception as e:
        logger.error(f"An error occurred in main execution: {e}", exc_info=True)
    finally:
        if graph:
            await graph.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())