import asyncio
import os
import logging
from dotenv import load_dotenv
from typing import Any, Optional, Dict, List

from neo4j import AsyncGraphDatabase, AsyncDriver # type: ignore
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from files.llm_models import setup_fallback_model # Import the setup function
from graphforrag_core.schema_manager import SchemaManager 
from graphforrag_core.embedder_client import EmbedderClient
from graphforrag_core.openai_embedder import OpenAIEmbedder, OpenAIEmbedderConfig

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("cypher_search_prototype")

# --- Pydantic Model for LLM Output (Cypher Query) ---
class GeneratedCypherQuery(BaseModel):
    cypher_query: str = Field(..., description="The generated Cypher query string.")

# --- LLM Prompt Template ---
# This template now expects a single {schema_and_indexes} placeholder
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

**Combining Results from Different Queries:**
*   If the question implies searching for entities that might satisfy different criteria or be found through distinct graph patterns (e.g., searching for a term in different node types or different properties), use `UNION ALL` to combine the results.
*   Each sub-query in a `UNION ALL` statement must return the same set of columns with the same names and compatible types. Use `AS` to alias column names if necessary to ensure consistency.

Index usage (e.g., Vector, Fulltext via `CALL db.index...` statements) is handled elsewhere; do not generate queries that call `db.index` procedures.

Schema (including Node properties, Relationship properties, and The relationships. Any index information, if present in the provided schema, should be ignored for the purpose of generating the Cypher query from this template):
{schema_and_indexes}
Note: Do not include any explanations or apologies in your responses.
Do not respond to any questions that might ask anything else than for you to construct a Cypher statement.
Strictly output only the Cypher query. If you cannot generate a query based on the schema and question, output "QUERY_GENERATION_FAILED".

Examples: Here are a few examples of generated Cypher statements for particular questions:

# What investment firms are in San Francisco? (Property match, case-insensitive)
# Assumes :Manager node with 'managerName' property, :Address node with 'city' property, and :LOCATED_AT relationship.
MATCH (mgr:Manager)-[:LOCATED_AT]->(mgrAddress:Address)
    WHERE toLower(mgrAddress.city) = toLower('San Francisco')
RETURN mgr.managerName

# What documents mention "renewable energy"?
# (Keyword search in content, case-insensitive. Assumes :Document node with 'content' and 'title' properties)
MATCH (doc:Document)
WHERE toLower(doc.content) CONTAINS toLower('renewable energy')
RETURN doc.title, doc.content

# Find products with "Dell XPS 13" in their description.
# (Keyword phrase search in product description, case-insensitive. Assumes :Product node with 'description' and 'name' properties)
MATCH (p:Product)
WHERE toLower(p.description) CONTAINS toLower('Dell XPS 13')
RETURN p.name, p.description

# Find products that have the tag "eco-friendly".
# (List property exact element match, case-insensitive. Assumes :Product node with 'tags: LIST<STRING>' property)
MATCH (p:Product)
WHERE ANY(tag IN p.tags WHERE toLower(tag) = toLower('eco-friendly'))
RETURN p.name, p.tags

# Find products where one of the features mentions "waterproof material".
# (List property, string element contains substring, case-insensitive. Assumes :Product node with 'features: LIST<STRING>' property)
MATCH (p:Product)
WHERE ANY(feature IN p.features WHERE toLower(feature) CONTAINS toLower('waterproof material'))
RETURN p.name, p.features

# Find any 'Company' or 'Person' named 'Apex Innovations' (case-insensitive).
# (Using UNION ALL to search across different node labels. Assumes :Company(name) and :Person(name) properties)
MATCH (c:Company)
WHERE toLower(c.name) = toLower('Apex Innovations')
RETURN c.name AS entityName, labels(c)[0] AS entityType
UNION ALL
MATCH (p:Person)
WHERE toLower(p.name) = toLower('Apex Innovations')
RETURN p.name AS entityName, labels(p)[0] AS entityType

# Find all documents or articles that mention 'AI ethics'.
# (Using UNION ALL to search a term in different node types, assuming they have a 'text' or 'content' property.
# Assumes :Document(text) and :Article(content) properties)
MATCH (d:Document)
WHERE toLower(d.text) CONTAINS toLower('ai ethics')
RETURN d.title AS title, d.text AS body, 'Document' AS type
UNION ALL
MATCH (a:Article)
WHERE toLower(a.content) CONTAINS toLower('ai ethics')
RETURN a.headline AS title, a.content AS body, 'Article' AS type

