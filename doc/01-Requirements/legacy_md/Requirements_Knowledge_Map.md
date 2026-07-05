# Requirements_Knowledge_Map.md

This file is a compact “graph view” of the RAGstream requirements.
It does not redefine behavior; it only names the main nodes and shows how they connect.

## 1. Node index

### 1.1 Requirement documents (REQ_*)

* REQ_MAIN                  = Requirements_Main.md
* REQ_RAG_PIPELINE          = Requirements_RAG_Pipeline.md
* REQ_AGENTSTACK            = Requirements_AgentStack.md
* REQ_INGESTION_MEMORY      = Requirements_Ingestion_Memory.md
* REQ_CONTROLLER            = Requirements_Orchestration_Controller.md
* REQ_GUI                   = Requirements_GUI.md
* REQ_BACKLOG               = Backlog_Future_Features.md

### 1.2 Core concepts (CON_*)

* CON_SuperPrompt           = Structured representation of current ask + context
* CON_Chunk                 = Small text unit with metadata and ID
* CON_DocVectorStore        = Vector store for documents (per project)
* CON_HistoryVectorStore    = Vector store for conversation history
* CON_IngestionPipelineDoc   = Document ingestion pipeline
* CON_IngestionPipelineHist  = History ingestion pipeline (future)
* CON_Controller            = AppController (orchestrates stages)
* CON_GUI_Intermediate      = Button-driven debug GUI
* CON_GUI_Main              = Main GUI with history and LLM calls (future)
* CON_GUI_Advanced          = Advanced GUI with attention controls / agency (future)
* CON_Agent                 = Abstract agent concept (A0, A2, A3, A4, A5)
* CON_Agent_A0              = A0_PreProcessing agent (hybrid: deterministic + optional LLM)
* CON_Agent_A2              = A2_PromptShaper agent (Chooser)
* CON_Agent_A3              = A3_NLIGate agent (Chooser/Extractor)
* CON_Agent_A4              = A4_Condenser agent (Writer/Extractor)
* CON_Agent_A5              = A5_FormatEnforcer agent (Writer)
* CON_AgentFactory          = Neutral factory that builds AgentPrompt from JSON
* CON_AgentPrompt           = Neutral prompt composer for agents
* CON_LLMClient             = llm_client abstraction for OpenAI / future models
* CON_PromptBuilder         = Deterministic final prompt composer
* CON_Project               = Logical project (doc_raw + chroma_db pair)
* CON_ConversationHistory   = Log of prompt/response pairs
* CON_TagSystem             = Tagging of history entries (GOLD, SILVER, etc.)
* CON_S_CTX                 = Condensed context block (facts/constraints/open-issues)
* CON_AttachmentsMD         = Optional raw excerpts region in final prompt

### 1.3 Implementation modules (MOD_*)

(Names are conceptual; actual file paths follow the existing project tree.)

* MOD_Controller            = app/controller.py

* MOD_GUI_Streamlit         = app/ui_streamlit.py

* MOD_SuperPrompt           = super_prompt.py

* MOD_PreProcessing         = preprocessing.py

* MOD_PromptSchema          = prompt_schema.py

* MOD_NameMatcher           = name_matcher.py

* MOD_IngestionManager      = ingestion/ingestion_manager.py

* MOD_Loader                = ingestion/loader.py

* MOD_Chunker               = ingestion/chunker.py

* MOD_Embedder              = ingestion/embedder.py

* MOD_VectorStoreBase       = ingestion/chroma_vector_store_base.py

* MOD_VectorStoreChroma     = ingestion/vector_store_chroma.py

* MOD_FileManifest          = ingestion/file_manifest.py

* MOD_Retriever             = retrieval/retriever.py

* MOD_ReRanker              = retrieval/reranker.py

* MOD_Attention             = retrieval/attention.py

* MOD_AgentFactory          = orchestration/agent_factory.py

* MOD_AgentPrompt           = orchestration/agent_prompt.py

* MOD_LLMClient             = orchestration/llm_client.py

* MOD_PromptBuilder         = orchestration/prompt_builder.py

* MOD_ToolingRegistry       = tooling/registry.py

* MOD_ToolingDispatcher     = tooling/dispatcher.py

* MOD_ToolingBaseTool       = tooling/base_tool.py

* MOD_ToolingMathTool       = tooling/math_tool.py

* MOD_ToolingPyTool         = tooling/py_tool.py

### 1.4 Backlog feature stubs (BF_*)

