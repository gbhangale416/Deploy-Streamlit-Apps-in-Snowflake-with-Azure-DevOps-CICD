import streamlit as st
from snowflake.snowpark.context import get_active_session

st.title("👤 User Profile Fetcher")

# 1. Capture the viewer's base corporate username
viewer_username = st.user.user_name

if st.button("Greet Me"):
    # Initialize defaults in case properties aren't configured
    first_name = "N/A"
    last_name = "N/A"
    display_name = viewer_username

    try:
        # 2. Query Snowflake to describe the current user's system profile
        session = get_active_session()
        user_metadata = session.sql(f"DESCRIBE USER {viewer_username}").collect()
        
        # 3. Loop through the rows to extract name properties
        for row in user_metadata:
            # Snowflake returns profile data in a key-value format (property, value)
            prop = row["property"]
            val = row["value"]
            
            if prop == "FIRST_NAME" and val:
                first_name = val
            elif prop == "LAST_NAME" and val:
                last_name = val
            elif prop == "DISPLAY_NAME" and val:
                display_name = val

        # 4. Display the results cleanly
        st.success(f"Hello, {first_name} {last_name}!")
        
        with st.expander("Detailed System Profile Attributes"):
            st.markdown(f"""
            * **First Name:** {first_name}
            * **Last Name:** {last_name}
            * **Display Name:** {display_name}
            * **Snowflake ID:** `{viewer_username}`
            """)

    except Exception as e:
        # Fallback if running locally or if the app role lacks MONITOR privileges
        st.warning("Could not read profile details. Ensure your app role has MONITOR privileges on USERS.")
        st.info(f"Fallback Greeting: Hello, {viewer_username}!")
