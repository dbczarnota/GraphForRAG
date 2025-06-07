import asyncio
import os
from dotenv import load_dotenv
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("get_embedding_script")

async def main():
    load_dotenv()
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found in environment variables.")
        return

    text_to_embed = input("Enter the text you want to embed: ")
    if not text_to_embed.strip():
        logger.error("No text provided to embed.")
        return

    try:
        # Use the same embedder config as in your main application for consistency
        embedder_config = OpenAIEmbedderConfig(
            api_key=OPENAI_API_KEY,
            model_name="text-embedding-3-small", # Or your default
            embedding_dimension=768             # Or your default
        )
        openai_embedder = OpenAIEmbedder(config=embedder_config)

        logger.info(f"Embedding text: '{text_to_embed}' using model '{embedder_config.model_name}' with dimension {embedder_config.embedding_dimension}...")
        
        embedding_vector, usage_info = await openai_embedder.embed_text(text_to_embed)

        if embedding_vector:
            logger.info(f"Successfully generated embedding vector (length: {len(embedding_vector)}).")
            print("\nEmbedding Vector (copy this list including brackets []):\n")
            print(embedding_vector) # This will print the list to the console
            
            if usage_info:
                 logger.info(f"Embedding Usage: Total Tokens={usage_info.total_tokens}, Requests={usage_info.requests}")

        else:
            logger.error("Failed to generate embedding vector.")

    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())