---
id: usage-tips
title: Usage Tips
category: usage
order: 4
version: 0.38.1
last_updated: 2026-01-17
tags:
  - tips
  - best-practices
  - web-scraping
  - performance
---

# Usage Tips

## Q: How do I ask AI to help me extract webpage data?

**A**: Use clear, specific descriptions with three elements: target URL, content to extract, and output format. The more specific, the more accurate AI execution.

**Three-Element Formula**:

```
Extract [specific content] from [URL], save as [format]
```

**Example Comparison**:

### ❌ Bad Description (Vague)

```
"Help me scrape data from this website"
→ AI doesn't know what to scrape, may extract irrelevant content
```

### ✅ Good Description (Clear)

```
"From https://example.com/products extract all product names, prices, and stock,
save as CSV file with columns: product_name, price, stock"

→ AI knows:
  - Target URL
  - Which fields to extract
  - Output format requirements
```

**More Examples**:

**Example 1: Extract Article List**
```
From https://news.example.com homepage extract titles and links of the first 20 articles,
save as JSON array, format: [{"title": "...", "url": "..."}]
```

**Example 2: Paginated Data**
```
From https://shop.example.com/category/electronics extract product data from first 3 pages,
including: product name, price, rating, image URL, save as products.json
```

**Example 3: Table Data**
```
From https://stats.example.com/table extract the data table (id="data-table"),
save as Excel file, preserving original formatting
```

**Advanced Techniques**:

**1. Specify Selectors (Optional)**
```
From homepage extract user reviews, CSS selector: .review-card
```

**2. Data Cleaning Requirements**
```
Extract price data, remove currency symbols, convert to numbers
```

**3. Pagination Handling**
```
Extract data from list page, click "Next" button to continue until no more data
```

**4. Extract After Login**
```
First login to https://example.com (username: xxx, password from environment variable),
then extract order history from personal center
```

**Common Errors & Corrections**:

| Error Description | Problem | Improvement |
|-------------------|---------|-------------|
| "Scrape this site" | Doesn't say what to scrape | "Extract all article titles and publish dates" |
| "Get prices" | URL not specified | "From https://... page get prices" |
| "Save data" | Format not specified | "Save as JSON/CSV/Excel" |
| "Extract content" | Fields not specified | "Extract: title, author, date" |

**Tips & Considerations**:

💡 **Step-by-Step Description**:
Complex tasks can be broken down:
```
1. Visit https://example.com
2. Enter "phone" in search box
3. Wait for results to load
4. Extract titles and prices of first 10 products
5. Save as mobile_prices.json
```

⚠️ **Anti-Scraping Notice**:
- Some sites have anti-scraping mechanisms
- AI will notify you if it encounters CAPTCHA
- Respect website's robots.txt rules

⚠️ **Data Volume Control**:
- First attempt: extract small amount (like 10 items)
- Verify correctness before scaling up

**Complete Example**:

```
Task Description:
From Douban Top 250 Movies (https://movie.douban.com/top250)
extract the following information for first 50 movies:
- Movie name (Chinese)
- Rating
- Number of ratings
- Director
- Actors (first 3)
- Release year

Save as JSON file, name it douban_top50.json
Format example:
[
  {
    "title": "The Shawshank Redemption",
    "rating": 9.7,
    "votes": 2800000,
    "director": "Frank Darabont",
    "actors": ["Tim Robbins", "Morgan Freeman", "Bob Gunton"],
    "year": 1994
  }
]

Notes:
- Need to paginate to page 2 (25 items per page)
- Display total count after extraction for confirmation
```

**Related Questions**: Recipe fails with "selector not found"? (See Troubleshooting chapter)