* BF_TaggedHistory          = Tag-based history filtering (GOLD, SILVER, etc.)
* BF_MultiSessionImport     = Import of selected history from other sessions/projects
* BF_TOONAdapter            = Optional JSON→TOON conversion before LLM calls
* BF_AdvancedGUIControls    = Advanced GUI for attention and multi-history control
* BF_AI_Agency              = Planner/critic around the 8-stage pipeline

## 2. Relations as triples

Format:
NODE_A -> relation -> NODE_B

### 2.1 Requirement-to-requirement

* REQ_MAIN           -> refines          -> REQ_RAG_PIPELINE

* REQ_MAIN           -> refines          -> REQ_AGENTSTACK

* REQ_MAIN           -> refines          -> REQ_INGESTION_MEMORY

* REQ_MAIN           -> refines          -> REQ_CONTROLLER

* REQ_MAIN           -> refines          -> REQ_GUI

* REQ_MAIN           -> references       -> REQ_BACKLOG

* REQ_RAG_PIPELINE   -> consistent_with  -> REQ_AGENTSTACK

* REQ_RAG_PIPELINE   -> consistent_with  -> REQ_INGESTION_MEMORY

* REQ_RAG_PIPELINE   -> consistent_with  -> REQ_CONTROLLER

* REQ_CONTROLLER     -> assumes          -> REQ_AGENTSTACK

* REQ_CONTROLLER     -> assumes          -> REQ_RAG_PIPELINE

* REQ_GUI            -> assumes          -> REQ_CONTROLLER

* REQ_GUI            -> assumes          -> REQ_RAG_PIPELINE

* REQ_BACKLOG        -> extends          -> REQ_RAG_PIPELINE

* REQ_BACKLOG        -> extends          -> REQ_INGESTION_MEMORY

* REQ_BACKLOG        -> extends          -> REQ_GUI

### 2.2 Requirements defining concepts

* REQ_MAIN           -> defines_core     -> CON_SuperPrompt

* REQ_MAIN           -> defines_core     -> CON_Project

* REQ_RAG_PIPELINE   -> defines          -> CON_SuperPrompt

* REQ_RAG_PIPELINE   -> defines          -> CON_Chunk

* REQ_RAG_PIPELINE   -> defines          -> CON_S_CTX

* REQ_RAG_PIPELINE   -> defines          -> CON_AttachmentsMD

* REQ_RAG_PIPELINE   -> defines          -> CON_Agent_A0

* REQ_RAG_PIPELINE   -> defines          -> CON_Agent_A2

* REQ_RAG_PIPELINE   -> defines          -> CON_Agent_A3

* REQ_RAG_PIPELINE   -> defines          -> CON_Agent_A4

* REQ_RAG_PIPELINE   -> defines          -> CON_Agent_A5

* REQ_RAG_PIPELINE   -> defines          -> CON_PromptBuilder

* REQ_AGENTSTACK     -> defines          -> CON_Agent

* REQ_AGENTSTACK     -> defines          -> CON_AgentFactory

* REQ_AGENTSTACK     -> defines          -> CON_AgentPrompt

* REQ_AGENTSTACK     -> defines          -> CON_LLMClient

* REQ_INGESTION_MEMORY -> defines        -> CON_DocVectorStore

* REQ_INGESTION_MEMORY -> defines        -> CON_HistoryVectorStore

* REQ_INGESTION_MEMORY -> defines        -> CON_IngestionPipelineDoc

* REQ_INGESTION_MEMORY -> defines        -> CON_IngestionPipelineHist

* REQ_INGESTION_MEMORY -> defines        -> CON_ConversationHistory

* REQ_CONTROLLER     -> defines          -> CON_Controller

* REQ_GUI            -> defines          -> CON_GUI_Intermediate

* REQ_GUI            -> defines          -> CON_GUI_Main

* REQ_GUI            -> defines          -> CON_GUI_Advanced

* REQ_BACKLOG        -> defines_future   -> CON_TagSystem

### 2.3 Concepts implemented by modules

* CON_SuperPrompt           -> implemented_by -> MOD_SuperPrompt

* CON_Agent_A0              -> implemented_by -> MOD_PreProcessing

* CON_AgentFactory          -> implemented_by -> MOD_AgentFactory

* CON_AgentPrompt           -> implemented_by -> MOD_AgentPrompt

* CON_LLMClient             -> implemented_by -> MOD_LLMClient

* CON_PromptBuilder         -> implemented_by -> MOD_PromptBuilder

* CON_IngestionPipelineDoc  -> implemented_by -> MOD_IngestionManager

