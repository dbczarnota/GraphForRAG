# graphforrag_core/multi_query_generator.py
import logging
from typing import Optional, Any, List, Tuple
from datetime import datetime, timezone

from pydantic_ai import Agent
from pydantic_ai.usage import Usage

from config.llm_prompts import (
    AlternativeQueriesList,
    MULTI_QUERY_GENERATION_SYSTEM_PROMPT,
    MULTI_QUERY_GENERATION_USER_PROMPT_TEMPLATE
)
# No need to import setup_fallback_model here, as the LLM client will be passed in
# from GraphForRAG's _ensure_services_llm_client method.

logger = logging.getLogger("graph_for_rag.multi_query_generator")

class MultiQueryGenerator:
    def __init__(self, llm_client: Any):
        """
        Initializes the MultiQueryGenerator.
        
        Args:
            llm_client: A pre-configured pydantic-ai LLM client.
        """
        self.llm_client = llm_client
        self.agent = Agent(
            output_type=AlternativeQueriesList,
            model=self.llm_client,
            system_prompt=MULTI_QUERY_GENERATION_SYSTEM_PROMPT
        )
        # --- Start of modification ---
        logger.info(f"MultiQueryGenerator initialized with LLM: {self._llm_client_display_name}")
        # --- End of modification ---

    # --- Start of new code ---
    @property
    def _llm_client_display_name(self) -> str:
        """Helper to get a display name for the LLM client, handling FallbackModel."""
        if hasattr(self.llm_client, 'models') and isinstance(self.llm_client.models, (list, tuple)) and hasattr(self.llm_client.models, '__len__') and len(self.llm_client.models) > 0: # FallbackModel check
            model_names = []
            for model_in_fallback in self.llm_client.models:
                name_found = "UnknownSubModel"
                if hasattr(model_in_fallback, 'model_name') and isinstance(model_in_fallback.model_name, str):
                    name_found = model_in_fallback.model_name
                elif hasattr(model_in_fallback, 'model') and isinstance(model_in_fallback.model, str): # pydantic-ai agent.model can be str
                    name_found = model_in_fallback.model
                model_names.append(name_found)
            return f"FallbackModel({', '.join(model_names)})"
        elif hasattr(self.llm_client, 'model_name') and isinstance(self.llm_client.model_name, str): 
            return self.llm_client.model_name
        elif hasattr(self.llm_client, 'model') and isinstance(self.llm_client.model, str): 
            return self.llm_client.model
        return "UnknownLLMClientType"

    async def generate_alternative_queries(
        self,
        original_query: str,
        max_alternative_questions: int = 3
    ) -> Tuple[List[str], Optional[Usage]]:
        """
        Generates alternative queries based on the original user query.

        Args:
            original_query: The user's original query string.
            max_alternative_questions: The maximum number of alternative queries to generate.

        Returns:
            A tuple containing a list of unique alternative query strings (excluding the original) 
            and optional LLM usage information.
        """
        if not original_query.strip():
            logger.warning("Received empty original_query for multi-query generation. Returning empty list.")
            return [], None

        now = datetime.now(timezone.utc)
        current_date_str = now.strftime("%Y-%m-%d")
        current_day_of_week_str = now.strftime("%A")

        user_prompt = MULTI_QUERY_GENERATION_USER_PROMPT_TEMPLATE.format(
            max_alternative_questions=max_alternative_questions,
            original_user_query=original_query,
            current_date=current_date_str,
            current_day_of_a_week=current_day_of_week_str
        )
        
        logger.debug(f"Generating alternative queries for: '{original_query}' (max: {max_alternative_questions})")

        current_op_usage: Optional[Usage] = None
        alternative_queries: List[str] = []
        
        try:
            agent_result_object = await self.agent.run(user_prompt=user_prompt)
            
            if agent_result_object and hasattr(agent_result_object, 'usage'):
                if isinstance(agent_result_object.usage, Usage):
                    current_op_usage = agent_result_object.usage
                elif callable(agent_result_object.usage): # Handle if .usage is a method
                    try:
                        usage_data_from_method = agent_result_object.usage()
                        if isinstance(usage_data_from_method, Usage):
                             current_op_usage = usage_data_from_method
                    except Exception:
                        pass # Ignore if .usage() fails or returns wrong type

            if agent_result_object and hasattr(agent_result_object, 'output'):
                if isinstance(agent_result_object.output, AlternativeQueriesList):
                    extracted_data: AlternativeQueriesList = agent_result_object.output
                    # Ensure queries are unique and not empty strings
                    unique_queries = set()
                    for alt_query_model in extracted_data.alternative_queries:
                        if alt_query_model.query and alt_query_model.query.strip():
                             # Avoid adding the original query if LLM includes it by mistake
                            if alt_query_model.query.strip().lower() != original_query.strip().lower():
                                unique_queries.add(alt_query_model.query.strip())
                    alternative_queries = list(unique_queries)
                    logger.info(f"Successfully generated {len(alternative_queries)} unique alternative queries for '{original_query}'.")
                else:
                    logger.error("Multi-query generation result's 'output' attribute is not of type AlternativeQueriesList.")
            else:
                logger.error("Multi-query generation did not return a valid result object or 'output' attribute.")
                
        except Exception as e:
            logger.error(f"Error during multi-query generation for '{original_query}': {e}", exc_info=True)
            # Return empty list but still propagate usage if any was captured before error
            return [], current_op_usage
        
        return alternative_queries, current_op_usage