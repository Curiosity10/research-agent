from typing import TypedDict, List, Literal, Dict, Optional
from datetime import datetime
import chromadb
import time
import logging
import requests
import tiktoken
from urllib.parse import urlparse
import trafilatura
import requests_html
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.docstore.document import Document
from langchain_chroma import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI
import os
import json
from langchain_core.output_parsers import JsonOutputParser
from langgraph.graph import END, StateGraph
import argparse
from dotenv import load_dotenv

# --- Constants ---
RANKING_TOKEN_LIMIT = 12000

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s ℹ️  %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("logs.txt", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Prompts ---
PROMPT_VALIDATE_COMPARISON = '''You are a technology classification expert. The user wants to compare the following technologies: {technologies}.
Are these technologies directly comparable for a detailed technical report? For example, "Next.js" and "Nuxt.js" are comparable (both are full-stack frameworks). "Next.js" and "Formik" are not (one is a framework, one is a form library).
Respond with only a single JSON object with one key, "is_comparable", set to either true or false.
'''

PROMPT_DEFINE_STAGES = '''You are a technology analyst creating the structure for a technical report.
The user wants a report on: **{technologies}**. The report mode is: **{report_mode}**.

- If the `report_mode` is "single", create a detailed, standalone report structure.
- If the `report_mode` is "comparison", create a structure that directly compares the technologies against each other for each key aspect. Avoid creating separate sections for each technology.

**Example for "comparison" of Next.js vs Remix:**
["Introduction", "Comparative Analysis: Performance", "Comparative Analysis: Scalability", "Comparative Analysis: Developer Experience", "Conclusion"]

Respond with only a single, valid JSON array of the chosen section titles.
'''

PROMPT_GENERATE_QUERIES = '''You are a search query expert, tasked with finding information for a high-quality technical report comparing {technologies}. The current year is {year}.
For the report section "{stage_name}", generate a single, highly effective Brave Search query.
The query must be comparative. For example, for "Performance", a good query would be "{technologies} performance benchmarks {year}". For "Developer Experience", a good query would be "comparing developer experience of {technologies}".
Return only the single search query. Do not add any other text.
'''

PROMPT_RANK_SOURCES = '''You are a data analyst. The user wants a report on {technologies}. For each source in the JSON list below, perform two tasks:
1.  Identify which of the listed technologies are discussed in the source's title and snippet.
2.  Determine the source's relevance to the report section: "{stage_name}". Rate relevance on a scale from 0.0 to 1.0.

Respond with only a single, valid JSON array. Each object in the array should correspond to an input source and contain its ID, the list of `discussed_technologies`, and the `relevance_score`.

Example Input:
[
  {{ "id": 1, "title": "Next.js vs Remix Performance", "snippet": "..." }},
  {{ "id": 2, "title": "Getting Started with SvelteKit", "snippet": "..." }}
]

Example Output:
[
  {{
    "id": 1,
    "discussed_technologies": ["Next.js", "Remix"],
    "relevance_score": 0.9
  }},
  {{
    "id": 2,
    "discussed_technologies": ["SvelteKit"],
    "relevance_score": 0.1
  }}
]

Actual Input:
{batch_of_sources}
'''

PROMPT_WRITE_SECTION = '''You are a meticulous Senior Technology Analyst writing a technical report for a CTO. Your tone must be objective, data-driven, and deeply technical.
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
'''

PROMPT_FINAL_REVIEW = '''You are a Chief Technology Officer reviewing a report generated by an AI analyst. Your task is to perform a final, critical quality check and write the "Final Assessment" section.
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
'''

# --- State Definition ---
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

# --- LLM Service ---
last_pro_call = 0
last_flash_call = 0

def get_llm(model_type: Literal["pro", "flash"]) -> ChatGoogleGenerativeAI:
    global last_pro_call, last_flash_call
    logger.info(f"Requesting LLM of type: {model_type}")
    now = time.time()
    if model_type == "pro":
        wait_time_str = os.getenv("LLM_PRO_RATE_LIMIT_SECONDS", "1.1")
        wait_time = float(wait_time_str) - (now - last_pro_call)
        if wait_time > 0:
            logger.info(f"Rate limiting PRO model. Sleeping for {wait_time:.2f} seconds.")
            time.sleep(wait_time)
        last_pro_call = time.time()
        model_name = os.getenv("GEMINI_PRO_MODEL")
    else:
        wait_time_str = os.getenv("LLM_FLASH_RATE_LIMIT_SECONDS", "0.5")
        wait_time = float(wait_time_str) - (now - last_flash_call)
        if wait_time > 0:
            logger.info(f"Rate limiting FLASH model. Sleeping for {wait_time:.2f} seconds.")
            time.sleep(wait_time)
        last_flash_call = time.time()
        model_name = os.getenv("GEMINI_FLASH_MODEL")
    
    logger.info(f"Returning {model_name} instance.")
    return ChatGoogleGenerativeAI(model=model_name, temperature=0.0)

# --- Graph Nodes ---
def define_report_stages(state: ResearchState) -> ResearchState:
    logger.info("🚀 ---NODE: DEFINING REPORT STAGES---")
    technologies = state['technologies']
    logger.info(f"Technologies to research: {technologies}")
    report_mode = "comparison" if len(technologies) > 1 else "single"
    state['report_mode'] = report_mode
    state['runtime_date'] = datetime.now()
    logger.info(f"Report mode set to: {report_mode}")

    if report_mode == "comparison":
        logger.info("Validating comparability of technologies.")
        llm = get_llm("flash")
        prompt = PROMPT_VALIDATE_COMPARISON.format(technologies=technologies)
        response = llm.invoke(prompt)
        parser = JsonOutputParser()
        is_comparable = parser.parse(response.content).get("is_comparable", False)
        state['is_comparable'] = is_comparable
        logger.info(f"Are technologies comparable? {'Yes' if is_comparable else 'No'}")
        if not is_comparable:
            logger.warning("Technologies not comparable. Ending workflow.")
            return state
    else:
        state['is_comparable'] = True

    logger.info("Defining report stages...")
    llm = get_llm("flash")
    prompt = PROMPT_DEFINE_STAGES.format(
        technologies=", ".join(technologies),
        report_mode=report_mode
    )
    response = llm.invoke(prompt)
    parser = JsonOutputParser()
    try:
        report_stages = parser.parse(response.content)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse report stages from LLM. Raw content: {response.content}")
        report_stages = ["Introduction", "Performance", "Scalability", "Developer Experience", "Security", "Ecosystem", "Conclusion"]
    state['report_stages'] = report_stages
    logger.info(f"Defined report stages: {report_stages}")
    return state

def generate_search_queries(state: ResearchState) -> ResearchState:
    logger.info("🔍 ---NODE: GENERATING SEARCH QUERIES---")
    llm = get_llm("flash")
    technologies = state['technologies']
    report_stages = state['report_stages']
    
    search_queries = []
    tech_string = " vs ".join(technologies)
    
    for stage in report_stages:
        if stage.lower() in ["introduction", "conclusion", "final assessment"]:
            continue
        prompt = PROMPT_GENERATE_QUERIES.format(
            technologies=tech_string,
            stage_name=stage,
            year=state['runtime_date'].year
        )
        response = llm.invoke(prompt)
        search_queries.append(response.content.strip())

    state['search_queries'] = list(set(search_queries)) # Remove duplicates
    logger.info(f"Generated {len(state['search_queries'])} unique search queries.")
    return state

def execute_web_search(state: ResearchState) -> ResearchState:
    logger.info("🌐 ---NODE: EXECUTING WEB SEARCH---")
    search_queries = state['search_queries']
    brave_api_key = os.getenv("BRAVE_API_KEY")
    if not brave_api_key:
        logger.error("BRAVE_API_KEY environment variable not set.")
        raise ValueError("BRAVE_API_KEY environment variable not set.")

    all_results = []
    session = requests.Session()
    headers = {
        "X-Subscription-Token": brave_api_key,
        "Accept": "application/json"
    }

    for query in search_queries:
        logger.info(f"Executing search for query: '{query}'")
        try:
            response = session.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers=headers,
                params={"q": query, "count": 10, "text_decorations": False},
                timeout=15
            )
            response.raise_for_status()
            results = response.json().get("web", {}).get("results", [])
            logger.info(f"Found {len(results)} results for query.")
            all_results.extend(results)
        except requests.exceptions.Timeout:
            logger.warning(f"Search query '{query}' timed out.")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error for query '{query}': {e}")
            if 400 <= e.response.status_code < 500:
                logger.critical("Critical API key or request error. Please check your BRAVE_API_KEY.")
        except requests.exceptions.RequestException as e:
            logger.error(f"An unexpected error occurred for query '{query}': {e}")
        finally:
            time.sleep(1)

    unique_urls = {result['url'] for result in all_results}
    unique_sources = [next(s for s in all_results if s['url'] == url) for url in unique_urls]
    
    state['raw_sources'] = list(unique_sources)
    logger.info(f"Found {len(state['raw_sources'])} unique sources across all queries.")
    return state

