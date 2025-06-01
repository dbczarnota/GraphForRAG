# graphforrag_core/entity_extractor.py
import logging
from typing import Optional, Any

from pydantic_ai import Agent
# from pydantic_ai.result import AgentRunResult # REMOVE THIS LINE

from config.llm_prompts import (
    ExtractedEntitiesList,
    ENTITY_EXTRACTION_SYSTEM_PROMPT,
    ENTITY_EXTRACTION_USER_PROMPT_TEMPLATE
)
from files.llm_models import setup_fallback_model


logger = logging.getLogger("graph_for_rag.entity_extractor")

class EntityExtractor:
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
    ) -> ExtractedEntitiesList:
        if not text_content.strip():
            logger.warning("Received empty text_content for entity extraction. Returning empty list.")
            return ExtractedEntitiesList(entities=[])

        user_prompt = ENTITY_EXTRACTION_USER_PROMPT_TEMPLATE.format(
            context_text=context_text if context_text else "No additional context provided.",
            text_content=text_content
        )

        logger.debug(f"Attempting entity extraction with user prompt:\n-----\n{user_prompt[:500]}...\n-----")
        
        try:
            # agent.run() returns an object; we expect our Pydantic model at its .output attribute
            agent_result_object = await self.agent.run(user_prompt=user_prompt) 
            
            # Check if the result object exists and has an 'output' attribute
            if agent_result_object and hasattr(agent_result_object, 'output'):
                # Now check if agent_result_object.output is an instance of our expected Pydantic model
                if isinstance(agent_result_object.output, ExtractedEntitiesList):
                    extracted_data: ExtractedEntitiesList = agent_result_object.output
                    logger.debug(f"Raw Agent output (ExtractedEntitiesList): {extracted_data}")
                    logger.debug(f"Successfully extracted {len(extracted_data.entities)} entities.")
                    for entity in extracted_data.entities:
                        logger.debug(f"  - Extracted: Name='{entity.name}', Label='{entity.label}'")
                    return extracted_data
                else:
                    logger.error(
                        f"Entity extraction result's 'output' attribute is not of type ExtractedEntitiesList. "
                        f"Got type: {type(agent_result_object.output)}. Value: {agent_result_object.output}"
                    )
                    return ExtractedEntitiesList(entities=[])
            else:
                logger.error(
                    f"Entity extraction did not return a valid result object or 'output' attribute. "
                    f"Got: {agent_result_object}"
                )
                return ExtractedEntitiesList(entities=[])
                
        except Exception as e:
            logger.error(f"Error during entity extraction or processing result: {e}", exc_info=True)
            return ExtractedEntitiesList(entities=[])