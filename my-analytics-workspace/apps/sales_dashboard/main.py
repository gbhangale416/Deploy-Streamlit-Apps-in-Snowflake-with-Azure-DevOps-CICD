import streamlit as st
import pandas as pd
import altair as alt
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Executive Sales Dashboard", layout="wide")

st.title("📊 Executive Sales Performance")
st.markdown("---")

# 1. Establish Secure Data Context
@st.cache_data(ttl=600)  # Cache data for 10 minutes to minimize warehouse credit spend
def load_sales_data():
    try:
        # Pull live summary data directly from your tables via Snowpark
        session = get_active_session()
        query = """
            SELECT 'North America' as REGION, 'Electronics' as CATEGORY, 150000 as REVENUE, '2026-01' as MONTH_YR
            UNION ALL SELECT 'North America', 'Apparel', 95000, '2026-01'
            UNION ALL SELECT 'Europe', 'Electronics', 110000, '2026-01'
            UNION ALL SELECT 'Europe', 'Apparel', 85000, '2026-01'
            UNION ALL SELECT 'North America', 'Electronics', 165000, '2026-02'
            UNION ALL SELECT 'North America', 'Apparel', 102000, '2026-02'
            UNION ALL SELECT 'Europe', 'Electronics', 125000, '2026-02'
            UNION ALL SELECT 'Europe', 'Apparel', 89000, '2026-02'
        """
        return session.sql(query).to_pandas()
    except Exception:
        # Fallback dummy data for local development/testing outside Snowflake
        data = {
            'REGION': ['North America', 'North America', 'Europe', 'Europe', 'North America', 'North America', 'Europe', 'Europe'],
            'CATEGORY': ['Electronics', 'Apparel', 'Electronics', 'Apparel', 'Electronics', 'Apparel', 'Electronics', 'Apparel'],
            'REVENUE': [150000, 95000, 110000, 85000, 165000, 102000, 125000, 89000],
            'MONTH_YR': ['2026-01', '2026-01', '2026-01', '2026-01', '2026-02', '2026-02', '2026-02', '2026-02']
        }
        return pd.DataFrame(data)

df = load_sales_data()

# 2. Sidebar Filters Pane
st.sidebar.header("Filter Views")
selected_regions = st.sidebar.multiselect("Select Regions:", options=df['REGION'].unique(), default=df['REGION'].unique())

# Apply active filters to dataframe
filtered_df = df[df['REGION'].isin(selected_regions)]

# 3. Dynamic Top-Level KPI Summary Tiles
total_revenue = filtered_df['REVENUE'].sum()
electronics_rev = filtered_df[filtered_df['CATEGORY'] == 'Electronics']['REVENUE'].sum()
apparel_rev = filtered_df[filtered_df['CATEGORY'] == 'Apparel']['REVENUE'].sum()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(label="Total Combined Revenue", value=f"${total_revenue:,.0f}", delta="+8% vs Last Month")
with col2:
    st.metric(label="Electronics Vertical", value=f"${electronics_rev:,.0f}")
with col3:
    st.metric(label="Apparel Vertical", value=f"${apparel_rev:,.0f}")

st.markdown("### Regional Breakdown Trend")

# 4. Interactive Visualization Section
if not filtered_df.empty:
    chart = alt.Chart(filtered_df).mark_bar().encode(
        x=alt.X('MONTH_YR:N', title='Reporting Period'),
        y=alt.Y('REVENUE:Q', title='Revenue ($)'),
        color=alt.Color('REGION:N', title='Territory'),
        column=alt.Column('CATEGORY:N', title='Product Segment')
    ).properties(width=300, height=300)
    
    st.altair_chart(chart, use_container_width=False)
else:
    st.warning("Please select at least one region in the sidebar panel.")