def rank_and_filter_sources(state: ResearchState) -> ResearchState:
    logger.info("📊 ---NODE: RANKING AND FILTERING SOURCES---")
    if not state.get('raw_sources'):
        logger.warning("No sources found to rank. Skipping node.")
        state['ranked_sources'] = {}
        return state

    def get_domain_score(url: str) -> float:
        domain_keywords = {
            "1.0": ["nextjs.org", "remix.run", "react.dev", "vuejs.org", "angular.io", "svelte.dev", "solidjs.com", "qwik.builder.io", "astro.build", "deno.land", "nodejs.org", "python.org", "docs.microsoft.com", "developer.mozilla.org", "w3.org", "ecma-international.org", "graphql.org", "restfulapi.net", "kubernetes.io", "docker.com", "cloud.google.com", "aws.amazon.com", "azure.microsoft.com", "spring.io", "golang.org", "rust-lang.org", "llvm.org", "kernel.org", "apache.org", "eclipse.org", "ietf.org", "iso.org", "nist.gov", "mit.edu", "stanford.edu", "berkeley.edu", "cmu.edu", "ieee.org", "acm.org", "arxiv.org", "dl.acm.org", "jstor.org", "sciencedirect.com", "link.springer.com", "wiley.com", "taylorandfrancis.com", "elsevier.com"],
            "0.9": ["vercel.com/blog", "engineering.fb.com", "aws.amazon.com/blogs", "netflixtechblog", "google.dev", "microsoft.com/research", "redhat.com/en/blog", "ibm.com/blogs", "developer.apple.com", "android.com/developers", "stripe.com/blog", "shopify.dev", "salesforce.com/news"],
            "0.8": ["smashingmagazine.com", "css-tricks.com", "infoq.com", "thenewstack.io", "martinfowler.com", "oreilly.com", "apress.com", "manning.com", "techcrunch.com", "wired.com", "zdnet.com", "infoworld.com", "computerworld.com", "arstechnica.com"],
            "0.7": ["dev.to", "freecodecamp.org", "logrocket.com", "toptal.com/developers", "hackernoon.com", "towardsdatascience.com", "betterprogramming.pub", "medium.com", "hashnode.dev", "devdojo.com"],
            "0.6": ["stackoverflow.com", "reddit.com/r/programming", "quora.com", "stackexchange.com"],
            "0.5": ["github.com", "gitlab.com", "bitbucket.org", "gitee.com"]
        }
        domain = urlparse(url).netloc
        for score, keywords in domain_keywords.items():
            if any(keyword in domain for keyword in keywords):
                return float(score)
        return 0.3

    def get_recency_score(source: Dict, runtime_date: datetime) -> float:
        if 'page_age' in source:
            page_age_str = source['page_age']
            try:
                page_date = datetime.fromisoformat(page_age_str.replace('Z', '+00:00'))
                if (runtime_date - page_date).days <= 365:
                    return 1.0
                else:
                    return 0.3
            except (ValueError, TypeError):
                return 0.6
        return 0.6

    raw_sources = state['raw_sources']
    runtime_date = state['runtime_date']
    technologies = state['technologies']
    report_stages = state['report_stages']
    
    tokenizer = tiktoken.get_encoding("cl100k_base")
    
    for i, source in enumerate(raw_sources):
        source['id'] = i

    ranked_sources_by_stage = {stage: [] for stage in report_stages}
    llm = get_llm("flash")

    for stage in report_stages:
        if stage.lower() in ["introduction", "conclusion", "final assessment"]:
            continue

        logger.info(f"Ranking sources for stage: '{stage}'")
        
        batches = []
        current_batch = []
        current_token_count = 0
        for source in raw_sources:
            content_to_tokenize = f"Title: {source.get('title', '')}\nSnippet: {source.get('description', '')}"
            token_count = len(tokenizer.encode(content_to_tokenize))
            if current_token_count + token_count > RANKING_TOKEN_LIMIT:
                batches.append(current_batch)
                current_batch = []
                current_token_count = 0
            current_batch.append(source)
            current_token_count += token_count
        if current_batch:
            batches.append(current_batch)

        all_llm_evals = []
        for i, batch in enumerate(batches):
            logger.info(f"Processing batch {i+1}/{len(batches)} for stage '{stage}'...")
            prompt_batch = [{"id": s["id"], "title": s.get("title"), "snippet": s.get("description")} for s in batch]
            prompt = PROMPT_RANK_SOURCES.format(
                stage_name=stage,
                technologies=json.dumps(technologies),
                batch_of_sources=json.dumps(prompt_batch)
            )
            response = llm.invoke(prompt)
            parser = JsonOutputParser()
            try:
                parsed_response = parser.parse(response.content)
                all_llm_evals.extend(parsed_response)
            except Exception as e:
                logger.error(f"Error parsing LLM response for batch {i+1} in stage '{stage}': {e}")

        eval_map = {item['id']: item for item in all_llm_evals}
        
        stage_scored_sources = []
        for source in raw_sources:
            llm_eval = eval_map.get(source['id'])
            if not llm_eval or llm_eval.get('relevance_score', 0) < 0.5:
                continue

            domain_score = get_domain_score(source['url'])
            recency_score = get_recency_score(source, runtime_date)
            final_score = (domain_score * 0.5) + (llm_eval['relevance_score'] * 0.3) + (recency_score * 0.2)
            
            stage_scored_sources.append({
                "url": source['url'],
                "title": source.get('title'),
                "final_score": final_score,
                "discussed_technologies": llm_eval.get('discussed_technologies', []),
                **source
            })
        
        stage_scored_sources.sort(key=lambda x: x['final_score'], reverse=True)
        ranked_sources_by_stage[stage] = stage_scored_sources[:10] # Keep top 10 sources per stage
        logger.info(f"Found {len(ranked_sources_by_stage[stage])} relevant sources for stage '{stage}'.")

    state['ranked_sources'] = ranked_sources_by_stage
    logger.info("---RANKING AND FILTERING COMPLETE---")
    return state

