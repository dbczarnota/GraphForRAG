# graphforrag_core/entity_resolver.py
# ... (imports, including Usage) ...
import logging
import json
from typing import Optional, Any, List, Tuple # <-- ADDED Tuple

from neo4j import AsyncDriver # type: ignore
from pydantic_ai import Agent
from pydantic_ai.usage import Usage # Assuming this import works

from config import cypher_queries 
from config.llm_prompts import ( 
    ExtractedEntity, 
    ExistingEntityCandidate,
    EntityDeduplicationDecision,
    ENTITY_DEDUPLICATION_SYSTEM_PROMPT,
    ENTITY_DEDUPLICATION_USER_PROMPT_TEMPLATE
)
from .embedder_client import EmbedderClient
from files.llm_models import setup_fallback_model 

logger = logging.getLogger("graph_for_rag.entity_resolver")
# ... (DEFAULT_SIMILARITY_THRESHOLD, DEFAULT_TOP_K_CANDIDATES) ...
DEFAULT_SIMILARITY_THRESHOLD = 0.85 
DEFAULT_TOP_K_CANDIDATES = 5       

class EntityResolver:
    # ... (__init__ and _find_similar_existing_entities remain the same) ...
    def __init__(
        self,
        driver: AsyncDriver,
        database_name: str,
        embedder_client: EmbedderClient,
        llm_client: Optional[Any] = None, 
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        top_k_candidates: int = DEFAULT_TOP_K_CANDIDATES
    ):
        self.driver = driver
        self.database = database_name
        self.embedder = embedder_client
        self.similarity_threshold = similarity_threshold
        self.top_k_candidates = top_k_candidates

        if llm_client:
            self.llm_client = llm_client
        else:
            logger.info("No LLM client provided to EntityResolver, setting up default fallback model.")
            self.llm_client = setup_fallback_model()

        self.deduplication_agent = Agent(
            output_type=EntityDeduplicationDecision,
            model=self.llm_client,
            system_prompt=ENTITY_DEDUPLICATION_SYSTEM_PROMPT
        )
        model_name_for_log = "Unknown"
        if hasattr(self.llm_client, 'model') and isinstance(self.llm_client.model, str):
            model_name_for_log = self.llm_client.model
        elif hasattr(self.llm_client, 'model_name') and isinstance(self.llm_client.model_name, str):
             model_name_for_log = self.llm_client.model_name
        logger.info(f"EntityResolver initialized with LLM: {model_name_for_log}")


    async def _find_similar_existing_entities(self, entity_name: str) -> List[ExistingEntityCandidate]:
        if not entity_name:
            return []
        
        try:
            embedding_vector = await self.embedder.embed_text(entity_name)
            if not embedding_vector:
                logger.warning(f"Could not generate embedding for new entity name: '{entity_name}'")
                return []

            vector_index_name = "entity_name_embedding_vector" 

            params = {
                "index_name_param": vector_index_name,
                "top_k_param": self.top_k_candidates,
                "embedding_vector_param": embedding_vector,
                "min_similarity_score_param": self.similarity_threshold
            }
            
            results, _, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.FIND_SIMILAR_ENTITIES_BY_VECTOR,
                params,
                database_=self.database
            )
            
            candidates = [
                ExistingEntityCandidate(
                    uuid=record["uuid"],
                    name=record["name"],
                    label=record["label"],
                    description=record.get("description") 
                ) for record in results
            ]
            logger.debug(f"Found {len(candidates)} similar entity candidates for '{entity_name}'.")
            return candidates
        except Exception as e:
            logger.error(f"Error finding similar entities for '{entity_name}': {e}", exc_info=True)
            return []

    async def resolve_entity(
        self, new_entity: ExtractedEntity
    ) -> Tuple[EntityDeduplicationDecision, Optional[Usage]]: # <-- MODIFIED return type
        # ... (logic before LLM call for existing_candidates remains the same)
        logger.debug(f"Resolving entity: Name='{new_entity.name}', Label='{new_entity.label}'")
        existing_candidates = await self._find_similar_existing_entities(new_entity.name)
        
        fallback_decision = EntityDeduplicationDecision(
            is_duplicate=False, 
            duplicate_of_uuid=None, 
            canonical_name=new_entity.name,
            # canonical_description might come from new_entity.description if no LLM call
            canonical_description=new_entity.description 
        )

        if not existing_candidates:
            logger.debug("No similar existing candidates found. Treating as new entity.")
            return fallback_decision, None # No LLM call, so no usage from this agent

        # ... (user_prompt preparation remains the same) ...
        candidates_json_string_list = [
            json.dumps(cand.model_dump(exclude_none=True)) for cand in existing_candidates
        ]
        existing_candidates_prompt_str = "\n".join(
            f"- Candidate {idx+1}: {json_str}" for idx, json_str in enumerate(candidates_json_string_list)
        )
        if not existing_candidates_prompt_str:
             existing_candidates_prompt_str = "No semantically similar candidates found in the knowledge graph."
        user_prompt = ENTITY_DEDUPLICATION_USER_PROMPT_TEMPLATE.format(
            new_entity_name=new_entity.name,
            new_entity_label=new_entity.label,
            new_entity_description=new_entity.description or "No description provided.",
            existing_candidates_json_string=existing_candidates_prompt_str
        )
        logger.debug(f"Attempting entity deduplication with LLM. New: '{new_entity.name}'. Candidates: {[c.name for c in existing_candidates]}")

        current_op_usage: Optional[Usage] = None
        try:
            agent_result_object = await self.deduplication_agent.run(user_prompt=user_prompt)
            
            if agent_result_object and hasattr(agent_result_object, 'usage'):
                if isinstance(agent_result_object.usage, Usage):
                    current_op_usage = agent_result_object.usage
                elif callable(agent_result_object.usage):
                    try:
                        usage_data_from_method = agent_result_object.usage()
                        if isinstance(usage_data_from_method, Usage):
                             current_op_usage = usage_data_from_method
                    except Exception:
                        pass

            if agent_result_object and hasattr(agent_result_object, 'output'):
                if isinstance(agent_result_object.output, EntityDeduplicationDecision):
                    decision = agent_result_object.output
                    return decision, current_op_usage
                else:
                    logger.error(f"Deduplication LLM call did not return expected EntityDeduplicationDecision.")
                    return fallback_decision, current_op_usage
            else:
                logger.error(f"Deduplication LLM call did not return a valid result object.")
                return fallback_decision, current_op_usage
        except Exception as e:
            logger.error(f"Error during LLM deduplication call for '{new_entity.name}': {e}", exc_info=True)
            return fallback_decision, None