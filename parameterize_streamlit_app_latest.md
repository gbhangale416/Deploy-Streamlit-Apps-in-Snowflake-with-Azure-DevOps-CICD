### 1. Azure DevOps Pipeline (`azure-pipelines.yml`)

This pipeline:

* Validates the target branch policy against `target_environment`.


* Sets Python 3.11 and installs `snowflake-cli` with `cryptography`.


* Authenticates using an unencrypted Base64 private key.


* Dynamically replaces `database`, `query_warehouse`, and `compute_pool` (if present) inside `snowflake.yml` prior to deployment, then reverts changes to keep the repository clean.



```yaml
parameters:
  - name: target_environment
    displayName: Environment
    type: string
    default: DEV_TEST
    values:
      - DEV_TEST
      - PROD

  - name: agentPoolName
    displayName: Select Agent Pool
    type: string
    default: prd-devops-linux-agent-pool
    values:
      - dev-devops-linux-agent-pool
      - tst-devops-linux-agent-pool
      - prd-devops-linux-agent-pool

  - name: streamlitBaseDir
    displayName: Streamlit Root Path
    type: string
    default: database/snowflake/coEDW/Streamlit_Apps
    values:
      - database/snowflake/coEDW/Streamlit_Apps

trigger: none

variables:
  - group: Snowflake_streamlit

jobs:
  - job: coedw_Analytics_streamlit
    timeoutInMinutes: 240

    pool:
      name: ${{ parameters.agentPoolName }}

    steps:
      - checkout: self
        persistCredentials: true

      - task: Bash@3
        displayName: 'Bash - Check git branch and target environment policy'
        inputs:
          targetType: 'inline'
          script: |
            sudo apt-get install -y jq
            echo "Target environment: ${{ parameters.target_environment }}"
            echo "Selected branch name: $(Build.SourceBranch)"

            CURRENT_BRANCH_NAME=$(echo "$(Build.SourceBranch)" | sed "s/refs\/heads\///")
            echo "Current branch name: $CURRENT_BRANCH_NAME"
            echo "##vso[task.setvariable variable=CURRENT_BRANCH_NAME]$CURRENT_BRANCH_NAME"

            if [[ "${{ parameters.target_environment }}" == "$(TARGET_ENV_DEV_TEST)" && "$CURRENT_BRANCH_NAME" != "$(TEAM_BRANCH_NAME)" ]]; then
              echo "Target environment ${{ parameters.target_environment }} can be used only with $(TEAM_BRANCH_NAME) branch"
              exit 1
            elif [[ "${{ parameters.target_environment }}" == "$(TARGET_ENV_PROD)" && "$CURRENT_BRANCH_NAME" != "$(MASTER_BRANCH_NAME)" ]]; then
              echo "Target environment ${{ parameters.target_environment }} can be used only with $(MASTER_BRANCH_NAME) branch"
              exit 1
            fi

            echo "Building $CURRENT_BRANCH_NAME against ${{ parameters.target_environment }}"

      - task: UsePythonVersion@0
        displayName: 'Set Python Version to 3.11'
        inputs:
          versionSpec: '3.11'
          disableDownloadFromRegistry: true
          addToPath: true
          architecture: 'x64'

      - script: |
          echo "[INFO] Updating pip..."
          python -m pip install --upgrade pip

          echo "[INFO] Installing Snowflake CLI and Cryptography..."
          pip install snowflake-cli==3.14.0 cryptography

          echo "[INFO] Verifying Snowflake CLI installation..."
          snow --version
        displayName: 'Install Snowflake CLI'

      - task: Bash@3
        displayName: 'Bash - Deploy Streamlit Apps'
        inputs:
          targetType: 'inline'
          script: |
            set -e

            function run_streamlit_deploy() {
              ROLE=$1
              WH=$2
              DB=$3
              CP=$4
              ENV_NAME=$5

              echo "=========================================================="
              echo "[INFO] Configuring Snowflake connection for $ENV_NAME"
              echo "      DB: $DB | WH: $WH | CP: $CP | Role: $ROLE"
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

              snow sql --connection ci --query "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE();"

              deployFailed=0
              appCount=0
              BASE_DIR="${{ parameters.streamlitBaseDir }}"

              if [ ! -d "$BASE_DIR" ]; then
                echo "[ERROR] $BASE_DIR not found. Check the path relative to the repo root."
                return 1
              fi

              echo "[INFO] Scanning $BASE_DIR for Streamlit apps (any Schema, any depth)..."

              while IFS= read -r -d '' manifest; do
                appDir=$(dirname "$manifest")
                appName=$(basename "$appDir")
                SchemaName=$(basename "$(dirname "$appDir")")
                appCount=$((appCount + 1))

                echo "----------------------------------------"
                echo "[INFO] Deploying Streamlit app: $SchemaName/$appName to $ENV_NAME"
                echo "----------------------------------------"

                pushd "$appDir" > /dev/null

                # Export environment variables mapped to <% ctx.env.* %> in snowflake.yml
                export STREAMLIT_DB="$DB"
                export STREAMLIT_WH="$WH"
                export STREAMLIT_CP="$CP"

                if snow streamlit deploy --replace -c ci; then
                  echo "[INFO] Successfully deployed $SchemaName/$appName"
                else
                  echo "[ERROR] Failed to deploy $SchemaName/$appName"
                  deployFailed=1
                fi

                popd > /dev/null
              done < <(find "$BASE_DIR" -type f -name "snowflake.yml" -print0)

              if [ "$appCount" -eq 0 ]; then
                echo "[WARN] No snowflake.yml files found under $BASE_DIR - nothing was deployed."
              fi

              if [ "$deployFailed" -ne 0 ]; then
                echo "[ERROR] One or more Streamlit app deployments failed for $ENV_NAME."
                return 1
              fi

              echo "[INFO] All $appCount Streamlit app(s) deployed successfully for $ENV_NAME."
            }

            # Deployment routing based on target_environment
            if [[ "${{ parameters.target_environment }}" == "$(TARGET_ENV_DEV_TEST)" ]]; then
              echo "[START] Executing DEV deployment..."
              run_streamlit_deploy "$(SF_ROLE_DEV)" "$(SF_WAREHOUSE_DEV)" "$(DB_NAME)$(DEV_DB_POSTFIX)" "$(SF_COMPUTE_POOL_DEV)" "dev"

              echo "[START] Executing TEST deployment..."
              run_streamlit_deploy "$(SF_ROLE_TEST)" "$(SF_WAREHOUSE_TEST)" "$(DB_NAME)$(TEST_DB_POSTFIX)" "$(SF_COMPUTE_POOL_TEST)" "tst"

              echo "Done with DEV TEST.........."

            elif [[ "${{ parameters.target_environment }}" == "$(TARGET_ENV_PROD)" ]]; then
              echo "[START] Executing PROD deployment..."
              run_streamlit_deploy "$(SF_ROLE)" "$(SF_WAREHOUSE)" "$(DB_NAME)" "$(SF_COMPUTE_POOL_PROD)" "prd"

              echo "Done with PROD.........."
            fi
        env:
          SNOWFLAKE_PRIVATE_KEY: $(SNOWFLAKE_PRIVATE_KEY)

```

---

### 2. Streamlit Configuration (`snowflake.yml`)

The file in your repository can keep standard default values for local development; the pipeline replaces them dynamically during CI/CD:

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
    compute_pool: <% ctx.env.STREAMLIT_CP %>
    main_file: streamlit_app.py
    artifacts:
      - environment.yml
      - streamlit_app.py
      - .streamlit/config.toml

```

---

### 3. Streamlit Python Code (`streamlit_app.py`)

Access the deployed database directly from the active Snowpark session so queries automatically run against whichever target database the app was deployed to:

```python
import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Login Info", layout="wide")

# Get active Snowflake session created for the app
session = get_active_session()

# Resolve current database and schema dynamically
current_db = session.get_current_database()
current_schema = session.get_current_schema()

st.title(f"Application Dashboard ({current_db})")

# Option A: Query tables without hardcoding DB/Schema
query = f"""
    SELECT *
    FROM {current_db}.{current_schema}.LOGIN_INFO
    LIMIT 100;
"""
data_df = session.sql(query).to_pandas()

# Option B: Snowpark DataFrame table lookup
# data_df = session.table("LOGIN_INFO").limit(100).to_pandas()

st.dataframe(data_df)

```
