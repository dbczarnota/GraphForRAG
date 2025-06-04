# data/source_data.py
from datetime import datetime
import json

# Each item in this list represents a "source"
# Each source has an 'identifier', 'source_content', 'source_metadata',
# and a list of 'chunks' (which can represent generic chunks or specific node types like products).
# Each item in the 'chunks' list will have:
#   - page_content: The core content.
#   - node_type: (Optional) Top-level hint for processing logic, e.g., "product", "chunk". Defaults to "chunk".
#   - content_type: (Optional) Top-level hint for page_content parsing, e.g., "json", "text". Defaults to "text".
#   - metadata: A dictionary for all other attributes.

source_data_sets = [
    {
        "identifier": "Winnie-the-Pooh: A Tight Spot at Rabbit's House (Chapter II Excerpt)",
        "source_content": "An extended excerpt from A. A. Milne's 'Winnie-the-Pooh', Chapter II, detailing Pooh's visit to Rabbit's house, his overindulgence in honey and condensed milk, and the subsequent predicament of getting stuck in Rabbit's front door. This section highlights the interactions between Pooh, Rabbit, and eventually Christopher Robin.",
        "source_metadata": { # Metadata for the Source node itself
            "author": "A. A. Milne",
            "illustrator": "E. H. Shepard",
            "original_publication_year": 1926,
            "category": "Children's Literature",
            "chapter_focus": "Pooh's Visit and Getting Stuck"
        },
        "chunks": [ # These are generic text chunks; node_type/content_type will default
            {
                "page_content": "Winnie-the-Pooh always liked a little something at eleven o’clock in the morning, and he was very glad to see Rabbit getting out the plates and mugs. 'Is this a party?' he asked. 'No, Pooh Bear,' said Rabbit kindly, 'just a little something for you.' 'Oh, thank you, Rabbit,' said Pooh. Rabbit, who was a hospitable sort, produced a jar of honey and a tin of condensed milk. Pooh, never one to refuse, settled down to enjoy his snack. 'You're sure there's enough for me?' he asked, peering into the honey jar.",
                "metadata": { 
                    "name": "Pooh Visits Rabbit - The Snack", 
                    "chunk_number": 1, 
                    "characters_present": ["Winnie-the-Pooh", "Rabbit"], 
                    "interaction_type": "Conversation, Hospitality", 
                    "setting": "Rabbit's House - Parlour"
                }
            },
            {
                "page_content": "Rabbit watched Pooh eat. 'Would you like some more honey, Pooh?' he offered, noticing the jar was nearly empty. 'Well,' said Pooh, reaching for the condensed milk, 'I did mean to just have a little, but perhaps a tiny bit more honey wouldn't go amiss.' Rabbit, trying to be a good host, although a little worried about his provisions, refilled the jar. Pooh ate, and ate, and ate, until at last he said that he must be going. 'Must you?' said Rabbit politely. 'Well, if you're sure... goodbye, Pooh.'",
                "metadata": {"name": "Pooh Overindulges", "chunk_number": 2, "characters_present": ["Winnie-the-Pooh", "Rabbit"], "interaction_type": "Offering food, Eating, Polite conversation", "theme": "Hospitality vs. Concern"}
            },
            {
                "page_content": "Pooh Bear began to climb out of Rabbit's front door. He pulled with his front paws, and pushed with his back paws, and in a little while his nose was out in the open again... and then his ears... and then his front paws... and then his shoulders... and then— 'Oh, help!' said Pooh. 'I'd better go back.' 'Oh, bother!' said Pooh. 'I shall have to go on.' 'I can't do either!' said Pooh. 'Oh, help and bother!' Now, by this time Rabbit wanted to go for a walk too, and finding the front door full, he went out by the back door, and came round to Pooh, and looked at him.",
                "metadata": {"name": "Pooh Gets Stuck", "chunk_number": 3, "characters_present": ["Winnie-the-Pooh", "Rabbit"], "interaction_type": "Physical struggle, Observation", "problem": "Pooh is stuck", "setting_detail": "Rabbit's front door"}
            },
            {
                "page_content": "'Hallo, are you stuck?' he asked. Pooh looked at him with his front paws dangling. 'N-no,' said Pooh carelessly. 'Just resting, and thinking, and humming to myself.' 'Here, give us a paw,' said Rabbit, and he took Pooh's paw and pulled, and Pooh pulled, but nothing happened. 'It all comes,' said Pooh crossly, 'of not having front doors big enough.' 'It all comes,' said Rabbit sternly, 'of eating too much. I thought at the time,' said Rabbit, 'only I didn't like to say anything,' said Rabbit, 'that one of us was eating too much,' said Rabbit, 'and I knew it wasn't me,' he said. 'He, he,' said Pooh.",
                "metadata": {"name": "Rabbit's Assessment", "chunk_number": 4, "characters_present": ["Winnie-the-Pooh", "Rabbit"], "interaction_type": "Dialogue, Attempted help, Gentle accusation", "theme": "Consequences of overeating"}
            },
            {
                "page_content": "So Rabbit pushed and pushed from behind, and Pooh pulled and pulled from in front, but Pooh's bottom just stayed where it was. Rabbit scratched his whiskers. 'We shall have to get Christopher Robin,' he said. 'He'll know what to do.' He hurried off to find him. Pooh, left alone, tried to hum a comforting sort of song, but it wasn't very comforting because he couldn't think of any words for the middle part. Christopher Robin soon arrived with Rabbit. 'Silly old Bear,' he said affectionately, looking at Pooh's predicament.",
                "metadata": {"name": "Calling Christopher Robin", "chunk_number": 5, "characters_present": ["Winnie-the-Pooh", "Rabbit", "Christopher Robin"], "interaction_type": "Decision to seek help, Arrival of help, Affectionate scolding", "resolution_pending": "Waiting for a solution"}
            }
        ]
    },
    {
        "identifier": "Navigating the World of Personal Computers: 2024 Edition",
        "source_content": "A comprehensive guide to understanding the diverse landscape of personal computers in 2024. This guide covers powerful desktops, versatile laptops, innovative 2-in-1s, budget-friendly Chromebooks, and compact Mini PCs, helping you identify the best device for your specific needs, whether for gaming, professional work, education, or everyday use.",
        "source_metadata": {
            "author": "Tech Savvy Guides Inc.",
            "publication_date": "2024-07-15",
            "category": "Technology Hardware",
            "version": "1.0"
        },
        "chunks": [
            {
                "page_content": "Personal computers have evolved dramatically, offering specialized solutions for every user. Desktops remain the champions of raw power and upgradability. High-performance gaming rigs, such as Alienware's Aurora R16, which often features the powerful Intel Core i9 CPU and a top-tier NVIDIA GeForce RTX 40-series GPU, or custom-built PCs utilizing AMD Ryzen 9 CPUs and AMD Radeon RX 7000-series GPUs, deliver unparalleled performance for demanding games and professional applications like 3D rendering or complex simulations. Apple's iMac series continues to offer elegant all-in-one solutions for creative professionals who value design and a streamlined macOS experience. The key advantages of desktops include superior thermal management, easier component replacement/upgrades, and often better cost-to-performance ratios for high-end configurations.",
                "metadata": {"name": "Guide - Desktops: Power & Upgradability", "chunk_number": 1, "keywords": ["desktops", "gaming PC", "custom PC", "Alienware Aurora R16", "Intel Core i9 CPU", "NVIDIA GeForce RTX 40-series GPU", "iMac", "AMD Ryzen 9 CPUs", "AMD Radeon RX 7000-series GPUs", "upgradability"]}
            },
            {
                "page_content": "Laptops masterfully blend portability with impressive performance, catering to a vast audience. Ultrabooks like the Dell XPS 13 (2024 model), often powered by an Intel Core Ultra 7 processor, and Apple's MacBook Air with the M3 chip are celebrated for their sleek designs, lightweight construction, and extended battery life, making them ideal for students, writers, and mobile professionals. The Dell XPS 13 is particularly well-suited for mobile professionals. For users needing more horsepower, gaming laptops such as the ASUS ROG Zephyrus G16, equipped with high-end NVIDIA GPUs, or the Razer Blade series, and creative powerhouses like the MacBook Pro (M3 Pro/Max chips) or Dell Precision mobile workstations, pack near desktop-grade components into a portable chassis. Key considerations when choosing a laptop include screen size and quality (OLED options are becoming more common), keyboard comfort, trackpad responsiveness, port selection, overall weight, and, crucially, battery endurance for your typical usage patterns. The ASUS ROG Zephyrus G16 is considered a strong competitor to other thin-and-light gaming machines.",
                "metadata": {"name": "Guide - Laptops: Portability & Performance", "chunk_number": 2, "keywords": ["laptops", "ultrabooks", "Dell XPS 13", "Intel Core Ultra 7", "MacBook Air M3", "gaming laptops", "ASUS ROG Zephyrus G16", "NVIDIA GPUs", "MacBook Pro M3", "mobile professionals"]}
            },
            {
                "page_content": "The distinction between laptops and tablets is increasingly blurred by 2-in-1 convertibles and tablets with first-party keyboard accessories. Microsoft's Surface Pro 9, a versatile device, and the newer Surface Pro 10 for Business are prime examples, offering a full Windows experience with tablet portability and excellent pen input, complemented by their Type Cover keyboards. The Surface Pro 9 is often compared to Apple's iPad Pro for creative tasks. Lenovo's Yoga series (e.g., Yoga 9i) features 360-degree hinges, allowing for versatile usage modes like tent, stand, and tablet. These devices excel for artists, note-takers, presenters, and anyone valuing adaptability. While performance can be very good, especially with higher-end configurations, it might not always match dedicated clamshell laptops or desktops at the same price point, and the typing experience on detachable keyboards can vary in comfort for extended sessions.",
                "metadata": {"name": "Guide - 2-in-1s & Convertibles: Flexibility", "chunk_number": 3, "keywords": ["2-in-1 laptops", "convertible laptops", "Microsoft Surface Pro 9", "Apple iPad Pro", "Lenovo Yoga", "tablets with keyboards", "pen input"]}
            },
            {
                "page_content": "For budget-conscious users or those with specific, less demanding needs, Chromebooks and Mini PCs present compelling alternatives. Chromebooks, powered by Google's ChromeOS, are known for their simplicity, security, fast boot times, and often very attractive pricing (e.g., Acer Chromebook Spin series, Lenovo Duet). They are excellent for web browsing, online productivity suites like Google Workspace, media consumption, and educational purposes. Mini PCs, such as the Intel NUC, Mac mini, or Beelink SER series, offer a remarkably small desktop footprint, ideal for home theatre PC (HTPC) setups, light office work, or digital signage. While their processing power and graphical capabilities are typically more limited than full-sized desktops or mainstream laptops, they shine in their specific niches due to their compact size and lower power consumption. The Mac mini, for example, is a good entry into the macOS ecosystem.",
                "metadata": {"name": "Guide - Chromebooks & Mini PCs: Niche Solutions", "chunk_number": 4, "keywords": ["Chromebooks", "ChromeOS", "Mini PCs", "Intel NUC", "Mac mini", "macOS", "budget computers", "education tech"]}
            },
            {
                "page_content": "Ultimately, selecting the right computer hinges on a clear understanding of your primary use cases, budget constraints, and portability requirements. Gamers and professional content creators (video editors, 3D artists) will likely gravitate towards powerful desktops or high-end gaming/creative laptops like the ASUS ROG Zephyrus G16. Students and mobile professionals often find ultrabooks like the Dell XPS 13 or the MacBook Air M3, or versatile 2-in-1s like the Microsoft Surface Pro 9, to be the best fit. For basic tasks, web browsing, and users prioritizing affordability and simplicity, Chromebooks are strong contenders. Key specifications to scrutinize before purchase include the amount of RAM (16GB is a good baseline for many, 32GB+ for demanding tasks), storage type and capacity (NVMe SSD is essential for speed), CPU model and generation (e.g. Intel Core Ultra 7), GPU (if needed for gaming or creative work), and display quality (resolution, color accuracy, refresh rate). Always read recent reviews and compare specific models within your chosen category.",
                "metadata": {"name": "Guide - Choosing Your Computer: Key Factors", "chunk_number": 5, "keywords": ["computer buying guide", "PC selection", "RAM", "SSD", "CPU choice", "GPU choice", "use case analysis", "Dell XPS 13", "MacBook Air M3", "Microsoft Surface Pro 9", "ASUS ROG Zephyrus G16"]}
            }
        ]
    },
    {
        "identifier": "Q3 2024 Tech Product Showcase",
        "source_content": "A curated selection of featured high-performance and versatile computing products for the third quarter of 2024. This showcase includes leading laptops, ultrabooks, and 2-in-1 devices from top brands, highlighting their key features and specifications to aid in your purchasing decisions.",
        "source_metadata": {
            "catalog_version": "2024.3.1",
            "release_date": datetime(2024, 7, 1).isoformat(),
            "region": "Global",
            "prepared_by": "TechReview Central"
        },
        "chunks": [ 
            {
                "node_type": "product",  
                "content_type": "json",  
                "page_content": json.dumps({ 
                    "productName": "Apple MacBook Air 13-inch (M3 Chip)", 
                    "brand": "Apple", "category": "Ultrabook Laptop", "sku": "APL-MBA-M3-13-256G8C",
                    "release_year": 2024, "price_usd": 1099.00,
                    "features": ["Apple M3 chip with 8-core CPU and up to 10-core GPU", "13.6-inch Liquid Retina display with True Tone", "Up to 18 hours battery life", "Fanless design for silent operation"], 
                    "description": "The latest MacBook Air, powered by the efficient M3 chip, delivers even more performance and capability in its incredibly thin and light design. Perfect for students and professionals on the go.",
                    "specifications": { "processor": "Apple M3", "memory_gb": "8GB Unified", "storage_gb_ssd": 256, "display_resolution": "2560x1664" } 
                }),
                "metadata": { 
                    "name": "Apple MacBook Air 13-inch (M3 Chip) - Showcase Entry", 
                    "description": "Showcase entry for the MacBook Air M3, highlighting its M3 chip and long battery life.", 
                    "brand_category": "Apple Laptop", "target_audience": "Students, Professionals, General Users",
                    "priority_display": 1,
                    "editor_rating": 4.5 
                }
            },
            {
                "node_type": "product",
                "content_type": "json",
                "page_content": json.dumps({
                    "productName": "Dell XPS 13 (2024 Model 9340)", "brand": "Dell", "sku": "DEL-XPS13-9340-I716512",
                    "category": "Ultrabook Laptop", "price_usd": 1299.00, "release_year": 2024,
                    "description": "The Dell XPS 13 (2024) continues its legacy of premium design and performance, now with Intel Core Ultra processors for enhanced AI capabilities and efficiency. Its stunning InfinityEdge display and compact form factor make it an ideal choice for productivity on the move.",
                    "key_specs": ["Intel Core Ultra 7 processor", "16GB LPDDR5x RAM", "512GB PCIe NVMe SSD", "13.4-inch FHD+ InfinityEdge display"],
                    "features": ["AI-powered performance", "CNC machined aluminum chassis", "Windows 11 Pro"]
                }),
                "metadata": {
                    "name": "Dell XPS 13 (2024) - Showcase Entry",
                    "description": "Detailed showcase of the Dell XPS 13 (2024) featuring Intel Core Ultra 7.",
                    "brand_category": "Dell Laptop", "target_audience": "Professionals, Executives, Power Users",
                    "review_score_techradar": 9.0
                }
            },
            {
                "node_type": "product",
                "content_type": "json",
                "page_content": json.dumps({
                    "productName": "Microsoft Surface Pro 9 (Intel)", "brand": "Microsoft", "sku": "MSFT-SP9-I58256",
                    "category": "2-in-1 Convertible", "price_usd": 999.00, "release_year": 2022, # Assuming 2022 release for SP9
                    "description": "The Surface Pro 9 offers the versatility of a tablet and the performance of a laptop. With 12th Gen Intel Core processors, a vibrant PixelSense display, and optional Surface Slim Pen 2 support, it's built for productivity and creativity.",
                    "pen_support": True, "operating_system": "Windows 11",
                    "key_specs": ["12th Gen Intel Core i5", "8GB RAM", "256GB SSD", "13-inch PixelSense Flow Display"]
                }),
                "metadata": {
                    "name": "Microsoft Surface Pro 9 - Showcase Entry", 
                    "description": "Showcase of the Microsoft Surface Pro 9 (Intel variant) emphasizing its 2-in-1 nature.",
                    "brand_category": "Microsoft 2-in-1", 
                    "target_audience": "Mobile Professionals, Creatives, Students",
                    "keyboard_sold_separately": True
                }
            },
            {
                "node_type": "product",
                "content_type": "json",
                "page_content": json.dumps({
                    "productName": "ASUS ROG Zephyrus G16 (2024 GU605)", "brand": "ASUS", "sku": "ASUS-ROG-G16-GU605-R9N4070",
                    "category": "Gaming Laptop", "price_usd": 1999.99, "release_year": 2024,
                    "description": "The 2024 ROG Zephyrus G16 redefines thin-and-light gaming with its stunning OLED Nebula Display, powerful Intel Core Ultra 9 processor, and NVIDIA GeForce RTX 4070 Laptop GPU. Its sleek chassis and advanced cooling make it a portable powerhouse.",
                    "display_type": "OLED Nebula Display", "refresh_rate_hz": 240,
                    "key_specs": ["Intel Core Ultra 9 processor", "NVIDIA GeForce RTX 4070", "16GB DDR5 RAM", "1TB PCIe 4.0 SSD"]
                }),
                "metadata": {
                    "name": "ASUS ROG Zephyrus G16 (2024) - Showcase Entry", 
                    "description": "Highlighting the ASUS ROG Zephyrus G16 (2024) gaming laptop with OLED display and RTX 4070.",
                    "brand_category": "ASUS Gaming Laptop", 
                    "target_audience": "Gamers, Content Creators, Power Users",
                    "availability_status": "Pre-order"
                }
            }
        ]
    }
]