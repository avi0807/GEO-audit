import os
import re
import json 
import httpx
from google import genai #type:ignore
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
SYSTEM_PROMPT = """You are a GEO (Generative Engine Optimization) expert.
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

        # removing markdown
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        try:
            return json.loads(raw)
        except Exception as e:
            print("❌ JSON PARSE ERROR:", e)
            return _fallback_recommendations(page_data,url)

    except Exception as e:
        print("❌ LLM ERROR:", e)
        return _fallback_recommendations(page_data,url)

def _score_structured_data(page_data: dict, schema_type: str) -> tuple[int, list[str]]:
    """
    Score 0-100 based on structured data signals. Returns (score, issues).
    Checks: existing JSON-LD, meta tags, Open Graph, title quality.
    """
    score = 0
    issues = []
 
    has_title = bool(page_data.get("title"))
    has_desc = bool(page_data.get("meta_description"))
    has_existing_jsonld = bool(page_data.get("existing_jsonld"))
    has_headings = bool(page_data.get("headings"))
    has_images = bool(page_data.get("images"))
 

    if has_existing_jsonld:
        score += 45
    else:
        issues.append("No JSON-LD structured data found on the page — this is the top priority fix for AI citation readiness.")
 

    if has_title:
        title = page_data["title"]
        if 10 <= len(title) <= 70:
            score += 20
        else:
            score += 10
            issues.append(f"Page title is {'too short' if len(title) < 10 else 'too long'} ({len(title)} chars). Aim for 10–70 characters for optimal AI comprehension.")
    else:
        issues.append("Missing <title> tag — AI engines use the page title as the primary citation label.")
 

    if has_desc:
        desc = page_data["meta_description"]
        if 50 <= len(desc) <= 160:
            score += 20
        else:
            score += 10
            issues.append(f"Meta description is {'too short' if len(desc) < 50 else 'too long'} ({len(desc)} chars). Aim for 50–160 characters.")
    else:
        issues.append("Missing meta description — AI search engines use this to understand and summarize the page.")
 

    if has_headings:
        score += 10
    else:
        issues.append("No heading tags (H1–H3) detected — headings help AI engines understand page structure and topic hierarchy.")
 

    if has_images:
        score += 5
 
    return min(score, 100), issues
def _classify_schema_type(title: str, desc: str, headings: list, body: str, url: str) -> str:
    """
    Multi-signal schema classifier. Scores each candidate schema type across
    all available text signals and returns the highest-scoring match.
    Signals: URL path, title, meta description, headings, body snippet.
    """
 
    url_path = urlparse(url).path.lower()
    all_text = " ".join([
        title * 3,           
        desc * 2,            
        " ".join(headings),  
        body[:800],          
        url_path,            
    ]).lower()
 

    candidates: dict[str, list[tuple[str, int]]] = {
        "Product": [
            ("product", 3), ("buy", 3), ("price", 3), ("add to cart", 4),
            ("shop", 2), ("store", 2), ("purchase", 3), ("order", 2),
            ("sku", 4), ("in stock", 4), ("shipping", 2), ("review", 1),
            ("/product", 3), ("/shop", 2), ("/item", 2),
        ],
        "Article": [
            ("blog", 3), ("article", 3), ("post", 2), ("news", 3),
            ("published", 2), ("author", 2), ("read more", 2), ("story", 2),
            ("report", 2), ("editorial", 3), ("interview", 2), ("opinion", 2),
            ("/blog", 3), ("/news", 3), ("/article", 3), ("/post", 2),
        ],
        "FAQPage": [
            ("faq", 5), ("frequently asked", 5), ("questions", 3),
            ("how to", 2), ("what is", 2), ("why does", 2), ("can i", 2),
            ("help center", 3), ("support", 2), ("answers", 3),
            ("/faq", 5), ("/help", 3), ("/support", 2),
        ],
        "HowTo": [
            ("how to", 4), ("step by step", 4), ("tutorial", 4),
            ("guide", 3), ("instructions", 3), ("steps", 3),
            ("walkthrough", 3), ("learn how", 3), ("beginner", 2),
            ("/tutorial", 4), ("/guide", 3), ("/how-to", 4),
        ],
        "Organization": [
            ("about us", 4), ("our team", 4), ("who we are", 4),
            ("company", 3), ("mission", 3), ("founded", 3), ("values", 2),
            ("leadership", 3), ("careers", 2), ("contact us", 2),
            ("/about", 4), ("/company", 3), ("/team", 3),
        ],
        "LocalBusiness": [
            ("restaurant", 4), ("clinic", 4), ("salon", 4), ("gym", 4),
            ("store", 3), ("office", 2), ("hours", 3), ("open", 2),
            ("location", 3), ("directions", 3), ("reserve", 3), ("book", 2),
            ("phone", 2), ("address", 3), ("near me", 4),
        ],
        "Event": [
            ("event", 4), ("conference", 4), ("webinar", 4), ("meetup", 4),
            ("workshop", 4), ("register", 3), ("tickets", 4), ("rsvp", 5),
            ("schedule", 2), ("agenda", 3), ("speaker", 3), ("session", 2),
            ("/event", 4), ("/conference", 4),
        ],
        "SoftwareApplication": [
            ("app", 3), ("software", 3), ("download", 3), ("platform", 2),
            ("saas", 4), ("api", 3), ("integration", 2), ("dashboard", 3),
            ("free trial", 4), ("sign up", 2), ("pricing", 3), ("feature", 2),
            ("/app", 3), ("/product", 2), ("/platform", 3),
        ],
        "WebPage": [], 
    }
 
    scores: dict[str, int] = {schema: 0 for schema in candidates}
    for schema, keywords in candidates.items():
        for keyword, weight in keywords:
            if keyword in all_text:
                scores[schema] += weight

    non_default = {k: v for k, v in scores.items() if k != "WebPage"}
    best_schema = max(non_default, key=lambda k: non_default[k])
    if non_default[best_schema] == 0:
        return "WebPage"
    return best_schema

def _score_content_clarity(page_data: dict) -> tuple[int, list[str]]:
    """
    Score 0-100 based on how clearly structured and readable the content is.
    Checks: heading hierarchy, description quality, body length, image presence.
    """
    score = 0
    issues = []
 
    title = page_data.get("title") or ""
    desc = page_data.get("meta_description") or ""
    headings = page_data.get("headings", [])
    body = page_data.get("body_snippet", "")
    images = page_data.get("images", [])

    if title and len(title) >= 10:
        score += 20
    elif title:
        score += 10
        issues.append("Page title is very short — a descriptive title improves AI understanding of the page topic.")
 

    if desc and len(desc) >= 50:
        score += 25
    elif desc:
        score += 12
        issues.append("Meta description is too brief to give AI engines enough context. Aim for 2–3 full sentences.")
    else:
        issues.append("Add a meta description to clearly communicate the page's purpose to AI search engines.")

    if len(headings) >= 3:
        score += 25
    elif len(headings) == 2:
        score += 18
    elif len(headings) == 1:
        score += 10
        issues.append("Only one heading found. A clear H1 → H2 → H3 hierarchy helps AI engines map the content structure.")
    else:
        issues.append("No headings detected. Use H1 for the main topic and H2/H3 for subtopics to aid AI parsing.")
 

    word_count = len(body.split())
    if word_count >= 200:
        score += 20
    elif word_count >= 100:
        score += 12
        issues.append("Page body appears short. Richer content gives AI engines more signals to cite from.")
    else:
        score += 4
        issues.append("Very little readable body text detected. Consider expanding page content for better AI comprehension.")
 

    if images:
        score += 10
 
    return min(score, 100), issues
def _build_jsonld(schema_type: str, title: str, desc: str, url: str, images: list) -> dict:
    """Build a reasonably populated JSON-LD block from available scraped signals."""
    base:dict = {
        "@context": "https://schema.org",
        "@type": schema_type,
        "name": title,
        "url": url,
    }
    if desc:
        base["description"] = desc
    if images:
        base["image"] = images[0]
 

    if schema_type == "Article":
        base.update({
            "headline": title,
            "datePublished": "FILL_IN",
            "author": {"@type": "Person", "name": "FILL_IN"},
            "publisher": {"@type": "Organization", "name": "FILL_IN", "logo": {"@type": "ImageObject", "url": "FILL_IN"}},
        })
    elif schema_type == "Product":
        base.update({
            "offers": {"@type": "Offer", "priceCurrency": "USD", "price": "FILL_IN", "availability": "https://schema.org/InStock"},
        })
    elif schema_type == "Organization":
        base.update({
            "logo": images[0] if images else "FILL_IN",
            "contactPoint": {"@type": "ContactPoint", "contactType": "customer service"},
        })
    elif schema_type == "HowTo":
        base.update({
            "totalTime": "FILL_IN",
            "step": [{"@type": "HowToStep", "name": "FILL_IN", "text": "FILL_IN"}],
        })
    elif schema_type == "FAQPage":
        base.update({
            "mainEntity": [{"@type": "Question", "name": "FILL_IN", "acceptedAnswer": {"@type": "Answer", "text": "FILL_IN"}}],
        })
    elif schema_type == "SoftwareApplication":
        base.update({
            "applicationCategory": "WebApplication",
            "operatingSystem": "Web",
            "offers": {"@type": "Offer", "price": "FILL_IN"},
        })
    elif schema_type == "Event":
        base.update({
            "startDate": "FILL_IN",
            "endDate": "FILL_IN",
            "location": {"@type": "Place", "name": "FILL_IN"},
            "organizer": {"@type": "Organization", "name": "FILL_IN"},
        })
    elif schema_type == "LocalBusiness":
        base.update({
            "address": {"@type": "PostalAddress", "streetAddress": "FILL_IN", "addressLocality": "FILL_IN"},
            "telephone": "FILL_IN",
            "openingHours": "FILL_IN",
        })
    return base
def _score_ai_citation_potential(
    page_data: dict,
    schema_type: str,
    structured_data_score: int,
    content_clarity_score: int,
) -> tuple[int, list[str]]:
    """
    Score 0-100 for how likely this page is to be cited by AI search engines.
    Derives from structured data + content clarity + schema type specificity.
    """
    score = 0
    issues = []
 
    has_existing_jsonld = bool(page_data.get("existing_jsonld"))
    has_desc = bool(page_data.get("meta_description"))
    has_title = bool(page_data.get("title"))

    if has_existing_jsonld:
        score += 30
    else:
        issues.append("Implementing the recommended JSON-LD schema is the highest-impact change for AI citation readiness.")
 

    specific_types = {"Article", "Product", "FAQPage", "HowTo", "Event", "LocalBusiness", "SoftwareApplication"}
    if schema_type in specific_types:
        score += 15
    else:
        issues.append(f"The detected schema type '{schema_type}' is generic. A more specific type (e.g., Article, Product, FAQPage) improves citability.")
 

    score += int(content_clarity_score * 0.30)
 

    if has_desc:
        score += 15
    else:
        issues.append("A meta description dramatically improves the chance of AI engines selecting this page as a citation source.")
 

    if has_title:
        score += 10
 
    return min(score, 100), issues
def _fallback_recommendations(page_data:dict,url:str = "")->dict:
    """
    Rule-based fallback when LLM is unavailable.
    """
    title = page_data.get("title") or "Unnamed Page"
    desc = page_data.get("meta_description") or ""
    headings=page_data.get("headings",[])
    body=page_data.get("body_snippet","")
    images=page_data.get("images",[])

    schema_type = _classify_schema_type(title,desc,headings,body,url)

    structured_data_score, sd_issues = _score_structured_data(page_data, schema_type)
    content_clarity_score, cc_issues = _score_content_clarity(page_data)
    citation_score, cp_issues = _score_ai_citation_potential(
        page_data, schema_type, structured_data_score, content_clarity_score
    )
 

    overall = int(
        structured_data_score * 0.40
        + citation_score * 0.35
        + content_clarity_score * 0.25
    )
 
    all_issues = sd_issues + cp_issues + cc_issues
    seen = set()
    insights = []
    for issue in all_issues:
        key = issue[:40] 
        if key not in seen:
            seen.add(key)
            insights.append(issue)
    insights = insights[:5] 
 

    json_ld = _build_jsonld(schema_type, title, desc, url, images)
 
    return {
        "schema_type": schema_type,
        "json_ld": json_ld,
        "reasoning": (
            f"Heuristic analysis (LLM unavailable). Schema type '{schema_type}' was selected "
            f"by scoring {len(_classify_schema_type.__code__.co_consts)} candidate types across "
            f"URL path, title, meta description, headings, and body text signals. "
            f"GEO scores reflect actual page signals: title={'present' if page_data.get('title') else 'missing'}, "
            f"meta description={'present' if desc else 'missing'}, "
            f"existing JSON-LD={'yes' if page_data.get('existing_jsonld') else 'no'}, "
            f"headings={len(headings)} found."
        ),
        "geo_scores": {
            "overall": overall,
            "structured_data": structured_data_score,
            "content_clarity": content_clarity_score,
            "ai_citation_potential": citation_score,
        },
        "geo_insights": insights if insights else [
            "Page has strong GEO foundations. Consider adding FAQ or HowTo schema for additional AI citation opportunities."
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
 

    page_data = await scrape_page(url_str)
 

    llm_result = await get_llm_recommendation(url_str, page_data)
 
 
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










