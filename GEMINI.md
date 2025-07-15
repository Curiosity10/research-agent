# Gemini AI Agent Rules for Project Research Agent

This document outlines the operational rules and constraints for the Gemini AI agent when working on the Project Research Agent. Adherence to these rules is mandatory to ensure the project meets its technical and quality specifications.

## 1. Core Objective Adherence
- **Primary Goal:** Your sole focus is to implement the logic for the Project Research Agent, which autonomously generates comprehensive, data-driven technology analysis reports.
- **Citation is Mandatory:** The final report's core requirement is that every statement of fact must be supported by a citation `[source_url]` derived from the provided context. Do not invent, infer, or use outside knowledge. If information is not present in the sources, you must explicitly state that.

## 2. Strict Prompt Compliance
- You must use the **exact prompts** as defined in `Appendix A` of the `doc.md` technical specification for all LLM-driven nodes in the graph.
- Do not modify, augment, or deviate from the provided prompt templates.

## 3. Model Usage Protocol
- **`GEMINI_FLASH_MODEL` (`gemini-2.5-flash-lite-preview-06-17`):** Use this model for tasks requiring speed and efficiency. This includes:
    - `define_report_stages`
    - `generate_search_queries`
    - `rank_and_filter_sources`
- **`GEMINI_PRO_MODEL` (`gemini-2.5-flash`):** Use this model for tasks requiring high reasoning capacity. This includes:
    - `generate_report_iteratively`
    - `final_review`

## 4. Zero-Cost Operation
- The system must operate strictly within the free tiers of all external services (Google AI, Brave Search).
- You must implement and respect the rate-limiting logic (`get_llm` function) for all LLM calls to avoid incurring costs.

## 5. Structured Data Output
- Your responses for certain nodes must conform to a strict, machine-readable format.
- **JSON Output:** For `PROMPT_VALIDATE_COMPARISON`, `PROMPT_DEFINE_STAGES`, and `PROMPT_RANK_SOURCES`, the output must be a single, valid JSON object or array as specified in the prompt.
- **List Output:** For `PROMPT_GENERATE_QUERIES`, the output must be only a newline-separated list of query strings.

## 6. Source Prioritization Algorithm
- The implementation of the `rank_and_filter_sources` node must strictly adhere to the scoring algorithm defined in the technical specification.
- The final score must be calculated using the formula: `Final_Score = (Domain_Score * 0.5) + (LLM_Relevance_Score * 0.3) + (Recency_Score * 0.2)`.

## 7. Architectural Integrity
- All Python code for the agent's logic, state, nodes, and graph assembly must be contained within the single `main.py` file, as per the specified monolithic architecture.
- Write as less code, as possible. Do not include redundant comments. Keep it simple and stable.
- Add logs for each new operations, to fully understand current state of app.
- Use venv to run the app. Use settings for Windows.
