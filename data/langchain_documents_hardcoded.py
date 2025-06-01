# C:\Users\czarn\Documents\A_PYTHON\GraphForRAG\data\langchain_documents_hardcoded.py
from langchain_core.documents import Document
import uuid
from datetime import datetime
import json

# --- Source 1: Project Phoenix ---
SOURCE_1_IDENTIFIER = "project_phoenix_plan_v1.docx"
SOURCE_1_METADATA = {
    "author": "Jane Doe",
    "project_lead": "John Smith",
    "status": "Draft",
    "version_history": ["v0.1-proposal", "v0.5-initial_draft"], # List of strings
    "last_reviewed": datetime(2024, 1, 15).isoformat() # Datetime to ISO string
}

project_phoenix_documents = [
    Document(
        page_content="Project Phoenix: Introduction and Goals. This project aims to revitalize the company's core product line by incorporating next-generation AI capabilities. The primary goal is to increase market share by 20% within two years.",
        metadata={
            "name": f"{SOURCE_1_IDENTIFIER} - Chunk 1 (Introduction)",
            "chunk_uuid": str(uuid.uuid4()),
            "chunk_number": 1,
            "section": "1.0 Introduction",
            "keywords": ["AI", "revitalization", "market share"]
        }
    ),
    Document(
        page_content="Technical Approach: The project will leverage a microservices architecture, with a dedicated AI inference engine. Key technologies include Python, TensorFlow, and Kubernetes for orchestration. Data pipelines will be built using Apache Kafka.",
        metadata={
            "name": f"{SOURCE_1_IDENTIFIER} - Chunk 2 (Tech Approach)",
            "chunk_uuid": str(uuid.uuid4()),
            "chunk_number": 2,
            "section": "2.0 Technical Details",
            "complexity": "high",
            "requires_specialist_review": True
        }
    ),
    Document(
        page_content="Team Structure and Roles: The core team consists of a Project Lead, two Senior AI Engineers, three Backend Developers, and a UX Designer. External consultants may be engaged for specialized tasks. Bi-weekly sprints are planned.",
        metadata={
            "name": f"{SOURCE_1_IDENTIFIER} - Chunk 3 (Team)",
            "chunk_uuid": str(uuid.uuid4()),
            "chunk_number": 3,
            "section": "3.0 Team and Organization",
            "team_size": 7,
            "agile_methodology": "Scrum-like"
        }
    ),
    Document(
        page_content="Risks and Mitigation: Potential risks include talent acquisition delays, underestimation of AI model training time, and integration challenges with legacy systems. Mitigation strategies involve proactive hiring and modular design.",
        metadata={
            "name": f"{SOURCE_1_IDENTIFIER} - Chunk 4 (Risks)",
            "chunk_uuid": str(uuid.uuid4()),
            "chunk_number": 4,
            "section": "4.0 Risk Assessment",
            "risk_level": "medium",
            "mitigation_plan_exists": True
        }
    )
]

# --- Source 2: Market Analysis Report ---
SOURCE_2_IDENTIFIER = "q1_market_analysis_2024.pdf"
SOURCE_2_METADATA = {
    "analyst_name": "Robert Analyst",
    "report_date": datetime(2024, 4, 5).isoformat(),
    "confidentiality": "Internal Use Only",
    "data_sources": ["Surveys", "Industry Reports", "Sales Data"],
    "executive_summary_available": True
}

market_analysis_documents = [
    Document(
        page_content="Q1 Market Analysis: Executive Summary. The first quarter saw a significant shift in consumer preferences towards sustainable products. Our key competitors have responded by launching eco-friendly product lines. Overall market growth was 3.5%.",
        metadata={
            "name": f"{SOURCE_2_IDENTIFIER} - Chunk 1 (Exec Summary)",
            "chunk_uuid": str(uuid.uuid4()),
            "chunk_number": 1,
            "report_section": "Executive Summary",
            "key_finding": "Shift to sustainability"
        }
    ),
    Document(
        page_content="Competitor Activity: Competitor A launched 'EcoPure' range, gaining 5% market share. Competitor B focused on digital marketing, increasing online engagement by 15%. We need to monitor Competitor C's upcoming product reveal closely.",
        metadata={
            "name": f"{SOURCE_2_IDENTIFIER} - Chunk 2 (Competitors)",
            "chunk_uuid": str(uuid.uuid4()),
            "chunk_number": 2,
            "report_section": "Competitive Landscape",
            "competitors_mentioned": ["Competitor A", "Competitor B", "Competitor C"]
        }
    ),
    Document(
        page_content="Customer Sentiment Analysis: Sentiment for our brand remains positive but shows a slight decline in the 18-25 demographic. Feedback indicates a desire for more innovative features and better customer support response times. Social media buzz is moderate.",
        metadata={
            "name": f"{SOURCE_2_IDENTIFIER} - Chunk 3 (Sentiment)",
            "chunk_uuid": str(uuid.uuid4()),
            "chunk_number": 3,
            "report_section": "Customer Sentiment",
            "sentiment_score_overall": 0.65, # Example numeric data
            "demographic_focus": "18-25"
        }
    ),
    Document(
        page_content="Recommendations and Outlook: We recommend investing in R&D for sustainable materials and launching a targeted marketing campaign for the younger demographic. The outlook for Q2 is cautiously optimistic, projecting 4% growth if strategies are implemented effectively.",
        metadata={
            "name": f"{SOURCE_2_IDENTIFIER} - Chunk 4 (Recommendations)",
            "chunk_uuid": str(uuid.uuid4()),
            "chunk_number": 4,
            "report_section": "Recommendations & Outlook",
            "action_items": ["R&D investment", "Targeted marketing"]
        }
    )
]



