# graphforrag_core/entity_resolver.py
import logging
import json # <-- ADDED
from typing import Optional, Any, List, Tuple, Dict # Added Dict for new_product_attributes

from neo4j import AsyncDriver # type: ignore
from pydantic_ai import Agent
from pydantic_ai.usage import Usage 

from config import cypher_queries 
from config.llm_prompts import ( 
    ExtractedEntity, 
    ExistingEntityCandidate,
    EntityDeduplicationDecision,
    ENTITY_DEDUPLICATION_SYSTEM_PROMPT,
    ENTITY_DEDUPLICATION_USER_PROMPT_TEMPLATE,
    ProductEntityMatchDecision, # ADDED
    PRODUCT_ENTITY_MATCH_SYSTEM_PROMPT, # ADDED
    PRODUCT_ENTITY_MATCH_USER_PROMPT_TEMPLATE # ADDED
)
from .embedder_client import EmbedderClient
from files.llm_models import setup_fallback_model 

logger = logging.getLogger("graph_for_rag.entity_resolver")
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


    async def _find_similar_existing_entities(self, entity_name: str) -> Tuple[List[ExistingEntityCandidate], Optional[Usage]]:
        if not entity_name:
            return [], None
        
        combined_candidates: List[ExistingEntityCandidate] = []
        total_embedding_usage_for_name_search = Usage()

        try:
            embedding_vector_data, name_embedding_usage = await self.embedder.embed_text(entity_name) 
            if name_embedding_usage:
                total_embedding_usage_for_name_search += name_embedding_usage
            
            if not embedding_vector_data: 
                logger.warning(f"Could not generate embedding for new entity name: '{entity_name}' for candidate search.")
                return [], total_embedding_usage_for_name_search

            # --- Search for similar Entities ---
            entity_index_name = "entity_name_embedding_vector" 
            entity_params = {
                "index_name_param": entity_index_name,
                "top_k_param": self.top_k_candidates,
                "embedding_vector_param": embedding_vector_data,
                "min_similarity_score_param": self.similarity_threshold
            }
            logger.debug(f"Searching for similar Entities for '{entity_name}' using index '{entity_index_name}'")
            entity_results, _, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.FIND_SIMILAR_ENTITIES_BY_VECTOR, 
                entity_params,
                database_=self.database
            )
            for record in entity_results:
                combined_candidates.append(
                    ExistingEntityCandidate(
                        uuid=record["uuid"], name=record["name"], label=record["label"], 
                        node_type="Entity", score=record["score"],
                        existing_mention_facts=record.get("mention_facts") # Populate new field
                    )
                )
            
            # --- Search for similar Products ---
            product_index_name = "product_name_embedding_vector"
            product_params = {
                "index_name_param": product_index_name,
                "top_k_param": self.top_k_candidates,
                "embedding_vector_param": embedding_vector_data,
                "min_similarity_score_param": self.similarity_threshold 
            }
            logger.debug(f"Searching for similar Products for '{entity_name}' using index '{product_index_name}'")
            product_results, _, _ = await self.driver.execute_query( # type: ignore
                cypher_queries.FIND_SIMILAR_PRODUCTS_BY_VECTOR, 
                product_params,
                database_=self.database
            )
            for record in product_results:
                combined_candidates.append(
                    ExistingEntityCandidate(
                        uuid=record["uuid"], name=record["name"],
                        label=record.get("label") or "Product", 
                        node_type="Product", score=record["score"],
                        existing_mention_facts=record.get("mention_facts") # Populate new field
                    )
                )

            combined_candidates.sort(key=lambda x: x.score if x.score is not None else 0.0, reverse=True)
            
            final_candidates = []
            seen_uuids = set()
            for cand in combined_candidates:
                if cand.uuid not in seen_uuids:
                    final_candidates.append(cand)
                    seen_uuids.add(cand.uuid)
                if len(final_candidates) >= self.top_k_candidates:
                    break
            
            logger.debug(f"Found {len(final_candidates)} combined unique similar entity/product candidates for '{entity_name}' (after sorting and limiting).")
            return final_candidates, total_embedding_usage_for_name_search
            
        except Exception as e:
            logger.error(f"Error finding similar entities/products for '{entity_name}': {e}", exc_info=True)
            return [], total_embedding_usage_for_name_search

    async def resolve_entity(
        self, new_entity: ExtractedEntity
    ) -> Tuple[EntityDeduplicationDecision, Optional[Usage], Optional[Usage]]: 
        
        logger.debug(f"Resolving entity: Name='{new_entity.name}', Label='{new_entity.label}'")
        
        final_generative_usage: Usage = Usage()
        final_embedding_usage: Usage = Usage()

        existing_candidates, name_embedding_usage_from_find = await self._find_similar_existing_entities(new_entity.name)
        if name_embedding_usage_from_find:
            final_embedding_usage += name_embedding_usage_from_find # type: ignore
        
        fallback_decision = EntityDeduplicationDecision(
            is_duplicate=False, 
            duplicate_of_uuid=None, 
            canonical_name=new_entity.name
        )

        if not existing_candidates:
            logger.debug("No similar existing candidates found. Treating as new entity.")
            return fallback_decision, final_generative_usage, final_embedding_usage

        # Format candidates for the prompt, now including existing_mention_facts
        candidates_prompt_parts = []
        for idx, cand_item in enumerate(existing_candidates):
            candidate_dict = {
                "uuid": cand_item.uuid,
                "name": cand_item.name,
                "label": cand_item.label,
                "node_type": cand_item.node_type,
                "score": round(cand_item.score, 4) if cand_item.score is not None else None,
                "existing_mention_facts": cand_item.existing_mention_facts if cand_item.existing_mention_facts else []
            }
            candidates_prompt_parts.append(f"- Candidate {idx+1}: {json.dumps(candidate_dict, indent=2)}")
        
        existing_candidates_prompt_str = "\n".join(candidates_prompt_parts)
        if not existing_candidates_prompt_str:
             existing_candidates_prompt_str = "No semantically similar candidates found in the knowledge graph."
        
        user_prompt = ENTITY_DEDUPLICATION_USER_PROMPT_TEMPLATE.format(
            new_entity_name=new_entity.name,
            new_entity_label=new_entity.label,
            new_entity_fact_sentence_about_mention=new_entity.fact_sentence_about_mention or "No specific fact sentence provided for this new mention.",
            existing_candidates_json_string=existing_candidates_prompt_str
        )
        logger.debug(f"Attempting entity deduplication with LLM. New: '{new_entity.name}'. Candidates considered: {len(existing_candidates)}. Prompt includes existing mention facts.")

        # ... (rest of the method: LLM call, processing results) ...
        agent_generative_usage: Optional[Usage] = None
        try:
            agent_result_object = await self.deduplication_agent.run(user_prompt=user_prompt)
            
            if agent_result_object and hasattr(agent_result_object, 'usage'):
                usage_val = agent_result_object.usage() if callable(agent_result_object.usage) else agent_result_object.usage
                if isinstance(usage_val, Usage): 
                    agent_generative_usage = usage_val
            
            if agent_generative_usage:
                final_generative_usage += agent_generative_usage # type: ignore

            if agent_result_object and hasattr(agent_result_object, 'output'):
                if isinstance(agent_result_object.output, EntityDeduplicationDecision):
                    decision = agent_result_object.output
                    return decision, final_generative_usage, final_embedding_usage
                else:
                    logger.error(f"Deduplication LLM call did not return expected EntityDeduplicationDecision.")
            else:
                logger.error(f"Deduplication LLM call did not return a valid result object.")
                
        except Exception as e:
            logger.error(f"Error during LLM deduplication call for '{new_entity.name}': {e}", exc_info=True)

        return fallback_decision, final_generative_usage, final_embedding_usage
        
        
    async def find_matching_entity_for_product_promotion(
        self,
        new_product_name: str,
        new_product_description: Optional[str], # This is the Product.content (JSON string)
        new_product_attributes: Optional[Dict[str, Any]] 
    ) -> Tuple[Optional[str], Optional[Usage], Optional[Usage]]: 
        
        logger.debug(f"Looking for existing Entity to promote for new product: '{new_product_name}'")
        
        final_generative_usage: Usage = Usage()
        final_embedding_usage: Usage = Usage()
        
        candidates, name_search_embedding_usage = await self._find_similar_existing_entities(new_product_name)
        if name_search_embedding_usage:
            final_embedding_usage += name_search_embedding_usage # type: ignore
        
        entity_candidates = [cand for cand in candidates if cand.node_type == "Entity"]

        if not entity_candidates:
            logger.debug(f"No existing :Entity candidates found for potential promotion for product '{new_product_name}'.")
            return None, final_generative_usage, final_embedding_usage

        top_entity_candidate = entity_candidates[0] 
        
        logger.info(f"Potential :Entity candidate for promotion: '{top_entity_candidate.name}' (UUID: {top_entity_candidate.uuid}) for new product '{new_product_name}'. Invoking LLM for match decision.")

        new_product_attributes_str = json.dumps(new_product_attributes) if new_product_attributes else "Not provided"

        # Since ExistingEntityCandidate no longer has a description, the prompt needs to be updated
        # to reflect that it might not be available, or we decide not to pass it.
        # The prompt PRODUCT_ENTITY_MATCH_USER_PROMPT_TEMPLATE refers to existing_entity_description.
        # Let's pass "Not available" for now.
        user_prompt = PRODUCT_ENTITY_MATCH_USER_PROMPT_TEMPLATE.format(
            new_product_name=new_product_name,
            new_product_description=new_product_description or "Not provided.", # This is product.content (JSON string)
            new_product_attributes_json_string=new_product_attributes_str,
            existing_entity_uuid=top_entity_candidate.uuid,
            existing_entity_name=top_entity_candidate.name,
            existing_entity_label=top_entity_candidate.label,
            existing_entity_description="Contextual statements for this entity are on its MENTIONS relationships, not directly on the entity." # Updated this part
        )

        match_agent = Agent(
            output_type=ProductEntityMatchDecision,
            model=self.llm_client, 
            system_prompt=PRODUCT_ENTITY_MATCH_SYSTEM_PROMPT
        )
        
        agent_generative_usage: Optional[Usage] = None
        try:
            agent_result_object = await match_agent.run(user_prompt=user_prompt)
            
            if agent_result_object and hasattr(agent_result_object, 'usage'):
                usage_val = agent_result_object.usage() if callable(agent_result_object.usage) else agent_result_object.usage
                if isinstance(usage_val, Usage): 
                    agent_generative_usage = usage_val
            
            if agent_generative_usage:
                final_generative_usage += agent_generative_usage # type: ignore

            if agent_result_object and isinstance(agent_result_object.output, ProductEntityMatchDecision):
                decision: ProductEntityMatchDecision = agent_result_object.output
                if decision.is_strong_match and decision.matched_entity_uuid == top_entity_candidate.uuid:
                    logger.info(f"Strong match found: New product '{new_product_name}' matches existing Entity UUID '{decision.matched_entity_uuid}'.")
                    return decision.matched_entity_uuid, final_generative_usage, final_embedding_usage
                else:
                    logger.info(f"LLM decided no strong match or mismatched UUID for '{new_product_name}' and candidate '{top_entity_candidate.name}'.")
            else:
                logger.warning("Product-Entity match LLM call did not return expected decision structure.")
        
        except Exception as e:
            logger.error(f"Error during Product-Entity match LLM call for '{new_product_name}': {e}", exc_info=True)

        return None, final_generative_usage, final_embedding_usage