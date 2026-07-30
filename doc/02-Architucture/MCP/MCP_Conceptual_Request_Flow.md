## 1. Start with the basic picture

Two programs communicate:

```text
Client program → sends a request → Server program
Client program ← receives a response ← Server program
```

In your case:

* **Client**: ChatGPT or Claude.
* **Server**: your GHOST MCP service.
* **Request**: “List your tools” or “Run `ghost_engineer_prompt`.”
* **Response**: tool information or the engineered prompt.

---

# 2. What is HTTP?

**HTTP means Hypertext Transfer Protocol.**

It is a standard format for sending requests and responses over a network.

A normal HTTP conversation is:

```text
Client opens connection
→ sends one request
→ server sends one response
→ communication finishes
```

Example:

```text
ChatGPT:
POST /mcp
Here is an MCP command.

GHOST:
200 OK
Here is the MCP result.
```

`POST` means: “I am sending data to this address.”

`/mcp` is the address inside your server.

---

# 3. What is a WebSocket?

A **WebSocket** is a connection that remains open so both sides can send messages at any time.

Normal HTTP:

```text
Client asks
→ server answers
→ connection is finished
```

WebSocket:

```text
Client and server open one connection
→ connection remains open
→ client can send messages
→ server can send messages
→ either side can send again later
```

Analogy:

* Normal HTTP is like sending individual letters.
* WebSocket is like keeping a telephone call open.

Streamlit usually keeps the browser connected to its Python process through a WebSocket. That allows the page to update when Python changes something.

For example:

```text
You click a Streamlit button
→ browser sends the event through the open WebSocket
→ Python executes the button code
→ Streamlit sends the updated page information back
```

Your MCP server does **not** currently use Streamlit’s WebSocket mechanism. It uses **Streamable HTTP**, which is the HTTP transport defined by the Model Context Protocol.

---

# 4. What does Streamlit hide from you?

When you run:

```bash
streamlit run app.py
```

Streamlit internally creates:

* a network server,
* browser communication,
* user-session handling,
* page updates,
* event handling,
* communication between the browser and Python.

You usually see only:

```python
st.button(...)
st.text_area(...)
```

So Streamlit hides most server infrastructure.

Your MCP service exposes the infrastructure more clearly because you are building a protocol server rather than a browser user interface.

---

# 5. The five objects in your MCP service

```text
Uvicorn
→ Starlette
→ Streamable HTTP Session Manager
→ MCP Server
→ GHOST Tool
```

Each object solves a different problem.

---

## 5.1 Uvicorn

**What is it?**

Uvicorn is a network server program.

Its job is to open a numbered network door, for example:

```text
127.0.0.1:8000
```

* `127.0.0.1` means: only this computer.
* `8000` is the port.
* A **port** is a numbered entrance used to reach a particular running program.

Uvicorn waits for incoming HTTP requests.

When a request arrives, Uvicorn gives it to Starlette.

```text
Incoming HTTP request
→ Uvicorn
→ Starlette
```

Uvicorn does not understand:

* Model Context Protocol,
* GHOST tools,
* prompt engineering,
* A2 PromptShaper.

It only understands network and HTTP communication.

### Why is Uvicorn necessary?

Because the Starlette object cannot independently open a network port.

Starlette describes how requests should be handled. Uvicorn actually receives those requests from the network.

---

## 5.2 Starlette

**What is it?**

Starlette is a web-application framework.

A framework is reusable code that provides common functionality. Here, Starlette provides:

* address routing,
* startup handling,
* shutdown handling,
* connection between Uvicorn and your Python handlers.

### What is routing?

Routing means deciding which Python code should receive a particular address.

Your Starlette application contains a rule similar to:

```text
/mcp → MCP request handler
```

When Starlette receives:

```text
POST /mcp
```

it checks its routes and finds the code responsible for `/mcp`.

### Why is Starlette necessary?

Uvicorn receives HTTP requests, but it does not decide what `/mcp` means.

Starlette provides that mapping:

```text
Requested address → corresponding Python handler
```

You could replace Starlette with another web framework or manually write this logic, but Starlette provides it cleanly.

---

## 5.3 Streamable HTTP Session Manager

The complete name is:

**Streamable HTTP Session Manager**

It belongs to the Model Context Protocol Python library.

### What is its job?

It handles the transport of Model Context Protocol messages through HTTP.

It receives the raw request from Starlette and performs work such as:

* reading the request data,
* checking whether the HTTP method is allowed,
* interpreting the Model Context Protocol message,
* passing the message to the MCP server,
* converting the MCP result into an HTTP response.

It contains the MCP server through this relationship:

```python
session_manager = StreamableHTTPSessionManager(
    app=mcp_server,
    ...
)
```