* CON_IngestionPipelineDoc  -> uses           -> MOD_Loader

* CON_IngestionPipelineDoc  -> uses           -> MOD_Chunker

* CON_IngestionPipelineDoc  -> uses           -> MOD_Embedder

* CON_IngestionPipelineDoc  -> uses           -> MOD_VectorStoreChroma

* CON_IngestionPipelineDoc  -> uses           -> MOD_FileManifest

* CON_DocVectorStore        -> implemented_by -> MOD_VectorStoreChroma

* CON_DocVectorStore        -> uses           -> MOD_VectorStoreBase

* CON_RAG_Pipeline (implicit) -> uses        -> MOD_Retriever

* CON_RAG_Pipeline (implicit) -> uses        -> MOD_ReRanker

* CON_Controller            -> implemented_by -> MOD_Controller

* CON_GUI_Intermediate      -> implemented_by -> MOD_GUI_Streamlit

* CON_ConversationHistory   -> implemented_by -> (future) history logger modules

* CON_HistoryVectorStore    -> implemented_by -> (future) history vector-store modules

### 2.4 Concept-to-concept relations (functional)

* CON_GUI_Intermediate      -> interacts_with -> CON_Controller

* CON_GUI_Main              -> interacts_with -> CON_Controller

* CON_Controller            -> owns           -> CON_SuperPrompt

* CON_Controller            -> orchestrates   -> CON_Agent_A0

* CON_Controller            -> orchestrates   -> CON_Agent_A2

* CON_Controller            -> orchestrates   -> CON_Agent_A3

* CON_Controller            -> orchestrates   -> CON_Agent_A4

* CON_Controller            -> orchestrates   -> CON_Agent_A5

* CON_Controller            -> orchestrates   -> CON_PromptBuilder

* CON_Agent_A0              -> uses           -> CON_PromptSchema

* CON_Agent_A0              -> reads          -> CON_SuperPrompt

* CON_Agent_A0              -> updates        -> CON_SuperPrompt

* CON_Agent_A2              -> reads          -> CON_SuperPrompt

* CON_Agent_A2              -> uses           -> CON_AgentFactory

* CON_Agent_A2              -> uses           -> CON_AgentPrompt

* CON_Agent_A2              -> uses           -> CON_LLMClient

* CON_Agent_A2              -> updates        -> CON_SuperPrompt

* CON_Agent_A3              -> reads          -> CON_SuperPrompt

* CON_Agent_A3              -> uses           -> CON_AgentFactory

* CON_Agent_A3              -> uses           -> CON_AgentPrompt

* CON_Agent_A3              -> uses           -> CON_LLMClient

* CON_Agent_A3              -> updates        -> CON_SuperPrompt

* CON_Agent_A4              -> reads          -> CON_SuperPrompt

* CON_Agent_A4              -> uses           -> CON_AgentFactory

* CON_Agent_A4              -> uses           -> CON_AgentPrompt

* CON_Agent_A4              -> uses           -> CON_LLMClient

* CON_Agent_A4              -> produces       -> CON_S_CTX

* CON_Agent_A4              -> updates        -> CON_SuperPrompt

* CON_Agent_A5              -> reads          -> CON_SuperPrompt

* CON_Agent_A5              -> uses           -> CON_AgentFactory

* CON_Agent_A5              -> uses           -> CON_AgentPrompt

* CON_Agent_A5              -> uses           -> CON_LLMClient

* CON_Agent_A5              -> updates        -> CON_SuperPrompt

* CON_PromptBuilder         -> reads          -> CON_SuperPrompt

* CON_PromptBuilder         -> builds         -> CON_AttachmentsMD

* CON_PromptBuilder         -> builds         -> final LLM prompt (System + User messages)

* CON_Retrieval (implicit)  -> reads          -> CON_DocVectorStore

* CON_Retrieval (implicit)  -> produces       -> CON_Chunk (hydrated working set + ordered stage snapshot in SuperPrompt)

* CON_Retrieval (implicit)  -> updates        -> CON_SuperPrompt

* CON_ReRanker (implicit)   -> reads          -> CON_Chunk

* CON_ReRanker (implicit)   -> updates        -> stage snapshot and current selection in CON_SuperPrompt

* CON_IngestionPipelineDoc  -> uses           -> CON_Project

* CON_DocVectorStore        -> associated_with -> CON_Project

* CON_ConversationHistory   -> uses           -> CON_TagSystem (future)

* CON_HistoryVectorStore    -> associated_with -> CON_ConversationHistory

### 2.5 Backlog extensions

