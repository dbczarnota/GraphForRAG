# graphforrag_core/cypher_generator.py
import logging
from typing import Optional, Any, List, Tuple

from neo4j import AsyncDriver # type: ignore
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.usage import Usage

from .schema_manager import SchemaManager
from .embedder_client import EmbedderClient
from .types import FlaggedPropertiesConfig
# from files.llm_models import setup_fallback_model # LLM client will be passed in

logger = logging.getLogger("graph_for_rag.cypher_generator")

# --- Pydantic Model for LLM Output (Cypher Query) ---
class GeneratedCypherQuery(BaseModel):
    cypher_query: str = Field(..., description="The generated Cypher query string.")

# --- LLM Prompt Template ---
# This template expects {schema_and_indexes} which will be just schema for now.
CYPHER_GENERATION_TEMPLATE = """Task:Generate Cypher statement to query a graph database.
Instructions:
Use only the provided relationship types and properties in the schema.
Do not use any other relationship types or properties that are not provided.
Focus on constructing base Cypher queries using property matching and relationship traversal.

**Property Value Handling:**
*   **Case-Insensitivity for Strings:** Property values in the database might have mixed casing. Ensure your queries handle this by performing case-insensitive comparisons on string properties when appropriate (e.g., using `toLower(n.property) = toLower('value')` or `toLower(n.property) CONTAINS toLower('keyword')`).
*   **List Properties:** If a property is a list:
    *   For checking if a specific value exists in a list (exact match for an element): `value IN n.listProperty` (if case sensitivity is desired or elements are not strings) or `ANY(item IN n.listProperty WHERE toLower(item) = toLower('value_to_check'))` for case-insensitive string element check.
    *   For checking if any string element in a list *contains* a sub-string (case-insensitive): `ANY(item IN n.listProperty WHERE toLower(item) CONTAINS toLower('substring_to_check'))`.
*   **Possible Values in Schema:** If the schema for a property includes '{{possible values: {{...}}}}', you can use these known values to construct more precise queries, e.g., `n.category IN ['laptops', 'desktops']`.

**Combining Results from Different Queries:**
*   If the question implies searching for entities that might satisfy different criteria or be found through distinct graph patterns (e.g., searching for a term in different node types or different properties), use `UNION ALL` to combine the results.
*   Each sub-query in a `UNION ALL` statement must return the same set of columns with the same names and compatible types. Use `AS` to alias column names if necessary to ensure consistency.

Do not generate queries that call `db.index` procedures for vector or fulltext search. These specialized searches are handled by other system components.

Schema:
{schema_string}

Note: Do not include any explanations or apologies in your responses.
Do not respond to any questions that might ask anything else than for you to construct a Cypher statement.
Strictly output only the Cypher query. If you cannot generate a query based on the schema and question, output the single word "NONE".

Examples:
# What investment firms are in San Francisco?
MATCH (mgr:Manager)-[:LOCATED_AT]->(mgrAddress:Address)
WHERE toLower(mgrAddress.city) = toLower('San Francisco')
RETURN mgr.managerName

# What documents mention "renewable energy"?
MATCH (doc:Document)
WHERE toLower(doc.content) CONTAINS toLower('renewable energy')
RETURN doc.title, doc.content

# Find products with "Dell XPS 13" in their description.
MATCH (p:Product)
WHERE toLower(p.description) CONTAINS toLower('Dell XPS 13')
RETURN p.name, p.description

# Find products that have the tag "eco-friendly". (Assumes tags is LIST<STRING>)
MATCH (p:Product)
WHERE ANY(tag IN p.tags WHERE toLower(tag) = toLower('eco-friendly'))
RETURN p.name, p.tags

# Find products where one of the features mentions "waterproof material". (Assumes features is LIST<STRING>)
MATCH (p:Product)
WHERE ANY(feature IN p.features WHERE toLower(feature) CONTAINS toLower('waterproof material'))
RETURN p.name, p.features

# Find any 'Company' or 'Person' named 'Apex Innovations'.
MATCH (c:Company) WHERE toLower(c.name) = toLower('Apex Innovations') RETURN c.name AS entityName, labels(c)[0] AS entityType
UNION ALL
MATCH (p:Person) WHERE toLower(p.name) = toLower('Apex Innovations') RETURN p.name AS entityName, labels(p)[0] AS entityType

The question is:
{question}"""


