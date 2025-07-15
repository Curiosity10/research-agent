### **Project Research Agent: Comprehensive Technical Specification**

**Document Version:** 1.2
**Status:** Implemented

#### **1. System Overview**

**1.1. Mission:** To autonomously generate comprehensive, data-driven technology analysis reports from a given list of technology names. The final output must be a markdown document with all statements supported by citations from high-quality, recent sources.

**1.2. Core Tenets:**
*   **Zero-Cost Operation:** The system must function strictly within the free tiers of all external services. This is a non-negotiable constraint.
*   **Source-of-Truth Quality:** Report quality is directly proportional to the quality of ingested sources. The system must programmatically prioritize authoritative and recent documentation.

**1.3. Architecture:** A monolithic script (`main.py`) orchestrating a stateful graph defined by LangGraph. This minimalist structure reduces complexity and simplifies deployment.

#### **2. Project Setup & Dependencies**

**2.1. File Structure:**
```
/rnd
|-- main.py              # Main script containing all logic: state, nodes, and graph assembly
|-- .env                   # Environment variables for API keys
|-- requirements.txt       # Project dependencies
|-- README.md
```

**2.2. Dependencies (`requirements.txt`):**```
langchain==<latest_version>
langgraph==<latest_version>
langchain-google-genai==<latest_version>
langchain-community==<latest_version>
requests==<latest_version>
requests-html==<latest_version>
trafilatura==<latest_version>
chromadb==<latest_version>

python-dotenv==<latest_version>
tiktoken==<latest_version>
```

**2.3. Environment Configuration (`.env`):**
```
GOOGLE_API_KEY="your_google_api_key_from_ai_studio"
BRAVE_API_KEY="your_brave_search_api_key"
GEMINI_FLASH_MODEL="gemini-2.5-flash-lite-preview-06-17"
GEMINI_PRO_MODEL="gemini-2.5-flash"
```

#### **3. Source Scoring & Prioritization Algorithm**

To ensure report quality, sources are ranked using a weighted scoring algorithm.

**3.1. Source Priority Table:**
This table defines the authority of a source based on its domain. A utility function will map a source's URL to one of these types.

| Priority | Type | Description | Domain Keywords | Domain Score |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Official Documentation | Official project sites, docs, developer blogs. | `nextjs.org`, `nuxtjs.org`, `svelte.dev`, `solidjs.com`, `qwik.builder.io`, `remix.run`, `vercel.com/blog`, `astro.build` | 1.0 |
| 2 | Maintainer Tech Blogs | Blogs from major tech companies maintaining frameworks. | `engineering.fb.com`, `aws.amazon.com/blogs`, `netflixtechblog` | 0.9 |
| 3 | Reputable Tech Blogs | Well-known independent tech publications. | `smashingmagazine.com`, `css-tricks.com`, `infoq.com`, `thenewstack.io` | 0.7 |
| 4 | Community Platforms | High-quality tutorials and discussions. | `dev.to`, `medium.com`, `stackoverflow.com` | 0.5 |
| 5 | Other | Any other indexed source. | * | 0.3 |

