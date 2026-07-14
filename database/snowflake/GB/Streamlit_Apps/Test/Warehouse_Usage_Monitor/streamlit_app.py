import streamlit as st
import pandas as pd
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Warehouse Usage Monitor", layout="wide", page_icon="📊")

session = get_active_session()

st.title("📊 Warehouse Usage Monitor")
st.caption("Live view of warehouse credit consumption and recent query activity from ACCOUNT_USAGE.")


# ---------- Data access ----------

@st.cache_data(ttl=600, show_spinner=False)
def get_warehouse_credit_usage(days: int) -> pd.DataFrame:
    query = f"""
        SELECT
            WAREHOUSE_NAME,
            DATE_TRUNC('day', START_TIME) AS USAGE_DATE,
            SUM(CREDITS_USED) AS CREDITS_USED
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
        WHERE START_TIME >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        GROUP BY WAREHOUSE_NAME, USAGE_DATE
        ORDER BY USAGE_DATE DESC, CREDITS_USED DESC
    """
    return session.sql(query).to_pandas()


@st.cache_data(ttl=300, show_spinner=False)
def get_running_queries() -> pd.DataFrame:
    query = """
        SELECT
            QUERY_ID,
            WAREHOUSE_NAME,
            USER_NAME,
            QUERY_TEXT,
            EXECUTION_STATUS,
            START_TIME
        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY())
        WHERE EXECUTION_STATUS = 'RUNNING'
        ORDER BY START_TIME
    """
    return session.sql(query).to_pandas()


@st.cache_data(ttl=300, show_spinner=False)
def get_longest_recent_queries(hours: int, limit: int) -> pd.DataFrame:
    query = f"""
        SELECT
            QUERY_ID,
            WAREHOUSE_NAME,
            USER_NAME,
            QUERY_TEXT,
            TOTAL_ELAPSED_TIME / 1000 AS ELAPSED_SECONDS,
            START_TIME,
            EXECUTION_STATUS
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
          AND EXECUTION_STATUS = 'SUCCESS'
        ORDER BY ELAPSED_SECONDS DESC
        LIMIT {limit}
    """
    return session.sql(query).to_pandas()


# ---------- UI ----------

with st.sidebar:
    st.header("Filters")
    lookback_days = st.slider("Credit usage lookback (days)", 1, 30, 7)
    query_lookback_hours = st.slider("Slow query lookback (hours)", 1, 72, 24)
    top_n_queries = st.slider("Number of slow queries to show", 5, 50, 15)
    if st.button("Refresh data", use_container_width=True):
        get_warehouse_credit_usage.clear()
        get_running_queries.clear()
        get_longest_recent_queries.clear()
        st.rerun()

tab_credits, tab_running, tab_slow = st.tabs(
    ["Credit Usage", "Currently Running Queries", "Slowest Recent Queries"]
)

with tab_credits:
    try:
        usage_df = get_warehouse_credit_usage(lookback_days)
        if usage_df.empty:
            st.info("No warehouse usage recorded in this window.")
        else:
            total_credits = usage_df["CREDITS_USED"].sum()
            st.metric(f"Total credits used (last {lookback_days} days)", f"{total_credits:,.1f}")

            pivot = usage_df.pivot_table(
                index="USAGE_DATE", columns="WAREHOUSE_NAME", values="CREDITS_USED", fill_value=0
            )
            st.bar_chart(pivot)

            st.subheader("By warehouse")
            by_wh = (
                usage_df.groupby("WAREHOUSE_NAME")["CREDITS_USED"]
                .sum()
                .sort_values(ascending=False)
                .reset_index()
            )
            st.dataframe(by_wh, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Could not load credit usage: {e}")

with tab_running:
    try:
        running_df = get_running_queries()
        if running_df.empty:
            st.success("No queries currently running.")
        else:
            st.warning(f"{len(running_df)} quer{'y is' if len(running_df) == 1 else 'ies are'} currently running.")
            st.dataframe(running_df, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Could not load running queries: {e}")

with tab_slow:
    try:
        slow_df = get_longest_recent_queries(query_lookback_hours, top_n_queries)
        if slow_df.empty:
            st.info("No completed queries in this window.")
        else:
            st.dataframe(
                slow_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "ELAPSED_SECONDS": st.column_config.NumberColumn("Elapsed (s)", format="%.1f"),
                },
            )
            st.download_button(
                "Export to CSV",
                slow_df.to_csv(index=False),
                file_name="slowest_queries.csv",
                mime="text/csv",
            )
    except Exception as e:
        st.error(f"Could not load query history: {e}")
