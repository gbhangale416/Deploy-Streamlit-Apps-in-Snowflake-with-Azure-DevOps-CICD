Based on your structure:

```text
database/
└── snowflake/
    └── coEDW/
        └── Streamlit_Apps/
            ├── SUPPORT/
            │   ├── Find_User_Details/
            │   │   ├── snowflake.yml
            │   │   ├── streamlit_app.py
            │   │   └── environment.yml
            │   └── Get_MEMBER_DETAILS/
            │       ├── snowflake.yml
            │       ├── streamlit_app.py
            │       └── environment.yml
            │
            ├── SALES/
            ├── HR/
            └── ...
```

Below is an **enterprise-ready Azure DevOps pipeline** that:

* ✅ No shell script files
* ✅ Uses Azure DevOps Library
* ✅ Uses Azure DevOps REST API
* ✅ Compares **last successful deployment → current commit**
* ✅ Supports **any schema**
* ✅ Supports **unlimited Streamlit apps**
* ✅ Deploys only changed apps

---

```yaml
parameters:
- name: App_Root_Path
  displayName: Streamlit Root Path
  type: string
  default: database/snowflake/coEDW/Streamlit_Apps

trigger: none

pool:
  name: prd-devops-linux-agent-pool

variables:
- group: Snowflake-DEV

steps:

# Checkout complete history
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

# Deploy Changed Streamlit Apps
- task: Bash@3
  displayName: Detect and Deploy Changed Streamlit Apps

  env:
    SYSTEM_ACCESSTOKEN: $(System.AccessToken)

    SNOWFLAKE_CONNECTIONS_DEFAULT_ACCOUNT: $(SNOWFLAKE_ACCOUNT)
    SNOWFLAKE_CONNECTIONS_DEFAULT_USER: $(SNOWFLAKE_USER)
    SNOWFLAKE_CONNECTIONS_DEFAULT_PASSWORD: $(SNOWFLAKE_PASSWORD)
    SNOWFLAKE_CONNECTIONS_DEFAULT_ROLE: $(SNOWFLAKE_ROLE)
    SNOWFLAKE_CONNECTIONS_DEFAULT_WAREHOUSE: $(SNOWFLAKE_WAREHOUSE)

  inputs:
    targetType: inline

    script: |

      set -e

      echo "======================================="
      echo "Finding last successful deployment"
      echo "======================================="

      RESPONSE=$(curl -s \
        -H "Authorization: Bearer $SYSTEM_ACCESSTOKEN" \
        "$(System.CollectionUri)$(System.TeamProject)/_apis/build/builds?definitions=$(System.DefinitionId)&branchName=$(Build.SourceBranch)&resultFilter=succeeded&statusFilter=completed&\$top=1&api-version=7.1")

      LAST_SUCCESSFUL_COMMIT=$(echo "$RESPONSE" | python3 -c "
import sys,json
data=json.load(sys.stdin)
print(data['value'][0]['sourceVersion'] if data['count']>0 else '')
")

      echo "Last Successful Commit : $LAST_SUCCESSFUL_COMMIT"
      echo "Current Commit         : $(Build.SourceVersion)"

      APP_ROOT="${{ parameters.App_Root_Path }}"

      echo ""
      echo "Application Root : $APP_ROOT"

      #############################################
      # First deployment
      #############################################

      if [ -z "$LAST_SUCCESSFUL_COMMIT" ]; then

          echo ""
          echo "First deployment detected."

          CHANGED_APPS=$(find "$APP_ROOT" \
              -mindepth 2 \
              -maxdepth 2 \
              -type d \
              | sed "s|$APP_ROOT/||")

      else

          echo ""
          echo "Finding changed applications..."

          CHANGED_APPS=$(git diff --name-only \
              "$LAST_SUCCESSFUL_COMMIT" \
              "$(Build.SourceVersion)" \
              | grep "^$APP_ROOT/" \
              | awk -F'/' '{print $(NF-2)"/"$(NF-1)}' \
              | sort -u || true)

      fi

      echo ""
      echo "Changed Applications"
      echo "===================="

      echo "$CHANGED_APPS"

      if [ -z "$CHANGED_APPS" ]; then
          echo ""
          echo "No Streamlit applications changed."
          exit 0
      fi

      ###################################################
      # Deploy
      ###################################################

      for APP in $CHANGED_APPS
      do

          SCHEMA=$(echo "$APP" | cut -d'/' -f1)
          APP_NAME=$(echo "$APP" | cut -d'/' -f2)

          echo ""
          echo "======================================="
          echo "Schema : $SCHEMA"
          echo "App    : $APP_NAME"
          echo "======================================="

          cd "$APP_ROOT/$SCHEMA/$APP_NAME"

          pwd

          ls -la

          snow streamlit deploy \
            --replace \
            --prune

          cd - > /dev/null

      done

      echo ""
      echo "Deployment completed successfully."
```

---

# Example

If the following files changed:

```
database/snowflake/coEDW/Streamlit_Apps/SUPPORT/Find_User_Details/streamlit_app.py

database/snowflake/coEDW/Streamlit_Apps/SALES/Sales_Dashboard/environment.yml

database/snowflake/coEDW/Streamlit_Apps/HR/Employee_App/snowflake.yml
```

The pipeline automatically discovers:

```
SUPPORT/Find_User_Details

SALES/Sales_Dashboard

HR/Employee_App
```

and executes:

```
cd database/snowflake/coEDW/Streamlit_Apps/SUPPORT/Find_User_Details
snow streamlit deploy --replace --prune

cd database/snowflake/coEDW/Streamlit_Apps/SALES/Sales_Dashboard
snow streamlit deploy --replace --prune

cd database/snowflake/coEDW/Streamlit_Apps/HR/Employee_App
snow streamlit deploy --replace --prune
```

without any hardcoded schema or application names.

> **Important:** Ensure your pipeline has **"Allow scripts to access the OAuth token"** enabled. Also verify that every application directory contains its own valid `snowflake.yml`, because `snow streamlit deploy` reads the configuration from the current working directory.
