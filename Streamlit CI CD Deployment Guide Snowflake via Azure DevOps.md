# Streamlit CI/CD Deployment Guide

**Snowflake Native Streamlit Apps via Azure DevOps**

Pipeline: `coedw_Analytics_streamlit` · Example app: `SUPPORT/LOGIN_INFO`

## Overview

This guide explains how to deploy Streamlit apps to Snowflake across environments (`dev`, `tst`, `prd`) using a single Azure DevOps pipeline. The same code is promoted unchanged; environment-specific values are injected at deploy time.

| Step | What you do | Where |
| --- | --- | --- |
| A | Parameterize database and warehouse | `snowflake.yml` |
| B | Resolve database and schema dynamically | `streamlit_app.py` |
| C | Run and verify the pipeline | Azure DevOps and Snowflake |
| D | Know the limitations | Design and review |

## A. Changes Required in the Streamlit App (`snowflake.yml`)

Replace hardcoded database and warehouse values with Snowflake CLI template variables (`<% ctx.env.* %>`). The pipeline sets these variables per target environment.

**1. Streamlit Container Runtime app**

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
    main_file: streamlit_app.py
    query_warehouse: <% ctx.env.STREAMLIT_WH %>
    compute_pool: "STREAMLIT_TEST_COMPUTE_POOL_CPU"
    runtime_name: SYSTEM$ST_CONTAINER_RUNTIME_PY3_11
    artifacts:
      - requirements.txt
      - streamlit_app.py
      - .streamlit/config.toml
```

**2. Streamlit Warehouse Runtime app**

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

## B. Dynamic SQL Queries (`streamlit_app.py`)

Do not hardcode database or schema names in SQL statements. Retrieve the active deployment context dynamically via Snowpark.

```python
import streamlit as st
from snowflake.snowpark.context import get_active_session

# Retrieve active Snowpark session created by Snowflake for this app
session = get_active_session()

# Resolve current database and schema dynamically
current_db = session.get_current_database()
current_schema = session.get_current_schema()

# Build queries dynamically without hardcoding environment DB names
query = f"""
    SELECT *
    FROM {current_db}.{current_schema}.LOGIN_INFO
    LIMIT 100;
"""
df = session.sql(query).to_pandas()

