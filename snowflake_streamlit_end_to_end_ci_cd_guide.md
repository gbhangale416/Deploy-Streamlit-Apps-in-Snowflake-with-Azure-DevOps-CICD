# Snowflake Native Streamlit CI/CD: Complete End-to-End Implementation Guide

This document contains the complete codebase and technical reference for automating Snowflake Native Streamlit deployments across multi-environment landscapes (DEV, TEST, PROD) using Azure DevOps YAML pipelines, Snowflake CLI (`snow`), Key-Pair authentication (`SNOWFLAKE_JWT`), and Git-diff automated cleanups.

---

## 1. Streamlit App Manifest Configuration (`snowflake.yml`)

Place this file in each application's root directory (e.g., `database/snowflake/coEDW/Streamlit_Apps/SUPPORT/LOGIN_INFO/snowflake.yml`). It uses Snowflake CLI `definition_version: 2` with dynamic templating placeholders (`<% ctx.env.* %>`).

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
```

---

## 2. Dynamic SQL Application Code (`streamlit_app.py`)

Do not hardcode database or schema names. Use `get_active_session()` to dynamically resolve the current deployment context at runtime.

```python
import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Login Info", layout="wide")

# Retrieve active Snowpark session created natively inside Snowflake
session = get_active_session()

# Resolve deployment database and schema dynamically
current_db = session.get_current_database()
current_schema = session.get_current_schema()

st.title(f"Login Info ({current_db}.{current_schema})")

# Construct query using dynamically resolved context
query = f"""
    SELECT *
    FROM {current_db}.{current_schema}.LOGIN_INFO
    LIMIT 100;
"""
df = session.sql(query).to_pandas()

