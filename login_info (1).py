import streamlit as st
import pandas as pd
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Login Info", layout="wide")

session = get_active_session()

st.title("Login Info")
st.caption(
    "Authentication activity from ACCOUNT_USAGE.LOGIN_HISTORY - "
    "successes, failures, and MFA usage."
)


# ---------- Data access ----------

@st.cache_data(ttl=300, show_spinner=False)
def get_login_history(days: int) -> pd.DataFrame:
    # USER_TYPE comes from ACCOUNT_USAGE.USERS (NULL type = regular PERSON user).
    # Users no longer in the USERS view are labelled DELETED/UNKNOWN.
    query = f"""
        SELECT
            l.EVENT_TIMESTAMP,
            l.USER_NAME,
            CASE
                WHEN u.NAME IS NULL THEN 'DELETED/UNKNOWN'
                ELSE COALESCE(u.TYPE, 'PERSON')
            END AS USER_TYPE,
            l.CLIENT_IP,
            l.REPORTED_CLIENT_TYPE,
            l.IS_SUCCESS,
            l.ERROR_CODE,
            l.ERROR_MESSAGE,
            l.FIRST_AUTHENTICATION_FACTOR,
            l.SECOND_AUTHENTICATION_FACTOR
        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY l
        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS u
            ON l.USER_NAME = u.NAME
           AND u.DELETED_ON IS NULL
        WHERE l.EVENT_TIMESTAMP >= DATEADD('day', -{days}, CURRENT_TIMESTAMP())
        ORDER BY l.EVENT_TIMESTAMP DESC
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

# Normalise columns
df["IS_SUCCESS"] = df["IS_SUCCESS"].astype(str).str.upper() == "YES"
df["FIRST_AUTHENTICATION_FACTOR"] = df["FIRST_AUTHENTICATION_FACTOR"].fillna("UNKNOWN")
df["USER_TYPE"] = df["USER_TYPE"].fillna("UNKNOWN")

# Sidebar filters
user_filter = st.sidebar.multiselect(
    "Filter by user",
    sorted(df["USER_NAME"].dropna().unique().tolist()),
)
user_type_filter = st.sidebar.multiselect(
    "User account type",
    sorted(df["USER_TYPE"].unique().tolist()),
    help="PERSON = human users, SERVICE / LEGACY_SERVICE = service accounts",
)
auth_type_filter = st.sidebar.multiselect(
    "Authentication type",
    sorted(df["FIRST_AUTHENTICATION_FACTOR"].unique().tolist()),
    help="First authentication factor (password, SAML, OAuth, key pair, etc.)",
)
mfa_filter = st.sidebar.radio("MFA", ["All", "MFA used", "No MFA"])
status_filter = st.sidebar.radio("Status", ["All", "Successful only", "Failed only"])

# Apply filters
filtered = df.copy()
if user_filter:
    filtered = filtered[filtered["USER_NAME"].isin(user_filter)]
if user_type_filter:
    filtered = filtered[filtered["USER_TYPE"].isin(user_type_filter)]
if auth_type_filter:
    filtered = filtered[filtered["FIRST_AUTHENTICATION_FACTOR"].isin(auth_type_filter)]
if mfa_filter == "MFA used":
    filtered = filtered[filtered["SECOND_AUTHENTICATION_FACTOR"].notna()]
elif mfa_filter == "No MFA":
    filtered = filtered[filtered["SECOND_AUTHENTICATION_FACTOR"].isna()]
if status_filter == "Successful only":
    filtered = filtered[filtered["IS_SUCCESS"]]
elif status_filter == "Failed only":
    filtered = filtered[~filtered["IS_SUCCESS"]]

if filtered.empty:
    st.info("No login events match the selected filters.")
    st.stop()


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

tab_activity, tab_failed, tab_breakdown, tab_trend = st.tabs(
    ["All Activity", "Failed Logins", "Breakdown", "Trend"]
)

# ---------- All activity ----------

with tab_activity:
    st.dataframe(
        filtered[
            [
                "EVENT_TIMESTAMP", "USER_NAME", "USER_TYPE", "CLIENT_IP",
                "REPORTED_CLIENT_TYPE", "IS_SUCCESS",
                "FIRST_AUTHENTICATION_FACTOR", "SECOND_AUTHENTICATION_FACTOR",
            ]
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

# ---------- Failed logins ----------

with tab_failed:
    failed_df = filtered[~filtered["IS_SUCCESS"]]
    if failed_df.empty:
        st.success("No failed login attempts in this window.")
    else:
        st.warning(f"{len(failed_df)} failed login attempt(s) found.")

        top_offenders = (
            failed_df.groupby(["USER_NAME", "USER_TYPE"])
            .size()
            .sort_values(ascending=False)
            .reset_index(name="FAILED_ATTEMPTS")
        )
        st.subheader("Users with the most failed attempts")
        st.dataframe(top_offenders.head(20), use_container_width=True, hide_index=True)

        st.subheader("Failed attempt details")
        st.dataframe(
            failed_df[
                [
                    "EVENT_TIMESTAMP", "USER_NAME", "USER_TYPE",
                    "FIRST_AUTHENTICATION_FACTOR", "CLIENT_IP",
                    "ERROR_CODE", "ERROR_MESSAGE",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

# ---------- Breakdown (new) ----------

with tab_breakdown:
    left, right = st.columns(2)

    with left:
        st.subheader("Logins by authentication type")
        by_auth = (
            filtered.assign(
                RESULT=filtered["IS_SUCCESS"].map({True: "Successful", False: "Failed"})
            )
            .groupby(["FIRST_AUTHENTICATION_FACTOR", "RESULT"])
            .size()
            .reset_index(name="COUNT")
            .pivot(index="FIRST_AUTHENTICATION_FACTOR", columns="RESULT", values="COUNT")
            .fillna(0)
        )
        st.bar_chart(by_auth)

    with right:
        st.subheader("Logins by user account type")
        by_type = (
            filtered.assign(
                RESULT=filtered["IS_SUCCESS"].map({True: "Successful", False: "Failed"})
            )
            .groupby(["USER_TYPE", "RESULT"])
            .size()
            .reset_index(name="COUNT")
            .pivot(index="USER_TYPE", columns="RESULT", values="COUNT")
            .fillna(0)
        )
        st.bar_chart(by_type)

    st.subheader("Authentication type x user account type")
    matrix = (
        filtered.groupby(["USER_TYPE", "FIRST_AUTHENTICATION_FACTOR"])
        .agg(
            ATTEMPTS=("USER_NAME", "size"),
            FAILED=("IS_SUCCESS", lambda s: int((~s).sum())),
            UNIQUE_USERS=("USER_NAME", "nunique"),
        )
        .reset_index()
        .sort_values("ATTEMPTS", ascending=False)
    )
    st.dataframe(matrix, use_container_width=True, hide_index=True)

# ---------- Trend ----------

with tab_trend:
    split_by = st.radio(
        "Split trend by",
        ["Status", "Authentication type", "User account type"],
        horizontal=True,
    )

    trend_df = filtered.assign(DAY=filtered["EVENT_TIMESTAMP"].dt.date)

    if split_by == "Status":
        trend_df = trend_df.assign(
            SERIES=trend_df["IS_SUCCESS"].map({True: "Successful", False: "Failed"})
        )
    elif split_by == "Authentication type":
        trend_df = trend_df.assign(SERIES=trend_df["FIRST_AUTHENTICATION_FACTOR"])
    else:
        trend_df = trend_df.assign(SERIES=trend_df["USER_TYPE"])

    trend = trend_df.groupby(["DAY", "SERIES"]).size().reset_index(name="COUNT")

    if trend.empty:
        st.info("No data to chart for this window.")
    else:
        pivot = trend.pivot(index="DAY", columns="SERIES", values="COUNT").fillna(0)
        st.bar_chart(pivot)
