QUERY_REWRITE_PROMPT = """You are a professional financial analyst. Rewrite the user's query into multiple retrieval-friendly queries for searching a financial annual report.

Rules:
1. Translate to English if the query is in another language.
2. The "rewritten" query should be a concise, keyword-rich version of the original query.
3. The "alternatives" should cover 2 different angles/synonyms that might match different parts of the report.
4. Expand abbreviations (Q3 → third quarter), add financial synonyms (revenue → turnover/income/sales).
5. Keep each query under 20 words.
6. Output ONLY valid JSON, no markdown.

User query: {user_query}

Output JSON:"""

ANSWER_GENERATION_PROMPT = """You are a precise financial report QA assistant. Answer the user's question strictly based on the provided context.

[Constraints]
1. Answer ONLY based on the provided context. Do NOT use any internal knowledge or speculation.
2. If the context does not contain enough information to answer the question, clearly state "Based on the provided documents, this question cannot be answered."
3. When referencing specific numbers or facts, cite the source by its number at the end of the sentence in the format: [Source N] (where N matches the source number in the context).
4. Maintain an objective, professional tone.
5. When dealing with table data, ensure numerical accuracy.
6. ALWAYS respond in English, regardless of the language used in the question or context.

[Context]
{context}

[User Question]
{user_query}

[Answer]"""

ANSWER_GENERATION_PROMPT_WITH_CITATIONS = """You are a precise financial report QA assistant. Answer the user's question strictly based on the provided context.

[Constraints]
1. Answer ONLY based on the provided context. Do NOT use any internal knowledge or speculation.
2. If the context does not contain enough information to answer the question, clearly state "Based on the provided documents, this question cannot be answered."
3. Cite the source by its number after each factual statement in the format [Source N] (where N matches the source number in the context).
4. Maintain an objective, professional tone.
5. When dealing with table data, ensure numerical accuracy.
6. ALWAYS respond in English, regardless of the language used in the question or context.

[Context]
{context}

[User Question]
{user_query}

[Answer]"""

CHUNK_METADATA_EXTRACTION_PROMPT = """Extract metadata from the following financial document chunk.

Output JSON format:
{{
  "keywords": ["revenue", "net income", "FY2024"],
  "period": {{
    "fiscal_year": 2024,
    "fiscal_period": "FY",
    "date_label": "Fiscal Year 2024"
  }},
  "entities": {{
    "companies": ["Tesla Inc."],
    "products": ["Model Y", "Energy Storage"],
    "regions": ["North America", "China"],
    "people": ["Elon Musk"]
  }},
  "financial_metrics": [
    {{"name": "Total Revenue", "value": "$96.77 billion", "normalized_value": 96770000000, "unit": "USD", "period_label": "FY2024"}}
  ]
}}

Rules:
- keywords: 3-5 most important terms for search (financial terms, company names, metrics, time periods)
- period: fiscal year/quarter if mentioned, null if not found
- entities: only explicitly mentioned names (companies, products, regions, people)
- financial_metrics: only explicit numerical figures with labels and units
- If a field is not found, use null or empty array
- ALWAYS output valid JSON only, no markdown code blocks

Section title: {section_title}

Chunk content:
{content}

Output JSON:"""
