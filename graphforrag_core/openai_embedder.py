# C:\Users\czarn\Documents\A_PYTHON\GraphForRAG\graphforrag_core\openai_embedder.py
import os
from typing import List
from openai import AsyncOpenAI # Use AsyncOpenAI
from .embedder_client import EmbedderClient, EmbedderConfig, DEFAULT_EMBEDDING_DIMENSION

# It's good practice to load API keys from environment variables
# Ensure OPENAI_API_KEY is set in your .env file
# load_dotenv() # Handled in main.py or globally

class OpenAIEmbedderConfig(EmbedderConfig):
    model_name: str = "text-embedding-3-small" # OpenAI's newer small model
    # text-embedding-3-small default output is 1536, but can be reduced
    # Let's set a default dimension we want to use, e.g. 768
    # If you use "text-embedding-ada-002", its dimension is 1536
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION # Default for our example
    api_key: str | None = None
    base_url: str | None = None


class OpenAIEmbedder(EmbedderClient):
    def __init__(self, config: OpenAIEmbedderConfig = OpenAIEmbedderConfig()):
        super().__init__(config)
        # Ensure config is specifically OpenAIEmbedderConfig for type hinting
        self.config: OpenAIEmbedderConfig = config
        
        api_key_to_use = self.config.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key_to_use:
            raise ValueError("OpenAI API key not found. Set OPENAI_API_KEY environment variable or pass via config.")

        self.client = AsyncOpenAI(
            api_key=api_key_to_use,
            base_url=self.config.base_url # For Azure OpenAI or custom endpoints
        )
        # Update dimension if model is known to have a different default output before truncation
        if self.config.model_name == "text-embedding-ada-002":
            self._openai_native_dimension = 1536
        elif self.config.model_name == "text-embedding-3-small":
             self._openai_native_dimension = 1536 # Its default output
        elif self.config.model_name == "text-embedding-3-large":
             self._openai_native_dimension = 3072
        else: # Default or unknown, assume it can output desired dimension or will be truncated
             self._openai_native_dimension = self.config.embedding_dimension


    async def embed_text(self, text: str) -> List[float]:
        embeddings = await self.embed_texts([text])
        return embeddings[0]

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        texts_to_embed = [t.replace("\n", " ") for t in texts]
        try:
            # For models like text-embedding-3-small, you can request a specific dimension
            # For ada-002, it always returns 1536, so we'd truncate if config.embedding_dimension is smaller
            if "text-embedding-3" in self.config.model_name:
                response = await self.client.embeddings.create(
                    input=texts_to_embed, 
                    model=self.config.model_name,
                    dimensions=self.config.embedding_dimension # Request specific dimension
                 )
            else: # For older models like ada-002 or others not supporting 'dimensions' param
                 response = await self.client.embeddings.create(
                    input=texts_to_embed, 
                    model=self.config.model_name
                 )

            return [
                embedding.embedding[:self.config.embedding_dimension] 
                for embedding in response.data
            ]
        except Exception as e:
            # logger.error(f"Error getting embeddings from OpenAI: {e}", exc_info=True) # Use logger from GraphForRAG
            raise