# graphforrag_core/graphforrag.py
import logging
import uuid
from datetime import datetime, timezone
import json
from typing import Optional, Any, List, Tuple, Dict 

from neo4j import AsyncGraphDatabase, AsyncDriver # type: ignore
from .embedder_client import EmbedderClient
from .openai_embedder import OpenAIEmbedder
from .schema_manager import SchemaManager
from .entity_extractor import EntityExtractor
from .entity_resolver import EntityResolver
from .relationship_extractor import RelationshipExtractor
from .node_manager import NodeManager
from files.llm_models import setup_fallback_model
from pydantic_ai.usage import Usage
# Removed pydantic BaseModel import as ResolvedEntityInfo is moved
# from pydantic import BaseModel # REMOVE THIS LINE

# Import the new knowledge base building function
from .build_knowledge_base import add_documents_to_knowledge_base 
# Import ResolvedEntityInfo from the new types file
from .types import ResolvedEntityInfo # ADDED THIS LINE

logger = logging.getLogger("graph_for_rag")

# ResolvedEntityInfo class definition is REMOVED from here

class GraphForRAG:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        embedder_client: Optional[EmbedderClient] = None,
        llm_client: Optional[Any] = None
    ):
        try:
            self.driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=(user, password)) # type: ignore
            self.database: str = database
            
            if embedder_client:
                self.embedder = embedder_client
            else:
                logger.info("No embedder client provided to GraphForRAG, defaulting to OpenAIEmbedder.")
                self.embedder = OpenAIEmbedder()
            
            self.services_llm_client = llm_client if llm_client else setup_fallback_model()

            self.entity_extractor = EntityExtractor(llm_client=self.services_llm_client)
            self.entity_resolver = EntityResolver( 
                driver=self.driver,
                database_name=self.database,
                embedder_client=self.embedder,
                llm_client=self.services_llm_client
            )
            self.relationship_extractor = RelationshipExtractor(llm_client=self.services_llm_client)
            
            self.schema_manager = SchemaManager(self.driver, self.database, self.embedder)
            self.node_manager = NodeManager(self.driver, self.database)
            
            self.total_llm_usage: Usage = Usage()

            logger.info(f"Using embedder: {self.embedder.config.model_name} with dimension {self.embedder.dimension}")
            
            services_llm_model_name = "Unknown"
            if hasattr(self.services_llm_client, 'model') and isinstance(self.services_llm_client.model, str):
                services_llm_model_name = self.services_llm_client.model
            elif hasattr(self.services_llm_client, 'model_name') and isinstance(self.services_llm_client.model_name, str):
                services_llm_model_name = self.services_llm_client.model_name
            elif hasattr(self.services_llm_client, 'models') and isinstance(self.services_llm_client.models, list) and self.services_llm_client.models: 
                first_model_in_fallback = self.services_llm_client.models[0]
                if hasattr(first_model_in_fallback, 'model') and isinstance(first_model_in_fallback.model, str):
                    services_llm_model_name = f"Fallback starting with: {first_model_in_fallback.model}"
                elif hasattr(first_model_in_fallback, 'model_name') and isinstance(first_model_in_fallback.model_name, str):
                    services_llm_model_name = f"Fallback starting with: {first_model_in_fallback.model_name}"
                else:
                    services_llm_model_name = "Fallback (model name unretrievable)"

            logger.info(f"GraphForRAG initialized. LLM for Entity/Relationship Services: {services_llm_model_name}")
            logger.info(f"Successfully initialized Neo4j driver for database '{database}' at '{uri}'")
        except Exception as e:
            logger.error(f"Failed to initialize GraphForRAG: {e}", exc_info=True)
            raise

    def _accumulate_usage(self, new_usage: Optional[Usage]):
        if new_usage and hasattr(new_usage, 'has_values') and new_usage.has_values():
            self.total_llm_usage = self.total_llm_usage + new_usage # type: ignore
    
    def get_total_llm_usage(self) -> Usage: # type: ignore
        return self.total_llm_usage

    async def close(self):
        if self.driver:
            await self.driver.close()
            logger.info("Neo4j driver closed.")

    async def ensure_indices(self):
        await self.schema_manager.ensure_indices_and_constraints()

    async def clear_all_data(self):
        await self.schema_manager.clear_all_data()

    async def clear_all_known_indexes_and_constraints(self):
        await self.schema_manager.clear_all_known_indexes_and_constraints()
    
    async def add_documents_from_source(
        self,
        source_identifier: str,
        documents_data: List[dict], 
        source_content: Optional[str] = None,
        source_dynamic_metadata: Optional[dict] = None,
        allow_same_name_chunks_for_this_source: bool = True
    ) -> Tuple[Optional[str], List[str]]:
        source_node_uuid, added_chunk_uuids, usage_for_set = await add_documents_to_knowledge_base(
            source_identifier=source_identifier,
            documents_data=documents_data,
            node_manager=self.node_manager,
            embedder=self.embedder,
            entity_extractor=self.entity_extractor,
            entity_resolver=self.entity_resolver,
            relationship_extractor=self.relationship_extractor,
            source_content=source_content,
            source_dynamic_metadata=source_dynamic_metadata,
            allow_same_name_chunks_for_this_source=allow_same_name_chunks_for_this_source
        )
        self._accumulate_usage(usage_for_set)
        return source_node_uuid, added_chunk_uuids