st.dataframe(df)
```

---

## 3. Azure DevOps CI/CD Pipeline (`azure-pipelines.yml`)

This pipeline:
- Validates branch governance (`DEV_TEST` with `TEAM_BRANCH_NAME`, `PROD` with `MASTER_BRANCH_NAME`).
- Uses `fetchDepth: 0` to enable Git history comparison.
- Checks `git diff` for deleted `snowflake.yml` manifests and runs `DROP STREAMLIT IF EXISTS`.
- Decodes unencrypted Base64 private keys into `~/.snowflake/rsa_key.p8` (`chmod 600`).
- Configures `SNOWFLAKE_JWT` authentication in `~/.snowflake/config.toml`.
- Exports `STREAMLIT_DB` and `STREAMLIT_WH` for CLI substitution, then runs `snow streamlit deploy --replace`.

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
        fetchDepth: 0  # Required for git diff history comparison

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

            if [[ "${{ parameters.target_environment }}" == "$TARGET_ENV_DEV_TEST" && "$CURRENT_BRANCH_NAME" != "$TEAM_BRANCH_NAME" ]]; then
              echo "Target environment ${{ parameters.target_environment }} can be used only with $TEAM_BRANCH_NAME branch"
              exit 1
            elif [[ "${{ parameters.target_environment }}" == "$TARGET_ENV_PROD" && "$CURRENT_BRANCH_NAME" != "$MASTER_BRANCH_NAME" ]]; then
              echo "Target environment ${{ parameters.target_environment }} can be used only with $MASTER_BRANCH_NAME branch"
              exit 1
            fi

            echo "Building $CURRENT_BRANCH_NAME against ${{ parameters.target_environment }}"
        env:
          TARGET_ENV_DEV_TEST: $(TARGET_ENV_DEV_TEST)
          TARGET_ENV_PROD: $(TARGET_ENV_PROD)
          TEAM_BRANCH_NAME: $(TEAM_BRANCH_NAME)
          MASTER_BRANCH_NAME: $(MASTER_BRANCH_NAME)

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
        displayName: 'Bash - Sync and Deploy Streamlit Apps'
        inputs:
          targetType: 'inline'
          script: |
            set -e

            function run_streamlit_deploy() {
              ROLE=$1
              WH=$2
              DB=$3
              ENV_NAME=$4

              echo "=========================================================="
              echo "[INFO] Configuring Snowflake connection for $ENV_NAME"
              echo "      DB: $DB | WH: $WH | Role: $ROLE"
              echo "=========================================================="

              mkdir -p ~/.snowflake
              KEY_PATH="$HOME/.snowflake/rsa_key.p8"

              echo "$SNOWFLAKE_PRIVATE_KEY" | base64 -d > "$KEY_PATH"
              chmod 600 "$KEY_PATH"

              cat > ~/.snowflake/config.toml <<EOF
            default_connection_name = "ci"

            [connections.ci]
            account = "$SNOWFLAKE_ACCOUNT"
            user = "$SNOWFLAKE_USER"
            authenticator = "SNOWFLAKE_JWT"
            private_key_file = "$KEY_PATH"
            warehouse = "$WH"
            role = "$ROLE"
            EOF

              chmod 700 ~/.snowflake
              chmod 600 ~/.snowflake/config.toml

              snow sql --connection ci --query "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_WAREHOUSE();"

              BASE_DIR="${{ parameters.streamlitBaseDir }}"

              # ------------------------------------------------------------------
              # STEP 1: GIT DIFF CHECK FOR DELETED APPS
              # ------------------------------------------------------------------
              echo "--------------------------------------------------------"
              echo "[INFO] Checking Git diff for deleted Streamlit apps..."
              echo "--------------------------------------------------------"

              DIFF_TARGET="HEAD~1"
              if ! git rev-parse --verify HEAD~1 >/dev/null 2>&1; then
                DIFF_TARGET=$(git hash-object -t tree /dev/null)
              fi

              DELETED_MANIFESTS=$(git diff --name-only --diff-filter=D "$DIFF_TARGET" HEAD -- "$BASE_DIR/**/snowflake.yml" || true)

              if [ -n "$DELETED_MANIFESTS" ]; then
                echo "$DELETED_MANIFESTS" | while read -r deleted_file; do
                  if [ -n "$deleted_file" ]; then
                    appDir=$(dirname "$deleted_file")
                    appName=$(basename "$appDir")
                    schemaName=$(basename "$(dirname "$appDir")")

                    echo "[WARN] Detected deleted app in Git: $schemaName/$appName"
                    echo "[ACTION] Dropping Streamlit object in Snowflake: $DB.$schemaName.$appName"

                    snow sql --connection ci --query "DROP STREAMLIT IF EXISTS ${DB}.${schemaName}.${appName};"
                    echo "[INFO] Successfully dropped Streamlit app ${DB}.${schemaName}.${appName}"
                  fi
                done
              else
                echo "[INFO] No deleted Streamlit apps detected in Git diff."
              fi

              # ------------------------------------------------------------------
              # STEP 2: SCAN AND DEPLOY EXISTING APPS
              # ------------------------------------------------------------------
              deployFailed=0
              appCount=0

              if [ ! -d "$BASE_DIR" ]; then
                echo "[ERROR] $BASE_DIR not found. Check the path relative to the repo root."
                return 1
              fi

              echo "[INFO] Scanning $BASE_DIR for active Streamlit apps..."

              while IFS= read -r -d '' manifest; do
                appDir=$(dirname "$manifest")
                appName=$(basename "$appDir")
                SchemaName=$(basename "$(dirname "$appDir")")
                appCount=$((appCount + 1))

                echo "----------------------------------------"
                echo "[INFO] Deploying Streamlit app: $SchemaName/$appName to $ENV_NAME"
                echo "----------------------------------------"

                pushd "$appDir" > /dev/null

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

              if [ "$appCount" -eq 0 ]; then
                echo "[WARN] No snowflake.yml files found under $BASE_DIR."
              fi

              if [ "$deployFailed" -ne 0 ]; then
                echo "[ERROR] One or more Streamlit app deployments failed for $ENV_NAME."
                return 1
              fi

              echo "[INFO] All $appCount Streamlit app(s) deployed successfully for $ENV_NAME."
            }

            # Deployment routing based on target_environment
            if [[ "${{ parameters.target_environment }}" == "$TARGET_ENV_DEV_TEST" ]]; then
              echo "[START] Executing DEV deployment..."
              run_streamlit_deploy "$SF_ROLE_DEV" "${SF_WAREHOUSE}${DEV_DB_POSTFIX}" "${DB_NAME}${DEV_DB_POSTFIX}" "dev"

              echo "[START] Executing TEST deployment..."
              run_streamlit_deploy "$SF_ROLE_TEST" "${SF_WAREHOUSE}${TEST_DB_POSTFIX}" "${DB_NAME}${TEST_DB_POSTFIX}" "tst"

              echo "Done with DEV TEST.........."

            elif [[ "${{ parameters.target_environment }}" == "$TARGET_ENV_PROD" ]]; then
              echo "[START] Executing PROD deployment..."
              run_streamlit_deploy "$SF_ROLE" "$SF_WAREHOUSE" "$DB_NAME" "prd"

              echo "Done with PROD.........."
            fi
        env:
          SNOWFLAKE_ACCOUNT: $(SNOWFLAKE_ACCOUNT)
          SNOWFLAKE_USER: $(SNOWFLAKE_USER)
          SNOWFLAKE_PRIVATE_KEY: $(SF_Private_key)
          SF_WAREHOUSE: $(SF_WAREHOUSE)
          SF_ROLE: $(SF_ROLE)
          SF_ROLE_DEV: $(SF_ROLE_DEV)
          SF_ROLE_TEST: $(SF_ROLE_TEST)
          DB_NAME: $(DB_NAME)
          DEV_DB_POSTFIX: $(DEV_DB_POSTFIX)
          TEST_DB_POSTFIX: $(TEST_DB_POSTFIX)
          TARGET_ENV_DEV_TEST: $(TARGET_ENV_DEV_TEST)
          TARGET_ENV_PROD: $(TARGET_ENV_PROD)
```

