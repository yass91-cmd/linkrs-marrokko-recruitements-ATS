from _shared import st, query

st.set_page_config(page_title="Dashboard — CV Matcher", page_icon="📊", layout="wide")
st.title("📊 Dashboard")

# ---- headline metrics ----
stats = query("""
    SELECT
      (SELECT COUNT(*) FROM candidates)                                    AS candidates,
      (SELECT COUNT(*) FROM jobs WHERE status = 'active')                  AS active_jobs,
      (SELECT COUNT(*) FROM matches)                                       AS matches,
      (SELECT COUNT(*) FROM jobs WHERE status = 'active' AND hr_verified = false) AS pending_hr;
""").iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("👤 Candidates", int(stats["candidates"]))
c2.metric("💼 Active jobs", int(stats["active_jobs"]))
c3.metric("🔗 Matches", int(stats["matches"]))
c4.metric("📞 Awaiting HR call", int(stats["pending_hr"]))

st.divider()

left, right = st.columns(2)

# ---- recruitment funnel ----
with left:
    st.subheader("Recruitment pipeline")
    order = ["suggested", "presented", "approved", "applied", "hired", "declined", "rejected"]
    funnel = query("SELECT status, COUNT(*) AS n FROM matches GROUP BY status;")
    counts = dict(zip(funnel["status"], funnel["n"])) if not funnel.empty else {}
    if counts:
        for stage in order:
            n = int(counts.get(stage, 0))
            if n or stage in ("suggested", "presented", "approved"):
                st.write(f"**{stage.capitalize()}** — {n}")
                st.progress(min(n / max(counts.values()), 1.0))
    else:
        st.caption("No matches yet. Run the matcher on a candidate.")

# ---- eligibility split ----
with right:
    st.subheader("Eligibility")
    elig = query("""
        SELECT CASE WHEN eligible THEN 'Eligible' ELSE 'Blocked' END AS state,
               COUNT(*) AS n
        FROM matches GROUP BY 1;
    """)
    if not elig.empty:
        st.bar_chart(elig.set_index("state")["n"], color="#E8590C")
        st.caption("Blocked = fails a hard requirement (e.g. Dutch not listed)")
    else:
        st.caption("No matches yet.")

st.divider()

# ---- best matches ----
st.subheader("Top matches")
top = query("""
    SELECT c.name AS candidate, j.title AS job, j.employer, j.city,
           m.llm_score, m.verdict, m.eligible, m.status
    FROM matches m
    JOIN candidates c ON c.id = m.candidate_id
    JOIN jobs j       ON j.job_uid = m.job_uid
    WHERE m.eligible = true
    ORDER BY m.llm_score DESC NULLS LAST
    LIMIT 10;
""")
if top.empty:
    st.caption("No eligible matches yet.")
else:
    st.dataframe(top, use_container_width=True, hide_index=True)

# ---- jobs by city ----
st.subheader("Active jobs by city")
cities = query("""
    SELECT COALESCE(city, 'Non précisé') AS city, COUNT(*) AS n
    FROM jobs WHERE status = 'active'
    GROUP BY 1 ORDER BY n DESC;
""")
if not cities.empty:
    st.bar_chart(cities.set_index("city")["n"], color="#3E5A6E")