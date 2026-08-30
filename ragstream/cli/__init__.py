"""Execute owner-scoped CLI commands for the GHOST MCP application.

The package contains the backend used by the future MCP adapter. It keeps
command policy, durable command state, and execution coordination separate
while exposing no MCP or HTTP behavior itself.

Main modules:
    command_policy:
        Decides whether an exact command needs user confirmation.
    command_store:
        Persists confirmations and asynchronous job state in SQLite.
    command_service:
        Runs commands locally or through AWS Systems Manager.
"""