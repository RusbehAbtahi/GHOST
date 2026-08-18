# SAM builds RuntimeControlFunction from the repository root so that both the
# Lambda-specific code and the shared Cognito authentication module are inside
# the build context.

# Avoid Makefile's TAB requirement for command lines.
.RECIPEPREFIX := >

build-RuntimeControlFunction:
>python3 -m pip install \
>    --requirement lambda/runtime_control/requirements.txt \
>    --target "$(ARTIFACTS_DIR)"

># Copy the Lambda-specific runtime-control package.
>mkdir -p "$(ARTIFACTS_DIR)/ghost_runtime_control"
>cp -R \
>    lambda/runtime_control/ghost_runtime_control/. \
>    "$(ARTIFACTS_DIR)/ghost_runtime_control/"

># Package the existing shared Cognito authentication implementation.
>mkdir -p "$(ARTIFACTS_DIR)/ragstream/mcp"
>cp \
>    ragstream/__init__.py \
>    "$(ARTIFACTS_DIR)/ragstream/__init__.py"
>cp \
>    ragstream/mcp/__init__.py \
>    "$(ARTIFACTS_DIR)/ragstream/mcp/__init__.py"
>cp \
>    ragstream/mcp/auth.py \
>    "$(ARTIFACTS_DIR)/ragstream/mcp/auth.py"