class ChromaEmbeddingFunction(chromadb.EmbeddingFunction):
    def __init__(self, embeddings_model):
        self.embeddings_model = embeddings_model

    def __call__(self, input: chromadb.Documents) -> chromadb.Embeddings:
        return self.embeddings_model.embed_documents(input)

def crawl_and_build_rag_store(state: ResearchState) -> ResearchState:
    logger.info("🧠 ---NODE: CRAWLING AND BUILDING RAG STORE---")
    ranked_sources = state['ranked_sources']
    
    db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
    collection_name = os.getenv("CHROMA_COLLECTION_NAME", "report")
    
    logger.info(f"Initializing Google Generative AI embeddings and ChromaDB client at {db_path}.")
    embeddings_model = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    embeddings = ChromaEmbeddingFunction(embeddings_model)
    
    chroma_client = chromadb.PersistentClient(path=db_path)
    try:
        chroma_client.delete_collection(name=collection_name)
        logger.info(f"Existing ChromaDB collection '{collection_name}' deleted.")
    except Exception as e:
        logger.info(f"ChromaDB collection '{collection_name}' did not exist or could not be deleted: {e}")
    vector_store = chroma_client.create_collection(name=collection_name, embedding_function=embeddings)
    state['chroma_client'] = chroma_client

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    html_session = requests_html.HTMLSession()
    
    all_sources_to_crawl = []
    for stage, sources in ranked_sources.items():
        all_sources_to_crawl.extend(sources)
        
    unique_urls_to_crawl = {s['url']: s for s in all_sources_to_crawl}.values()
    logger.info(f"Identified {len(unique_urls_to_crawl)} unique sources to crawl across all stages.")

    for i, source in enumerate(unique_urls_to_crawl):
        url = source['url']
        logger.info(f"Crawling {i+1}/{len(unique_urls_to_crawl)}: {url}")
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            cleaned_text = trafilatura.extract(response.text)

            if not cleaned_text or len(cleaned_text) < 250:
                logger.warning("Initial crawl failed or content too short. Falling back to robust JS rendering.")
                try:
                    r = html_session.get(url)
                    r.html.render(sleep=3, timeout=25)
                    cleaned_text = trafilatura.extract(r.html.html)
                except Exception as e:
                    logger.error(f"Robust JS rendering failed for {url}: {e}")
                    cleaned_text = None

            if cleaned_text:
                discussed_techs = source.get('discussed_technologies', [])
                if not discussed_techs:
                    logger.warning(f"Skipping source {url} as no technologies were associated with it by the LLM.")
                    continue
                
                docs = [Document(page_content=cleaned_text, metadata={"source_url": url, "technologies": ", ".join(discussed_techs)})]
                chunks = text_splitter.split_documents(docs)
                
                ids = [f"{url}_{j}" for j in range(len(chunks))]
                vector_store.add(ids=ids, documents=[chunk.page_content for chunk in chunks], metadatas=[chunk.metadata for chunk in chunks])
                logger.info(f"Successfully added {len(chunks)} chunks for {url}.")
            else:
                logger.warning(f"Failed to extract content from {url} after robust attempt.")

        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")

    state['vector_store'] = vector_store
    logger.info("---CRAWLING AND RAG STORE COMPLETE---")
    return state

