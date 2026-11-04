
import streamlit as st
import pandas as pd
from snowflake.snowpark.context import get_active_session


# --------------------------------------------------
# Page Configuration
# --------------------------------------------------

st.set_page_config(
    page_title="Login Info",
    layout="wide"
)

session = get_active_session()

st.title("Login Info")

st.caption(
    "Authentication activity from ACCOUNT_USAGE.LOGIN_HISTORY "
    "- successes, failures, and MFA usage."
)


# --------------------------------------------------
# Data Access
# --------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_login_history(days: int) -> pd.DataFrame:

    query = f"""
        SELECT
            LH.EVENT_TIMESTAMP,
            LH.USER_NAME,
            LH.CLIENT_IP,
            LH.REPORTED_CLIENT_TYPE,
            LH.IS_SUCCESS,
            LH.ERROR_CODE,
            LH.ERROR_MESSAGE,
            LH.FIRST_AUTHENTICATION_FACTOR,
            LH.SECOND_AUTHENTICATION_FACTOR,
            COALESCE(U.TYPE, 'UNKNOWN') AS USER_ACCOUNT_TYPE

        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY LH

        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS U
            ON LH.USER_NAME = U.NAME

        WHERE LH.EVENT_TIMESTAMP >=
            DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())

        ORDER BY LH.EVENT_TIMESTAMP DESC
    """

    return session.sql(query).to_pandas()


# --------------------------------------------------
# Sidebar - Filters
# --------------------------------------------------

with st.sidebar:

    st.header("Filters")

    lookback_days = st.slider(
        "Lookback window (days)",
        min_value=1,
        max_value=90,
        value=7
    )

    if st.button("Refresh data", use_container_width=True):

        get_login_history.clear()
        st.rerun()


# --------------------------------------------------
# Load Data
# --------------------------------------------------

try:

    df = get_login_history(lookback_days)

except Exception as e:

    st.error(f"Could not load login history: {e}")
    st.stop()


if df.empty:

    st.info("No login events found in this window.")
    st.stop()


# --------------------------------------------------
# Data Preparation
# --------------------------------------------------

df["IS_SUCCESS"] = (
    df["IS_SUCCESS"]
    .astype(str)
    .str.upper()
    .isin(["TRUE", "YES", "1"])
)

df["USER_NAME"] = df["USER_NAME"].fillna("UNKNOWN")

df["FIRST_AUTHENTICATION_FACTOR"] = (
    df["FIRST_AUTHENTICATION_FACTOR"]
    .fillna("UNKNOWN")
)

df["USER_ACCOUNT_TYPE"] = (
    df["USER_ACCOUNT_TYPE"]
    .fillna("UNKNOWN")
)


# --------------------------------------------------
# Sidebar - Dynamic Filters
# --------------------------------------------------

# 1. Filter by User

user_options = sorted(
    df["USER_NAME"].unique().tolist()
)

user_filter = st.sidebar.multiselect(
    "Filter by user",
    options=user_options,
    default=[]
)


# 2. Authentication Type

auth_options = sorted(
    df["FIRST_AUTHENTICATION_FACTOR"]
    .unique()
    .tolist()
)

auth_filter = st.sidebar.multiselect(
    "Authentication Type",
    options=auth_options,
    default=[]
)


# 3. User Account Type

account_type_options = sorted(
    df["USER_ACCOUNT_TYPE"]
    .unique()
    .tolist()
)

account_type_filter = st.sidebar.multiselect(
    "User Account Type",
    options=account_type_options,
    default=[]
)


# 4. Login Status

status_filter = st.sidebar.radio(
    "Status",
    ["All", "Successful only", "Failed only"]
)


# 5. Remove Duplicates

st.sidebar.divider()

remove_duplicates = st.sidebar.checkbox(
    "Remove duplicate CLIENT_IP + CLIENT_TYPE",
    value=False,
    help=(
        "Keep only the latest login record for each "
        "unique CLIENT_IP and REPORTED_CLIENT_TYPE combination."
    )
)


# --------------------------------------------------
# Apply All Filters
# --------------------------------------------------

filtered = df.copy()


# User filter

if user_filter:

    filtered = filtered[
        filtered["USER_NAME"].isin(user_filter)
    ]


# Authentication Type filter

if auth_filter:

    filtered = filtered[
        filtered["FIRST_AUTHENTICATION_FACTOR"].isin(auth_filter)
    ]


# User Account Type filter

if account_type_filter:

    filtered = filtered[
        filtered["USER_ACCOUNT_TYPE"].isin(account_type_filter)
    ]


# Status filter

if status_filter == "Successful only":

    filtered = filtered[
        filtered["IS_SUCCESS"]
    ]

elif status_filter == "Failed only":

    filtered = filtered[
        ~filtered["IS_SUCCESS"]
    ]


# --------------------------------------------------
# Remove Duplicates
# --------------------------------------------------

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


# --------------------------------------------------
# Check Filtered Data
# --------------------------------------------------

