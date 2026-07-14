import streamlit as st
import pandas as pd
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Login Info", layout="wide", page_icon="🔐")

session = get_active_session()

st.title("🔐 Login Info")
st.caption("Authentication activity from ACCOUNT_USAGE.LOGIN_HISTORY - successes, failures, and MFA usage.")


# ---------- Data access ----------

@st.cache_data(ttl=300, show_spinner=False)
def get_login_history(days: int) -> pd.DataFrame:
    query = f"""
        SELECT
            EVENT_TIMESTAMP,
            USER_NAME,
            CLIENT_IP,
            REPORTED_CLIENT_TYPE,
            IS_SUCCESS,
            ERROR_CODE,
            ERROR_MESSAGE,
            FIRST_AUTHENTICATION_FACTOR,
            SECOND_AUTHENTICATION_FACTOR
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY
        WHERE EVENT_TIMESTAMP >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        ORDER BY EVENT_TIMESTAMP DESC
    """
    return session.sql(query).to_pandas()


# ---------- UI ----------

with st.sidebar:
    st.header("Filters")
    lookback_days = st.slider("Lookback window (days)", 1, 90, 7)
    if st.button("Refresh data", use_container_width=True):
        get_login_history.clear()
        st.rerun()

try:
    df = get_login_history(lookback_days)
except Exception as e:
    st.error(f"Could not load login history: {e}")
    st.stop()

if df.empty:
    st.info("No login events found in this window.")
    st.stop()

df["IS_SUCCESS"] = df["IS_SUCCESS"].astype(str).str.upper() == "YES"

user_filter = st.sidebar.multiselect("Filter by user", sorted(df["USER_NAME"].dropna().unique().tolist()))
status_filter = st.sidebar.radio("Status", ["All", "Successful only", "Failed only"])

filtered = df.copy()
if user_filter:
    filtered = filtered[filtered["USER_NAME"].isin(user_filter)]
if status_filter == "Successful only":
    filtered = filtered[filtered["IS_SUCCESS"]]
elif status_filter == "Failed only":
    filtered = filtered[~filtered["IS_SUCCESS"]]

# ---------- Summary metrics ----------
total_logins = len(filtered)
failed_logins = int((~filtered["IS_SUCCESS"]).sum())
unique_users = filtered["USER_NAME"].nunique()
mfa_logins = int(filtered["SECOND_AUTHENTICATION_FACTOR"].notna().sum())
mfa_rate = (mfa_logins / total_logins * 100) if total_logins else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total login attempts", f"{total_logins:,}")
col2.metric("Failed attempts", f"{failed_logins:,}")
col3.metric("Unique users", f"{unique_users:,}")
col4.metric("MFA usage", f"{mfa_rate:.0f}%")

tab_activity, tab_failed, tab_trend = st.tabs(["All Activity", "Failed Logins", "Trend"])

with tab_activity:
    st.dataframe(
        filtered[
            ["EVENT_TIMESTAMP", "USER_NAME", "CLIENT_IP", "REPORTED_CLIENT_TYPE",
             "IS_SUCCESS", "FIRST_AUTHENTICATION_FACTOR", "SECOND_AUTHENTICATION_FACTOR"]
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Export to CSV",
        filtered.to_csv(index=False),
        file_name="login_history.csv",
        mime="text/csv",
    )

with tab_failed:
    failed_df = filtered[~filtered["IS_SUCCESS"]]
    if failed_df.empty:
        st.success("No failed login attempts in this window.")
    else:
        st.warning(f"{len(failed_df)} failed login attempt(s) found.")
        top_offenders = (
            failed_df.groupby("USER_NAME")
            .size()
            .sort_values(ascending=False)
            .reset_index(name="FAILED_ATTEMPTS")
        )
        st.subheader("Users with the most failed attempts")
        st.dataframe(top_offenders.head(20), use_container_width=True, hide_index=True)

        st.subheader("Failed attempt details")
        st.dataframe(
            failed_df[["EVENT_TIMESTAMP", "USER_NAME", "CLIENT_IP", "ERROR_CODE", "ERROR_MESSAGE"]],
            use_container_width=True,
            hide_index=True,
        )

with tab_trend:
    trend = (
        filtered.assign(DAY=filtered["EVENT_TIMESTAMP"].dt.date)
        .groupby(["DAY", "IS_SUCCESS"])
        .size()
        .reset_index(name="COUNT")
    )
    if trend.empty:
        st.info("No data to chart for this window.")
    else:
        pivot = trend.pivot(index="DAY", columns="IS_SUCCESS", values="COUNT").fillna(0)
        pivot.columns = ["Failed" if c is False else "Successful" for c in pivot.columns]
        st.bar_chart(pivot)