# --- Source 3: Product Feed (JSON content, with key fields also in metadata) ---
SOURCE_3_IDENTIFIER = "product_catalog_electronics_v3.jsonl" # Slightly different name for clarity
SOURCE_3_METADATA = {
    "feed_generator": "CatalogSystemXYZ",
    "last_full_export": datetime(2024, 5, 10, 14, 0, 0).isoformat(),
    "format_version": "3.1"
}

# Product Data Definitions (Python Dictionaries)
product1_data = {
    "productId": "ELEC-001-PRO",
    "productName": "SmartHome Hub X2000 Pro",
    "category": "Smart Home Automation",
    "price": 149.99,
    "stock": 60,
    "features": ["Enhanced AI", "Matter Support", "Improved Mobile App"],
    "supplier_details": {"name": "Supplier Alpha Rev.2", "contact_id": "SA-987-R2", "rating": 4.5},
    "release_date": datetime(2024, 2, 1).isoformat()
}
product2_data = {
    "productId": "ELEC-002-ULTRA",
    "productName": "UltraSound Headphones Elite",
    "category": "Premium Audio",
    "price": 249.00,
    "stock": 90,
    "color_options": ["Midnight Black", "Arctic White"],
    "rating_avg": 4.8,
    "audio_specs": {"driver_size_mm": 50, "impedance_ohm": 32, "noise_cancellation": "active_hybrid"}
}
product3_data = {
    "sku": "ELEC-003-C-GREEN",
    "title": "EcoCharge Solar PowerBank G2 (Green)",
    "category": "Portable Power",
    "price": 55.00,
    "capacity_mAh": 12000,
    "is_eco_friendly": True,
    "ports": ["USB-C PD", "USB-A QC3.0"],
    "dimensions_cm": {"length": 15, "width": 7, "height": 2.5}
}
product4_data = {
    "item_id": "ELEC-004-QLED",
    "item_name": "VividView 8K QLED TV 65-inch",
    "category": "Home Entertainment - Televisions",
    "price": 1299.00,
    "stock": 20,
    "resolution": "7680x4320",
    "smart_os": "QuantumOS v3",
    "available_since": datetime(2023,11,1).isoformat(),
    "energy_rating": "A+"
}

product_feed_documents = [
    Document(
        page_content=json.dumps(product1_data), # Full JSON string as content
        metadata={
            # Key fields from product1_data are explicitly added here for direct property creation
            "name": product1_data["productName"], # Use a field from JSON for the chunk name
            "chunk_uuid": str(uuid.uuid4()),
            # No "chunk_number" for individual product listings
            "content_type": "json", # Good practice to still tag it
            "productId": product1_data["productId"],
            "category": product1_data["category"],
            "price": product1_data["price"],
            "stock": product1_data["stock"],
            "features": product1_data["features"], # List of strings
            "supplier_info_json": product1_data["supplier_details"], # Nested dict will be stringified by _preprocess
            "release_date": product1_data["release_date"] # Already a string
        }
    ),
    Document(
        page_content=json.dumps(product2_data),
        metadata={
            "name": product2_data["productName"],
            "chunk_uuid": str(uuid.uuid4()),
            "content_type": "json",
            "productId": product2_data["productId"],
            "category": product2_data["category"],
            "price": product2_data["price"],
            "color_options": product2_data["color_options"],
            "rating_avg": product2_data["rating_avg"],
            "audio_specs_json": product2_data["audio_specs"] # Nested dict
        }
    ),
    Document(
        page_content=json.dumps(product3_data),
        metadata={
            "name": product3_data["title"], # Using "title" field from this product's JSON
            "chunk_uuid": str(uuid.uuid4()),
            "content_type": "json",
            "sku": product3_data["sku"],
            "category": product3_data["category"],
            "price": product3_data["price"],
            "capacity_mAh": product3_data["capacity_mAh"],
            "is_eco_friendly": product3_data["is_eco_friendly"],
            "ports": product3_data["ports"],
            "dimensions_cm_json": product3_data["dimensions_cm"] # Nested dict
        }
    ),
    Document(
        page_content=json.dumps(product4_data),
        metadata={
            "name": product4_data["item_name"], # Using "item_name"
            "chunk_uuid": str(uuid.uuid4()),
            "content_type": "json",
            "item_id": product4_data["item_id"],
            "category": product4_data["category"],
            "price": product4_data["price"],
            "resolution": product4_data["resolution"],
            "smart_os": product4_data["smart_os"],
            "available_since": product4_data["available_since"], # Already a string
            "energy_rating": product4_data["energy_rating"]
        }
    )
]

source_data_sets = [
    {
        "identifier": SOURCE_1_IDENTIFIER,
        "source_metadata": SOURCE_1_METADATA,
        "source_content": "This is a summary or main content for Source A itself. It describes the overall theme of the narrative text contained in its chunks.",
        "documents": project_phoenix_documents
    },
    {
        "identifier": SOURCE_2_IDENTIFIER,
        "source_metadata": SOURCE_2_METADATA,
        "documents": market_analysis_documents
    },
    {
        "identifier": SOURCE_3_IDENTIFIER,
        "source_metadata": SOURCE_3_METADATA,
        "source_content": "This source contains a catalog of electronic widgets and gadgets. Each product is detailed in its respective chunk.", # <-- ADDED
        "documents": product_feed_documents
    }
]