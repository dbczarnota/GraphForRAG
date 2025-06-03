# C:\Users\czarn\Documents\A_PYTHON\GraphForRAG\graphforrag_core\embedder_client.py
from abc import ABC, abstractmethod
from typing import List, Union, Iterable, Tuple, Optional # Added Tuple, Optional
from pydantic import BaseModel, Field
from pydantic_ai.usage import Usage # Import Usage

DEFAULT_EMBEDDING_DIMENSION = 768 # Example, can be changed

class EmbedderConfig(BaseModel):
    embedding_dimension: int = Field(default=DEFAULT_EMBEDDING_DIMENSION)
    model_name: str = Field(default="default_model") # For identification

class EmbedderClient(ABC):
    config: EmbedderConfig

    def __init__(self, config: EmbedderConfig):
        self.config = config

    @abstractmethod
    async def embed_text(self, text: str) -> Tuple[List[float], Optional[Usage]]: # MODIFIED return type
        pass

    @abstractmethod
    async def embed_texts(self, texts: List[str]) -> Tuple[List[List[float]], Optional[Usage]]: # MODIFIED return type
        pass

    @property
    def dimension(self) -> int:
        return self.config.embedding_dimension