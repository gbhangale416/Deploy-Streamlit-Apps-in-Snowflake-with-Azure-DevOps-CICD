
import streamlit as st
import pandas as pd
from snowflake.snowpark.context import get_active_session


# ==================================================
# PAGE CONFIGURATION
# ==================================================

st.set_page_config(
    page_title="Login Info",
    layout="wide"
)

session = get_active_session()

st.title("Login Info")

st.caption(
    "Authentication activity from Snowflake ACCOUNT_USAGE.LOGIN_HISTORY "
    "- successes, failures, and MFA usage."
)


# ==================================================
# DATA ACCESS
# ==================================================

@st.cache_data(ttl=300, show_spinner=False)
def get_login_history(days: int) -> pd.DataFrame:

    query = f"""
        SELECT
            LH.*,
            COALESCE(U.TYPE, 'UNKNOWN') AS USER_ACCOUNT_TYPE

        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY LH

        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS U
            ON LH.USER_NAME = U.NAME

        WHERE LH.EVENT_TIMESTAMP >=
            DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())

        ORDER BY LH.EVENT_TIMESTAMP DESC
    """

    return session.sql(query).to_pandas()


# ==================================================
# SIDEBAR - FILTERS
# ==================================================

with st.sidebar:

    st.header("Filters")

    lookback_days = st.slider(
        "Lookback window (days)",
        min_value=1,
        max_value=90,
        value=7
    )

    if st.button(
        "Refresh data",
        use_container_width=True
    ):

        get_login_history.clear()
        st.rerun()


# ==================================================
# LOAD DATA
# ==================================================

try:

    df = get_login_history(lookback_days)

except Exception as e:

    st.error(f"Could not load login history: {e}")
    st.stop()


if df.empty:

    st.info("No login events found in this window.")
    st.stop()


# ==================================================
# DATA PREPARATION
# ==================================================

# Normalize column names

df.columns = df.columns.str.upper()

# Convert login status to Boolean

df["IS_SUCCESS"] = (
    df["IS_SUCCESS"]
    .astype(str)
    .str.upper()
    .isin(["TRUE", "YES", "1"])
)

# Handle missing filter values

df["USER_NAME"] = (
    df["USER_NAME"]
    .fillna("UNKNOWN")
)

df["FIRST_AUTHENTICATION_FACTOR"] = (
    df["FIRST_AUTHENTICATION_FACTOR"]
    .fillna("UNKNOWN")
)

df["USER_ACCOUNT_TYPE"] = (
    df["USER_ACCOUNT_TYPE"]
    .fillna("UNKNOWN")
)


# ==================================================
# SIDEBAR - DYNAMIC FILTER OPTIONS
# ==================================================

# 1. USER FILTER

user_options = sorted(
    df["USER_NAME"].unique().tolist()
)

user_filter = st.sidebar.multiselect(
    "Filter by user",
    options=user_options,
    default=[]
)


# 2. AUTHENTICATION TYPE FILTER

auth_options = sorted(
    df["FIRST_AUTHENTICATION_FACTOR"].unique().tolist()
)

auth_filter = st.sidebar.multiselect(
    "Authentication Type",
    options=auth_options,
    default=[]
)


# 3. USER ACCOUNT TYPE FILTER

account_type_options = sorted(
    df["USER_ACCOUNT_TYPE"].unique().tolist()
)

account_type_filter = st.sidebar.multiselect(
    "User Account Type",
    options=account_type_options,
    default=[]
)


# 4. LOGIN STATUS FILTER

status_filter = st.sidebar.radio(
    "Status",
    options=[
        "All",
        "Successful only",
        "Failed only"
    ],
    index=0
)


# 5. DUPLICATE REMOVAL OPTION

st.sidebar.divider()

remove_duplicates = st.sidebar.checkbox(
    "Remove duplicate CLIENT_IP + CLIENT_TYPE",
    value=False,
    help=(
        "Keep only the latest login record for each unique "
        "CLIENT_IP and REPORTED_CLIENT_TYPE combination."
    )
)


# ==================================================
# APPLY FILTERS
# ==================================================

filtered = df.copy()


# USER FILTER

if user_filter:

    filtered = filtered[
        filtered["USER_NAME"].isin(user_filter)
    ]


# AUTHENTICATION TYPE FILTER

if auth_filter:

    filtered = filtered[
        filtered["FIRST_AUTHENTICATION_FACTOR"].isin(auth_filter)
    ]


# USER ACCOUNT TYPE FILTER

if account_type_filter:

    filtered = filtered[
        filtered["USER_ACCOUNT_TYPE"].isin(account_type_filter)
    ]


# STATUS FILTER

