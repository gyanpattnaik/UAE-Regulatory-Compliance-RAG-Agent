"""
components.py — Helper functions for rendering Streamlit UI elements cleanly.
"""

import streamlit as st
from typing import List

def render_metrics(answer_mode: str, confidence_score: float):
    """Render the Analysis Mode and Confidence Score in a clean layout."""
    # Format confidence as percentage
    conf_pct = confidence_score * 100
    
    # We use a clean markdown string instead of large metrics to match ChatGPT style
    if conf_pct >= 75:
        color = "green"
    elif conf_pct >= 40:
        color = "orange"
    else:
        color = "red"
        
    st.markdown(f"**Analysis Mode:** `{answer_mode}` | **Confidence:** <span style='color:{color}'>**{conf_pct:.1f}%**</span>", unsafe_allow_html=True)


def render_citations(citations: List):
    """Render citations cleanly inside interactive expanders."""
    if not citations:
        return
        
    for i, cit in enumerate(citations, 1):
        # Clean inline expander
        short_id = cit.chunk_id.split('_')[0] if '_' in cit.chunk_id else cit.chunk_id[:8]
        expander_label = f"[{short_id}] {cit.explanation[:60]}..." if len(cit.explanation) > 60 else f"[{short_id}] {cit.explanation}"
        
        with st.expander(expander_label):
            st.markdown(f"**Exact Quote:**\n> *{cit.exact_quote}*")
            st.markdown(f"**Explanation:**\n{cit.explanation}")
            st.caption(f"Source ID: `{cit.chunk_id}`")
