import os
from dotenv import load_dotenv
from typing import List
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.google_gla import GoogleGLAProvider
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.models.gemini import GeminiModel
from pydantic_ai.models.groq import GroqModel
from pydantic_ai.providers.groq import GroqProvider
from pydantic_ai.models.fallback import FallbackModel
from httpx import AsyncClient
import logging

logger = logging.getLogger("llm_models")

load_dotenv()



def setup_fallback_model(models: List[str] = ["gpt-4.1-mini", "gemini-2.0-flash"]):
    """
    Initialize fallback LLM model based on a list of model names.
    Providers are only initialized if at least one requested model comes from them.
    
    Args:
        models (List[str]): List of strings representing the desired model names.

    Returns:
        FallbackModel instance if any models were initialized successfully,
        otherwise returns "classification_failed_no_models".
    """

    logger.info("\n[bold blue]--- Initialization Start ---[/bold blue]")
    logger.info(f"Requested models: {models}")

    # Define which models depend on which provider.
    openai_models = {"gpt-4o-mini", "o3-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"}
    gemini_models = {"gemini-2.5-flash-preview-04-17", "gemini-2.0-flash", "gemini-2.5-pro-preview-05-06", "gemma-3-27b-it"}
    groq_models   = {"meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"}
    openrouter_models = {"google/gemma-3-27b-it", "qwen/qwen-vl-plus", "deepseek/deepseek-r1"}
    ollama_models = {"ollama/gemma3:4b", "ollama/gemma3:27b"}



    # Determine if a provider is needed based on the input list.
    need_openai = any(model in openai_models for model in models)
    need_gemini = any(model in gemini_models for model in models)
    need_groq = any(model in groq_models for model in models)
    need_openrouter = any(model in openrouter_models for model in models)
    need_ollama  = any(model in ollama_models for model in models)


    # --- Providers Initialization ---
    # OpenAI Provider
    openai_provider = None
    if need_openai:
        openai_api_key = os.getenv('OPENAI_API_KEY')
        if openai_api_key:
            try:
                openai_provider = OpenAIProvider(api_key=openai_api_key)
                logger.info("OpenAI Provider initialized successfully.")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI Provider: {e}", exc_info=True)
        else:
            logger.warning("OPENAI_API_KEY not found. Skipping OpenAI provider initialization.")
    else:
        logger.info("OpenAI Provider not required by requested models.")

    # Gemini Provider (Google GLA)
    gemini_provider = None
    if need_gemini:
        gemini_api_key = os.getenv('GEMINI_API_KEY')
        if gemini_api_key:
            try:
                gemini_provider = GoogleGLAProvider(api_key=gemini_api_key)
                logger.info("Google GLA Provider initialized successfully.")
            except Exception as e:
                logger.warning(f"Failed to initialize Google GLA Provider: {e}", exc_info=True)
        else:
            logger.warning("GEMINI_API_KEY not found. Skipping Gemini provider initialization.")
    else:
        logger.info("Gemini Provider not required by requested models.")

    # Groq Provider
    groq_provider = None
    if need_groq:
        groq_api_key = os.getenv('GROQ_API_KEY')
        if groq_api_key:
            try:
                groq_provider = GroqProvider(api_key=groq_api_key)
                logger.info("Groq Provider initialized successfully.")
            except Exception as e:
                logger.warning(f"Failed to initialize Groq Provider: {e}", exc_info=True)
        else:
            logger.warning("GROQ_API_KEY not found. Skipping Groq provider initialization.")
    else:
        logger.info("Groq Provider not required by requested models.")
        
    
    # Openrouter Provider
    openrouter_provider = None
    if need_openrouter:
        openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
        if openrouter_api_key:
            try:
                custom_http_client = AsyncClient(timeout=30)
                openrouter_provider = OpenAIProvider(
                # base_url='https://openrouter.ai/api/v1',
                base_url="https://openrouter.ai/api/v1/chat/completions",
                api_key=openrouter_api_key,
                http_client=custom_http_client
                )
                
                logger.info("Openrouter Provider initialized successfully.")
            except Exception as e:
                logger.warning(f"Failed to initialize Openrouter Provider: {e}", exc_info=True)
        else:
            logger.warning("OPENROUTER_API_KEY not found. Skipping Openrouter provider initialization.")
    else:
        logger.info("Openrouter Provider not required by requested models.")
    
    
    # Ollama Provider - set up on runpod
    ollama_provider = None
    if need_ollama:
        try:
            ollama_provider = OpenAIProvider(
            base_url='https://z8dc1gdrcy9i17.proxy.runpod.net/v1',
            )
            
            logger.info("Ollama Provider initialized successfully.")
        except Exception as e:
            logger.warning(f"Failed to initialize Ollama Provider: {e}", exc_info=True)

    else:
        logger.info("Openrouter Provider not required by requested models.")

    # --- Define a Mapping of Model Initializers ---
    # The key is the requested model name; the value is a lambda returning the model instance.
    model_initializers = {
        # OpenAI Models
        "gpt-4o-mini": lambda: OpenAIModel("gpt-4o-mini", provider=openai_provider) if openai_provider else None,
        "gpt-4.1-mini": lambda: OpenAIModel("gpt-4.1-mini", provider=openai_provider) if openai_provider else None,
        "o3-mini": lambda: OpenAIModel("o3-mini", provider=openai_provider) if openai_provider else None,
        "gpt-4o": lambda: OpenAIModel("gpt-4o", provider=openai_provider) if openai_provider else None,
        "gpt-4.1": lambda: OpenAIModel("gpt-4.1", provider=openai_provider) if openai_provider else None,
        # Gemini Models
        "gemini-2.0-flash": lambda: GeminiModel("gemini-2.0-flash", provider=gemini_provider) if gemini_provider else None,
        "gemini-2.5-flash-preview-04-17": lambda: GeminiModel("gemini-2.5-flash-preview-04-17", provider=gemini_provider) if gemini_provider else None,
        "gemini-2.5-pro-preview-05-06": lambda: GeminiModel("gemini-2.5-pro-preview-05-06", provider=gemini_provider) if gemini_provider else None,
        "gemma-3-27b-it": lambda: GeminiModel("gemma-3-27b-it", provider=gemini_provider) if gemini_provider else None,
        # Groq Models
        "meta-llama/llama-4-scout-17b-16e-instruct": lambda: GroqModel("meta-llama/llama-4-scout-17b-16e-instruct", provider=groq_provider) if groq_provider else None,
        "meta-llama/llama-4-maverick-17b-128e-instruct": lambda: GroqModel("meta-llama/llama-4-maverick-17b-128e-instruct", provider=groq_provider) if groq_provider else None,
        # Openrouter Models
        "google/gemma-3-27b-it": lambda: OpenAIModel("google/gemma-3-27b-it", provider=openrouter_provider) if openrouter_provider else None,
        "qwen/qwen-vl-plus": lambda: OpenAIModel("qwen/qwen-vl-plus", provider=openrouter_provider) if openrouter_provider else None,
        "deepseek/deepseek-r1": lambda: OpenAIModel("deepseek/deepseek-r1", provider=openrouter_provider) if openrouter_provider else None,
        # Ollama Models
        "ollama/gemma3:4b": lambda: OpenAIModel("gemma3:4b", provider=ollama_provider) if ollama_provider else None,
        "ollama/gemma3:27b": lambda: OpenAIModel("gemma3:27b", provider=ollama_provider) if ollama_provider else None,
    }

    # --- Initialize Only the Requested Models ---
    available_models = []
    for model_str in models:
        initializer = model_initializers.get(model_str)
        if initializer is None:
            logger.warning(f"Model '{model_str}' is not recognized. Skipping it.")
        else:
            try:
                model_instance = initializer()
                if model_instance:
                    available_models.append(model_instance)
                    logger.info(f"Model '{model_str}' initialized successfully.")
                else:
                    logger.warning(f"Provider not available for model '{model_str}'. Skipping it.")
            except Exception as e:
                logger.warning(f"Failed to initialize model '{model_str}': {e}", exc_info=True)

    logger.info("[bold blue]--- Initialization Complete ---[/bold blue]\n")
    if not available_models:
        logger.error("No LLM models available after initialization.")
        return "classification_failed_no_models"

    model_names = [getattr(m, 'model_name', 'UnknownModel') for m in available_models]
    logger.info(f"Using fallback model with available models: {model_names}")

    fallback_model = FallbackModel(*available_models)
    return fallback_model


if __name__ == "__main__":
    
    # ──────────────────────────────  logging  ──────────────────────────────
    from rich import traceback
    from rich.logging import RichHandler
    from datetime import datetime
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )
    logger = logging.getLogger(__name__)
    traceback.install()

    def now_timestamp() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # up to milliseconds
    
    
    # Define which models to initialize.
    models_to_initialize = [
        "ollama/gemma3:27b",
        # "ollama/gemma3:4b",
        # "google/gemma-3-27b-it",
        "gpt-4o-mini",
        "o3-mini",
        "gemini-2.0-flash",
        "meta-llama/llama-4-scout-17b-16e-instruct"
    ]
    
    fallback_model = setup_fallback_model(models_to_initialize)
    
    from pydantic_ai import Agent
    agent = Agent(model=fallback_model, system_prompt="Concisely answer the user prompt in user prompt language")
    
    
    # Output the result.
    logger.info(f"Agent START at {now_timestamp()}")
    logger.info(f'Agent output: {agent.run_sync("Cześć witam! mówisz po polsku?")}')
    logger.info(f"Agent STOP at {now_timestamp()}")