class CypherGenerator:
    def __init__(
        self,
        llm_client: Any,
        driver: AsyncDriver,
        database_name: str,
        embedder_client: EmbedderClient, # Needed for SchemaManager
        flagged_properties_config: Optional[FlaggedPropertiesConfig] = None
    ):
        self.llm_client = llm_client
        self.driver = driver
        self.database = database_name
        self.embedder_client = embedder_client
        self.flagged_properties_config = flagged_properties_config if flagged_properties_config else FlaggedPropertiesConfig()
        
        self.schema_manager = SchemaManager(
            self.driver, 
            self.database, 
            self.embedder_client, 
            self.flagged_properties_config # Pass the specific config for this generator's schema
        )
        
        self.agent = Agent(
            output_type=GeneratedCypherQuery,
            model=self.llm_client,
            system_prompt="" # System prompt elements are in the user prompt template
        )
        logger.info(f"CypherGenerator initialized with LLM: {self._llm_client_display_name}")

    @property
    def _llm_client_display_name(self) -> str:
        """Helper to get a display name for the LLM client."""
        if hasattr(self.llm_client, 'models') and isinstance(self.llm_client.models, (list, tuple)) and hasattr(self.llm_client.models, '__len__') and len(self.llm_client.models) > 0: # FallbackModel check
            model_names = [getattr(m, 'model_name', 'UnknownSubModel') for m in self.llm_client.models]
            return f"FallbackModel({', '.join(model_names)})"
        elif hasattr(self.llm_client, 'model_name') and isinstance(self.llm_client.model_name, str): 
            return self.llm_client.model_name
        elif hasattr(self.llm_client, 'model') and isinstance(self.llm_client.model, str): 
            return self.llm_client.model
        return "UnknownLLMClientType"

    async def generate_cypher_query(
        self,
        question: str,
        custom_schema_string: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[Usage]]:
        """
        Generates a Cypher query from a natural language question using an LLM,
        based on the database schema (potentially customized with flagged properties).
        """
        current_op_usage: Optional[Usage] = None
        
        schema_to_use_for_llm: Optional[str] = None
        if custom_schema_string:
            logger.info(f"CypherGenerator: Using provided custom schema string for question: '{question[:50]}...'")
            schema_to_use_for_llm = custom_schema_string
        else:
            logger.info(f"CypherGenerator: Fetching schema via SchemaManager for question: '{question[:50]}...'")
            # SchemaManager instance within CypherGenerator already has its flagged_properties_config
            schema_to_use_for_llm = await self.schema_manager.get_schema_string() 

        if not schema_to_use_for_llm or "Error" in schema_to_use_for_llm: # Handles "Error" string from schema_manager or empty custom string
            logger.error(f"CypherGenerator: Failed to obtain a valid schema. Cannot generate Cypher. Schema output/provided: {schema_to_use_for_llm}")
            return None, None
        
        logger.debug(f"CypherGenerator: Schema for LLM (first 500 chars):\n{schema_to_use_for_llm[:500]}...")

        prompt = CYPHER_GENERATION_TEMPLATE.format(schema_string=schema_to_use_for_llm, question=question)
        
        try:
            logger.info(f"CypherGenerator: Attempting to generate Cypher query for: '{question[:50]}...'")
            agent_result_object = await self.agent.run(user_prompt=prompt)

            if agent_result_object and hasattr(agent_result_object, 'usage'):
                usage_val = agent_result_object.usage() if callable(agent_result_object.usage) else agent_result_object.usage
                if isinstance(usage_val, Usage): current_op_usage = usage_val
            
            if agent_result_object and hasattr(agent_result_object, 'output') and isinstance(agent_result_object.output, GeneratedCypherQuery):
                generated_query_model: GeneratedCypherQuery = agent_result_object.output
                query_text = generated_query_model.cypher_query.strip()
                if query_text and query_text.upper() != "NONE": # Check for "NONE"
                    logger.info(f"CypherGenerator: Generated Cypher: \n{query_text}")
                    return query_text, current_op_usage
                elif query_text.upper() == "NONE":
                    logger.warning("CypherGenerator: LLM indicated no viable query could be generated (returned 'NONE').")
                    return None, current_op_usage
                else: # Empty query string after strip
                    logger.warning("CypherGenerator: LLM returned an empty query string.")
                    return None, current_op_usage
            else:
                logger.error(f"CypherGenerator: LLM did not return expected GeneratedCypherQuery object. Got: {type(agent_result_object)}. Output: {getattr(agent_result_object, 'output', 'N/A')}")
                return None, current_op_usage
            
        except Exception as e:
            logger.error(f"CypherGenerator: Error generating Cypher query: {e}", exc_info=True)
            return None, current_op_usage