---

## 4. How to Run the CI/CD Pipeline

### Step 1: Navigate to Azure DevOps
1. Go to **Azure DevOps** > **Pipelines**.
2. Select pipeline: `coedw_Analytics_streamlit`.
3. Click **Run pipeline** in the top-right corner.

### Step 2: Configure Parameters
| Parameter | Value / Selection | Description |
| :--- | :--- | :--- |
| **Branch** | `feature/*` or `main`/`master` | Must match target environment policy (`DEV_TEST` requires team branch; `PROD` requires master branch). |
| **`target_environment`** | `DEV_TEST` or `PROD` | `DEV_TEST` deploys sequentially to `dev` then `tst`. `PROD` deploys directly to `prd`. |
| **`agentPoolName`** | Matching Linux pool | Select `dev-devops-linux-agent-pool`, `tst-devops-linux-agent-pool`, or `prd-devops-linux-agent-pool`. |
| **`streamlitBaseDir`** | Directory path | Defaults to `database/snowflake/coEDW/Streamlit_Apps`. Subpaths can be specified to deploy a single app. |

### Step 3: Trigger and Verify
1. Click **Run**.
2. Confirm the pipeline logs show successful JWT authentication and app deployments:
   ```text
   [INFO] Successfully deployed SUPPORT/LOGIN_INFO
   [INFO] All 1 Streamlit app(s) deployed successfully for dev.
   [INFO] All 1 Streamlit app(s) deployed successfully for tst.
   ```
3. Verify the entities in Snowflake:
   ```sql
   SHOW STREAMLITS IN SCHEMA COEDW_DEV.SUPPORT;
   SHOW STREAMLITS IN SCHEMA COEDW_TST.SUPPORT;
   ```

---

## 5. What is NOT Supported & Platform Limitations

The following architectural restrictions must be factored into application design; they cannot be resolved automatically by CI/CD scripts:

1. **Hardcoded Secondary/External Databases in Python Code**:
   - `session.get_current_database()` only resolves the database where the Streamlit app itself was deployed.
   - If Python code contains raw SQL referencing other databases (e.g., `SELECT * FROM RAW_DEV.SCHEMA.TABLE` or `SHARED_DEV.SCHEMA.TABLE`), the pipeline **will NOT replace or rename them**.
   - When deployed to `PROD`, those queries will still attempt to hit the `DEV` database, causing access denied errors or cross-environment data leakage.
   - *Mitigation:* Create local views inside the app's local schema pointing to external sources, or resolve external database names via a dynamic configuration lookup.

2. **Hardcoded Warehouses in SQL (`USE WAREHOUSE`)**:
   - The pipeline dynamically configures the warehouse **only** in `snowflake.yml` (`query_warehouse`).
   - Any explicit `session.sql("USE WAREHOUSE ...")` commands inside `streamlit_app.py` bypass this setting and are **not** replaced. In higher environments, they will fail with permission errors or run on the wrong compute size.

3. **Runtime Access to Pipeline/OS Environment Variables**:
   - Variables set in Azure DevOps (or via `export VAR=val`) exist **only on the build agent during the CI/CD run**.
   - Streamlit app code executing inside Snowflake cannot read build agent environment variables via `os.environ` at runtime.
   - *Mitigation:* Manage external API credentials and secrets natively in Snowflake using **Snowflake Secrets** and **External Access Integrations (EAI)**.

4. **Python Packages Outside the Snowflake Anaconda Channel**:
   - `environment.yml` can only load packages available in Snowflake’s official Anaconda channel.
   - Native Streamlit apps cannot run `pip install` from public internet repositories at runtime. Custom packages or unsupported wheels must be manually uploaded to a Snowflake internal stage and referenced as stage artifacts.

5. **In-Memory Session State Across Deployments**:
   - Deploying with `--replace` recreates the Streamlit application entity.
   - Any active in-memory user sessions (`st.session_state`) and cached data will be instantly cleared upon deployment. Persistent user data must be written to Snowflake tables.

6. **Automatic Multi-Region / Cross-Account Replication**:
   - The deployment task strictly targets the account specified in `SNOWFLAKE_ACCOUNT`.
   - The pipeline does not automatically replicate staged files, metadata, or Streamlit app instances across secondary Snowflake regions or accounts.