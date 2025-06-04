# graphforrag_core/entity_extractor.py
import logging
from typing import Optional, Any, Tuple # <-- ADDED Tuple

from pydantic_ai import Agent
from pydantic_ai.usage import Usage # Assuming this import works

from config.llm_prompts import (
    ExtractedEntitiesList,
    ENTITY_EXTRACTION_SYSTEM_PROMPT,
    ENTITY_EXTRACTION_USER_PROMPT_TEMPLATE
)
from files.llm_models import setup_fallback_model

logger = logging.getLogger("graph_for_rag.entity_extractor")

# log_llm_usage helper can be removed from here if we accumulate globally
# or kept for per-operation logging if desired. For now, let's remove it
# to focus on the cumulative sum.

class EntityExtractor:
    # ... (__init__ remains the same) ...
    def __init__(self, llm_client: Optional[Any] = None):
        if llm_client:
            self.llm_client = llm_client
        else:
            logger.info("No LLM client provided to EntityExtractor, setting up default fallback model.")
            self.llm_client = setup_fallback_model() 

        self.agent = Agent(
            output_type=ExtractedEntitiesList,
            model=self.llm_client, 
            system_prompt=ENTITY_EXTRACTION_SYSTEM_PROMPT
        )
        model_name_for_log = "Unknown"
        if hasattr(self.llm_client, 'model') and isinstance(self.llm_client.model, str):
            model_name_for_log = self.llm_client.model
        elif hasattr(self.llm_client, 'model_name') and isinstance(self.llm_client.model_name, str):
             model_name_for_log = self.llm_client.model_name

        logger.info(f"EntityExtractor initialized with LLM: {model_name_for_log}")


    async def extract_entities(
        self, 
        text_content: str, 
        context_text: Optional[str] = None
    ) -> Tuple[ExtractedEntitiesList, Optional[Usage]]: 
        if not text_content.strip():
            logger.warning("Received empty text_content for entity extraction. Returning empty list and no usage.")
            return ExtractedEntitiesList(entities=[]), None

        user_prompt = ENTITY_EXTRACTION_USER_PROMPT_TEMPLATE.format(
            context_text=context_text if context_text else "No additional context provided.",
            text_content=text_content
        )
        
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

            if agent_result_object and hasattr(agent_result_object, 'output'):
                if isinstance(agent_result_object.output, ExtractedEntitiesList):
                    extracted_data: ExtractedEntitiesList = agent_result_object.output
                    # logger.debug(f"Successfully extracted {len(extracted_data.entities)} entities. First entity contextual_statement: {extracted_data.entities[0].contextual_statement if extracted_data.entities else 'N/A'}")
                    return extracted_data, current_op_usage
                else:
                    logger.error(f"Entity extraction result's 'output' attribute is not of type ExtractedEntitiesList.")
                    return ExtractedEntitiesList(entities=[]), current_op_usage 
            else:
                logger.error(f"Entity extraction did not return a valid result object or 'output' attribute.")
                return ExtractedEntitiesList(entities=[]), current_op_usage
                
        except Exception as e:
            logger.error(f"Error during entity extraction: {e}", exc_info=True)
            return ExtractedEntitiesList(entities=[]), None