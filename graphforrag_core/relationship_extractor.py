# graphforrag_core/relationship_extractor.py
import logging
import json
from typing import Optional, Any, List, Tuple

from pydantic_ai import Agent
from pydantic_ai.usage import Usage # Assuming this import works

# Import Pydantic models and prompts related to relationship extraction
from config.llm_prompts import (
    ExtractedRelationship,      # Though not directly used as input type here, it's what we expect in the list
    ExtractedRelationshipsList, # This is the output_type for the agent
    RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT,
    RELATIONSHIP_EXTRACTION_USER_PROMPT_TEMPLATE
)
# Import the Pydantic model for entities that will be passed as context
from config.llm_prompts import ExtractedEntity # This is the type for the entities_in_chunk list

from files.llm_models import setup_fallback_model

logger = logging.getLogger("graph_for_rag.relationship_extractor")

# Helper function to log usage (can be moved to a common utils if not already there)
def log_llm_usage(operation_name: str, usage_info: Optional[Usage]):
    if usage_info and hasattr(usage_info, 'has_values') and usage_info.has_values():
        details = (
            f"Requests: {usage_info.requests}, "
            f"Request Tokens: {usage_info.request_tokens or 0}, "
            f"Response Tokens: {usage_info.response_tokens or 0}, "
            f"Total Tokens: {usage_info.total_tokens or 0}"
        )
        logger.info(f"LLM Usage for '{operation_name}': {details}")
    else:
        logger.info(f"LLM Usage for '{operation_name}': No usage data reported.")


class RelationshipExtractor:
    def __init__(self, llm_client: Optional[Any] = None):
        """
        Initializes the RelationshipExtractor.
        
        Args:
            llm_client: An optional pre-configured pydantic-ai LLM client.
                        If None, a default OpenAI model will be set up.
        """
        if llm_client:
            self.llm_client = llm_client
        else:
            logger.info("No LLM client provided to RelationshipExtractor, setting up default fallback model.")
            self.llm_client = setup_fallback_model() 

        self.agent = Agent(
            output_type=ExtractedRelationshipsList, # Expecting a list of relationships
            model=self.llm_client, 
            system_prompt=RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT
        )
        model_name_for_log = "Unknown"
        if hasattr(self.llm_client, 'model') and isinstance(self.llm_client.model, str):
            model_name_for_log = self.llm_client.model
        elif hasattr(self.llm_client, 'model_name') and isinstance(self.llm_client.model_name, str):
             model_name_for_log = self.llm_client.model_name
        logger.info(f"RelationshipExtractor initialized with LLM: {model_name_for_log}")

    async def extract_relationships(
        self, 
        text_content: str, 
        entities_in_chunk: List[ExtractedEntity] # List of entities found in this chunk
    ) -> Tuple[ExtractedRelationshipsList, Optional[Usage]]:
        """
        Extracts relationships between the provided entities from the given text content.

        Args:
            text_content: The main text from which to extract relationships.
            entities_in_chunk: A list of ExtractedEntity objects that were identified in this text_content.
                               The LLM will try to find relationships *between these entities*.

        Returns:
            A tuple containing an ExtractedRelationshipsList Pydantic model instance and optional Usage info.
        """
        if not text_content.strip() or not entities_in_chunk:
            logger.warning("Received empty text_content or no entities for relationship extraction. Returning empty list.")
            return ExtractedRelationshipsList(relationships=[]), None

        # Prepare the entity list for the prompt (just name and label might be enough)
        # The prompt asks for names to match exactly.
        entities_for_prompt = [
            {"name": entity.name, "label": entity.label} for entity in entities_in_chunk
        ]
        entities_json_string = json.dumps(entities_for_prompt)

        user_prompt = RELATIONSHIP_EXTRACTION_USER_PROMPT_TEMPLATE.format(
            text_content=text_content,
            entities_json_string=entities_json_string
        )

        logger.debug(f"Attempting relationship extraction. Entities provided: {[e.name for e in entities_in_chunk]}. User prompt:\n-----\n{user_prompt[:700]}...\n-----")
        
        current_op_usage: Optional[Usage] = None
        try:
            agent_result_object = await self.agent.run(user_prompt=user_prompt)
            
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
                # Log usage immediately if desired, or just return it
                # log_llm_usage(f"RelationshipExtractor ({text_content[:30]}...)", current_op_usage)


            if agent_result_object and hasattr(agent_result_object, 'output'):
                if isinstance(agent_result_object.output, ExtractedRelationshipsList):
                    extracted_data: ExtractedRelationshipsList = agent_result_object.output
                    logger.debug(f"Successfully extracted {len(extracted_data.relationships)} relationships.")
                    for rel in extracted_data.relationships:
                        logger.debug(f"  - Extracted Rel: {rel.source_entity_name} --[{rel.relation_label}]--> {rel.target_entity_name} (Fact: {rel.fact_sentence})")
                    return extracted_data, current_op_usage
                else:
                    logger.error(f"Relationship extraction result's 'output' attribute is not of type ExtractedRelationshipsList.")
                    return ExtractedRelationshipsList(relationships=[]), current_op_usage
            else:
                logger.error(f"Relationship extraction did not return a valid result object or 'output' attribute.")
                return ExtractedRelationshipsList(relationships=[]), current_op_usage
                
        except Exception as e:
            logger.error(f"Error during relationship extraction: {e}", exc_info=True)
            return ExtractedRelationshipsList(relationships=[]), None