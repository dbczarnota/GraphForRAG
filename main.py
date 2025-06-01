from graphforrag_core.graphforrag import GraphForRAG
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig # Import embedder
from data.langchain_documents_hardcoded import source_data_sets

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
logger = logging.getLogger("graph_for_rag_main") # Differentiate main logger
traceback.install()

async def main():
    load_dotenv()
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password')
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") # For the embedder

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found in environment variables. Cannot initialize OpenAIEmbedder.")
        return

    graph = None
    try:
        
        # Configure and initialize the embedder
        # You can choose different models and dimensions here
        embedder_config = OpenAIEmbedderConfig(
            api_key=OPENAI_API_KEY,
            model_name="text-embedding-3-small", # Or "text-embedding-ada-002"
            embedding_dimension=768 # Ensure this matches your desired vector index dimension
        )
        openai_embedder = OpenAIEmbedder(config=embedder_config)

        # Initialize GraphForRAG with the embedder
        graph = GraphForRAG(
            NEO4J_URI,
            NEO4J_USER,
            NEO4J_PASSWORD,
            embedder_client=openai_embedder # Pass the embedder instance
        )
        
        # Example: Clean up before starting
        # Be very careful with these on a real database!
        await graph.clear_all_known_indexes_and_constraints() # Drop our specific schema
        await graph.clear_all_data()                        # Delete all data
        
        # Ensure indices are set up
        await graph.ensure_indices()

        # Proceed with adding documents
        for source_set_info in source_data_sets:
            source_id = source_set_info["identifier"]
            docs_for_source = source_set_info["documents"]
            dynamic_metadata_for_source = source_set_info["source_metadata"]

            await graph.add_documents_from_source(
                source_identifier=source_id,
                documents=docs_for_source,
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