**3.2. Recency Score:**
A score based on the publication date, calculated dynamically.
*   Date found & within 1 year of `runtime_date`: **1.0**
*   Date not found: **0.6** (Neutral penalty; we don't discard valuable undated docs).
*   Date found & older than 1 year: **0.3**

**3.3. Final Scoring Formula:**
The final rank for each source is calculated as follows. This formula prioritizes source authority above all else.
`Final_Score = (Domain_Score * 0.5) + (LLM_Relevance_Score * 0.3) + (Recency_Score * 0.2)`

---

#### **4. State Management & Core Logic**

All logic will reside in `main.py`.

**4.1. `ResearchState` Definition:**
The central `TypedDict` that manages the application's state through the graph.

```python
# main.py
from typing import TypedDict, List, Literal, Dict
# ... other imports

class ResearchState(TypedDict):
    technologies: List[str]
    report_mode: Optional[Literal["single", "comparison"]]
    is_comparable: Optional[bool]
    runtime_date: Optional[datetime]
    report_stages: Optional[List[str]]
    search_queries: Optional[List[str]]
    raw_sources: Optional[List[Dict]]
    ranked_sources: Optional[Dict[str, List[Dict]]]
    vector_store: Optional[chromadb.Collection]
    chroma_client: Optional[chromadb.Client]
    report_draft: Optional[str]
    final_report: Optional[str]
    reviewer_notes: Optional[str]
```

**4.2. Rate-Limited LLM Service:**
A function to wrap LLM instantiation, enforcing rate limits to stay within the free tier.

```python
# main.py
# ...
last_pro_call = 0
last_flash_call = 0

def get_llm(model_type: Literal["pro", "flash"]) -> ChatGoogleGenerativeAI:
    # Detailed implementation as specified in the previous plan,
    # checking time since last call and sleeping if necessary.
    # Returns an LLM instance.
```

---

#### **5. Node-by-Node Implementation Specification**

The following functions will be defined in `main.py` and added to the LangGraph instance.

**Node 1: `define_report_stages`**
*   **Objective:** To dynamically determine a logical structure for the report.
*   **Input from State:** `technologies`
*   **Output to State:** `report_mode`, `is_comparable`, `report_stages`, `runtime_date`
*   **Implementation Steps:**
    1.  Set `report_mode` to "single" or "comparison" based on the number of technologies.
    2.  If in "comparison" mode, use `PROMPT_VALIDATE_COMPARISON` to ensure technologies are comparable.
    3.  Invoke `get_llm("flash")` with the dynamic `PROMPT_DEFINE_STAGES`, passing in the `report_mode` and `technologies`. This prompt instructs the LLM to create a logical report outline suitable for either a single-subject or comparative analysis.
    4.  Parse the JSON response to get the list of stages.
    5.  Set `runtime_date = datetime.now()`.

**Node 2: `generate_search_queries`**
*   **Objective:** To create a minimal, high-yield set of search queries.
*   **Input from State:** `technologies`, `report_stages`, `runtime_date`
*   **Output to State:** `search_queries`
*   **Implementation Steps:**
    1.  Iterate through each `stage` in `report_stages` (skipping introduction/conclusion).
    2.  For each stage, format the new `PROMPT_GENERATE_QUERIES` to create a single, highly-targeted comparative query.
    3.  Invoke `get_llm("flash")` for each stage.
    4.  Collect the unique queries into the `search_queries` list.

**Node 3: `execute_web_search`**
*   **Objective:** To gather raw source material using the Brave Search API.
*   **Input from State:** `search_queries`
*   **Output to State:** `raw_sources`
*   **Implementation Steps:**
    1.  Initialize a `requests.Session`.
    2.  Iterate through `search_queries`, executing a request to the Brave Search API for each.
    3.  Aggregate all results and de-duplicate them based on URL to create `raw_sources`.

**Node 4: `rank_and_filter_sources`**
*   **Objective:** To rank all found sources for each report stage based on the defined scoring algorithm.
*   **Input from State:** `raw_sources`, `runtime_date`, `report_stages`, `technologies`
*   **Output to State:** `ranked_sources`
*   **Implementation Steps:**
    1.  Iterate through each `stage` in `report_stages`.
    2.  For each stage, batch the `raw_sources` to fit within the LLM's token limit.
    3.  For each batch, invoke `get_llm("flash")` with `PROMPT_RANK_SOURCES`. This prompt asks the LLM to identify which technologies are discussed and to provide a relevance score for the current stage.
    4.  For each source, calculate its `Domain_Score` and `Recency_Score`.
    5.  Apply the `Final_Scoring_Formula` using the LLM's relevance score.
    6.  Sort the sources for the stage by `final_score` and keep the top 10.
    7.  Store the results in the `ranked_sources` dictionary, keyed by stage.

**Node 5: `crawl_and_build_rag_store`**
*   **Objective:** To robustly extract content and build the RAG knowledge base.
*   **Input from State:** `ranked_sources`
*   **Output to State:** `vector_store`, `chroma_client`
*   **Implementation Steps:**
    1.  Aggregate all sources from all stages in `ranked_sources` and create a unique list of URLs to crawl.
    2.  Initialize ChromaDB client and create a new collection.
    3.  For each unique URL, use an adaptive crawling strategy (fast path with `requests`, robust path with `requests_html` for JS rendering).
    4.  If content is extracted, create `langchain.docstore.document.Document` objects. The metadata must contain `{'source_url': url, 'technologies': 'Technology1, Technology2'}`.
    5.  Chunk the documents and add them to the `vector_store`.

**Node 6: `generate_report_iteratively`**
*   **Objective:** To write the report, section by section, using the powerful model and RAG store.
*   **Input from State:** `report_stages`, `vector_store`, `technologies`, `ranked_sources`
*   **Output to State:** `report_draft`
*   **Implementation Steps:**
    1.  Initialize a retriever from the `vector_store`.
    2.  Loop through each `stage` in `report_stages`.
    3.  For each stage, create a context block by combining documents from two sources:
        *   A general similarity search from the retriever based on the stage name.
        *   The specific top-ranked sources for that stage from the `ranked_sources` map.
    4.  De-duplicate the combined list of documents.
    5.  Format `PROMPT_WRITE_SECTION` with the `stage`, `technologies`, and the retrieved context.
    6.  Invoke the **Gemini Pro** model to generate the markdown for that section.
    7.  Append the section to the `report_draft`.

**Node 7: `final_review`**
*   **Objective:** To perform an automated quality check and write the final assessment.
*   **Input from State:** `report_draft`
*   **Output to State:** `reviewer_notes`
*   **Implementation Steps:**
    1.  Format `PROMPT_FINAL_REVIEW` with the entire `report_draft`.
    2.  Invoke `get_llm("pro")`.
    3.  Store the complete, unedited markdown response in `reviewer_notes`. No JSON parsing is performed.

**Node 8: `compile_final_report`**
*   **Objective:** Final assembly and saving the report.
*   **Input from State:** `report_draft`, `reviewer_notes`
*   **Output to State:** `final_report` (and saves file to disk)
*   **Implementation Steps:**
    1.  Construct the final markdown string by concatenating the `report_draft` and the `reviewer_notes`.
    2.  Generate a filename and write the report to disk.

#### **6. Graph Assembly & Execution**

To be placed at the end of `main.py`.

1.  Instantiate `langgraph.graph.StateGraph(ResearchState)`.
2.  Add all node functions to the graph instance.
3.  Set the entry point to `define_report_stages`.
4.  Define a conditional edge after `define_report_stages` that routes to `generate_search_queries` if `is_comparable` is `True`, and to `END` otherwise.
5.  Define the sequential edges connecting the rest of the nodes.
6.  Compile the graph: `app = workflow.compile()`.
7.  The main execution block will parse CLI args, invoke `app.stream()` with the initial state, and print progress updates as the graph executes.

---

### **Appendix A: Prompt Library**

This section contains the exact prompts to be used.

**PROMPT_VALIDATE_COMPARISON:**
```
You are a technology classification expert. The user wants to compare the following technologies: {technologies}.
Are these technologies directly comparable for a detailed technical report? For example, "Next.js" and "Nuxt.js" are comparable (both are full-stack frameworks). "Next.js" and "Formik" are not (one is a framework, one is a form library).
Respond with only a single JSON object with one key, "is_comparable", set to either true or false.
```

**PROMPT_DEFINE_STAGES:**
```
You are a technology analyst creating the structure for a technical report.
The user wants a report on: **{technologies}**. The report mode is: **{report_mode}**.

- If the `report_mode` is "single", create a detailed, standalone report structure.
- If the `report_mode` is "comparison", create a structure that directly compares the technologies against each other for each key aspect. Avoid creating separate sections for each technology.

**Example for "comparison" of Next.js vs Remix:**
["Introduction", "Comparative Analysis: Performance", "Comparative Analysis: Scalability", "Comparative Analysis: Developer Experience", "Conclusion"]

Respond with only a single, valid JSON array of the chosen section titles.
```

**PROMPT_GENERATE_QUERIES:**
```
You are a search query expert, tasked with finding information for a high-quality technical report comparing {technologies}. The current year is {year}.
For the report section "{stage_name}", generate a single, highly effective Brave Search query.
The query must be comparative. For example, for "Performance", a good query would be "{technologies} performance benchmarks {year}". For "Developer Experience", a good query would be "comparing developer experience of {technologies}".
Return only the single search query. Do not add any other text.
```

**PROMPT_RANK_SOURCES:**
```
You are a data analyst. The user wants a report on {technologies}. For each source in the JSON list below, perform two tasks:
1.  Identify which of the listed technologies are discussed in the source's title and snippet.
2.  Determine the source's relevance to the report section: "{stage_name}". Rate relevance on a scale from 0.0 to 1.0.

Respond with only a single, valid JSON array. Each object in the array should correspond to an input source and contain its ID, the list of `discussed_technologies`, and the `relevance_score`.

Example Input:
[
  { "id": 1, "title": "Next.js vs Remix Performance", "snippet": "..." },
  { "id": 2, "title": "Getting Started with SvelteKit", "snippet": "..." }
]

Example Output:
[
  {
    "id": 1,
    "discussed_technologies": ["Next.js", "Remix"],
    "relevance_score": 0.9
  },
  {
    "id": 2,
    "discussed_technologies": ["SvelteKit"],
    "relevance_score": 0.1
  }
]

Actual Input:
{batch_of_sources}
```

**PROMPT_WRITE_SECTION:**
```
You are a meticulous Senior Technology Analyst writing a technical report for a CTO. Your tone must be objective, data-driven, and deeply technical.
Your current task is to write the "{stage_name}" section of the report.
If the report is a comparison of {technologies}, you must synthesize information and create a comparative analysis for this section.
If the report is for a single technology ({technologies}), focus solely on that technology.

**Instructions:**
- Use ONLY the provided context. Do not invent, infer, or use any external knowledge.
- Every single statement of fact or data point MUST be followed by a citation, like this: [source_url].
- If multiple sources support a single point, cite them together: [source_url_1, source_url_2].
- If the context lacks information for a specific point, you MUST explicitly state: "Information regarding [specific point] was not found in the analyzed sources."
- If you find conflicting information, present both sides and cite their respective sources.
- Do NOT include the section title in your response.
- Structure the output in clear, concise markdown.

CONTEXT:
---
{context_documents}
---
```

**PROMPT_FINAL_REVIEW:**
```
You are a Chief Technology Officer reviewing a report generated by an AI analyst. Your task is to perform a final, critical quality check and write the "Final Assessment" section.
Read the entire report draft below. Your goal is to identify weaknesses a senior engineering leader would spot and provide a conclusive summary.

Analyze the report for the following:
1.  **Contradictions:** Are there any statements that contradict each other?
2.  **Weak Justifications:** Are any conclusions based on weak or single sources?
3.  **Missing Citations:** Are there any statements of fact that are missing a citation?
4.  **Critical Gaps:** What crucial information is missing that would be required for a technology adoption decision? (e.g., "The report details performance but lacks any analysis of the security landscape or recent CVEs.")

Based on your analysis, write a concise "Final Assessment" section in markdown. This should be your final verdict and summary. If the report is sound, state that. If it has weaknesses, clearly articulate them.

REPORT DRAFT:
---
{report_draft}
---
```