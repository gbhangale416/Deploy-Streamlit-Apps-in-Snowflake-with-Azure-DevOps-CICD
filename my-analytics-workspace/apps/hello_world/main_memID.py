import streamlit as st
import pandas as pd
from snowflake.snowpark.context import get_active_session

# Set up page configurations
st.set_page_config(page_title="Member Lookup Tool", layout="wide")

st.title("🔍 Member Data Explorer")
st.markdown("Retrieve and audit records safely directly from the warehouse data tier.")
st.markdown("---")

# 1. User Input Elements
col1, col2 = st.columns([1, 3])
with col1:
    # Text input box for entering the Member ID filter variable
    search_memid = st.text_input("Enter Member ID (MEMID):", value="M10294")

# 2. Executing Data Extraction inside Snowflake
if search_memid:
    with st.spinner("Fetching matching records from Snowflake..."):
        try:
            # Grabs the live secure wrapper session context
            session = get_active_session()
            
            # Formulating the SQL structure using Snowflake's native LIMIT clause.
            # Using 'params' variables natively protects against malicious SQL injection.
            query = """
                SELECT * FROM YOUR_DATABASE.YOUR_SCHEMA.YOUR_TABLE 
                WHERE MEMID = ?
                LIMIT 10
            """
            
            # Execute and convert the dataset back into a standard Python Pandas DataFrame
            raw_data = session.sql(query, params=[search_memid]).collect()
            df = pd.DataFrame(raw_data)
            
            # 3. Presenting the Results to the UI Layout
            if not df.empty:
                st.success(f"✅ Found {len(df)} records matching MEMID: `{search_memid}`")
                
                # Tabbed system view component breakdown
                tab1, tab2 = st.tabs(["📊 Interactive Data Grid", "📋 Raw Transposed Record View"])
                
                with tab1:
                    # High-performance native data viewing frame grid container
                    st.dataframe(df, use_container_width=True)
                    
                with tab2:
                    # Renders columns as rows (excellent for auditing single wide-table rows)
                    st.write(df.T)
            else:
                st.warning(f"No records found in the database table matching MEMID: `{search_memid}`")
                
        except Exception as e:
            # Fallback error logger panel context hook
            st.error("An error occurred while communicating with Snowflake.")
            with st.expander("Show detailed backend traceback log"):
                st.code(str(e))
else:
    st.info("💡 Please provide a valid Member ID in the field above to query logs.")