def generate_report_iteratively(state: ResearchState) -> ResearchState:
    logger.info("✍️ ---NODE: GENERATING REPORT ITERATIVELY---")
    report_stages = state['report_stages']
    technologies = state['technologies']
    ranked_sources = state['ranked_sources']
    
    collection_name = os.getenv("CHROMA_COLLECTION_NAME", "report")
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    chroma_vector_store = Chroma(client=state['chroma_client'], collection_name=collection_name, embedding_function=embeddings)
    retriever = chroma_vector_store.as_retriever(search_kwargs={"k": 15})
    
    pro_llm = get_llm("pro")
    report_draft = ""

    for stage in report_stages:
        logger.info(f"Generating section: '{stage}'")
        
        # For intro and conclusion, we don't need RAG, just the tech names
        if stage in ["Introduction", "Conclusion"]:
            context_docs = "No context needed for this section."
        else:
            # Create a focused query for the retriever
            query = f"Information about {stage} for {' vs '.join(technologies)}"
            retrieved_docs = retriever.invoke(query)
            
            # Also include the hand-picked top sources for this stage
            top_urls_for_stage = {s['url'] for s in ranked_sources.get(stage, [])}
            if top_urls_for_stage:
                top_docs = chroma_vector_store.get(where={"source_url": {"$in": list(top_urls_for_stage)}})
                
                # Combine and de-duplicate
                all_docs_for_stage = retrieved_docs
                for i, doc_id in enumerate(top_docs['ids']):
                    if doc_id not in [d.metadata.get('id') for d in all_docs_for_stage]:
                         all_docs_for_stage.append(Document(page_content=top_docs['documents'][i], metadata=top_docs['metadatas'][i]))
            else:
                all_docs_for_stage = retrieved_docs

            unique_docs = {f"{doc.metadata.get('source_url')}_{doc.page_content}": doc for doc in all_docs_for_stage}
            context_docs = "\n\n---\n\n".join([f"Source: {doc.metadata['source_url']}\nContent: {doc.page_content}" for doc in unique_docs.values()])

        prompt = PROMPT_WRITE_SECTION.format(
            stage_name=stage,
            technologies=", ".join(technologies),
            context_documents=context_docs
        )
        
        section_content = pro_llm.invoke(prompt).content
        report_draft += f"## {stage}\n\n{section_content}\n\n"

    state['report_draft'] = report_draft
    logger.info("---REPORT DRAFT COMPLETE---")
    return state

