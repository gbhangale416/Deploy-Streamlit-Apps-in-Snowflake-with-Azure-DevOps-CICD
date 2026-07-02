import streamlit as st
from snowflake.snowpark.context import get_active_session

st.title("🔍 Find Snowflake User by Email")

session = get_active_session()

email = st.text_input("Enter Email ID")

if st.button("Search"):

    query = f"""
    SELECT
        NAME,
        EMAIL,
        FIRST_NAME,
        LAST_NAME,
        DISPLAY_NAME,
        DEFAULT_ROLE,
        DEFAULT_WAREHOUSE,
        DEFAULT_NAMESPACE,
        CREATED_ON,
        DISABLED
    FROM SNOWFLAKE.ACCOUNT_USAGE.USERS
    WHERE UPPER(EMAIL) = UPPER('{email}')
    LIMIT 1
    """

    try:
        result = session.sql(query).collect()

        if result:
            user = result[0]

            st.success("User Found")

            st.write(f"**Username:** {user['NAME']}")
            st.write(f"**Email:** {user['EMAIL']}")
            st.write(f"**First Name:** {user['FIRST_NAME']}")
            st.write(f"**Last Name:** {user['LAST_NAME']}")
            st.write(f"**Display Name:** {user['DISPLAY_NAME']}")
            st.write(f"**Default Role:** {user['DEFAULT_ROLE']}")
            st.write(f"**Default Warehouse:** {user['DEFAULT_WAREHOUSE']}")
            st.write(f"**Default Namespace:** {user['DEFAULT_NAMESPACE']}")
            st.write(f"**Created On:** {user['CREATED_ON']}")
            st.write(f"**Disabled:** {user['DISABLED']}")

        else:
            st.warning("No user found.")

    except Exception as e:
        st.error(str(e))
