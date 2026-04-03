# GEO Audit Tool 

An AI-powered tool that analyzes websites for **AI search visibility (GEO - Generative Engine Optimization)** and provides actionable insights, scoring, and schema recommendations.


#  Project Overview

GEO Audit evaluates how well a webpage is optimized for AI-driven search engines (like ChatGPT, Gemini, etc.) by:

* Extracting metadata and content
* Computing GEO scores
* Generating AI-based insights
* Recommending structured data (JSON-LD)

---

#  Setup Instructions

## 1. Clone the repository

```bash
git clone https://github.com/avi0807/GEO-audit.git
cd GEO-audit
```

---

## 2. Backend Setup (FastAPI)

```bash
cd backend
python3 -m venv geoenv
source geoenv/bin/activate
pip install -r requirements.txt
```

### Add Gemini API Key

Create `.env` file inside `backend/`:

```env
GEMINI_API_KEY=your_api_key_here
```

---

## Run backend

```bash
uvicorn main:app --reload
```

Backend runs on:

```text
http://127.0.0.1:8000
```

---

## 3. Frontend Setup (React)

```bash
cd frontend
npm install
npm start
```

Frontend runs on:

```text
http://localhost:3000
```

---

#  Architecture Overview

```text
User Input (URL)
        ↓
React Frontend
        ↓
FastAPI Backend (/audit endpoint)
        ↓
Web Scraper (httpx + BeautifulSoup)
        ↓
Data Extraction (title, meta, headings, images)
        ↓
GEO Scoring Engine
        ↓
LLM (Gemini API) → Insights + JSON-LD
        ↓
Response → Frontend Dashboard
```

---

#  Design Decision Log

## 1. Problem Breakdown

The goal was to evaluate websites for AI-readiness:

* Extract structured + unstructured data
* Evaluate clarity and machine readability
* Generate improvements

---

## 2. Web Scraping Approach

### Options:

* Selenium (heavy)
* BeautifulSoup + requests/httpx (lightweight)

### Decision:

✔ Used **BeautifulSoup + httpx**

* Faster
* Lightweight
* Enough for static pages

---

## 3. Backend Framework

### Options:

* Flask
* FastAPI

### Decision:

✔ Used **FastAPI**

* Built-in validation (Pydantic)
* Async support
* Auto Swagger docs

---

## 4. Scoring System

Designed a custom GEO scoring system:

* Structured Data
* Content Clarity
* AI Citation Potential

Reason:
✔ Keeps logic transparent and deterministic
✔ Avoids full reliance on LLM

---

## 5. LLM Usage (Gemini)

### Options:

* No LLM
* Full LLM pipeline
* Hybrid approach

### Decision:

✔ Used **Hybrid Approach**

Used LLM for:

* Insights generation
* JSON-LD recommendation

Avoided LLM for:

* Scraping
* Scoring

### Why:

* Reduces cost
* Improves reliability
* Keeps system explainable

---

## 6. Frontend Design

### Decisions:

* React for UI
* Framer Motion for animations
* Circular progress for scoring

Reason:
✔ Clean UX
✔ Dashboard-style visualization

---

#  Assumptions

* Target pages are mostly static HTML
* Metadata exists (title, description)
* Users input valid URLs
* LLM outputs valid JSON (fallback added)

---

#  Known Limitations

*  Dynamic JS-heavy sites may not be scraped fully
*  LLM output may occasionally require fallback
*  Basic scoring logic (not ML-based)
*  No caching (repeated requests hit target site)
*  No authentication or rate limiting

---

#  Features

*  URL-based website analysis
*  GEO scoring system
*  AI-generated insights
*  JSON-LD schema recommendations
*  Modern dashboard UI

---

#  Future Improvements

* Add caching layer (Redis)
* Improve scoring with ML models
* Support JS rendering (Playwright)
* Deploy (Vercel + Render)
* Add user authentication

---

# 👨 Tech Stack

**Frontend**

* React
* Framer Motion
* react-circular-progressbar

**Backend**

* FastAPI
* Pydantic
* httpx
* BeautifulSoup

**AI**

* Google Gemini API

---

#  Conclusion

This project demonstrates a hybrid AI system combining:

* Deterministic scoring
* LLM-powered reasoning
* Modern UI

Designed to be **efficient, explainable, and extensible**.

---
