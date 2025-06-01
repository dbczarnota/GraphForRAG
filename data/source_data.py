from datetime import datetime
import json

# data/source_data.py

# Each item in this list represents a "source"
# Each source has an 'identifier', 'source_content', 'source_metadata',
# and a list of 'chunks'.
# Each chunk is a dictionary with 'page_content' and 'metadata'.

source_data_sets = [
    {
        "identifier": "Winnie-the-Pooh: A Tight Spot at Rabbit's House (Chapter II Excerpt)",
        "source_content": "An extended excerpt from A. A. Milne's 'Winnie-the-Pooh', Chapter II, detailing Pooh's visit to Rabbit's house, his overindulgence in honey and condensed milk, and the subsequent predicament of getting stuck in Rabbit's front door. This section highlights the interactions between Pooh, Rabbit, and eventually Christopher Robin.",
        "source_metadata": {
            "author": "A. A. Milne",
            "illustrator": "E. H. Shepard",
            "original_publication_year": 1926,
            "category": "Children's Literature",
            "chapter_focus": "Pooh's Visit and Getting Stuck"
        },
        "chunks": [
            {
                "page_content": "Winnie-the-Pooh always liked a little something at eleven o’clock in the morning, and he was very glad to see Rabbit getting out the plates and mugs. 'Is this a party?' he asked. 'No, Pooh Bear,' said Rabbit kindly, 'just a little something for you.' 'Oh, thank you, Rabbit,' said Pooh. Rabbit, who was a hospitable sort, produced a jar of honey and a tin of condensed milk. Pooh, never one to refuse, settled down to enjoy his snack. 'You're sure there's enough for me?' he asked, peering into the honey jar.",
                "metadata": {"name": "Pooh Visits Rabbit - The Snack", "chunk_number": 1, "content_type": "text", "characters_present": ["Winnie-the-Pooh", "Rabbit"], "interaction_type": "Conversation, Hospitality", "setting": "Rabbit's House - Parlour"}
            },
            {
                "page_content": "Rabbit watched Pooh eat. 'Would you like some more honey, Pooh?' he offered, noticing the jar was nearly empty. 'Well,' said Pooh, reaching for the condensed milk, 'I did mean to just have a little, but perhaps a tiny bit more honey wouldn't go amiss.' Rabbit, trying to be a good host, although a little worried about his provisions, refilled the jar. Pooh ate, and ate, and ate, until at last he said that he must be going. 'Must you?' said Rabbit politely. 'Well, if you're sure... goodbye, Pooh.'",
                "metadata": {"name": "Pooh Overindulges", "chunk_number": 2, "content_type": "text", "characters_present": ["Winnie-the-Pooh", "Rabbit"], "interaction_type": "Offering food, Eating, Polite conversation", "theme": "Hospitality vs. Concern"}
            },
            {
                "page_content": "Pooh Bear began to climb out of Rabbit's front door. He pulled with his front paws, and pushed with his back paws, and in a little while his nose was out in the open again... and then his ears... and then his front paws... and then his shoulders... and then— 'Oh, help!' said Pooh. 'I'd better go back.' 'Oh, bother!' said Pooh. 'I shall have to go on.' 'I can't do either!' said Pooh. 'Oh, help and bother!' Now, by this time Rabbit wanted to go for a walk too, and finding the front door full, he went out by the back door, and came round to Pooh, and looked at him.",
                "metadata": {"name": "Pooh Gets Stuck", "chunk_number": 3, "content_type": "text", "characters_present": ["Winnie-the-Pooh", "Rabbit"], "interaction_type": "Physical struggle, Observation", "problem": "Pooh is stuck", "setting_detail": "Rabbit's front door"}
            },
            {
                "page_content": "'Hallo, are you stuck?' he asked. Pooh looked at him with his front paws dangling. 'N-no,' said Pooh carelessly. 'Just resting, and thinking, and humming to myself.' 'Here, give us a paw,' said Rabbit, and he took Pooh's paw and pulled, and Pooh pulled, but nothing happened. 'It all comes,' said Pooh crossly, 'of not having front doors big enough.' 'It all comes,' said Rabbit sternly, 'of eating too much. I thought at the time,' said Rabbit, 'only I didn't like to say anything,' said Rabbit, 'that one of us was eating too much,' said Rabbit, 'and I knew it wasn't me,' he said. 'He, he,' said Pooh.",
                "metadata": {"name": "Rabbit's Assessment", "chunk_number": 4, "content_type": "text", "characters_present": ["Winnie-the-Pooh", "Rabbit"], "interaction_type": "Dialogue, Attempted help, Gentle accusation", "theme": "Consequences of overeating"}
            },
            {
                "page_content": "So Rabbit pushed and pushed from behind, and Pooh pulled and pulled from in front, but Pooh's bottom just stayed where it was. Rabbit scratched his whiskers. 'We shall have to get Christopher Robin,' he said. 'He'll know what to do.' He hurried off to find him. Pooh, left alone, tried to hum a comforting sort of song, but it wasn't very comforting because he couldn't think of any words for the middle part. Christopher Robin soon arrived with Rabbit. 'Silly old Bear,' he said affectionately, looking at Pooh's predicament.",
                "metadata": {"name": "Calling Christopher Robin", "chunk_number": 5, "content_type": "text", "characters_present": ["Winnie-the-Pooh", "Rabbit", "Christopher Robin"], "interaction_type": "Decision to seek help, Arrival of help, Affectionate scolding", "resolution_pending": "Waiting for a solution"}
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
                "page_content": "Personal computers have evolved dramatically, offering specialized solutions for every user. Desktops remain the champions of raw power and upgradability. High-performance gaming rigs, such as Alienware's Aurora R16 or custom-built PCs featuring the latest Intel Core i9 or AMD Ryzen 9 CPUs and NVIDIA GeForce RTX 40-series / AMD Radeon RX 7000-series GPUs, deliver unparalleled performance for demanding games and professional applications like 3D rendering or complex simulations. Apple's iMac series continues to offer elegant all-in-one solutions for creative professionals who value design and a streamlined macOS experience. The key advantages of desktops include superior thermal management, easier component replacement/upgrades, and often better cost-to-performance ratios for high-end configurations.",
                "metadata": {"name": "Guide - Desktops: Power & Upgradability", "chunk_number": 1, "content_type": "text", "keywords": ["desktops", "gaming PC", "custom PC", "Alienware Aurora", "iMac", "CPU", "GPU", "upgradability"]}
            },
            {
                "page_content": "Laptops masterfully blend portability with impressive performance, catering to a vast audience. Ultrabooks like the Dell XPS 13 (2024 model) and Apple's MacBook Air with the M3 chip are celebrated for their sleek designs, lightweight construction, and extended battery life, making them ideal for students, writers, and mobile professionals. For users needing more horsepower, gaming laptops such as the ASUS ROG Zephyrus G16 or Razer Blade series, and creative powerhouses like the MacBook Pro (M3 Pro/Max chips) or Dell Precision mobile workstations, pack near desktop-grade components into a portable chassis. Key considerations when choosing a laptop include screen size and quality (OLED options are becoming more common), keyboard comfort, trackpad responsiveness, port selection, overall weight, and, crucially, battery endurance for your typical usage patterns.",
                "metadata": {"name": "Guide - Laptops: Portability & Performance", "chunk_number": 2, "content_type": "text", "keywords": ["laptops", "ultrabooks", "Dell XPS 13", "MacBook Air M3", "gaming laptops", "ASUS ROG Zephyrus", "MacBook Pro M3"]}
            },
            {
                "page_content": "The distinction between laptops and tablets is increasingly blurred by 2-in-1 convertibles and tablets with first-party keyboard accessories. Microsoft's Surface Pro 9 and the newer Surface Pro 10 for Business are prime examples, offering a full Windows experience with tablet portability and excellent pen input, complemented by their Type Cover keyboards. Lenovo's Yoga series (e.g., Yoga 9i) features 360-degree hinges, allowing for versatile usage modes like tent, stand, and tablet. These devices excel for artists, note-takers, presenters, and anyone valuing adaptability. While performance can be very good, especially with higher-end configurations, it might not always match dedicated clamshell laptops or desktops at the same price point, and the typing experience on detachable keyboards can vary in comfort for extended sessions.",
                "metadata": {"name": "Guide - 2-in-1s & Convertibles: Flexibility", "chunk_number": 3, "content_type": "text", "keywords": ["2-in-1 laptops", "convertible laptops", "Microsoft Surface Pro", "Lenovo Yoga", "tablets with keyboards", "pen input"]}
            },
            {
                "page_content": "For budget-conscious users or those with specific, less demanding needs, Chromebooks and Mini PCs present compelling alternatives. Chromebooks, powered by Google's ChromeOS, are known for their simplicity, security, fast boot times, and often very attractive pricing (e.g., Acer Chromebook Spin series, Lenovo Duet). They are excellent for web browsing, online productivity suites like Google Workspace, media consumption, and educational purposes. Mini PCs, such as the Intel NUC, Mac mini, or Beelink SER series, offer a remarkably small desktop footprint, ideal for home theatre PC (HTPC) setups, light office work, or digital signage. While their processing power and graphical capabilities are typically more limited than full-sized desktops or mainstream laptops, they shine in their specific niches due to their compact size and lower power consumption.",
                "metadata": {"name": "Guide - Chromebooks & Mini PCs: Niche Solutions", "chunk_number": 4, "content_type": "text", "keywords": ["Chromebooks", "ChromeOS", "Mini PCs", "Intel NUC", "Mac mini", "budget computers", "education tech"]}
            },
            {
                "page_content": "Ultimately, selecting the right computer hinges on a clear understanding of your primary use cases, budget constraints, and portability requirements. Gamers and professional content creators (video editors, 3D artists) will likely gravitate towards powerful desktops or high-end gaming/creative laptops. Students and mobile professionals often find ultrabooks or versatile 2-in-1s to be the best fit. For basic tasks, web browsing, and users prioritizing affordability and simplicity, Chromebooks are strong contenders. Key specifications to scrutinize before purchase include the amount of RAM (16GB is a good baseline for many, 32GB+ for demanding tasks), storage type and capacity (NVMe SSD is essential for speed), CPU model and generation, GPU (if needed for gaming or creative work), and display quality (resolution, color accuracy, refresh rate). Always read recent reviews and compare specific models within your chosen category.",
                "metadata": {"name": "Guide - Choosing Your Computer: Key Factors", "chunk_number": 5, "content_type": "text", "keywords": ["computer buying guide", "PC selection", "RAM", "SSD", "CPU choice", "GPU choice", "use case analysis"]}
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
                "page_content": json.dumps({
                    "productName": "Apple MacBook Air 13-inch (M3 Chip)",
                    "brand": "Apple",
                    "category": "Ultrabook Laptop",
                    "sku": "APL-MBA-M3-13-256G8C",
                    "release_year": 2024,
                    "price_usd": 1099.00,
                    "features": [
                        "Apple M3 chip with 8-core CPU and up to 10-core GPU",
                        "13.6-inch Liquid Retina display with True Tone",
                        "Up to 18 hours of battery life",
                        "Fanless, silent design",
                        "Thin and lightweight aluminum enclosure (2.7 pounds)",
                        "1080p FaceTime HD camera",
                        "Magic Keyboard with Touch ID"
                    ],
                    "description": "The latest MacBook Air, powered by the efficient M3 chip, offers a perfect blend of portability and performance for everyday tasks, creative projects, and light gaming. Its stunning Liquid Retina display and long battery life make it an ideal companion for users on the go.",
                    "specifications": {
                        "processor": "Apple M3 (8-core CPU, 8-core or 10-core GPU, 16-core Neural Engine)",
                        "memory_gb": "8GB unified (configurable to 16GB or 24GB)",
                        "storage_gb_ssd": "256GB (configurable to 512GB, 1TB, or 2TB)",
                        "display_size_inches": 13.6,
                        "display_resolution": "2560x1664",
                        "ports": ["2x Thunderbolt / USB 4", "MagSafe 3 charging", "3.5mm headphone jack"],
                        "operating_system": "macOS"
                    }
                }),
                "metadata": {"name": "Product - Apple MacBook Air M3 (13-inch)", "content_type": "json", "brand_category": "Apple Laptop", "target_audience": "Students, Professionals, General Users"}
            },
            {
                "page_content": json.dumps({
                    "productName": "Dell XPS 13 (2024 Model 9340)",
                    "brand": "Dell",
                    "category": "Ultrabook Laptop",
                    "sku": "DEL-XPS13-9340-I716512",
                    "release_year": 2024,
                    "price_usd": 1299.00,
                    "features": [
                        "Intel Core Ultra 7 processor (e.g., 155H)",
                        "13.4-inch InfinityEdge display (FHD+ or QHD+ options, touch optional)",
                        "CNC machined aluminum chassis with minimalist design",
                        "Seamless glass haptic touchpad",
                        "Zero-lattice keyboard for a comfortable typing experience",
                        "Windows 11 Home/Pro",
                        "Long battery life"
                    ],
                    "description": "The Dell XPS 13 (2024) continues its legacy of premium design and performance in an ultra-compact form factor. Featuring the latest Intel Core Ultra processors, a stunning InfinityEdge display, and innovative design elements, it's built for productivity and portability.",
                    "specifications": {
                        "processor": "Intel Core Ultra 7 155H (or similar variants)",
                        "memory_gb_lpddr5x": "16GB (configurable up to 64GB)",
                        "storage_gb_nvme_ssd": "512GB (configurable up to 2TB)",
                        "display_options": ["13.4\" FHD+ (1920x1200) Anti-Glare, 500-nit", "13.4\" QHD+ (2560x1600) Touch, Anti-Reflect, 500-nit"],
                        "graphics": "Intel Arc Graphics (integrated)",
                        "ports": ["2x Thunderbolt 4 (USB-C) with DisplayPort and Power Delivery"],
                        "weight_kg": "Starts at 1.19 kg (2.6 lbs)"
                    }
                }),
                "metadata": {"name": "Product - Dell XPS 13 (2024)", "content_type": "json", "brand_category": "Dell Laptop", "target_audience": "Professionals, Executives, Power Users"}
            },
            {
                "page_content": json.dumps({
                    "productName": "Microsoft Surface Pro 9 (Intel)",
                    "brand": "Microsoft",
                    "category": "2-in-1 Convertible Tablet/Laptop",
                    "sku": "MSF-SP9-I58256P",
                    "release_year": 2022, # (Surface Pro 10 is newer but SP9 is still widely sold)
                    "price_usd": 999.00, # Base model, keyboard often separate
                    "features": [
                        "12th Gen Intel Core i5 or i7 processors",
                        "13-inch PixelSense Flow Display (2880 x 1920) with 120Hz refresh rate",
                        "Ultra-portable tablet design with optional Surface Pro Signature Keyboard",
                        "Supports Surface Slim Pen 2 with tactile signals",
                        "Windows 11",
                        "Dual Thunderbolt 4 ports",
                        "Up to 15.5 hours of typical device usage"
                    ],
                    "description": "The Surface Pro 9 offers the versatility of a tablet and the performance of a laptop. With its vibrant touchscreen, powerful Intel processors, and support for pen input, it adapts to your way of working, creating, and playing. (Note: Keyboard and Pen sold separately).",
                    "specifications": {
                        "processor_options": ["12th Gen Intel Core i5-1235U", "12th Gen Intel Core i7-1255U"],
                        "memory_gb_lpddr5": "8GB, 16GB, or 32GB",
                        "storage_gb_ssd": "128GB, 256GB, 512GB, or 1TB (removable)",
                        "display_size_inches": 13,
                        "display_resolution": "2880 x 1920 (267 PPI)",
                        "front_camera": "1080p full HD video",
                        "rear_camera": "10.0MP autofocus camera with 1080p HD and 4k video",
                        "weight_g": "879 g (1.94 lbs) (tablet only)"
                    }
                }),
                "metadata": {"name": "Product - Microsoft Surface Pro 9", "content_type": "json", "brand_category": "Microsoft 2-in-1", "target_audience": "Mobile Professionals, Creatives, Students"}
            },
            {
                "page_content": json.dumps({
                    "productName": "ASUS ROG Zephyrus G16 (2024 GU605)",
                    "brand": "ASUS",
                    "category": "Gaming Laptop / Creative Laptop",
                    "sku": "ASU-ROG-ZG16-U94070161T",
                    "release_year": 2024,
                    "price_usd": 1999.99, # Example configuration
                    "features": [
                        "Intel Core Ultra 9 processor 185H",
                        "NVIDIA GeForce RTX 4070 Laptop GPU (or up to RTX 4090)",
                        "16-inch ROG Nebula Display (OLED, 2.5K, 240Hz, G-SYNC)",
                        "Slim and premium CNC-milled aluminum chassis",
                        "Slash Lighting array on lid",
                        "Advanced ROG Intelligent Cooling system",
                        "Six-speaker system with Dolby Atmos"
                    ],
                    "description": "The 2024 ROG Zephyrus G16 redefines thin-and-light gaming with its stunning OLED Nebula Display, powerful Intel Core Ultra 9 processor, and NVIDIA RTX 40-series graphics. Its redesigned chassis is both elegant and robust, perfect for gamers and creators who demand performance and style.",
                    "specifications": {
                        "processor": "Intel Core Ultra 9 185H",
                        "graphics_card": "NVIDIA GeForce RTX 4070 Laptop GPU (8GB GDDR6, TGP up to 105W with Dynamic Boost)",
                        "memory_gb_lpddr5x": "16GB or 32GB onboard",
                        "storage_gb_pcie_4_ssd": "1TB (or 2TB)",
                        "display_specs": "16-inch OLED, 2560 x 1600 (2.5K), 16:10, 240Hz, 0.2ms, 100% DCI-P3, G-SYNC, Pantone Validated",
                        "ports": ["1x Thunderbolt 4", "1x USB 3.2 Gen 2 Type-C (DP/PD)", "2x USB 3.2 Gen 2 Type-A", "1x HDMI 2.1", "1x SD card reader"],
                        "weight_kg": "1.85 - 1.95 kg (4.08 - 4.30 lbs)"
                    }
                }),
                "metadata": {"name": "Product - ASUS ROG Zephyrus G16 (2024)", "content_type": "json", "brand_category": "ASUS Gaming Laptop", "target_audience": "Gamers, Content Creators, Power Users"}
            }
        ]
    }
]

# Example of how to access a specific chunk's page_content
# print("Winnie-the-Pooh, Chunk 1:", source_data_sets[0]["chunks"][0]["page_content"])
# print("\nComputer Guide, Chunk 2:", source_data_sets[1]["chunks"][1]["page_content"])
# Example of how to access a specific product's JSON data (as a string)
# product_json_string = source_data_sets[2]["chunks"][0]["page_content"]
# product_data = json.loads(product_json_string)
# print("\nProduct Feed, Product 1 Name:", product_data["productName"])
# print("Product 1 Price:", product_data["price_usd"])