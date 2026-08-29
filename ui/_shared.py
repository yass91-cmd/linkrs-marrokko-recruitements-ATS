import sys
from pathlib import Path

# Streamlit runs scripts directly, so put the project root on the import path.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from db.database import get_connection


@st.cache_data(ttl=60)
def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    """Run a read query and return a DataFrame. Cached for 60s."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [d.name for d in cur.description]
            rows = cur.fetchall()
    return pd.DataFrame(rows, columns=columns)


def execute(sql: str, params: tuple = ()) -> None:
    """Run a write query."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    st.cache_data.clear()      # results changed — drop cached reads