The question is:
{question}"""


async def get_db_schema_with_indexes(driver: AsyncDriver, db_name: str, embedder: EmbedderClient) -> str:
    """Helper to get the schema string including index information."""
    schema_manager = SchemaManager(driver, db_name, embedder)
    full_schema_with_indexes = await schema_manager.get_schema_string()
    logger.info(f"Generated Schema: \n{full_schema_with_indexes}")
    return full_schema_with_indexes

async def generate_cypher_from_question(
    question: str, 
    schema_with_indexes: str, 
    llm_model_instance: Any # Expecting a configured LLM model instance (e.g., from setup_fallback_model)
) -> Optional[str]:
    """Generates a Cypher query from a natural language question using an LLM."""
    
    agent = Agent(
        output_type=GeneratedCypherQuery, 
        model=llm_model_instance, 
        system_prompt="" # System prompt elements are included in the user prompt template
    )
    
    prompt = CYPHER_GENERATION_TEMPLATE.format(schema_and_indexes=schema_with_indexes, question=question)
    
    try:
        logger.info("Attempting to generate Cypher query...")
        agent_result_object = await agent.run(user_prompt=prompt)

        if agent_result_object and hasattr(agent_result_object, 'output') and isinstance(agent_result_object.output, GeneratedCypherQuery):
            generated_query_model: GeneratedCypherQuery = agent_result_object.output
            query_text = generated_query_model.cypher_query.strip()
            if query_text and query_text.upper() != "QUERY_GENERATION_FAILED":
                logger.info(f"Generated Cypher: \n{query_text}")
                return query_text
            else:
                logger.warning("LLM indicated query generation failed or returned an empty/invalid query.")
                return None
        else:
            logger.error(f"LLM did not return expected GeneratedCypherQuery object. Got: {type(agent_result_object)}. Output: {getattr(agent_result_object, 'output', 'N/A')}")
            return None
            
    except Exception as e:
        logger.error(f"Error generating Cypher query: {e}", exc_info=True)
        return None

async def execute_cypher_query(driver: AsyncDriver, db_name: str, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Executes a Cypher query and returns the results."""
    if not query:
        return []
    try:
        logger.info(f"Executing Cypher query: \n{query} \nWith params: {params or {}}")
        results, _, _ = await driver.execute_query(query, parameters_=params or {}, database_=db_name) # type: ignore
        return [dict(record) for record in results]
    except Exception as e:
        logger.error(f"Error executing Cypher query: {e}", exc_info=True)
        # Return the error in a structured way if execution fails
        return [{"error_executing_query": str(e), "failed_query": query}]


async def main_prototype():
    load_dotenv()
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'password')
    NEO4J_DATABASE = os.environ.get('NEO4J_DATABASE', 'neo4j')
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found. This prototype requires it for the LLM and Embedder.")
        return

    driver: Optional[AsyncDriver] = None
    try:
        driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) # type: ignore
        await driver.verify_connectivity() # Good practice to verify connection
        
        embedder_config = OpenAIEmbedderConfig(api_key=OPENAI_API_KEY)
        openai_embedder = OpenAIEmbedder(config=embedder_config)

        logger.info("Fetching database schema (including indexes)...")
        schema_str_with_indexes = await get_db_schema_with_indexes(driver, NEO4J_DATABASE, openai_embedder)
        if not schema_str_with_indexes or "Error" in schema_str_with_indexes: # Basic check for error string
            logger.error(f"Failed to retrieve a valid schema: {schema_str_with_indexes}")
            return
        logger.info("Schema fetched successfully.")
        # logger.info(f"Full Schema for LLM:\n{schema_str_with_indexes}") # Uncomment for debugging

        logger.info("Setting up LLM for Cypher generation using setup_fallback_model...")
        # Using a specific model for Cypher generation is good.
        # gpt-4o-mini is often good, gpt-4o might be better for complex Cypher.
        llm_cypher_generator = setup_fallback_model(models=["gpt-4o-mini"]) 
        if isinstance(llm_cypher_generator, str) and llm_cypher_generator == "classification_failed_no_models":
            logger.error("Failed to set up LLM for Cypher generation. Ensure your LLM provider (e.g., OpenAI) is correctly configured.")
            return
        # The name of the actual model used will be logged by setup_fallback_model itself.

        user_question = input("\nEnter your question for the Neo4j database: ")
        if not user_question.strip():
            logger.info("No question provided. Exiting.")
            return

        generated_cypher = await generate_cypher_from_question(user_question, schema_str_with_indexes, llm_cypher_generator)

        if generated_cypher:
            # For this prototype, we assume no parameters are needed unless explicitly extracted by a more advanced LLM step.
            # If the generated Cypher uses parameters like $query_embedding, this execution will fail unless they are provided.
            # A more advanced system would:
            # 1. Have the LLM also identify if parameters (like embeddings for vector search) are needed.
            # 2. If so, generate the embedding for the relevant part of the user question.
            # 3. Pass it in the `params` dictionary to `execute_cypher_query`.
            
            execution_params = {}
            # Simple placeholder for embedding if a vector search is generated:
            if "$query_embedding" in generated_cypher:
                 logger.info("Vector search detected in Cypher. Generating placeholder embedding for the question.")
                 # In a real app, you'd embed the relevant part of the question or the whole question.
                 # For prototype, we'll just embed the question.
                 embedding_vector, _ = await openai_embedder.embed_text(user_question)
                 if embedding_vector:
                     execution_params["query_embedding"] = embedding_vector
                 else:
                     logger.error("Failed to generate embedding for vector search query. Execution will likely fail.")
            
            query_results = await execute_cypher_query(driver, NEO4J_DATABASE, generated_cypher, params=execution_params)
            
            logger.info("\n--- Query Results ---")
            if query_results:
                for i, row in enumerate(query_results):
                    logger.info(f"Result {i+1}: {row}")
                    if i >= 19: # Limit printing for very long results
                        logger.info(f"... and {len(query_results) - 20} more rows.")
                        break
            elif not query_results: # Empty list, but no error reported by execute_cypher_query
                logger.info("Query executed successfully but returned no data.")
            # If execute_cypher_query returned an error structure, it would have been logged there already.
        else:
            logger.warning("No Cypher query was generated. Cannot execute.")

    except Exception as e:
        logger.error(f"An error occurred in the main_prototype: {e}", exc_info=True)
    finally:
        if driver:
            await driver.close()
            logger.info("Neo4j driver closed.")

if __name__ == "__main__":
    asyncio.run(main_prototype())