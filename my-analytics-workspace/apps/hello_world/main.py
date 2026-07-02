import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Hello World", layout="centered")

st.title("👋 Hello World from Snowflake!")
st.write("This is a simple interactive test running natively inside your data warehouse.")

# Collect user input
user_name = st.text_input("What is your name?", "Data Engineer")

if st.button("Greet Me"):
    st.success(f"Welcome to Streamlit in Snowflake, {user_name}!")

# Grab background session information safely
try:
    session = get_active_session()
    current_role = session.get_current_role()
    current_wh = session.get_current_warehouse()
    
    st.info(f"App is executing as **{current_role}** using warehouse **{current_wh}**.")
except Exception:
    st.warning(" Running locally or active Snowflake session context not found.")
