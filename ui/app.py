from _shared import st

st.set_page_config(page_title="CV Matcher — Linkrs", page_icon="🇳🇱", layout="wide")

st.title("🇳🇱 CV Matcher")
st.subheader("Matching Moroccan candidates to Dutch-speaking roles")

st.markdown(
    """
    This system ingests candidate CVs, extracts structured profiles, collects
    Dutch-requirement job openings in Morocco, and ranks the best matches with
    explanations.

    **Use the sidebar to navigate.** Candidate CV upload will be added here.
    """
)

st.info("Pipeline: **Ingest → Extract → Store → Collect jobs → Match → Present**")