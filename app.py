"""
app.py — Main Streamlit application entry point for the RAG Agent.
"""

import streamlit as st
import logging
import json
import os
import uuid

from src.retrieval.hybrid_search import HybridRetriever
from src.generation.generator import Generator
from src.generation.citation_verifier import verify_citations
from src.ui.components import render_metrics, render_citations
from src.generation.formatter import DISCLAIMER

# Setup basic logging
logging.basicConfig(level=logging.WARNING)

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="UAE Regulatory AI",
    page_icon="🇦🇪",
    layout="centered",
    initial_sidebar_state="expanded"
)

# Hide Streamlit default Deploy button, hamburger menu, and header
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    .stDeployButton {display:none;}
    header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# Top left logo (Streamlit 1.35+)
st.logo("assets/logo.png")

# --- INITIALIZE BACKEND ---
# We use st.cache_resource to avoid reloading heavy models on every UI interaction
@st.cache_resource
def get_retriever():
    return HybridRetriever()

@st.cache_resource
def get_generator():
    return Generator()

retriever = get_retriever()
generator = get_generator()

# --- SESSION MANAGEMENT ---
HISTORY_FILE = "chat_history.json"

def load_all_sessions():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_all_sessions(sessions):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2)

def create_new_session_messages():
    return [
        {
            "role": "assistant",
            "content": "Welcome to the UAE Regulatory Compliance AI. Ask me any question regarding CBUAE or VARA regulations.",
            "metrics": None,
            "citations": None
        }
    ]

# Initialize state
if "all_sessions" not in st.session_state:
    st.session_state.all_sessions = load_all_sessions()

if "current_session_id" not in st.session_state:
    if st.session_state.all_sessions:
        # Load most recent session
        st.session_state.current_session_id = list(st.session_state.all_sessions.keys())[-1]
    else:
        # Create first session
        new_id = str(uuid.uuid4())
        st.session_state.current_session_id = new_id
        st.session_state.all_sessions[new_id] = {
            "title": "New Chat",
            "messages": create_new_session_messages()
        }
        save_all_sessions(st.session_state.all_sessions)

current_messages = st.session_state.all_sessions[st.session_state.current_session_id]["messages"]

def save_current_messages(msgs):
    # Determine title based on first user message if title is still "New Chat"
    title = st.session_state.all_sessions[st.session_state.current_session_id].get("title", "New Chat")
    if title == "New Chat":
        for m in msgs:
            if m["role"] == "user":
                title = m["content"][:25] + "..." if len(m["content"]) > 25 else m["content"]
                break
    
    st.session_state.all_sessions[st.session_state.current_session_id] = {
        "title": title,
        "messages": msgs
    }
    save_all_sessions(st.session_state.all_sessions)