* REQ_BACKLOG        -> future_ext     -> BF_TaggedHistory

* REQ_BACKLOG        -> future_ext     -> BF_MultiSessionImport

* REQ_BACKLOG        -> future_ext     -> BF_TOONAdapter

* REQ_BACKLOG        -> future_ext     -> BF_AdvancedGUIControls

* REQ_BACKLOG        -> future_ext     -> BF_AI_Agency

* BF_TaggedHistory   -> extends        -> CON_TagSystem

* BF_TaggedHistory   -> extends        -> CON_ConversationHistory

* BF_TaggedHistory   -> extends        -> CON_HistoryVectorStore

* BF_MultiSessionImport -> extends     -> CON_ConversationHistory

* BF_MultiSessionImport -> extends     -> CON_Project

* BF_TOONAdapter     -> extends        -> CON_LLMClient

* BF_TOONAdapter     -> extends        -> CON_PromptBuilder

* BF_AdvancedGUIControls -> extends    -> CON_GUI_Advanced

* BF_AdvancedGUIControls -> extends    -> CON_GUI_Main

* BF_AI_Agency       -> extends        -> CON_Controller

* BF_AI_Agency       -> extends        -> CON_Agent

## 3. Example views

These views are not new relations, only filtered perspectives on the triples above.

### 3.1 From requirements to code

* REQ_AGENTSTACK     -> defines        -> CON_AgentFactory

* CON_AgentFactory   -> implemented_by -> MOD_AgentFactory

* REQ_AGENTSTACK     -> defines        -> CON_AgentPrompt

* CON_AgentPrompt    -> implemented_by -> MOD_AgentPrompt

* REQ_AGENTSTACK     -> defines        -> CON_LLMClient

* CON_LLMClient      -> implemented_by -> MOD_LLMClient

* REQ_CONTROLLER     -> defines        -> CON_Controller

* CON_Controller     -> implemented_by -> MOD_Controller

* REQ_GUI            -> defines        -> CON_GUI_Intermediate

* CON_GUI_Intermediate -> implemented_by -> MOD_GUI_Streamlit

* REQ_INGESTION_MEMORY -> defines      -> CON_IngestionPipelineDoc

* CON_IngestionPipelineDoc -> implemented_by -> MOD_IngestionManager

This view answers: “If this requirement changes, which modules are most likely affected?”

### 3.2 SuperPrompt-centered view

* REQ_MAIN           -> defines_core   -> CON_SuperPrompt

* REQ_RAG_PIPELINE   -> defines        -> CON_SuperPrompt

* CON_Controller     -> owns           -> CON_SuperPrompt

* CON_Agent_A0       -> reads          -> CON_SuperPrompt

* CON_Agent_A0       -> updates        -> CON_SuperPrompt

* CON_Agent_A2       -> reads          -> CON_SuperPrompt

* CON_Agent_A2       -> updates        -> CON_SuperPrompt

* CON_Agent_A3       -> reads          -> CON_SuperPrompt

* CON_Agent_A3       -> updates        -> CON_SuperPrompt

* CON_Agent_A4       -> reads          -> CON_SuperPrompt

* CON_Agent_A4       -> updates        -> CON_SuperPrompt

* CON_Agent_A5       -> reads          -> CON_SuperPrompt

* CON_Agent_A5       -> updates        -> CON_SuperPrompt

* CON_PromptBuilder  -> reads          -> CON_SuperPrompt

This view answers: “Who touches SuperPrompt, and under which requirements is that defined?”

### 3.3 Agent stack view

* REQ_AGENTSTACK     -> defines        -> CON_Agent

* REQ_AGENTSTACK     -> defines        -> CON_AgentFactory

* REQ_AGENTSTACK     -> defines        -> CON_AgentPrompt

* REQ_AGENTSTACK     -> defines        -> CON_LLMClient

* CON_Agent_A0       -> uses           -> CON_AgentFactory (optional later)

* CON_Agent_A2       -> uses           -> CON_AgentFactory

* CON_Agent_A3       -> uses           -> CON_AgentFactory

* CON_Agent_A4       -> uses           -> CON_AgentFactory

* CON_Agent_A5       -> uses           -> CON_AgentFactory

* CON_AgentFactory   -> implemented_by -> MOD_AgentFactory

* CON_AgentPrompt    -> implemented_by -> MOD_AgentPrompt

* CON_LLMClient      -> implemented_by -> MOD_LLMClient

This view answers: “Which parts form the neutral agent infrastructure, and which agents rely on it?”