if status_filter == "Successful only":

    filtered = filtered[
        filtered["IS_SUCCESS"]
    ]

elif status_filter == "Failed only":

    filtered = filtered[
        ~filtered["IS_SUCCESS"]
    ]


# ==================================================
# REMOVE DUPLICATES
# ==================================================

original_count = len(filtered)

if remove_duplicates:

    filtered = (
        filtered
        .sort_values(
            by="EVENT_TIMESTAMP",
            ascending=False
        )
        .drop_duplicates(
            subset=[
                "CLIENT_IP",
                "REPORTED_CLIENT_TYPE"
            ],
            keep="first"
        )
        .reset_index(drop=True)
    )

removed_count = original_count - len(filtered)


# ==================================================
# CHECK FILTERED DATA
# ==================================================

if filtered.empty:

    st.warning(
        "No login records found for the selected filters."
    )

    st.stop()


# ==================================================
# DUPLICATE REMOVAL INFORMATION
# ==================================================

if remove_duplicates:

    st.caption(
        f"Duplicate removal enabled | "
        f"Original records: {original_count:,} | "
        f"Duplicates removed: {removed_count:,} | "
        f"Remaining records: {len(filtered):,}"
    )


# ==================================================
# SUMMARY METRICS
# ==================================================

total_logins = len(filtered)

failed_logins = int(
    (~filtered["IS_SUCCESS"]).sum()
)

unique_users = filtered["USER_NAME"].nunique()

mfa_logins = int(
    filtered["SECOND_AUTHENTICATION_FACTOR"]
    .notna()
    .sum()
)

mfa_rate = (
    mfa_logins / total_logins * 100
    if total_logins > 0
    else 0
)


col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Total login attempts",
    f"{total_logins:,}"
)

col2.metric(
    "Failed attempts",
    f"{failed_logins:,}"
)

col3.metric(
    "Unique users",
    f"{unique_users:,}"
)

col4.metric(
    "MFA usage",
    f"{mfa_rate:.0f}%"
)


# ==================================================
# TABS
# ==================================================

tab_activity, tab_failed, tab_trend = st.tabs(
    [
        "All Activity",
        "Failed Logins",
        "Trend"
    ]
)


# ==================================================
# TAB 1 - ALL ACTIVITY
# ==================================================

with tab_activity:

    st.subheader("All Login Activity")

    # Display all columns returned by SELECT LH.*

    st.dataframe(
        filtered,
        use_container_width=True,
        hide_index=True
    )

    st.download_button(
        "Export to CSV",
        data=filtered.to_csv(index=False),
        file_name="login_history.csv",
        mime="text/csv"
    )


# ==================================================
# TAB 2 - FAILED LOGINS
# ==================================================

with tab_failed:

    failed_df = filtered[
        ~filtered["IS_SUCCESS"]
    ]

    if failed_df.empty:

        st.success(
            "No failed login attempts in this window."
        )

    else:

        st.warning(
            f"{len(failed_df):,} failed login attempt(s) found."
        )

        # Top users with failed attempts

        top_offenders = (
            failed_df.groupby("USER_NAME")
            .size()
            .sort_values(ascending=False)
            .reset_index(name="FAILED_ATTEMPTS")
        )

        st.subheader(
            "Users with the most failed attempts"
        )

        st.dataframe(
            top_offenders.head(20),
            use_container_width=True,
            hide_index=True
        )

        # Failed login details

        st.subheader("Failed Login Details")

        st.dataframe(
            failed_df,
            use_container_width=True,
            hide_index=True
        )

        st.download_button(
            "Export failed logins",
            data=failed_df.to_csv(index=False),
            file_name="failed_login_history.csv",
            mime="text/csv"
        )


# ==================================================
# TAB 3 - LOGIN TREND
# ==================================================

with tab_trend:

    st.subheader("Daily Login Activity")

    trend = (
        filtered.assign(
            DAY=pd.to_datetime(
                filtered["EVENT_TIMESTAMP"]
            ).dt.date
        )
        .groupby(
            ["DAY", "IS_SUCCESS"]
        )
        .size()
        .reset_index(name="COUNT")
    )

    if trend.empty:

        st.info(
            "No data to chart for this window."
        )

    else:

        pivot = (
            trend.pivot(
                index="DAY",
                columns="IS_SUCCESS",
                values="COUNT"
            )
            .fillna(0)
        )

        pivot = pivot.rename(
            columns={
                False: "Failed",
                True: "Successful"
            }
        )

        for column in ["Failed", "Successful"]:

            if column not in pivot.columns:
                pivot[column] = 0

        pivot = pivot[
            ["Failed", "Successful"]
        ]

        st.bar_chart(pivot)


# ==================================================
# END OF APPLICATION
# ==================================================