if filtered.empty:

    st.warning(
        "No login records found for the selected filters."
    )
    st.stop()


# --------------------------------------------------
# Duplicate Removal Information
# --------------------------------------------------

if remove_duplicates:

    st.caption(
        f"Duplicate removal enabled: "
        f"{removed_count:,} duplicate record(s) removed. "
        f"{len(filtered):,} unique combination(s) remaining."
    )


# --------------------------------------------------
# Summary Metrics
# --------------------------------------------------

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


# --------------------------------------------------
# Tabs
# --------------------------------------------------

tab_activity, tab_failed, tab_trend = st.tabs(
    ["All Activity", "Failed Logins", "Trend"]
)


# --------------------------------------------------
# Tab 1 - All Activity
# --------------------------------------------------

with tab_activity:

    activity_columns = [
        "EVENT_TIMESTAMP",
        "USER_NAME",
        "USER_ACCOUNT_TYPE",
        "CLIENT_IP",
        "REPORTED_CLIENT_TYPE",
        "FIRST_AUTHENTICATION_FACTOR",
        "SECOND_AUTHENTICATION_FACTOR",
        "IS_SUCCESS"
    ]

    st.dataframe(
        filtered[activity_columns],
        use_container_width=True,
        hide_index=True
    )

    st.download_button(
        "Export to CSV",
        filtered.to_csv(index=False),
        file_name="login_history.csv",
        mime="text/csv"
    )


# --------------------------------------------------
# Tab 2 - Failed Logins
# --------------------------------------------------

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
            f"{len(failed_df)} failed login attempt(s) found."
        )

        # Users with most failed attempts

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

        # Failed attempt details

        st.subheader("Failed attempt details")

        failed_columns = [
            "EVENT_TIMESTAMP",
            "USER_NAME",
            "USER_ACCOUNT_TYPE",
            "CLIENT_IP",
            "ERROR_CODE",
            "ERROR_MESSAGE",
            "FIRST_AUTHENTICATION_FACTOR"
        ]

        st.dataframe(
            failed_df[failed_columns],
            use_container_width=True,
            hide_index=True
        )

        st.download_button(
            "Export failed logins",
            failed_df.to_csv(index=False),
            file_name="failed_login_history.csv",
            mime="text/csv"
        )


# --------------------------------------------------
# Tab 3 - Login Trend
# --------------------------------------------------