# --- SIDEBAR CONFIGURATION ---
with st.sidebar:
    st.title("💬 Chat History")
    
    if st.button("➕ New Chat", use_container_width=True, type="primary"):
        new_id = str(uuid.uuid4())
        st.session_state.current_session_id = new_id
        st.session_state.all_sessions[new_id] = {
            "title": "New Chat",
            "messages": create_new_session_messages()
        }
        save_all_sessions(st.session_state.all_sessions)
        st.rerun()
    
    # Render past sessions
    st.markdown("<br>", unsafe_allow_html=True)
    if not st.session_state.all_sessions:
        st.caption("No history yet.")
    else:
        # Show most recent first
        for sess_id, sess_data in reversed(list(st.session_state.all_sessions.items())):
            col1, col2 = st.columns([0.85, 0.15])
            btn_type = "primary" if sess_id == st.session_state.current_session_id else "secondary"
            with col1:
                if st.button(sess_data["title"], key=f"hist_{sess_id}", use_container_width=True, type=btn_type):
                    st.session_state.current_session_id = sess_id
                    st.rerun()
            with col2:
                if st.button("🗑️", key=f"del_{sess_id}", help="Delete chat"):
                    del st.session_state.all_sessions[sess_id]
                    save_all_sessions(st.session_state.all_sessions)
                    
                    # Reset if we deleted the currently active session
                    if sess_id == st.session_state.current_session_id:
                        if "current_session_id" in st.session_state:
                            del st.session_state["current_session_id"]
                    st.rerun()
        
    st.divider()
    
    st.title("⚙️ Configuration")
    
    # Filtering Options
    st.subheader("Retrieval Filters")
    regulator_choice = st.selectbox(
        "Select Regulator",
        options=["All", "CBUAE", "VARA"],
        index=0
    )
    filter_dict = None if regulator_choice == "All" else {"regulator": regulator_choice}
    
    top_k = st.slider("Context Chunks (k)", min_value=1, max_value=15, value=5)
    
    st.divider()
    
    # Architecture Info for Portfolio
    st.subheader("System Architecture")
    st.markdown("""
    - **Vector Store**: ChromaDB
    - **Embedding**: `all-MiniLM-L6-v2`
    - **Lexical**: `rank-bm25` (Pickle DB)
    - **Reranker**: `ms-marco-MiniLM-L-6-v2`
    - **LLM**: Groq `llama-3.3-70b-versatile`
    """)

# --- MAIN UI LAYOUT ---
# Remove bulky title for a clean ChatGPT-like experience

# Render existing chat history
for msg in current_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        # If this is an assistant message with metadata, render it
        if msg.get("metrics"):
            render_metrics(msg["metrics"]["mode"], msg["metrics"]["score"])
        if msg.get("citations"):
            # Citations are saved as dicts in JSON, so we pass them directly
            from src.generation.schemas import Citation
            citations_objs = [Citation(**c) for c in msg["citations"]] if msg["citations"] else None
            render_citations(citations_objs)
            st.caption(DISCLAIMER)

# --- CHAT INPUT HANDLING ---
if prompt := st.chat_input("Ask a compliance question (e.g., 'What are the rules for virtual assets?')..."):
    # Display user input immediately
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Save user input to history
    current_messages.append({"role": "user", "content": prompt})
    save_current_messages(current_messages)
    
    # Process the query
    with st.chat_message("assistant"):
        try:
            with st.spinner(f"Retrieving {top_k} chunks from {regulator_choice if regulator_choice != 'All' else 'All Regulators'}..."):
                retrieved_chunks = retriever.retrieve(query=prompt, top_k=top_k, filter_dict=filter_dict)
            
            if not retrieved_chunks:
                st.warning("No relevant documents found for this query.")
                answer_text = "I could not find relevant regulatory text to answer this question."
                st.markdown(answer_text)
                st.caption(DISCLAIMER)
                current_messages.append({
                    "role": "assistant",
                    "content": answer_text,
                    "metrics": None,
                    "citations": None
                })
                save_current_messages(current_messages)
            else:
                with st.spinner("Analyzing context and generating strict response via Groq..."):
                    answer = generator.generate_answer(prompt, retrieved_chunks)
                
                # Extract server-side retrieval confidence from the retrieval pipeline
                retrieval_conf = retrieved_chunks[0].get("_retrieval_confidence", 0.0) if retrieved_chunks else 0.0

                # Post-generation citation verification + composite confidence
                answer = verify_citations(answer, retrieved_chunks, retrieval_confidence=retrieval_conf)
                
                # Render results — use composite confidence (not LLM self-report)
                st.markdown(answer.final_text)
                render_metrics(answer.answer_mode, answer.composite_confidence)
                render_citations(answer.citations)
                st.caption(DISCLAIMER)
                
                # Save assistant response to history
                current_messages.append({
                    "role": "assistant",
                    "content": answer.final_text,
                    "metrics": {"mode": answer.answer_mode, "score": answer.composite_confidence},
                    "citations": [cit.model_dump() for cit in answer.citations] if answer.citations else None
                })
                save_current_messages(current_messages)
                
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
