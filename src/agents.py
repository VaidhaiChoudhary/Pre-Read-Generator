# Description: This file contains the implementation of the agents that will be used in the pipeline.
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from typing import List
from langchain_core.messages import HumanMessage, SystemMessage
from prompts import query_template, report_prompt
from state import AgentState, Queries
import os, re
from dotenv import load_dotenv
from tavily import TavilyClient, AsyncTavilyClient
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from md2docx_python.src.md2docx_python import markdown_to_word
import streamlit as st
import asyncio
from langchain_openai import ChatOpenAI
import shutil  
import pypandoc
# pypandoc.download_pandoc()

# # Only download pandoc if it's not already installed
# if not shutil.which("pandoc"):
#     pypandoc.download_pandoc()

# Force-set pandoc download location inside the project
pandoc_dir = os.path.join(os.getcwd(), "pandoc-bin")
if not shutil.which("pandoc"):
    pypandoc.download_pandoc(targetfolder=pandoc_dir)
    os.environ["PATH"] = pandoc_dir + os.pathsep + os.environ["PATH"]
    
#from utils import replace_image_placeholders
from src.utils import replace_image_placeholders

# Query geneartive agent with curriculum
def generate_queries(topic: str, curriculum: str = "") -> dict:
    # Format system instructions
    system_instruction_query = query_template.format(topic=topic, curriculum=curriculum)
    # Generate queries
    structured_llm = llm.with_structured_output(Queries)
    result = structured_llm.invoke(
        [SystemMessage(content=system_instruction_query)] +
        [HumanMessage(content="Generate search queries that will help with planning the sections of the report.")]
    )
    return {'query': [i.search_query for i in result.queries]}


# Web Search Agent
async def perform_search(state: AgentState):
    results = []
    tasks = []
    
    for query in state['query']:
        tasks.append(tavily_async_client.search(query, max_results=2))  # Collect tasks

    search_results_list = await asyncio.gather(*tasks)  # Execute all tasks concurrently

    for query, search_results in zip(state['query'], search_results_list):
        results.append({
            "query": query,
            "results": [{
                "title": res["title"],
                "url": res["url"],
                "content": res["content"][:1000]  # Truncate for demo
            } for res in search_results['results']]
        })
    return {"search_results": results}

#Report generating agent with image replacement with serpapi placeholder logic
def report_generation(state: AgentState) -> dict:
    search_results = state['search_results']
    curriculum = state.get('curriculum', '') ###
    
    formatted_results = "\n".join(
        [f"**{result['query']}**\n" + "\n".join(
            [f"- [{res['title']}]({res['url']}): {res['content']}" for res in result['results']]
        ) for result in search_results]
    )
    
    system_instruction = f"{report_prompt}\n\nCurriculum guidelines:\n{curriculum}\n\n{formatted_results}" 
    
    result = llm.invoke(
        [SystemMessage(content=system_instruction)] +
        [HumanMessage(content="Write a concise report using the above information. Include image suggestions as <<image:...>> placeholders.")]
    )
    
    report_text = result.content

    # Save report with placeholders first
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report_text)

    # Replace placeholders with actual image markdowns in-place
    replace_image_placeholders("report.md")

    # Read final result
    with open("report.md", "r", encoding="utf-8") as f:
        report_with_images = f.read()

    return {"report": report_with_images}

# Build LangGraph workflow
workflow = StateGraph(AgentState)
workflow.add_node("generate_queries", generate_queries)
workflow.add_node("perform_search", perform_search)
workflow.add_node("report_generation", report_generation)


workflow.set_entry_point("generate_queries")
workflow.add_edge("generate_queries", "perform_search")
workflow.add_edge("perform_search", "report_generation")
workflow.add_edge("report_generation",END)

workflow_graph = workflow.compile()

#############################################################################################################
# streamlit application

# Set the title of the app
st.title("Pre-Read Generator")