def final_review(state: ResearchState) -> ResearchState:
    logger.info("🧐 ---NODE: PERFORMING FINAL REVIEW---")
    llm = get_llm("pro")
    prompt = PROMPT_FINAL_REVIEW.format(report_draft=state['report_draft'])
    response = llm.invoke(prompt).content
    state['reviewer_notes'] = response
    logger.info("Final review complete. Notes generated.")
    return state

def compile_final_report(state: ResearchState) -> ResearchState:
    logger.info("✅ ---NODE: COMPILING FINAL REPORT---")
    technologies = state['technologies']
    runtime_date = state['runtime_date']
    report_draft = state['report_draft']
    reviewer_notes = state['reviewer_notes']

    final_report = f"# Technology Analysis Report: {', '.join(technologies)}\n\n"
    final_report += f"*Report generated on: {runtime_date.strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
    final_report += report_draft
    
    if reviewer_notes:
        final_report += f"## Final Assessment\n\n{reviewer_notes}\n"

    file_name = f"report_{'_vs_'.join(t.lower().replace(' ', '_') for t in technologies)}_{runtime_date.strftime('%Y-%m-%d')}.md"
    with open(file_name, "w", encoding='utf-8') as f:
        f.write(final_report)

    state['final_report'] = final_report
    logger.info(f"Report generation complete. File saved to: {file_name}")
    return state