with tab_trend:

    trend = (
        filtered.assign(
            DAY=pd.to_datetime(
                filtered["EVENT_TIMESTAMP"]
            ).dt.date
        )
        .groupby(["DAY", "IS_SUCCESS"])
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

        st.subheader("Daily Login Activity")

        st.bar_chart(pivot)


# --------------------------------------------------
# End of Application
# --------------------------------------------------

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


import streamlit as st
import pandas as pd
from snowflake.snowpark.context import get_active_session


# --------------------------------------------------
# Page Configuration
# --------------------------------------------------

st.set_page_config(
    page_title="Login Info",
    layout="wide"
)

session = get_active_session()

st.title("Login Info")

st.caption(
    "Authentication activity from ACCOUNT_USAGE.LOGIN_HISTORY "
    "- successes, failures, and MFA usage."
)


# --------------------------------------------------
# Data Access
# --------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def get_login_history(days: int) -> pd.DataFrame:

    query = f"""
        SELECT
            LH.EVENT_TIMESTAMP,
            LH.USER_NAME,
            LH.CLIENT_IP,
            LH.REPORTED_CLIENT_TYPE,
            LH.IS_SUCCESS,
            LH.ERROR_CODE,
            LH.ERROR_MESSAGE,
            LH.FIRST_AUTHENTICATION_FACTOR,
            LH.SECOND_AUTHENTICATION_FACTOR,
            COALESCE(U.TYPE, 'UNKNOWN') AS USER_ACCOUNT_TYPE

        FROM SNOWFLAKE.ACCOUNT_USAGE.LOGIN_HISTORY LH

        LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.USERS U
            ON LH.USER_NAME = U.NAME

        WHERE LH.EVENT_TIMESTAMP >=
            DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP())

        ORDER BY LH.EVENT_TIMESTAMP DESC
    """

    return session.sql(query).to_pandas()


# --------------------------------------------------
# Sidebar - Filters
# --------------------------------------------------

with st.sidebar:

    st.header("Filters")

    lookback_days = st.slider(
        "Lookback window (days)",
        min_value=1,
        max_value=90,
        value=7
    )

    if st.button("Refresh data", use_container_width=True):

        get_login_history.clear()
        st.rerun()


# --------------------------------------------------
# Load Data
# --------------------------------------------------

try:

    df = get_login_history(lookback_days)

except Exception as e:

    st.error(f"Could not load login history: {e}")
    st.stop()


if df.empty:

    st.info("No login events found in this window.")
    st.stop()


# --------------------------------------------------
# Data Preparation
# --------------------------------------------------

df["IS_SUCCESS"] = (
    df["IS_SUCCESS"]
    .astype(str)
    .str.upper()
    .isin(["TRUE", "YES", "1"])
)

# Handle missing values in filter columns

df["USER_NAME"] = df["USER_NAME"].fillna("UNKNOWN")

df["FIRST_AUTHENTICATION_FACTOR"] = (
    df["FIRST_AUTHENTICATION_FACTOR"]
    .fillna("UNKNOWN")
)

df["USER_ACCOUNT_TYPE"] = (
    df["USER_ACCOUNT_TYPE"]
    .fillna("UNKNOWN")
)


# --------------------------------------------------
# Sidebar - Dynamic Filters
# --------------------------------------------------

# 1. Filter by User

user_options = sorted(
    df["USER_NAME"].unique().tolist()
)

user_filter = st.sidebar.multiselect(
    "Filter by user",
    options=user_options,
    default=[]
)


# 2. Filter by Authentication Type

auth_options = sorted(
    df["FIRST_AUTHENTICATION_FACTOR"]
    .unique()
    .tolist()
)

auth_filter = st.sidebar.multiselect(
    "Authentication Type",
    options=auth_options,
    default=[]
)


# 3. Filter by User Account Type

account_type_options = sorted(
    df["USER_ACCOUNT_TYPE"]
    .unique()
    .tolist()
)

account_type_filter = st.sidebar.multiselect(
    "User Account Type",
    options=account_type_options,
    default=[]
)


# 4. Filter by Login Status

status_filter = st.sidebar.radio(
    "Status",
    ["All", "Successful only", "Failed only"]
)


# --------------------------------------------------
# Apply All Filters
# --------------------------------------------------

filtered = df.copy()


# User filter

if user_filter:

    filtered = filtered[
        filtered["USER_NAME"].isin(user_filter)
    ]


# Authentication Type filter

if auth_filter:

    filtered = filtered[
        filtered["FIRST_AUTHENTICATION_FACTOR"].isin(auth_filter)
    ]


# User Account Type filter

if account_type_filter:

    filtered = filtered[
        filtered["USER_ACCOUNT_TYPE"].isin(account_type_filter)
    ]


# Status filter

if status_filter == "Successful only":

    filtered = filtered[
        filtered["IS_SUCCESS"]
    ]

elif status_filter == "Failed only":

    filtered = filtered[
        ~filtered["IS_SUCCESS"]
    ]


# --------------------------------------------------
# Check Filtered Data
# --------------------------------------------------

if filtered.empty:

    st.warning("No login records found for the selected filters.")
    st.stop()


# --------------------------------------------------
# Summary Metrics
# --------------------------------------------------

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


# --------------------------------------------------
# Tabs
# --------------------------------------------------

tab_activity, tab_failed, tab_trend = st.tabs(
    ["All Activity", "Failed Logins", "Trend"]
)


# --------------------------------------------------
# Tab 1 - All Activity
# --------------------------------------------------

with tab_activity:

    activity_columns = [
        "EVENT_TIMESTAMP",
        "USER_NAME",
        "USER_ACCOUNT_TYPE",
        "CLIENT_IP",
        "REPORTED_CLIENT_TYPE",
        "FIRST_AUTHENTICATION_FACTOR",
        "SECOND_AUTHENTICATION_FACTOR",
        "IS_SUCCESS"
    ]

    st.dataframe(
        filtered[activity_columns],
        use_container_width=True,
        hide_index=True
    )

    st.download_button(
        "Export to CSV",
        filtered.to_csv(index=False),
        file_name="login_history.csv",
        mime="text/csv"
    )


# --------------------------------------------------
# Tab 2 - Failed Logins
# --------------------------------------------------

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
            f"{len(failed_df)} failed login attempt(s) found."
        )

        # Users with most failed attempts

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

        # Failed attempt details

        st.subheader("Failed attempt details")

        failed_columns = [
            "EVENT_TIMESTAMP",
            "USER_NAME",
            "USER_ACCOUNT_TYPE",
            "CLIENT_IP",
            "ERROR_CODE",
            "ERROR_MESSAGE",
            "FIRST_AUTHENTICATION_FACTOR"
        ]

        st.dataframe(
            failed_df[failed_columns],
            use_container_width=True,
            hide_index=True
        )

        st.download_button(
            "Export failed logins",
            failed_df.to_csv(index=False),
            file_name="failed_login_history.csv",
            mime="text/csv"
        )


# --------------------------------------------------
# Tab 3 - Login Trend
# --------------------------------------------------

with tab_trend:

    trend = (
        filtered.assign(
            DAY=pd.to_datetime(
                filtered["EVENT_TIMESTAMP"]
            ).dt.date
        )
        .groupby(["DAY", "IS_SUCCESS"])
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

        # Ensure both columns are available

        for column in ["Failed", "Successful"]:

            if column not in pivot.columns:
                pivot[column] = 0

        pivot = pivot[
            ["Failed", "Successful"]
        ]

        st.subheader("Daily Login Activity")

        st.bar_chart(pivot)


# --------------------------------------------------
# End of Application
# --------------------------------------------------
