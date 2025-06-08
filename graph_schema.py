from graphforrag_core.graphforrag import GraphForRAG
from dotenv import load_dotenv
import os
import logging
from rich.logging import RichHandler
import textwrap
import asyncio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[RichHandler(rich_tracebacks=True, markup=True, show_path=False, log_time_format="[%X.%f]")],
)
logger = logging.getLogger("graph_schema")


async def main():
    load_dotenv()
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password')
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found in environment variables. Cannot initialize OpenAIEmbedder.")
        return

    graph = GraphForRAG(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    schema_text = await graph.get_schema()
    logger.info("SCHEMA:")
    logger.info(textwrap.fill(schema_text, 60))
    await graph.close()


if __name__ == "__main__":
    asyncio.run(main())
