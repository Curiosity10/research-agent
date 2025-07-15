# Project Research Agent

This project is a research agent that autonomously generates comprehensive, data-driven technology analysis reports.

## Installation

1.  Clone the repository.
2.  Create and activate a virtual environment:
    ```bash
    python -m venv venv
    Linux:
    source venv/bin/activate
    Windows:
    .\venv\Scripts\Activate.ps1
    ```
3.  Install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## Setup

1.  Create a `.env` file in the root of the project by copying the `env.example` file:
    ```bash
    cp env.example .env
    ```
2.  Open the newly created `.env` file and replace the placeholder values with your actual API keys and preferred model names:
    ```
    GOOGLE_API_KEY="your_google_api_key_from_ai_studio"
    BRAVE_API_KEY="your_brave_search_api_key"
    GEMINI_FLASH_MODEL="gemini-2.5-flash-lite-preview-06-17"
    GEMINI_PRO_MODEL="gemini-2.5-flash"
    ```

## Usage

To run the research agent, activate your virtual environment (if not already active) and execute the following command:

```bash
python main.py <technology_1> <technology_2> ...
```

For example:

```bash
python main.py "Next.js" "Nuxt.js" "Remix"
```