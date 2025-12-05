import asyncio, os
from langsmith import traceable
from pydantic import BaseModel, Field
#from state import Section
from tavily import TavilyClient, AsyncTavilyClient


# Search engine Tavily
os.environ["TAVILY_API_KEY"]="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"
tavily_client = TavilyClient()
tavily_async_client = AsyncTavilyClient()


def deduplicate_and_format_sources(search_response, max_tokens_per_source, include_raw_content=True):
    """
    Takes either a single search response or list of responses from Tavily API and formats them.
    Limits the raw_content to approximately max_tokens_per_source.
    include_raw_content specifies whether to include the raw_content from Tavily in the formatted string.
    
    Args:
        search_response: Either:
            - A dict with a 'results' key containing a list of search results
            - A list of dicts, each containing search results
            
    Returns:
        str: Formatted string with deduplicated sources
    """
    # Convert input to list of results
    if isinstance(search_response, dict):
        sources_list = search_response['results']
    elif isinstance(search_response, list):
        sources_list = []
        for response in search_response:
            if isinstance(response, dict) and 'results' in response:
                sources_list.extend(response['results'])
            else:
                sources_list.extend(response)
    else:
        raise ValueError("Input must be either a dict with 'results' or a list of search results")
    
    # Deduplicate by URL
    unique_sources = {}
    for source in sources_list:
        if source['url'] not in unique_sources:
            unique_sources[source['url']] = source
    
    # Format output
    formatted_text = "Sources:\n\n"
    for i, source in enumerate(unique_sources.values(), 1):
        formatted_text += f"Source {source['title']}:\n===\n"
        formatted_text += f"URL: {source['url']}\n===\n"
        formatted_text += f"Most relevant content from source: {source['content']}\n===\n"
        if include_raw_content:
            # Using rough estimate of 4 characters per token
            char_limit = max_tokens_per_source * 4
            # Handle None raw_content
            raw_content = source.get('raw_content', '')
            if raw_content is None:
                raw_content = ''
                print(f"Warning: No raw_content found for source {source['url']}")
            if len(raw_content) > char_limit:
                raw_content = raw_content[:char_limit] + "... [truncated]"
            formatted_text += f"Full source content limited to {max_tokens_per_source} tokens: {raw_content}\n\n"
                
    return formatted_text.strip()

#def format_sections(sections: list[Section]) -> str:
def format_sections(sections: list) -> str:
    """ Format a list of sections into a string """
    formatted_str = ""
    for idx, section in enumerate(sections, 1):
        formatted_str += f"""
{'='*60}
Section {idx}: {section.name}
{'='*60}
Description:
{section.description}
Requires Research: 
{section.research}

Content:
{section.content if section.content else '[Not yet written]'}

"""
    return formatted_str

@traceable
def tavily_search(query):
    """ Search the web using the Tavily API.
    
    Args:
        query (str): The search query to execute
        
    Returns:
        dict: Tavily search response containing:
            - results (list): List of search result dictionaries, each containing:
                - title (str): Title of the search result
                - url (str): URL of the search result
                - content (str): Snippet/summary of the content
                - raw_content (str): Full content of the page if available"""
     
    return tavily_client.search(query, 
                         max_results=5, 
                         include_raw_content=True)

@traceable
async def tavily_search_async(search_queries, tavily_topic, tavily_days):
    """
    Performs concurrent web searches using the Tavily API.

    Args:
        search_queries (List[SearchQuery]): List of search queries to process
        tavily_topic (str): Type of search to perform ('news' or 'general')
        tavily_days (int): Number of days to look back for news articles (only used when tavily_topic='news')

    Returns:
        List[dict]: List of search results from Tavily API, one per query

    Note:
        For news searches, each result will include articles from the last `tavily_days` days.
        For general searches, the time range is unrestricted.
    """
    
    search_tasks = []
    for query in search_queries:
        if tavily_topic == "news":
            search_tasks.append(
                tavily_async_client.search(
                    query,
                    max_results=5,
                    include_raw_content=True,
                    topic="news",
                    days=tavily_days
                )
            )
        else:
            search_tasks.append(
                tavily_async_client.search(
                    query,
                    max_results=5,
                    include_raw_content=True,
                    topic="general"
                )
            )

    # Execute all searches concurrently
    search_docs = await asyncio.gather(*search_tasks)

    return search_docs


########## SerpAPI (Google Search Engine) logic

import re
import os
import requests
try:
    from serpapi import GoogleSearch
except ImportError:
    import sys
    import subprocess
    # Attempt to fix the dependency conflict
    subprocess.check_call([sys.executable, "-m", "pip", "uninstall", "-y", "serpapi"])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "google-search-results"])
    if 'serpapi' in sys.modules:
        del sys.modules['serpapi']
    from serpapi import GoogleSearch
from dotenv import load_dotenv

# load_dotenv()
# SERPAPI_KEY = os.getenv("SERPAPI_KEY")


def fetch_image_url(query): 
    
    ### # fetch dynamically
    SERPAPI_KEY = os.getenv("SERPAPI_KEY")  
    if not SERPAPI_KEY:
        print("No SERPAPI_KEY found in environment")
        return None
    ####
    
    def is_supported_and_relevant(url):
        url = url.lower()
        if not url.endswith((".jpg", ".jpeg", ".png")):
            return False
        bad_keywords = ["logo", "cover", "poster", "book", "thumbnail", "coverpage"]
        return not any(bad in url for bad in bad_keywords)

    params = {
        "engine": "google",
        "q": query,
        "tbm": "isch",
        "api_key": SERPAPI_KEY
    }
    
    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        images = results.get("images_results", [])

        if images:
            # Only check top 1–2 results
            for img in images[:2]:
                url = img.get("original", "")
                if is_supported_and_relevant(url):
                    return url

        # If no relevant image in top 2, return None
        return None

    except Exception as e:
        print("Error fetching image:", e)
        return None

def replace_image_placeholders(report_path="report.md"):
    with open(report_path, "r", encoding="utf-8") as file:
        content = file.read()

    placeholders = re.findall(r"<<image:(.*?)>>", content)

    for query in placeholders:
        query = query.strip()
        image_url = fetch_image_url(query)
        if image_url:
            markdown_img = f"![{query}]({image_url})"
        else:
            markdown_img = f"*Image for '{query}' not found*"
        content = content.replace(f"<<image:{query}>>", markdown_img)

    with open(report_path, "w", encoding="utf-8") as file:
        file.write(content)