# --- Graph Definition ---
def should_continue(state: ResearchState) -> str:
    if not state.get('is_comparable', True):
        return "end"
    else:
        return "generate_search_queries"

workflow = StateGraph(ResearchState)

workflow.add_node("define_report_stages", define_report_stages)
workflow.add_node("generate_search_queries", generate_search_queries)
workflow.add_node("execute_web_search", execute_web_search)
workflow.add_node("rank_and_filter_sources", rank_and_filter_sources)
workflow.add_node("crawl_and_build_rag_store", crawl_and_build_rag_store)
workflow.add_node("generate_report_iteratively", generate_report_iteratively)
workflow.add_node("final_review", final_review)
workflow.add_node("compile_final_report", compile_final_report)

workflow.set_entry_point("define_report_stages")

workflow.add_conditional_edges(
    "define_report_stages",
    should_continue,
    {"generate_search_queries": "generate_search_queries", "end": END}
)

workflow.add_edge("generate_search_queries", "execute_web_search")
workflow.add_edge("execute_web_search", "rank_and_filter_sources")
workflow.add_edge("rank_and_filter_sources", "crawl_and_build_rag_store")
workflow.add_edge("crawl_and_build_rag_store", "generate_report_iteratively")
workflow.add_edge("generate_report_iteratively", "final_review")
workflow.add_edge("final_review", "compile_final_report")
workflow.add_edge("compile_final_report", END)

app = workflow.compile()

# --- Main Execution ---
if __name__ == '__main__':
    load_dotenv()
    os.environ.setdefault("GEMINI_FLASH_MODEL", "gemini-2.5-flash-lite-preview-06-17")
    os.environ.setdefault("GEMINI_PRO_MODEL", "gemini-2.5-flash")

    parser = argparse.ArgumentParser()
    parser.add_argument("technologies", nargs='+', help="List of technologies to research.")
    args = parser.parse_args()

    logger.info(f"---STARTING RESEARCH PROCESS for: {args.technologies}---")
    initial_state = {"technologies": args.technologies}

    for event in app.stream(initial_state):
        for key, value in event.items():
            logger.info(f"➡️ ---GRAPH EVENT: {key.upper()}---")

    logger.info("---RESEARCH PROCESS COMPLETE---")