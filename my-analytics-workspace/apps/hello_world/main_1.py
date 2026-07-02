import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Hello World", layout="centered")

st.title("👋 Hello World from Snowflake!")
st.write("This is a simple interactive test running natively inside your data warehouse.")

# 1. Fetch User Metadata from the browser context
# st.user works automatically when running live inside Snowsight
viewer_username = st.user.user_name
viewer_email = st.user.email

if st.button("Greet Me"):
    # Clear visual feedback of who clicked the action
    st.success(f"Action triggered successfully!")
    
    # 2. Display the granular user details inside a clean visual container
    with st.expander("👁️ View Interactive Caller Session Details", expanded=True):
        st.markdown(f"""
        * **Snowflake Username:** `{viewer_username}`
        * **Associated Corporate Email:** `{viewer_email}`
        """)
        
    # 3. Optional: Write the click event directly to an audit log table in Snowflake
    try:
        session = get_active_session()
        # Escaping parameters to prevent SQL Injection
        session.sql(
            "INSERT INTO audit_log_table (clicked_by, clicked_email, event_time) VALUES (?, ?, CURRENT_TIMESTAMP())",
            params=[viewer_username, viewer_email]
        ).collect()
        st.caption("⚡ Click event saved securely to your Snowflake audit logs.")
    except Exception:
        # Fallback handling for local testing when active snowpark session isn't available
        st.caption("ℹ️ Skipping audit log database write (running locally).")
