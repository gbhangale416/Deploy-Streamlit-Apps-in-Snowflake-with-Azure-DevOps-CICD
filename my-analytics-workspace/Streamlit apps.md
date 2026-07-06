Below is a **single Azure DevOps YAML** that:

* ✅ Uses **Azure DevOps Library** (`Snowflake-DEV`)
* ✅ Uses **Azure DevOps REST API** to get the **last successful build**
* ✅ Finds **all apps changed since the last successful deployment**
* ✅ Deploys **only those Streamlit apps**
* ✅ **No `.sh` scripts**
* ✅ One `snowflake.yml` per application
* ✅ Supports any number of Streamlit apps

> **Before using this pipeline**
>
> 1. Enable **"Allow scripts to access the OAuth token"** in the pipeline.
> 2. Ensure each app contains its own `snowflake.yml`.
> 3. Use `fetchDepth: 0` so Git history is available for comparison. Azure DevOps exposes build information (including `sourceVersion`) through the Build REST API. ([Microsoft Learn][1])

```yaml
trigger:
  branches:
    include:
      - main

  paths:
    include:
      - Streamlit_Apps/Apps/**

pool:
  vmImage: ubuntu-latest

variables:
- group: Snowflake-DEV

steps:

# Checkout complete git history
- checkout: self
  fetchDepth: 0

# Install Python
- task: UsePythonVersion@0
  inputs:
    versionSpec: '3.11'

# Install Snowflake CLI
- script: |
    python -m pip install --upgrade pip
    pip install snowflake-cli
  displayName: Install Snowflake CLI

# Configure Snowflake Connection
- script: |
    echo "Configuring Snowflake Connection..."

    export SNOWFLAKE_CONNECTIONS_DEFAULT_ACCOUNT="$(SNOWFLAKE_ACCOUNT)"
    export SNOWFLAKE_CONNECTIONS_DEFAULT_USER="$(SNOWFLAKE_USER)"
    export SNOWFLAKE_CONNECTIONS_DEFAULT_PASSWORD="$(SNOWFLAKE_PASSWORD)"
    export SNOWFLAKE_CONNECTIONS_DEFAULT_ROLE="$(SNOWFLAKE_ROLE)"
    export SNOWFLAKE_CONNECTIONS_DEFAULT_WAREHOUSE="$(SNOWFLAKE_WAREHOUSE)"

    snow connection test
  displayName: Test Snowflake Connection

# Detect changed applications and deploy
- script: |

    set -e

    echo "=============================================="
    echo "Finding Last Successful Pipeline Run"
    echo "=============================================="

    RESPONSE=$(curl -s \
      -H "Authorization: Bearer $SYSTEM_ACCESSTOKEN" \
      "$(System.CollectionUri)$(System.TeamProject)/_apis/build/builds?definitions=$(System.DefinitionId)&resultFilter=succeeded&statusFilter=completed&\$top=1&api-version=7.1")

    LAST_SUCCESSFUL_COMMIT=$(python - <<'PY'
import json,sys
data=json.load(sys.stdin)
if data.get("count",0)>0:
    print(data["value"][0]["sourceVersion"])
PY
<<< "$RESPONSE")

    echo "Last Successful Commit : $LAST_SUCCESSFUL_COMMIT"
    echo "Current Commit         : $(Build.SourceVersion)"

    echo ""

    ##############################################
    # First deployment
    ##############################################

    if [ -z "$LAST_SUCCESSFUL_COMMIT" ]; then

        echo "No previous successful deployment found."

        APPS=$(find Streamlit_Apps/Apps -mindepth 1 -maxdepth 1 -type d -exec basename {} \;)

    else

        echo "Finding changed applications..."

        APPS=$(git diff --name-only \
            $LAST_SUCCESSFUL_COMMIT \
            $(Build.SourceVersion) \
            | grep '^Streamlit_Apps/Apps/' \
            | cut -d'/' -f3 \
            | sort -u || true)

    fi

    echo ""
    echo "Changed Applications"
    echo "===================="
    echo "$APPS"

    if [ -z "$APPS" ]; then
        echo "No Streamlit apps changed."
        exit 0
    fi

    ##############################################
    # Deploy each changed application
    ##############################################

    for APP in $APPS
    do

        echo ""
        echo "======================================="
        echo "Deploying $APP"
        echo "======================================="

        cd Streamlit_Apps/Apps/$APP

        echo "Current Folder:"
        pwd

        ls -la

        snow streamlit deploy \
            --replace \
            --prune

        cd ../../..

        echo "$APP deployed successfully."

    done

    echo ""
    echo "Deployment completed successfully."

  displayName: Detect & Deploy Changed Streamlit Apps

  env:
    SYSTEM_ACCESSTOKEN: $(System.AccessToken)
```

## Repository Layout

```text
STREAMLIT_APP_CICD8R

│
├── azure-pipelines.yml
│
└── Streamlit_Apps
    └── Apps
        ├── Find_User_Details
        │   ├── streamlit_app.py
        │   ├── environment.yml
        │   └── snowflake.yml
        │
        ├── Get_MEMBER_DETAILS
        │   ├── streamlit_app.py
        │   ├── environment.yml
        │   └── snowflake.yml
        │
        └── Hello_world
            ├── streamlit_app.py
            ├── environment.yml
            └── snowflake.yml
```

Each app has its own `snowflake.yml`.

---

### One improvement I'd recommend

The pipeline above uses the **latest successful build**. If you have multiple branches (for example, `main`, `develop`, and release branches), it's better to filter the REST API by the current branch:

```
branchName=$(Build.SourceBranch)
```

when calling the Builds API. That way, the "last successful build" is taken **from the same branch** rather than any branch. Azure DevOps supports filtering build queries by branch. ([Microsoft Learn][1])

This avoids deploying changes based on a successful build from a different branch.

[1]: https://learn.microsoft.com/en-us/rest/api/azure/devops/build/builds/list?view=azure-devops-rest-7.1&utm_source=chatgpt.com "Builds - List - REST API (Azure DevOps Build) | Microsoft Learn"
