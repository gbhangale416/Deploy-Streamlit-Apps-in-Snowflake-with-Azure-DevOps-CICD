import streamlit as st
import pandas as pd
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Query Monitoring", layout="wide", page_icon="📈")

session = get_active_session()

st.title("📈 Query Monitoring")
st.caption("Live and recent query activity across warehouses, with the ability to cancel a running query.")


# ---------- Data access ----------

@st.cache_data(ttl=30, show_spinner=False)
def get_running_queries() -> pd.DataFrame:
    query = """
        SELECT
            QUERY_ID,
            WAREHOUSE_NAME,
            USER_NAME,
            QUERY_TEXT,
            EXECUTION_STATUS,
            START_TIME,
            DATEDIFF('second', START_TIME, CURRENT_TIMESTAMP()) AS RUNNING_SECONDS
        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY())
        WHERE EXECUTION_STATUS = 'RUNNING'
        ORDER BY START_TIME
    """
    return session.sql(query).to_pandas()


@st.cache_data(ttl=120, show_spinner=False)
def get_recent_queries(hours: int, status_filter: str, limit: int) -> pd.DataFrame:
    status_clause = "" if status_filter == "All" else f"AND EXECUTION_STATUS = '{status_filter.upper()}'"
    query = f"""
        SELECT
            QUERY_ID,
            WAREHOUSE_NAME,
            USER_NAME,
            QUERY_TEXT,
            EXECUTION_STATUS,
            TOTAL_ELAPSED_TIME / 1000 AS ELAPSED_SECONDS,
            START_TIME,
            BYTES_SCANNED,
            ROWS_PRODUCED
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
        {status_clause}
        ORDER BY ELAPSED_SECONDS DESC
        LIMIT {limit}
    """
    return session.sql(query).to_pandas()


@st.cache_data(ttl=300, show_spinner=False)
def get_activity_by_warehouse(hours: int) -> pd.DataFrame:
    query = f"""
        SELECT
            WAREHOUSE_NAME,
            COUNT(*) AS QUERY_COUNT,
            AVG(TOTAL_ELAPSED_TIME) / 1000 AS AVG_ELAPSED_SECONDS
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
        GROUP BY WAREHOUSE_NAME
        ORDER BY QUERY_COUNT DESC
    """
    return session.sql(query).to_pandas()


def cancel_query(query_id: str):
    session.sql("SELECT SYSTEM$CANCEL_QUERY(?)", params=[query_id]).collect()


# ---------- UI ----------

with st.sidebar:
    st.header("Filters")
    hours_back = st.slider("Recent queries lookback (hours)", 1, 72, 24)
    status_filter = st.selectbox("Status filter (recent queries)", ["All", "Success", "Failed"])
    result_limit = st.slider("Max rows (recent queries)", 10, 200, 50)
    auto_note = st.caption("Running-query data refreshes every ~30s on interaction.")
    if st.button("Refresh now", use_container_width=True):
        get_running_queries.clear()
        get_recent_queries.clear()
        get_activity_by_warehouse.clear()
        st.rerun()

tab_running, tab_recent, tab_by_wh = st.tabs(
    ["Currently Running", "Recent Query History", "Activity by Warehouse"]
)

with tab_running:
    try:
        running_df = get_running_queries()
    except Exception as e:
        st.error(f"Could not load running queries: {e}")
        running_df = pd.DataFrame()

    if running_df.empty:
        st.success("No queries currently running.")
    else:
        st.warning(f"{len(running_df)} quer{'y is' if len(running_df) == 1 else 'ies are'} currently running.")
        st.dataframe(running_df, use_container_width=True, hide_index=True)

        st.subheader("Cancel a running query")
        st.caption("Requires sufficient privileges on the target query's session/warehouse.")
        query_to_cancel = st.selectbox(
            "Select QUERY_ID to cancel", options=running_df["QUERY_ID"].tolist()
        )
        if st.button("Cancel selected query", type="primary"):
            try:
                cancel_query(query_to_cancel)
                st.success(f"Cancel request sent for {query_to_cancel}.")
                get_running_queries.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Could not cancel query: {e}")

with tab_recent:
    try:
        recent_df = get_recent_queries(hours_back, status_filter, result_limit)
        if recent_df.empty:
            st.info("No queries found for this window/filter.")
        else:
            st.dataframe(
                recent_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ELAPSED_SECONDS": st.column_config.NumberColumn("Elapsed (s)", format="%.1f"),
                },
            )
            st.download_button(
                "Export to CSV",
                recent_df.to_csv(index=False),
                file_name="recent_queries.csv",
                mime="text/csv",
            )
    except Exception as e:
        st.error(f"Could not load recent query history: {e}")

with tab_by_wh:
    try:
        by_wh_df = get_activity_by_warehouse(hours_back)
        if by_wh_df.empty:
            st.info("No warehouse activity in this window.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Query count by warehouse")
                st.bar_chart(by_wh_df.set_index("WAREHOUSE_NAME")["QUERY_COUNT"])
            with col2:
                st.subheader("Avg elapsed time (s) by warehouse")
                st.bar_chart(by_wh_df.set_index("WAREHOUSE_NAME")["AVG_ELAPSED_SECONDS"])
            st.dataframe(by_wh_df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Could not load warehouse activity: {e}")
