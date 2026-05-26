# Local Project Tree

```
/home/rusbeh_ab/project/RAGstream
├── Run.txt
├── __init__.py
├── diag_chroma_wo_ort.txt
├── requirements-dev.txt
├── requirements.txt
├── ragstream
│   ├── MD_Print.py
│   ├── __init__.py
│   ├── __pycache__
│   ├── agents
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   ├── a1_dci.py
│   │   ├── a2_promptshaper.py
│   │   ├── a3_nli_gate.py
│   │   ├── a4_condenser.py
│   │   ├── a4_det_processing.py
│   │   └── a4_llm_helper.py
│   ├── app
│   │   ├── Hook_ChatGTP.py
│   │   ├── Hook_ChatGTP2.py
│   │   ├── Hook_ChatGTP_TO_DO.txt
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   ├── agents.py
│   │   ├── controller.py
│   │   ├── controller_legacy.py
│   │   ├── pipeline_runner.py
│   │   ├── ui_actions.py
│   │   ├── ui_actions_files.py
│   │   ├── ui_files.py
│   │   ├── ui_layout.py
│   │   ├── ui_metrics.py
│   │   ├── ui_settings.py
│   │   └── ui_streamlit.py
│   ├── config
│   │   ├── __init__.py
│   │   ├── prompt_schema.json
│   │   ├── runtime_config.json
│   │   └── settings.py
│   ├── ingestion
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   ├── chroma_vector_store_base.py
│   │   ├── chunker.py
│   │   ├── embedder.py
│   │   ├── file_manifest.py
│   │   ├── ingestion_manager.py
│   │   ├── loader.py
│   │   ├── splade_embedder.py
│   │   ├── splade_vector_store_base.py
│   │   ├── vector_store_chroma.py
│   │   └── vector_store_splade.py
│   ├── memory
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   ├── compression
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   ├── memory_active_retrieval_brief.py
│   │   │   ├── memory_activebrief_relevance_gate.py
│   │   │   ├── memory_compressor.py
│   │   │   └── memory_sentence_reducer.py
│   │   ├── importers
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   ├── chatgpt_shared_link_importer.py
│   │   │   └── chatgpt_shared_link_importer_helpers.py
│   │   ├── ingestion
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   ├── memory_chunker.py
│   │   │   ├── memory_ingestion_manager.py
│   │   │   └── memory_vector_store.py
│   │   ├── memory_actions.py
│   │   ├── memory_manager.py
│   │   ├── memory_merge_synthesizer.py
│   │   ├── memory_record.py
│   │   ├── retrieval
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   ├── memory_context_pack.py
│   │   │   ├── memory_index_lookup.py
│   │   │   └── memory_scoring.py
│   │   └── storage
│   │       ├── __init__.py
│   │       ├── __pycache__
│   │       └── memory_file_manager.py
│   ├── orchestration
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   ├── agent_factory.py
│   │   ├── agent_prompt.py
│   │   ├── agent_prompt_helpers
│   │   │   ├── __init__.py
│   │   │   ├── __pycache__
│   │   │   ├── compose_texts.py
│   │   │   ├── config_loader.py
│   │   │   ├── field_normalizer.py
│   │   │   ├── json_parser.py
│   │   │   └── schema_map.py
│   │   ├── llm_client.py
│   │   ├── prompt_builder.py
│   │   ├── super_prompt.py
│   │   └── superprompt_projector.py
│   ├── preprocessing
│   │   ├── __pycache__
│   │   ├── activebrief_relation_classifier.py
│   │   ├── name_matcher.py
│   │   ├── preprocessing.py
│   │   └── prompt_schema.py
│   ├── retrieval
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   ├── attention.py
│   │   ├── chunk.py
│   │   ├── doc_score.py
│   │   ├── reranker.py
│   │   ├── retriever.py
│   │   ├── retriever_emb.py
│   │   ├── retriever_mem.py
│   │   ├── retriever_splade.py
│   │   ├── rrf_merger.py
│   │   └── smart_query_splitter.py
│   ├── textforge
│   │   ├── CliSink.py
│   │   ├── FileSink.py
│   │   ├── GUISink.py
│   │   ├── RagLog.py
│   │   ├── TextForge.py
│   │   ├── TextSink.py
│   │   ├── __init__.py
│   │   └── __pycache__
│   └── utils
│       ├── __init__.py
│       ├── __pycache__
│       ├── logging.py
│       └── paths.py
└── data
    ├── A2_SLM_Training
    │   ├── A2_dataset_list.json
    │   ├── Create_DataSet.py
    │   ├── conversations.json
    │   └── file_manifest.json
    ├── agents
    │   ├── Template
    │   │   └── Selector.json
    │   ├── a2_promptshaper
    │   │   ├── 003.json
    │   │   ├── Old_Versions
    │   │   │   ├── 001.json
    │   │   │   └── 002.json
    │   │   └── a2_catalogs
    │   │       ├── 003_option_catalogs_rest.json
    │   │       └── 003_option_catalogs_system.json
    │   ├── a3_nli_gate
    │   │   ├── 001.json
    │   │   ├── 002.json
    │   │   └── a3_catalogs
    │   │       ├── 001_option_catalogs_labels.json
    │   │       └── 002_option_catalogs_labels.json
    │   ├── a4_condenser
    │   │   ├── chunk_classifier
    │   │   │   └── a4_2_001.json
    │   │   ├── chunk_phraser
    │   │   │   └── a4_1_001.json
    │   │   └── final_condenser
    │   │       └── a4_3_001.json
    │   ├── activebrief_relation_classifier
    │   │   └── activebrief_relation_classifier_001.json
    │   ├── memory_activebrief_qa_summarizer
    │   │   ├── memory_activebrief_qa_summarizer_init_001.json
    │   │   └── memory_activebrief_qa_summarizer_update_001.json
    │   └── memory_synthesizer
    │       └── memory_synthesizer_001.json
    ├── chroma_db
    │   ├── EMb treshhold
    │   │   ├── a436251d-1b0f-4f9b-91cd-dd13446fc2de
    │   │   └── file_manifest.json
    │   ├── MOVIES
    │   │   ├── 5a90e8ef-39b2-44be-9e13-c87268f9e221
    │   │   └── file_manifest.json
    │   ├── TESt2
    │   │   ├── c46756c6-1e4c-44a9-8685-e3023a9551d7
    │   │   └── file_manifest.json
    │   └── UINTTEST
    │       ├── 39588d8d-2378-4c9f-9eec-6e6bb7fbea27
    │       └── file_manifest.json
    ├── doc_raw
    │   ├── EMb treshhold
    │   ├── MOVIES
    │   │   └── Movie_Scarface.txt
    │   ├── TESt2
    │   │   ├── Movie_Scarface.txt
    │   └── UINTTEST
    ├── logs
    │   ├── archive
    │   ├── backups
    │   ├── developer
    │   ├── public_run
    │   └── sqlite
    ├── memory
    │   ├── files
    │   │   ├── 2026-05-07-16-14-memory-record.ragmeta.json
    │   │   ├── 2026-05-07-16-33-memory-record.ragmeta.json
    │   │   ├── 2026-05-07-17-01-memory-record.ragmeta.json
    │   │   ├── 2026-05-07-17-59-memory-record.ragmeta.json
    │   │   ├── 2026-05-07-18-24-memory-record.ragmeta.json
    │   │   ├── 2026-05-08-16-27-memory-record.ragmeta.json
    │   │   ├── 2026-05-08-16-48-memory-record.ragmeta.json
    │   │   ├── 2026-05-08-16-55-memory-record.ragmeta.json
    │   │   ├── 2026-05-08-17-05-memory-record.ragmeta.json
    │   │   ├── 2026-05-08-18-39-memory-record.ragmeta.json
    │   │   ├── 2026-05-08-18-52-memory-record.ragmeta.json
    │   │   ├── 2026-05-08-23-13-memory-record.ragmeta.json
    │   │   ├── 2026-05-13-12-02-memory-record.ragmeta.json
    │   │   ├── 2026-05-13-14-24-TEST.ragmeta.json
    │   │   ├── 2026-05-14-15-55-memory-record.ragmeta.json
    │   │   ├── 2026-05-14-16-16-memory-record.ragmeta.json
    │   │   ├── 2026-05-17-11-57-memory-record.ragmeta.json
    │   │   ├── 2026-05-20-14-30-TinyLlama-EC2-GPU-SetUP.ragmeta.json
    │   │   ├── 2026-05-20-14-31-TinyLlama-EC2-GPU-SetUP.ragmeta.json
    │   │   └── 2026-05-20-15-51-EC2_PYthon.ragmeta.json
    │   └── vector_db
    │       ├── 1128b4bb-998c-47e7-81fc-244ccb598bf9
    ├── np_store
    │   └── project1
    ├── project1
    └── splade_db
        ├── EMb treshhold
        ├── MOVIES
        ├── TESt2
        └── UINTTEST
```
