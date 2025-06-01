# C:\Users\czarn\Documents\A_PYTHON\GraphForRAG\data\langchain_documents.py
from langchain_core.documents import Document
import uuid
from datetime import datetime # For last_modified example

BASE_TEXT_1 = "Artificial intelligence (AI) is intelligence demonstrated by machines, as opposed to the natural intelligence displayed by humans and animals. Leading AI textbooks define the field as the study of 'intelligent agents': any device that perceives its environment and takes actions that maximize its chance of successfully achieving its goals. Some popular accounts use the term 'artificial intelligence' to describe machines that mimic 'cognitive' functions that humans associate with the human mind, such as 'learning' and 'problem solving', however, this definition is rejected by major AI researchers. AI applications include advanced web search engines (e.g., Google Search), recommendation systems (used by YouTube, Amazon and Netflix), understanding human speech (such as Siri and Alexa), self-driving cars (e.g., Waymo), generative or creative tools (ChatGPT and AI art), and competing at the highest level in strategic games (such as chess and Go)."
BASE_TEXT_2 = "Climate change includes both global warming driven by human emissions of greenhouse gases and the resulting large-scale shifts in weather patterns. Though there have been previous periods of climatic change, since the mid-20th century humans have had an unprecedented impact on Earth's climate system and caused change on a global scale. The largest driver of warming is the emission of greenhouse gases, of which more than 90% are carbon dioxide (CO2) and methane. Fossil fuel burning (coal, oil, and natural gas) for energy consumption is the main source of these emissions, with additional contributions from agriculture, deforestation, and industrial processes. The human cause of climate change is not disputed by any scientific body of national or international standing. Temperature rise is accelerated or tempered by climate feedbacks, such as loss of sunlight-reflecting snow and ice cover, increased water vapour (a greenhouse gas itself), and changes to land and ocean carbon sinks."
CHUNK_SIZE = 180

def generate_document_chunks(base_text: str, source_file_name: str, chunk_size: int) -> list[Document]:
    docs = []
    num_total_chunks = (len(base_text) + chunk_size - 1) // chunk_size
    for i in range(num_total_chunks):
        start_char = i * chunk_size
        end_char = start_char + chunk_size
        content_chunk = base_text[start_char:end_char].strip()
        if not content_chunk:
            continue

        current_chunk_number = i + 1
        chunk_name = f"{source_file_name} - Chunk {current_chunk_number}"
        doc_uuid = str(uuid.uuid4())

        chunk_metadata = {
            "name": chunk_name, # Will be used as direct property
            "chunk_uuid": doc_uuid, # Will be used as direct property
            "chunk_number": current_chunk_number, # Will be used as direct property
            "processed_by_script_version": "1.3.0",
            "chunk_length_chars": len(content_chunk)
        }
        if i == 0:
            chunk_metadata["is_first_chunk"] = True
            chunk_metadata["review_status"] = "pending"
            # Example of a nested dictionary that will be JSON stringified
            chunk_metadata["processing_details"] = {
                "tokenizer": "default_v2",
                "split_method": "char_count"
            }
        if i == 1:
             chunk_metadata["priority_level"] = 2


        docs.append(
            Document(
                page_content=content_chunk,
                metadata=chunk_metadata # Python will process this before sending to Cypher
            )
        )
    return docs

source_data_sets = [
    {
        "identifier": "ai_overview_article.pdf",
        "source_metadata": {
            "author": "AI Research Group",
            "publication_year": 2024,
            "category": "technology_review",
            "last_modified": datetime(2024, 3, 10).isoformat(), # Stringified datetime
            "tags": ["AI", "ML", "Review"] # List of strings
        },
        "documents": generate_document_chunks(
            BASE_TEXT_1, "ai_overview_article.pdf", CHUNK_SIZE
        )
    },
    {
        "identifier": "climate_change_summary.pdf",
        "source_metadata": {
            "author": "Environmental Science Dept.",
            "publication_year": 2023,
            "category": "science_report",
            "keywords": ["global warming", "emissions", "policy"],
            "version" : "final_draft",
            "review_date": datetime(2023,12,1).isoformat(),
            # Example of a nested dictionary for source metadata
            "contact_info": {
                "email": "env_sci@example.com",
                "phone": "555-0123"
            }
        },
        "documents": generate_document_chunks(
            BASE_TEXT_2, "climate_change_summary.pdf", CHUNK_SIZE
        )
    }
]