# Custom HTML and CSS for the About section in a square box

with st.sidebar.container():
    st.markdown("""
    <div style="padding: 10px; border: 2px solid #ccc; border-radius: 10px; background-color: #000000; color: #ffffff;">
        <h4>About</h4>
        <p>The Pre-Read Report Generator Agent is a state-of-the-art AI-powered application designed to simplify and enhance 
        the process of generating comprehensive technical reports. Built on Streamlit, this intelligent tool leverages advanced
        AI models and APIs to structure detailed, high-quality reports effortlessly.</p>
    </div>
    """, unsafe_allow_html=True)


### runapp with SerpAPI and curriculum
async def run_app(topic, curriculum):
    st.write(f"Processing topic: {topic}")
    result = await workflow_graph.ainvoke({
    "topic": topic,
    "curriculum": curriculum})

    # Clean final report (already has images)
    final_report = re.sub(r'<think>.*?</think>\n\n', '', result['report'], flags=re.DOTALL)

    # Show on Streamlit
    st.markdown(final_report)

    # Save markdown 
    with open('report.md', 'w', encoding='utf-8') as f:
        f.write(final_report)

    # Convert to docx
    pypandoc.convert_file('report.md', 'docx', outputfile="output.docx")
    st.success("Report generated successfully. Check the markdown and docx files for the report.")

    # Download button
    with open("output.docx", "rb") as file:
        report_data = file.read()

    st.download_button(
        label="Download Report",
        data=report_data,
        file_name="output.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

# Sidebar with API key input fields and a brief description
st.sidebar.title("API Keys Configuration")
# Sidebar for API key inputs
api_key_serpapi = st.sidebar.text_input("SerpAPI API Key", type="password")
api_key_1 = st.sidebar.text_input("Tavily API Key 1", type="password")
api_key_2 = st.sidebar.text_input("Groq API Key 2", type="password")
api_key_3 = st.sidebar.text_input("OpenAI API Key 3", type="password")

# Model Selection
model_option = st.sidebar.selectbox(
    "Select Model",
    #("ChatGroq LLaMA-70B", "OpenAI GPT-4o","gpt-4o-mini-2024-07-18", "gpt-4", "gpt-3.5-turbo")
    ("Llama 3.3 70B", "OpenAI GPT-4o","gpt-4o-mini-2024-07-18", "gpt-4", "gpt-3.5-turbo")
)

# Main screen input field for topic and curriculum
topic = st.text_input("Enter the topic")
curriculum = st.text_area("Enter the curriculum", height=100)

# Submit button to run the app
if st.button("Submit"):

    # Validate and set API keys only after clicking submit
    os.environ["SERPAPI_KEY"] = api_key_serpapi
    os.environ["TAVILY_API_KEY"] = api_key_1
    os.environ["GROQ_API_KEY"] = api_key_2
    os.environ["OPENAI_API_KEY"] = api_key_3

    # Ensure required keys are present before proceeding
    if (not api_key_1 and not api_key_2) or (not api_key_1 and not api_key_3):
        st.error("🚨 Please enter required API keys before proceeding!")
    else:
        # Initialize API clients after successful validation
        try:
            tavily_client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))
            tavily_async_client = AsyncTavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))

            # if model_option == "ChatGroq LLaMA-70B":
            #     llm = ChatGroq(model="deepseek-r1-distill-llama-70b", verbose=False)
            if model_option == "Llama 3.3 70B":
                llm = ChatGroq(model="llama-3.3-70b-versatile", verbose=False)
            else:
                llm = ChatOpenAI(
                    model="gpt-4o",
                    temperature=0,
                    max_tokens=None,
                    timeout=None,
                    max_retries=2,
                )

            # Run the app logic
            # asyncio.run(run_app(topic))
            asyncio.run(run_app(topic, curriculum))

        except Exception as e:
            st.error(f"❌ Error initializing API clients: {e}")

