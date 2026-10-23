The best and most reliable design pattern for Snowflake Native Streamlit apps is **dynamic context resolution** rather than string replacement or environment variables.

In Snowflake Native Streamlit, the app executes directly within an active Snowflake session. The session inherits the target database and schema where the Streamlit entity was deployed.

---

### 1. In `streamlit_app.py`: Read the Current Database Directly from Session

Instead of hardcoding or replacing database strings at build time, query `CURRENT_DATABASE()` and `CURRENT_SCHEMA()` directly from the active Snowpark session.

```python
import streamlit as st
from snowflake.snowpark.context import get_active_session

# Retrieve active Snowpark session created by Snowflake for this app
session = get_active_session()

# Resolve current database and schema dynamically
current_db = session.get_current_database()
current_schema = session.get_current_schema()

# Example 1: Use fully qualified dynamic names in raw SQL
query = f"""
    SELECT *
    FROM {current_db}.{current_schema}.MY_TABLE
    LIMIT 100
"""
df = session.sql(query).to_pandas()

# Example 2: Use unqualified names (Snowflake resolves them against current DB/Schema)
# In Snowflake, if DB and Schema are not specified, it defaults to the app's location:
df_direct = session.table("MY_TABLE").to_pandas()

st.title(f"Streamlit App - {current_db}")
st.dataframe(df)

```

**Why this is best:**

* Code remains environment-agnostic (the exact same `streamlit_app.py` runs seamlessly in `DEV`, `TEST`, and `PROD`).


* No code modification or git tampering is needed during CI/CD.

---

### 2. In `snowflake.yml`: Parameterize Database & Warehouse via CLI Context

Use Snowflake CLI’s native templating syntax `<% ctx.env.VARIABLE_NAME %>` inside `snowflake.yml`. The Snowflake CLI will automatically interpolate these variables at deploy time.

```yaml
definition_version: 2
entities:
  streamlit_app:
    type: streamlit
    identifier:
      database: <% ctx.env.STREAMLIT_DB %>
      schema: SUPPORT
      name: LOGIN_INFO
    title: Login_Info
    query_warehouse: <% ctx.env.STREAMLIT_WH %>
    main_file: streamlit_app.py
    artifacts:
      - environment.yml
      - streamlit_app.py
      - .streamlit/config.toml
```[cite: 7]

---

### 3. In Azure DevOps YAML: Export the Variables in the Deployment Function

Pass the database and warehouse as parameters into your deployment function, export them as environment variables, and run `snow streamlit deploy`[cite: 2]:

```bash
function run_streamlit_deploy() {
  ROLE=$1
  WH=$2
  DB=$3
  ENV_NAME=$4

  echo "=========================================================="
  echo "[INFO] Deploying to $ENV_NAME (DB: $DB, WH: $WH, Role: $ROLE)"
  echo "=========================================================="

  mkdir -p ~/.snowflake
  KEY_PATH="$HOME/.snowflake/rsa_key.p8"

  echo "$SNOWFLAKE_PRIVATE_KEY" | base64 -d > "$KEY_PATH"
  chmod 600 "$KEY_PATH"

  cat > ~/.snowflake/config.toml <<EOF
default_connection_name = "ci"

[connections.ci]
account = "$(SNOWFLAKE_ACCOUNT)"
user = "$(SNOWFLAKE_USER)"
private_key_file = "$KEY_PATH"
warehouse = "$WH"
role = "$ROLE"
EOF

  chmod 700 ~/.snowflake
  chmod 600 ~/.snowflake/config.toml

  deployFailed=0
  appCount=0
  BASE_DIR="${{ parameters.streamlitBaseDir }}"

  while IFS= read -r -d '' manifest; do
    appDir=$(dirname "$manifest")
    appName=$(basename "$appDir")
    SchemaName=$(basename "$(dirname "$appDir")")
    appCount=$((appCount + 1))

    echo "----------------------------------------"
    echo "[INFO] Deploying $SchemaName/$appName to $ENV_NAME"
    echo "----------------------------------------"

    pushd "$appDir" > /dev/null

    # Export variables used by <% ctx.env.* %> in snowflake.yml
    export STREAMLIT_DB="$DB"
    export STREAMLIT_WH="$WH"

    if snow streamlit deploy --replace -c ci; then
      echo "[INFO] Successfully deployed $SchemaName/$appName"
    else
      echo "[ERROR] Failed to deploy $SchemaName/$appName"
      deployFailed=1
    fi
    popd > /dev/null
  done < <(find "$BASE_DIR" -type f -name "snowflake.yml" -print0)

  if [ "$deployFailed" -ne 0 ]; then
    echo "[ERROR] Streamlit deployment failed for $ENV_NAME."
    return 1
  fi
}

# Deployment branch condition
if [[ "${{ parameters.target_environment }}" == "$(TARGET_ENV_DEV_TEST)" ]]; then
  echo "[START] Executing DEV deployment..."
  run_streamlit_deploy "$(SF_ROLE_DEV)" "$(SF_WAREHOUSE_DEV)" "COEDW_DEV" "dev"

  echo "[START] Executing TEST deployment..."
  run_streamlit_deploy "$(SF_ROLE_TEST)" "$(SF_WAREHOUSE_TEST)" "COEDW_TST" "tst"

elif [[ "${{ parameters.target_environment }}" == "$(TARGET_ENV_PROD)" ]]; then
  echo "[START] Executing PROD deployment..."
  run_streamlit_deploy "$(SF_ROLE)" "$(SF_WAREHOUSE)" "COEDW_PRD" "prd"
fi
```[cite: 2, 4, 6, 7]

```