Inside the session manager:

```text
session_manager.app → mcp_server
```

### Why is it necessary?

The MCP server understands Model Context Protocol commands, but it does not directly handle HTTP network communication.

The session manager connects:

```text
HTTP communication ↔ Model Context Protocol server
```

### What does “session” mean here?

A session normally means an ongoing communication context between a client and server.

However, your configuration uses:

```python
stateless=True
```

That means each request should work independently. The server does not require a previous request to understand the next request.

The class is still called a session manager because it implements the general Streamable HTTP transport, which can also support session-based operation.

---

## 5.4 MCP Server

**MCP means Model Context Protocol.**

The MCP server is the object that understands Model Context Protocol commands.

Examples:

```text
tools/list
tools/call
```

### `tools/list`

This means:

```text
Tell the client which tools you provide.
```

The MCP server calls your registered `handle_list_tools` method.

### `tools/call`

This means:

```text
Execute a particular tool with these arguments.
```

The MCP server calls your registered `handle_call_tool` method.

### Why is the MCP server necessary?

The session manager transports MCP messages through HTTP.

The MCP server understands what those MCP messages mean.

```text
Session manager:
“I received an MCP message.”

MCP server:
“This message says tools/call, so I must call the tool handler.”
```

The MCP server does not perform GHOST prompt engineering itself. It only dispatches the request to the registered GHOST code.

---

## 5.5 GHOST Tool

This is your actual application logic.

It receives something like:

```text
User request: Explain retrieval-augmented generation.
```

Then it:

```text
creates a new SuperPrompt
→ runs GHOST preprocessing
→ runs A2 PromptShaper
→ reads prompt_ready
→ returns the engineered prompt
```

The GHOST tool does not understand:

* ports,
* HTTP,
* Starlette routes,
* Uvicorn,
* network connections.

That separation is deliberate. Your GHOST logic can be tested without starting a web server.

---

# 6. Complete request flow

Suppose ChatGPT sends an MCP command:

```text
tools/call
tool name: ghost_engineer_prompt
```

The exact flow is:

```text
1. ChatGPT sends an HTTP request to /mcp.

2. Uvicorn receives the request on port 8000.

3. Uvicorn gives the request to the Starlette application.

4. Starlette sees that the requested address is /mcp.

5. Starlette calls the configured MCP HTTP handler.

6. The handler passes the request to the
   Streamable HTTP Session Manager.

7. The Session Manager reads the MCP message.

8. The Session Manager passes the message to the MCP Server.

9. The MCP Server sees the command tools/call.

10. The MCP Server calls handle_call_tool.

11. handle_call_tool calls GhostMcpApplication.

12. GhostMcpApplication calls GhostEngineerPromptTool.

13. The GHOST tool runs preprocessing and A2 PromptShaper.

14. The result returns to the MCP Server.

15. The MCP Server returns it to the Session Manager.

16. The Session Manager creates the HTTP response.

17. Starlette passes the response to Uvicorn.

18. Uvicorn sends the response back to ChatGPT.
```

Compact form:

```text
ChatGPT
→ Uvicorn
→ Starlette
→ Session Manager
→ MCP Server
→ GHOST Tool

GHOST result
→ MCP Server
→ Session Manager
→ Starlette
→ Uvicorn
→ ChatGPT
```

---

# 7. Where asynchronous programming appears

**Asynchronous** means that when one operation is waiting, the program can work on another operation instead of freezing the entire server.

Example:

```text
Request A is waiting for network data.
→ The server pauses Request A.
→ The server works on Request B.
→ When Request A's data arrives, the server continues Request A.
```

It normally happens in the same main thread through an event loop.

An **event loop** is a controller that watches many waiting operations and resumes each one when it becomes ready.

This is different from a thread.

A **thread** is a separate execution path that can run code independently.

In your server:

* Uvicorn, Starlette, and the session manager use asynchronous operations.
* GHOST preprocessing and A2 are currently synchronous operations.
* Therefore, `anyio.to_thread.run_sync(...)` moves the synchronous GHOST work into a worker thread, preventing it from blocking the asynchronous network server.

---

# 8. Comparison with Streamlit

```text
MCP service                         Streamlit application
────────────────────────────────────────────────────────────
Uvicorn                             Streamlit's internal network server

Starlette                           Streamlit's internal web application
                                    and routing system

Streamable HTTP Session Manager     Streamlit's browser communication and
                                    session mechanisms

MCP Server                          No direct Streamlit equivalent because
                                    Streamlit does not speak MCP

GHOST Tool                          Your controller, retrieval, memory,
                                    agents, and other application logic
```

Streamlit bundles and hides most of the left side.

The MCP service shows the layers because each layer comes from a different library and has a separate responsibility.
