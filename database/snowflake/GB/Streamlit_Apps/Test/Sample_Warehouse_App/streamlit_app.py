import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Sample Warehouse App", layout="centered")
st.title("Sample Warehouse Runtime App")

session = get_active_session()

st.write("This is a warehouse-runtime Streamlit app used for pipeline testing.")

if st.button("Run test query"):
    df = session.sql("SELECT CURRENT_WAREHOUSE(), CURRENT_ROLE(), CURRENT_TIMESTAMP()").to_pandas()
    st.dataframe(df, use_container_width=True)
