import asyncio
import os
from dotenv import load_dotenv
from graphforrag_core.graphforrag import GraphForRAG
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("schema_manager_cli")

async def run_ensure_indices():
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

        graph = GraphForRAG(
            NEO4J_URI,
            NEO4J_USER,
            NEO4J_PASSWORD,
            embedder_client=openai_embedder
        )
        logger.info("Attempting to ensure indices and constraints...")
        await graph.ensure_indices() # Calls the method in GraphForRAG
        logger.info("Schema update process complete.")
    except Exception as e:
        logger.error(f"Error during schema management: {e}", exc_info=True)
    finally:
        if graph:
            await graph.close()

if __name__ == "__main__":
    asyncio.run(run_ensure_indices())