st.title(f"Login Info ({current_db})")
st.dataframe(df)
```

## C. How to Run the CI/CD Pipeline

### 1. Navigate to the Pipeline

1. Open **Azure DevOps** > **Pipelines** and select `coedw_Analytics_streamlit`.
2. Click **Run pipeline** in the top-right corner.

### 2. Parameters to Select

| Parameter | Value | Notes |
| --- | --- | --- |
| **Branch** | Feature/team branch for `DEV_TEST`; `main` (or `master`) for `PROD` | The pipeline fails automatically if the branch does not match the target environment policy. |
| **Environment** (`target_environment`) | `DEV_TEST` | Deploys sequentially to both `dev` and `tst` Snowflake environments. |
|  | `PROD` | Deploys directly to the `prd` Snowflake environment. |
| **Agent Pool** (`agentPoolName`) | `dev-devops-linux-agent-pool`, `tst-devops-linux-agent-pool` or `prd-devops-linux-agent-pool` | Choose the pool matching your target environment. |
| **Streamlit Root Path** (`streamlitBaseDir`) | Default: `database/snowflake/coEDW/Streamlit_Apps` | Scans and deploys all apps. |
|  | Subfolder, e.g. `database/snowflake/coEDW/Streamlit_Apps/SUPPORT/LOGIN_INFO` | Deploys only that one app. |

### 3. Execution and Verification

1. Click **Run**.
2. Confirm the logs show successful JWT authentication and deployment:

```text
[INFO] Successfully deployed SUPPORT/LOGIN_INFO
[INFO] All 1 Streamlit app(s) deployed successfully for dev.
[INFO] All 1 Streamlit app(s) deployed successfully for tst.
```

3. Verify in Snowflake using Snowsight or SQL:

```sql
SHOW STREAMLITS IN SCHEMA COEDW_DEV.SUPPORT;
SHOW STREAMLITS IN SCHEMA COEDW_TST.SUPPORT;
```

## D. What Is NOT Supported and Limitations

### Summary

| # | Limitation | Impact | Mitigation |
| --- | --- | --- | --- |
| 1 | Hardcoded secondary or external databases in Python code | Queries hit the wrong environment | Local views or dynamic config lookup |
| 2 | Hardcoded warehouses (`USE WAREHOUSE`) | Permission errors or wrong compute size | Remove; rely on `query_warehouse` |
| 3 | Runtime access to pipeline or OS environment variables | Values unavailable to app code | Snowflake Secrets and External Access Integrations |
| 4 | Packages outside the runtime's supported sources | App fails to load dependencies | Warehouse: upload to a stage. Container: use an EAI for PyPI |
| 5 | In-memory session state across deployments | Sessions and cache cleared | Persist user data in Snowflake tables |
| 6 | Automatic multi-region or cross-account replication | Other regions and accounts not updated | Deploy separately per account |

### Details

**1. Hardcoded Secondary/External Databases in Python Code**

- `session.get_current_database()` only resolves the database where the Streamlit app is deployed.
- If Python code contains raw SQL referencing other databases (e.g. `SELECT * FROM RAW_DEV.SCHEMA.TABLE` or `SHARED_DEV.SCHEMA.TABLE`), the pipeline **will not** replace or rename them.
- When deployed to `PROD`, those queries still attempt to hit the `DEV` database, causing access denied errors or cross-environment data leakage.
- *Mitigation:* Create local views inside the app's schema pointing to external sources, or resolve external database names via a dynamic configuration lookup.

**2. Hardcoded Warehouses in SQL (`USE WAREHOUSE`)**

- The pipeline configures the warehouse **only** in `snowflake.yml` (`query_warehouse`).
- Any explicit `session.sql("USE WAREHOUSE ...")` in `streamlit_app.py` bypasses this setting and is **not** replaced. In higher environments, it fails with permission errors or runs on the wrong compute size.

*Applies to the Warehouse Runtime. Container Runtime apps set compute with `compute_pool` instead of relying on the query warehouse alone.*

**3. Runtime Access to Pipeline/OS Environment Variables**

- Variables set in Azure DevOps (or via `export VAR=val`) exist **only on the build agent during the CI/CD run**.
- Streamlit app code running inside Snowflake cannot read build agent environment variables via `os.environ` at runtime.
- *Mitigation:* Manage external API credentials and secrets natively in Snowflake using **Snowflake Secrets** and **External Access Integrations (EAI)**.

**4. Package Sources Differ by Runtime**

- **Warehouse Runtime:** `environment.yml` can only load packages from Snowflake's Anaconda channel. Apps cannot `pip install` from public repositories at runtime; custom packages or unsupported wheels must be uploaded to a Snowflake internal stage and referenced as stage artifacts.
- **Container Runtime:** dependencies come from `requirements.txt` and can reach PyPI only if an External Access Integration allows it. Confirm the current behavior in Snowflake's documentation before relying on it.

**5. In-Memory Session State Across Deployments**

- Deploying with `--replace` recreates the Streamlit application entity.
- Active in-memory user sessions (`st.session_state`) and cached data are cleared immediately on deployment. Persistent user data must be written to Snowflake tables.

**6. Automatic Multi-Region / Cross-Account Replication**

- The deployment task strictly targets the account specified in `SNOWFLAKE_ACCOUNT`.
- The pipeline does not automatically replicate staged files, metadata or Streamlit app instances across secondary Snowflake regions or accounts.

## Quick Checklist Before You Deploy

- [ ] `snowflake.yml` uses `<% ctx.env.STREAMLIT_DB %>` and `<% ctx.env.STREAMLIT_WH %>`
- [ ] No hardcoded database, schema or warehouse names in `streamlit_app.py`
- [ ] Correct branch selected for the target environment
- [ ] Correct agent pool selected
- [ ] Logs show successful deployment; `SHOW STREAMLITS` confirms the app exists
