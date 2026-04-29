# Scrapling: Product Data Scraping Guide

> 🕷️ **Scrapling** is an adaptive web scraping framework that handles everything from single requests to full-scale crawls. This guide shows you how to use it for scraping specific product data from websites.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Installation](#installation)
- [Choosing Your Approach](#choosing-your-approach)
- [Basic Product Scraping](#basic-product-scraping)
- [Advanced Techniques](#advanced-techniques)
- [Real-World Product Scraping Examples](#real-world-product-scraping-examples)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

### Minimal Example: Scrape Products with One-Off Request

```python
from scrapling.fetchers import Fetcher

# Fetch the page
page = Fetcher.get('https://example-shop.com/products')

# Extract all products
products = page.css('.product-item')

# Get product details
for product in products:
    print({
        'name': product.css('.product-name::text').get(),
        'price': product.css('.product-price::text').get(),
        'description': product.css('.product-desc::text').get(),
    })
```

---

## Installation

### Basic Install (Parser Only)
```bash
pip install scrapling
```

### Full Install (with Fetchers & Browser Support)
```bash
pip install "scrapling[fetchers]"
scrapling install  # Download browser dependencies
```

### Complete Install (with AI & CLI Features)
```bash
pip install "scrapling[all]"
scrapling install
```

### Docker
```bash
docker pull pyd4vinci/scrapling
# or
docker pull ghcr.io/d4vinci/scrapling:latest
```

---

## Choosing Your Approach

Scrapling offers multiple ways to fetch pages, depending on your target website:

| Approach | Best For | Speed | Anti-Bot Bypass |
|----------|----------|-------|-----------------|
| **Fetcher** | Static HTML pages, APIs | ⚡ Fastest | ❌ No |
| **FetcherSession** | Multiple requests, cookies | ⚡ Fast | ❌ No |
| **DynamicFetcher** | JavaScript-rendered content | 🟡 Moderate | ❌ No |
| **StealthyFetcher** | Cloudflare, fingerprinting | 🟡 Moderate | ✅ Yes |
| **Spider** | Multi-page crawls, crawl resume | 🟡 Moderate | Configurable |

### Decision Tree
```
Is the page static HTML?
├─ YES → Use Fetcher / FetcherSession
└─ NO (JavaScript rendering needed)
   └─ Is the site blocking requests?
      ├─ NO → Use DynamicFetcher
      └─ YES → Use StealthyFetcher or Spider
```

---

## Basic Product Scraping

### Scenario 1: Static Product Page (Fastest)

```python
from scrapling.fetchers import Fetcher

# Single request - fastest option
page = Fetcher.get('https://example-shop.com/products')

# Extract product information
products = page.css('.product')  # CSS selector

for product in products:
    item = {
        'title': product.css('.product-title::text').get(),
        'price': product.css('.product-price::text').get(),
        'rating': product.css('.product-rating::text').get(),
        'url': product.css('a::attr(href)').get(),
        'in_stock': 'Out of stock' not in product.css('.status::text').get() or ''
    }
    print(item)
```

### Scenario 2: Session-Based Scraping (Multiple Pages)

```python
from scrapling.fetchers import FetcherSession

# Reuse session for better performance
with FetcherSession(impersonate='chrome') as session:
    # Page 1
    page = session.get('https://example-shop.com/products?page=1')
    products_p1 = page.css('.product')
    
    # Page 2 - session maintains cookies and headers
    page = session.get('https://example-shop.com/products?page=2')
    products_p2 = page.css('.product')
    
    # Extract from all pages
    all_products = products_p1 + products_p2
    
    for product in all_products:
        print({
            'name': product.css('h2::text').get(),
            'price': product.css('.price::text').get(),
        })
```

### Scenario 3: JavaScript-Heavy Page (Dynamic Content)

```python
from scrapling.fetchers import DynamicSession

# Use browser automation for JS-rendered content
with DynamicSession(headless=True, network_idle=True) as session:
    # Wait for network idle (all resources loaded)
    page = session.fetch('https://example-shop.com/products')
    
    # Now the JavaScript-rendered content is available
    products = page.css('.product-card')
    
    for product in products:
        print({
            'name': product.css('.product-name::text').get(),
            'price': product.css('[data-price]::attr(data-price)').get(),
            'reviews': product.css('.review-count::text').get(),
        })
```

### Scenario 4: Anti-Bot Protected Site (Cloudflare, etc.)

```python
from scrapling.fetchers import StealthySession

# For Cloudflare Turnstile and similar protections
with StealthySession(headless=True, solve_cloudflare=True) as session:
    page = session.fetch('https://protected-shop.com/products')
    
    # Extract products safely
    products = page.css('.product')
    
    for product in products:
        print({
            'id': product.css('::attr(data-product-id)').get(),
            'name': product.css('.name::text').get(),
            'price': product.css('.price::text').get(),
        })
```

---

## Advanced Techniques

### Multi-Page Crawling with Spider

Perfect for scraping entire product catalogs:

```python
from scrapling.spiders import Spider, Request, Response

class ProductSpider(Spider):
    name = "product_scraper"
    start_urls = ["https://example-shop.com/products"]
    concurrent_requests = 5  # Parallel requests
    
    async def parse(self, response: Response):
        # Extract products from current page
        for product in response.css('.product'):
            yield {
                'name': product.css('.name::text').get(),
                'price': product.css('.price::text').get(),
                'description': product.css('.desc::text').get(),
                'rating': product.css('.rating::text').get(),
                'url': product.css('a::attr(href)').get(),
            }
        
        # Follow pagination links
        next_page = response.css('.pagination .next::attr(href)').get()
        if next_page:
            # yield Request for next page (callback is default parse method)
            yield response.follow(next_page)

# Run the spider
result = ProductSpider().start()

# Export results to JSON
result.items.to_json("products.json")
print(f"Scraped {len(result.items)} products")
```

### Pause and Resume Long Crawls

```python
# First run - will save progress
spider = ProductSpider(crawldir="./product_crawl")
result = spider.start()

# If interrupted (Ctrl+C), run again with same crawldir to resume
# The spider will continue from where it stopped
```

### Multi-Session Spider (Mixed Fetchers)

```python
from scrapling.spiders import Spider, Request, Response
from scrapling.fetchers import FetcherSession, AsyncStealthySession

class SmartProductSpider(Spider):
    name = "smart_scraper"
    start_urls = ["https://example-shop.com/products"]
    
    def configure_sessions(self, manager):
        # Fast session for regular pages
        manager.add("fast", FetcherSession(impersonate="chrome"))
        # Stealth session for protected pages (lazy loaded)
        manager.add("stealth", AsyncStealthySession(headless=True), lazy=True)
    
    async def parse(self, response: Response):
        for product in response.css('.product'):
            url = product.css('a::attr(href)').get()
            
            # Route protected product pages through stealth session
            if 'protected' in url:
                yield Request(url, sid="stealth", callback=self.parse_product)
            else:
                yield Request(url, sid="fast", callback=self.parse_product)
    
    async def parse_product(self, response: Response):
        # Extract detailed product information
        yield {
            'url': response.url,
            'title': response.css('h1::text').get(),
            'price': response.css('.price::text').get(),
            'specs': response.css('.spec::text').getall(),
            'reviews': response.css('.review::text').getall(),
        }
```

### Adaptive Element Tracking (Survives Design Changes)

```python
from scrapling.fetchers import Fetcher

# First run - discover and save element structure
page = Fetcher.get('https://example-shop.com/products')
products = page.css('.product-card', auto_save=True)  # Saves selector patterns

# Later, if website changes its selectors:
page = Fetcher.get('https://example-shop.com/products')
# Scrapling finds similar elements even if selectors changed
products = page.css('.product-card', adaptive=True)
```

---

## Real-World Product Scraping Examples

### E-Commerce Site (Multiple Fields)

```python
from scrapling.fetchers import FetcherSession
import json

class EcommerceProductScraper:
    def __init__(self, base_url):
        self.base_url = base_url
        self.products = []
    
    def scrape_products(self, num_pages=5):
        with FetcherSession(impersonate='chrome') as session:
            for page_num in range(1, num_pages + 1):
                url = f"{self.base_url}/products?page={page_num}"
                print(f"Scraping {url}...")
                
                response = session.get(url)
                
                for product in response.css('[data-product]'):
                    self.products.append({
                        'sku': product.css('::attr(data-product-id)').get(),
                        'title': product.css('.product-title::text').get(),
                        'price': product.css('.product-price::text').get(),
                        'original_price': product.css('.product-original-price::text').get(),
                        'discount': product.css('.discount-badge::text').get(),
                        'rating': product.css('.star-rating::attr(data-rating)').get(),
                        'reviews_count': product.css('.reviews-count::text').get(),
                        'in_stock': product.css('.stock-status::text').get() == 'In Stock',
                        'description': product.css('.description::text').get(),
                        'url': product.css('a::attr(href)').get(),
                    })
        
        return self.products
    
    def save_to_file(self, filename='products.json'):
        with open(filename, 'w') as f:
            json.dump(self.products, f, indent=2)
        print(f"Saved {len(self.products)} products to {filename}")

# Usage
scraper = EcommerceProductScraper('https://example-shop.com')
products = scraper.scrape_products(num_pages=10)
scraper.save_to_file()
```

### Product Details Scraper (Detail Pages)

```python
from scrapling.fetchers import DynamicFetcher

def scrape_product_details(product_url):
    """Scrape detailed information from a single product page"""
    page = DynamicFetcher.fetch(product_url, network_idle=True)
    
    return {
        'title': page.css('h1::text').get(),
        'brand': page.css('[data-field="brand"]::text').get(),
        'price': page.css('.current-price::text').get(),
        'currency': page.css('.currency::text').get(),
        'rating': page.css('.overall-rating::text').get(),
        'review_count': page.css('.total-reviews::text').get(),
        'description': ' '.join(page.css('.description p::text').getall()),
        'specifications': {
            spec.css('::text')[0]: spec.css('::text')[1]
            for spec in page.css('.spec-item')
        },
        'images': page.css('.product-image::attr(src)').getall(),
        'availability': page.css('[data-availability]::attr(data-availability)').get(),
        'shipping_info': page.css('.shipping-info::text').get(),
        'warranty': page.css('.warranty-info::text').get(),
    }

# Usage
details = scrape_product_details('https://example-shop.com/product/12345')
print(details)
```

---

## Best Practices

### 1. **Be Respectful**
```python
from scrapling.spiders import Spider

class RespectfulSpider(Spider):
    name = "respectful"
    start_urls = ["https://example.com"]
    
    # Add delays between requests
    download_delay = 2
    
    # Limit concurrent requests
    concurrent_requests = 3
    
    # Obey robots.txt
    robots_txt_obey = True
    
    async def parse(self, response):
        pass
```

### 2. **Use Proxy Rotation for Large Crawls**
```python
from scrapling.fetchers import FetcherSession, ProxyRotator

# Set up rotating proxies
rotator = ProxyRotator([
    'http://proxy1.com:8080',
    'http://proxy2.com:8080',
    'http://proxy3.com:8080',
], strategy='cyclic')

with FetcherSession(proxy_rotator=rotator) as session:
    page = session.get('https://example.com')
```

### 3. **Handle Errors and Retries**
```python
from scrapling.fetchers import Fetcher

def scrape_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            page = Fetcher.get(url)
            if page.status == 200:
                return page
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                import time
                time.sleep(2 ** attempt)  # Exponential backoff
    
    return None
```

### 4. **Data Validation and Cleaning**
```python
def clean_product_data(product):
    """Validate and clean scraped product data"""
    import re
    
    # Clean price (remove currency symbols)
    price = product.get('price', '0')
    price = re.sub(r'[^\d.]', '', price)
    product['price'] = float(price) if price else None
    
    # Clean rating (ensure it's numeric)
    rating = product.get('rating', '0')
    rating = re.search(r'\d+\.?\d*', rating)
    product['rating'] = float(rating.group()) if rating else None
    
    # Trim whitespace
    for key in ['title', 'description']:
        if key in product and product[key]:
            product[key] = product[key].strip()
    
    return product
```

### 5. **Save Progress Incrementally**
```python
from scrapling.fetchers import FetcherSession
import json

def scrape_with_incremental_save(url, output_file, batch_size=100):
    products = []
    
    with FetcherSession() as session:
        page = session.get(url)
        
        for i, product in enumerate(page.css('.product')):
            products.append({
                'name': product.css('.name::text').get(),
                'price': product.css('.price::text').get(),
            })
            
            # Save every batch_size items
            if (i + 1) % batch_size == 0:
                with open(output_file, 'a') as f:
                    for p in products:
                        f.write(json.dumps(p) + '\n')
                products = []
                print(f"Saved {i + 1} products")
```

---

## Troubleshooting

### Issue: "404 Not Found" or "Access Denied"
**Solution:** Try StealthyFetcher with headers spoofing:
```python
from scrapling.fetchers import StealthyFetcher

page = StealthyFetcher.fetch('https://protected-site.com', headless=True)
```

### Issue: JavaScript Content Not Loading
**Solution:** Switch to DynamicFetcher or StealthyFetcher:
```python
from scrapling.fetchers import DynamicFetcher

page = DynamicFetcher.fetch('https://spa-site.com', network_idle=True)
```

### Issue: Cloudflare Blocking Requests
**Solution:** Use StealthyFetcher with Cloudflare solving:
```python
from scrapling.fetchers import StealthyFetcher

page = StealthyFetcher.fetch('https://cloudflare-site.com', solve_cloudflare=True)
```

### Issue: Selectors Not Finding Elements
**Solution:** Use adaptive mode or inspect the page manually:
```python
from scrapling.parser import Selector

html = "<html>...</html>"
page = Selector(html)

# Debug: print all elements matching a pattern
products = page.css('.product-item', adaptive=True)
print(f"Found {len(products)} products")
```

### Issue: Memory Issues with Large Crawls
**Solution:** Use Spider streaming mode instead of loading all items:
```python
from scrapling.spiders import Spider

class MemoryEfficientSpider(Spider):
    async def parse(self, response):
        # Process items immediately, don't accumulate
        for product in response.css('.product'):
            yield {
                'name': product.css('.name::text').get(),
                'price': product.css('.price::text').get(),
            }

# Stream results instead of loading all in memory
spider = MemoryEfficientSpider()
async for item in spider.stream():
    print(item)  # Process item immediately
```

---

## Additional Resources

- 📚 **Official Documentation:** https://scrapling.readthedocs.io
- 💬 **Discord Community:** https://discord.gg/EMgGbDceNQ
- 🐙 **GitHub Repository:** https://github.com/D4Vinci/Scrapling
- 📋 **Examples:** https://github.com/D4Vinci/Scrapling/tree/main/agent-skill/Scrapling-Skill/examples

---

## Quick Reference Cheat Sheet

```python
# One-off request
from scrapling.fetchers import Fetcher
page = Fetcher.get('https://example.com')

# Session (reusable)
from scrapling.fetchers import FetcherSession
with FetcherSession() as s:
    page = s.get('https://example.com')

# Dynamic content (JS)
from scrapling.fetchers import DynamicFetcher
page = DynamicFetcher.fetch('https://example.com')

# Anti-bot (Cloudflare)
from scrapling.fetchers import StealthyFetcher
page = StealthyFetcher.fetch('https://example.com', solve_cloudflare=True)

# Crawl multiple pages
from scrapling.spiders import Spider
class MySpider(Spider):
    name = "my_spider"
    start_urls = ["https://example.com"]
    async def parse(self, response):
        yield {'data': response.css('.item::text').get()}

# Extract data
products = page.css('.product')  # CSS selector
text = page.xpath('//div[@class="text"]/text()').get()  # XPath
element = page.find_by_text('Find Me', tag='span')  # Text search

# Save results
result.items.to_json("output.json")
result.items.to_jsonl("output.jsonl")
```

---

**Happy scraping! 🕷️** Remember to always respect robots.txt and website terms of service.