import os
import re
import json 
import httpx
from google import genai
from urllib.parse import urlparse,urljoin
from typing import Optional

from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware 
from pydantic import BaseModel,HttpUrl,field_validator
from bs4 import BeautifulSoup

app=FastAPI(
    title="GEO AUDIT API",
    description="Analyzes webpages for Generative Engine Optimization(GEO) readiness."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


class AuditRequest(BaseModel):
    url : HttpUrl

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls,v):
        parsed=urlparse(str(v))
        if parsed.scheme not in ("http","https"):
            raise ValueError("URL must use http or https scheme")
        return v

class GEOScores(BaseModel):
    overall: int
    structured_data: int
    content_clarity: int
    ai_citation_potential: int

class AuditResponse(BaseModel):
    url: str
    page_title: Optional[str]
    meta_description:Optional[str]
    headings:list[str]
    image_urls:list[str]
    detected_schema_type:str
    json_ld_recommendation: dict
    geo_scores: GEOScores
    geo_insights: list[str]
    llm_reasoning: Optional[str]

HEADERS={
    "User-Agent":(
        "Mozilla/5.0(Windows NT 10.0; Win64; x64)"
        "AppleWebKit/537.36 (KHTML, like Gecko)"
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

async def scrape_page(url:str)->dict:
    """
    Fetches and parses a webpage
    returns:structured page data    
    """
    async with httpx.AsyncClient(
        follow_redirects=True,timeout=15.0,headers=HEADERS
    ) as client:
        try:
            response=await client.get(url)
            response.raise_for_status()
        except httpx.TimeoutException:
            raise HTTPException(status_code=408,detail="Request timed out")
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Target page returned HTTP {e.response.status_code}",
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Could not reach URL: {e}")
    soup=BeautifulSoup(response.text,"html.parser")

    #title tag
    title_tag= soup.find("title")
    title=title_tag.get_text(strip=True) if title_tag else None

    #meta description
    meta=soup.find("meta",attrs={"name":re.compile(r"description",re.I)})
    meta_desc=meta.get("content","").strip() if meta else None

    #Headings 
    headings=[]
    for tag in soup.find_all(["h1","h2","h3"])[:10]:     #top 10 h1-h2-h3
        text = tag.get_text(strip=True)
        if text:
            headings.append(text)

    #Images
    images=[]
    for img in soup.find_all("img",src=True)[:10]:  
        src=img["src"].strip()
        if not src or src.startswith("data:"):
            continue
        abs_src=urljoin(url,src)   
        images.append(abs_src)      
        if len(images)>=5:              #only 5 absolute image urls
            break
    

    #Body Text
    body_text=soup.get_text(separator=" ",strip=True)
    body_snippet=" ".join(body_text.split())[:1500]


    #JSON-LD
    existing_jsonld=[]
    for script in soup.find_all("script",type="application/ld+json"):
        try:
            existing_jsonld.append(json.loads(script.string or "{}"))
        except json.JSONDecodeError:
            pass
    return {
        "title":title,
        "meta_description":meta_desc,
        "headings":headings,
        "images":images,
        "body_snippet":body_snippet,
        "existing_jsonld":existing_jsonld
    }

#SCHEMA RECOMMENDATION
SYSTEM_PROMPT = SYSTEM_PROMPT = """You are a GEO (Generative Engine Optimization) expert.
Your job is to analyze webpage content and recommend the most impactful JSON-LD
structured data schema to maximize the page's chances of being cited by AI search
engines like ChatGPT, Perplexity, and Google AI Overviews.
 
You MUST respond with a single valid JSON object — no markdown, no prose, no
code fences. The object must have exactly these keys:
 
{
  "schema_type": "<string: e.g. Organization, Article, Product, FAQPage, ...>",
  "json_ld": { <complete JSON-LD object with @context and @type> },
  "reasoning": "<2-3 sentence explanation of why this schema type was chosen>",
  "geo_scores": {
    "overall": <int 0-100>,
    "structured_data": <int 0-100>,
    "content_clarity": <int 0-100>,
    "ai_citation_potential": <int 0-100>
  },
  "geo_insights": ["<insight 1>", "<insight 2>", "<insight 3>"]
}
 
Rules for JSON-LD:
- Use schema.org vocabulary.
- Fill in fields using real data extracted from the page where possible.
- Leave placeholders like "FILL_IN" only for fields you cannot infer.
- Aim for a schema that is immediately useful, not just a skeleton.
"""

def build_user_prompt(url:str,page_data:dict)->str:
    existing=json.dumps(page_data["existing_jsonld"],indent=2) if page_data["existing_jsonld"] else None
    return f"""Analyze this webpage for GEO optimization:
 
URL: {url}
Title: {page_data['title'] or 'Not found'}
Meta Description: {page_data['meta_description'] or 'Not found'}
Headings: {json.dumps(page_data['headings'])}
Body snippet: {page_data['body_snippet']}
Existing JSON-LD on page: {existing}
 
Recommend the single best JSON-LD schema to maximize AI citation potential.
Respond with valid JSON only."""
 

async def get_llm_recommendation(url: str, page_data: dict) -> dict:
    try:
        full_prompt = SYSTEM_PROMPT + "\n\nReturn ONLY valid JSON.\n\n" + build_user_prompt(url, page_data)

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt
            )

        raw = response.text.strip()

        print("\n===== RAW LLM OUTPUT =====\n")
        print(raw)
        print("\n==========================\n")

        # remove markdown
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        try:
            return json.loads(raw)
        except Exception as e:
            print("❌ JSON PARSE ERROR:", e)
            return _fallback_recommendations(page_data)

    except Exception as e:
        print("❌ LLM ERROR:", e)
        return _fallback_recommendations(page_data)

def _fallback_recommendations(page_data:dict)->dict:
    """
    Rule-based fallback when LLM is unavailable.
    """
    title = page_data.get("title") or "Unnamed Page"
    desc = page_data.get("meta_description") or ""
    schema_type = "WebPage"
 
    text_lower = (title + " " + desc).lower()
    if any(w in text_lower for w in ["product", "buy", "price", "shop", "store"]):
        schema_type = "Product"
    elif any(w in text_lower for w in ["article", "blog", "news", "post", "story"]):
        schema_type = "Article"
    elif any(w in text_lower for w in ["faq", "question", "answer", "how to"]):
        schema_type = "FAQPage"
    elif any(w in text_lower for w in ["about", "company", "team", "who we are"]):
        schema_type = "Organization"
 
    return {
        "schema_type": schema_type,
        "json_ld": {
            "@context": "https://schema.org",
            "@type": schema_type,
            "name": title,
            "description": desc,
        },
        "reasoning": (
            "Fallback rule-based recommendation. LLM analysis was unavailable. "
            f"Schema type '{schema_type}' was inferred from page title and meta description keywords."
        ),
        "geo_scores": {
            "overall": 40,
            "structured_data": 20,
            "content_clarity": 50,
            "ai_citation_potential": 30,
        },
        "geo_insights": [
            "No LLM analysis available — scores are estimated.",
            "Add a meta description for better AI content comprehension.",
            "Implement JSON-LD structured data to improve citation potential.",
        ],
    }



#ENDPOINTS

@app.get("/",summary="Health check")
async def root():
    return {"status": "ok","service": "GEO AUDIT API"}

@app.post("/audit",response_model=AuditResponse,summary="Run a GEO Audit on a URL")
async def audit(request:AuditRequest):
    """
    Accepts a public webpage URL and returns:
    - Extracted page metadata (title, description, headings, images)
    - An AI-generated JSON-LD schema recommendation
    - GEO readiness scores and actionable insights
    
    """
    url_str = str(request.url)
 
    # 1. Scrape
    page_data = await scrape_page(url_str)
 
    # 2. LLM recommendation
    llm_result = await get_llm_recommendation(url_str, page_data)
 
    # 3. Assemble response
    scores = llm_result.get("geo_scores", {})
    return AuditResponse(
        url=url_str,
        page_title=page_data["title"],
        meta_description=page_data["meta_description"],
        headings=page_data["headings"],
        image_urls=page_data["images"],
        detected_schema_type=llm_result.get("schema_type", "WebPage"),
        json_ld_recommendation=llm_result.get("json_ld", {}),
        geo_scores=GEOScores(
            overall=scores.get("overall", 0),
            structured_data=scores.get("structured_data", 0),
            content_clarity=scores.get("content_clarity", 0),
            ai_citation_potential=scores.get("ai_citation_potential", 0),
        ),
        geo_insights=llm_result.get("geo_insights", []),
        llm_reasoning=llm_result.get("reasoning"),
    )










