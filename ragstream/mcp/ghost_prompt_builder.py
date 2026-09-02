"""Central internal builder shared by future GHOST Prompt Show and Run tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ragstream.mcp.ghost_prompt_settings import GhostPromptSettings
from ragstream.mcp.prompt_build_receipt import build_prompt_receipt
from ragstream.mcp.prompt_build_session import (
    PromptBuildSession,
    PromptBuildSessionError,
    PromptBuildSessionStore,
)
from ragstream.mcp.prompt_context_adapters import (
    ContextAdapterError,
    DEFAULT_DOCUMENT_CONTEXT_TOKENS,
    DEFAULT_DOCUMENT_MAX_OUTPUT_TOKENS,
    DEFAULT_MEMORY_CONTEXT_TOKENS,
    DEFAULT_MEMORY_MAX_OUTPUT_TOKENS,
    DocumentContextAdapter,
    GeneralSkillContextAdapter,
    MemoryContextAdapter,
    load_runtime_config,
)
from ragstream.mcp.prompt_engineering_runner import PromptEngineeringRunner
from ragstream.orchestration.agent_factory import AgentFactory
from ragstream.orchestration.llm_client import LLMClient
from ragstream.orchestration.super_prompt import SuperPrompt
from ragstream.orchestration.superprompt_projector import SuperPromptProjector


STATUS_COMPLETE = "complete"
STATUS_CLARIFICATION_REQUIRED = "clarification_required"
STATUS_SELECTION_REQUIRED = "selection_required"

KNOWLEDGE_RETRIEVAL_WARNING = (
    "knowledge_retrieval is not implemented and was skipped"
)


class PromptBuildError(RuntimeError):
    """Expected failure while constructing one configured GHOST prompt."""

    def __init__(self, stage: str, reason: str) -> None:
        self.stage = str(stage or "prompt_build").strip()
        self.reason = str(reason or "unknown failure").strip()
        super().__init__(
            f"{self.stage} failed: {self.reason}"
        )


class GhostPromptBuilder:
    """Build one final prompt from task text and enabled GHOST context sources."""

    def __init__(
        self,
        *,
        settings: GhostPromptSettings | None = None,
        prompt_runner: PromptEngineeringRunner | None = None,
        document_adapter: DocumentContextAdapter | None = None,
        memory_adapter: MemoryContextAdapter | None = None,
        general_skill_adapter: GeneralSkillContextAdapter | None = None,
        agent_factory: AgentFactory | None = None,
        llm_client: LLMClient | None = None,
        runtime_config: dict[str, Any] | None = None,
        session_store: PromptBuildSessionStore | None = None,
    ) -> None:
        self.settings = settings or GhostPromptSettings()
        self.prompt_runner = prompt_runner or PromptEngineeringRunner()
        self.agent_factory = agent_factory or AgentFactory()
        self.llm_client = llm_client or LLMClient()
        self.document_adapter = document_adapter or DocumentContextAdapter(
            agent_factory=self.agent_factory,
            llm_client=self.llm_client,
        )
        self.memory_adapter = memory_adapter or MemoryContextAdapter()
        self.general_skill_adapter = (
            general_skill_adapter or GeneralSkillContextAdapter()
        )
        self.runtime_config = (
            runtime_config
            if runtime_config is not None
            else load_runtime_config()
        )
        self.session_store = (
            session_store or PromptBuildSessionStore()
        )

    def build(
        self,
        *,
        owner_sub: str,
        prompt_text: str | None = None,
        build_id: str | None = None,
        setting_overrides: Mapping[str, Any] | None = None,
        project_name: str | None = None,
        ragmem_path: str | None = None,
        document_context_tokens: int | None = None,
        document_max_output_tokens: int | None = None,
        memory_context_tokens: int | None = None,
        memory_max_output_tokens: int | None = None,
        general_skill_ids: Sequence[str] | None = None,
        general_skill_query: str | None = None,
    ) -> dict[str, Any]:
        """Build one prompt or return a deterministic intermediate status."""
        owner = str(owner_sub or "").strip()
        if not owner:
            raise PromptBuildError(
                "request_validation",
                "authenticated owner is required",
            )

        identifier = str(build_id or "").strip()
        if identifier:
            if any(
                value is not None
                for value in (
                    setting_overrides,
                    project_name,
                    ragmem_path,
                    document_context_tokens,
                    document_max_output_tokens,
                    memory_context_tokens,
                    memory_max_output_tokens,
                    general_skill_query,
                )
            ):
                raise PromptBuildError(
                    "build_session",
                    "continuation cannot replace saved settings or sources",
                )
            return self._continue_build(
                owner=owner,
                build_id=identifier,
                prompt_text=prompt_text,
                general_skill_ids=general_skill_ids,
            )

        text = str(prompt_text or "")
        if not text.strip():
            raise PromptBuildError(
                "request_validation",
                "prompt_text must not be empty",
            )

        try:
            effective = self.settings.effective(
                owner,
                setting_overrides,
            )
        except ValueError as error:
            raise PromptBuildError(
                "prompt_settings",
                str(error),
            ) from error

        warnings: list[str] = []
        effective = dict(effective)
        if effective["knowledge_retrieval"]:
            effective["knowledge_retrieval"] = False
            warnings.append(KNOWLEDGE_RETRIEVAL_WARNING)

        active_project = self._effective_optional_text(
            project_name,
            effective["default_project_name"],
        )
        active_ragmem = self._effective_optional_text(
            ragmem_path,
            effective["default_ragmem_path"],
        )
        document_context_tokens = self._effective_positive_int(
            document_context_tokens,
            DEFAULT_DOCUMENT_CONTEXT_TOKENS,
            "document_context_tokens",
        )
        document_max_output_tokens = self._effective_positive_int(
            document_max_output_tokens,
            DEFAULT_DOCUMENT_MAX_OUTPUT_TOKENS,
            "document_max_output_tokens",
        )
        memory_context_tokens = self._effective_positive_int(
            memory_context_tokens,
            DEFAULT_MEMORY_CONTEXT_TOKENS,
            "memory_context_tokens",
        )
        memory_max_output_tokens = self._effective_positive_int(
            memory_max_output_tokens,
            DEFAULT_MEMORY_MAX_OUTPUT_TOKENS,
            "memory_max_output_tokens",
        )
        return self._prepare_build(
            owner=owner,
            prompt_text=text,
            effective=effective,
            project_name=active_project,
            ragmem_path=active_ragmem,
            document_context_tokens=document_context_tokens,
            document_max_output_tokens=document_max_output_tokens,
            memory_context_tokens=memory_context_tokens,
            memory_max_output_tokens=memory_max_output_tokens,
            general_skill_query=str(
                general_skill_query or ""
            ).strip(),
            general_skill_ids=general_skill_ids,
            warnings=warnings,
        )

    def _continue_build(
        self,
        *,
        owner: str,
        build_id: str,
        prompt_text: str | None,
        general_skill_ids: Sequence[str] | None,
    ) -> dict[str, Any]:
        try:
            session = self.session_store.get(owner, build_id)
        except PromptBuildSessionError as error:
            raise PromptBuildError(
                "build_session",
                str(error),
            ) from error

        if session.workflow_state == STATUS_CLARIFICATION_REQUIRED:
            clarified_text = str(prompt_text or "")
            if not clarified_text.strip():
                raise PromptBuildError(
                    "build_session",
                    "clarification continuation requires prompt_text",
                )
            if general_skill_ids is not None:
                raise PromptBuildError(
                    "build_session",
                    "clarification continuation cannot select Skills",
                )
            self.session_store.delete(owner, build_id)
            return self._prepare_build(
                owner=owner,
                prompt_text=clarified_text,
                effective=dict(session.effective_settings),
                project_name=session.project_name,
                ragmem_path=session.ragmem_path,
                document_context_tokens=session.document_context_tokens,
                document_max_output_tokens=session.document_max_output_tokens,
                memory_context_tokens=session.memory_context_tokens,
                memory_max_output_tokens=session.memory_max_output_tokens,
                general_skill_query=session.general_skill_query,
                general_skill_ids=None,
                warnings=list(session.warnings),
            )

        if session.workflow_state != STATUS_SELECTION_REQUIRED:
            raise PromptBuildError(
                "build_session",
                "build_id has an unsupported workflow state",
            )
        if prompt_text is not None:
            raise PromptBuildError(
                "build_session",
                "Skill-selection continuation must not replace prompt_text",
            )
        if not general_skill_ids:
            raise PromptBuildError(
                "build_session",
                "Skill-selection continuation requires general_skill_ids",
            )

        return self._complete_build(
            owner=owner,
            prompt_text=session.prompt_text,
            cleaned_text=session.cleaned_text,
            cleanup_changed=session.cleanup_changed,
            effective=dict(session.effective_settings),
            project_name=session.project_name,
            ragmem_path=session.ragmem_path,
            document_context_tokens=session.document_context_tokens,
            document_max_output_tokens=session.document_max_output_tokens,
            memory_context_tokens=session.memory_context_tokens,
            memory_max_output_tokens=session.memory_max_output_tokens,
            general_skill_query=session.general_skill_query,
            general_skill_ids=general_skill_ids,
            warnings=list(session.warnings),
            build_id=build_id,
        )

    def _prepare_build(
        self,
        *,
        owner: str,
        prompt_text: str,
        effective: Mapping[str, Any],
        project_name: str | None,
        ragmem_path: str | None,
        document_context_tokens: int,
        document_max_output_tokens: int,
        memory_context_tokens: int,
        memory_max_output_tokens: int,
        general_skill_query: str,
        general_skill_ids: Sequence[str] | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        cleaned_text = prompt_text
        cleanup_changed = False
        if effective["input_cleanup"]:
            cleanup = self._cleanup_input(prompt_text)
            if cleanup["status"] == STATUS_CLARIFICATION_REQUIRED:
                build_id = self.session_store.create(
                    owner,
                    PromptBuildSession(
                        workflow_state=STATUS_CLARIFICATION_REQUIRED,
                        prompt_text=prompt_text,
                        cleaned_text="",
                        cleanup_changed=False,
                        effective_settings=dict(effective),
                        project_name=project_name,
                        ragmem_path=ragmem_path,
                        general_skill_query=general_skill_query,
                        document_context_tokens=document_context_tokens,
                        document_max_output_tokens=document_max_output_tokens,
                        memory_context_tokens=memory_context_tokens,
                        memory_max_output_tokens=memory_max_output_tokens,
                        warnings=tuple(warnings),
                    ),
                )
                return {
                    "status": STATUS_CLARIFICATION_REQUIRED,
                    "prompt": "",
                    "clarification_question": cleanup[
                        "clarification_question"
                    ],
                    "general_skill_candidates": [],
                    "receipt": build_prompt_receipt(
                        effective=effective,
                        project_name=project_name,
                        document_receipt=None,
                        memory_receipt=None,
                        cleanup_changed=False,
                        sources_used=[],
                        selected_skill_ids=[],
                        status=STATUS_CLARIFICATION_REQUIRED,
                        build_id=build_id,
                        stages_completed=[],
                        warnings=warnings,
                    ),
                }
            cleaned_text = cleanup["cleaned_text"]
            cleanup_changed = cleaned_text != prompt_text

        return self._complete_build(
            owner=owner,
            prompt_text=prompt_text,
            cleaned_text=cleaned_text,
            cleanup_changed=cleanup_changed,
            effective=effective,
            project_name=project_name,
            ragmem_path=ragmem_path,
            document_context_tokens=document_context_tokens,
            document_max_output_tokens=document_max_output_tokens,
            memory_context_tokens=memory_context_tokens,
            memory_max_output_tokens=memory_max_output_tokens,
            general_skill_query=general_skill_query,
            general_skill_ids=general_skill_ids,
            warnings=warnings,
            build_id=None,
        )

    def _complete_build(
        self,
        *,
        owner: str,
        prompt_text: str,
        cleaned_text: str,
        cleanup_changed: bool,
        effective: Mapping[str, Any],
        project_name: str | None,
        ragmem_path: str | None,
        document_context_tokens: int,
        document_max_output_tokens: int,
        memory_context_tokens: int,
        memory_max_output_tokens: int,
        general_skill_query: str,
        general_skill_ids: Sequence[str] | None,
        warnings: list[str],
        build_id: str | None,
    ) -> dict[str, Any]:
        super_prompt = self._build_base_superprompt(
            cleaned_text,
            prompt_shaping=effective["prompt_shaping"],
        )
        stages_completed = [
            "prompt_shaping"
            if effective["prompt_shaping"]
            else "base_prompt"
        ]
        if effective["input_cleanup"]:
            stages_completed.insert(0, "input_cleanup")
        sources_used: list[str] = []
        selected_skill_ids: list[str] = []

        if effective["general_skill_retrieval"]:
            query = general_skill_query
            if not query:
                query = (
                    str(
                        getattr(
                            super_prompt,
                            "effective_retrieval_query_text",
                            "",
                        )
                        or ""
                    ).strip()
                    or SuperPromptProjector.build_query_text(super_prompt)
                )

            try:
                skill_receipt = self.general_skill_adapter.apply(
                    super_prompt,
                    owner_sub=owner,
                    query=query,
                    selected_skill_ids=general_skill_ids,
                )
            except ContextAdapterError as error:
                raise PromptBuildError(
                    "general_skill_retrieval",
                    str(error),
                ) from error
            if (
                skill_receipt.get("workflow_state")
                == STATUS_SELECTION_REQUIRED
            ):
                if build_id is not None:
                    self.session_store.delete(owner, build_id)
                next_build_id = self.session_store.create(
                    owner,
                    PromptBuildSession(
                        workflow_state=STATUS_SELECTION_REQUIRED,
                        prompt_text=prompt_text,
                        cleaned_text=cleaned_text,
                        cleanup_changed=cleanup_changed,
                        effective_settings=dict(effective),
                        project_name=project_name,
                        ragmem_path=ragmem_path,
                        general_skill_query=query,
                        document_context_tokens=document_context_tokens,
                        document_max_output_tokens=document_max_output_tokens,
                        memory_context_tokens=memory_context_tokens,
                        memory_max_output_tokens=memory_max_output_tokens,
                        warnings=tuple(warnings),
                    ),
                )
                return {
                    "status": STATUS_SELECTION_REQUIRED,
                    "prompt": "",
                    "clarification_question": "",
                    "general_skill_candidates": list(
                        skill_receipt.get("candidates", []) or []
                    ),
                    "receipt": build_prompt_receipt(
                        effective=effective,
                        project_name=project_name,
                        document_receipt=None,
                        memory_receipt=None,
                        cleanup_changed=cleanup_changed,
                        sources_used=[],
                        selected_skill_ids=[],
                        status=STATUS_SELECTION_REQUIRED,
                        build_id=next_build_id,
                        stages_completed=stages_completed,
                        warnings=warnings,
                    ),
                }

            selected_skill_ids = list(
                skill_receipt.get("selected_skill_ids", []) or []
            )
            if selected_skill_ids:
                sources_used.append("general_skills")
            stages_completed.append("general_skill_retrieval")

        document_receipt: dict[str, Any] | None = None
        if effective["document_retrieval"]:
            if project_name is None:
                raise PromptBuildError(
                    "document_retrieval",
                    "project_name or default_project_name is required",
                )
            try:
                document_receipt = self.document_adapter.apply(
                    super_prompt,
                    project_name=project_name,
                    runtime_config=self.runtime_config,
                    context_tokens=document_context_tokens,
                    max_output_tokens=document_max_output_tokens,
                )
            except ContextAdapterError as error:
                stage, separator, reason = str(error).partition(" failed: ")
                raise PromptBuildError(
                    stage if separator else "document_retrieval",
                    reason if separator else str(error),
                ) from error
            sources_used.append("document")
            stages_completed.extend(
                document_receipt.get("stages_completed", [])
            )

        memory_receipt: dict[str, Any] | None = None
        if effective["memory_retrieval"]:
            if ragmem_path is None:
                raise PromptBuildError(
                    "memory_retrieval",
                    "ragmem_path or default_ragmem_path is required",
                )
            try:
                memory_receipt = self.memory_adapter.apply(
                    super_prompt,
                    owner_sub=owner,
                    ragmem_path=ragmem_path,
                    runtime_config=self.runtime_config,
                    recency_enabled=effective[
                        "memory_recency_enabled"
                    ],
                    context_tokens=memory_context_tokens,
                    max_output_tokens=memory_max_output_tokens,
                )
            except ContextAdapterError as error:
                raise PromptBuildError(
                    "memory_retrieval",
                    str(error),
                ) from error
            sources_used.append("memory")
            stages_completed.append("memory_retrieval")

        try:
            final_prompt = super_prompt.compose_prompt_ready()
        except Exception as error:
            raise PromptBuildError(
                "prompt_composition",
                str(error),
            ) from error
        if not final_prompt.strip():
            raise PromptBuildError(
                "prompt_composition",
                "prompt builder produced an empty prompt",
            )
        stages_completed.append("prompt_composition")
        if build_id is not None:
            self.session_store.delete(owner, build_id)

        return {
            "status": STATUS_COMPLETE,
            "prompt": final_prompt,
            "clarification_question": "",
            "general_skill_candidates": [],
            "receipt": build_prompt_receipt(
                effective=effective,
                project_name=project_name
                if effective["document_retrieval"]
                else None,
                document_receipt=document_receipt,
                memory_receipt=memory_receipt,
                cleanup_changed=cleanup_changed,
                sources_used=sources_used,
                selected_skill_ids=selected_skill_ids,
                status=STATUS_COMPLETE,
                build_id=None,
                stages_completed=stages_completed,
                warnings=warnings,
            ),
        }

    def _build_base_superprompt(
        self,
        prompt_text: str,
        *,
        prompt_shaping: bool,
    ) -> SuperPrompt:
        if prompt_shaping:
            try:
                return self.prompt_runner.run_superprompt(prompt_text)
            except Exception as error:
                raise PromptBuildError(
                    "prompt_shaping",
                    str(error),
                ) from error

        super_prompt = SuperPrompt()
        super_prompt.body["task"] = prompt_text
        super_prompt.effective_retrieval_query_text = prompt_text.strip()
        return super_prompt

    def _cleanup_input(self, prompt_text: str) -> dict[str, str]:
        try:
            agent = self.agent_factory.get_agent(
                "prompt_input_cleanup",
                "001",
            )
            messages, response_format = agent.compose(
                input_payload={"input_text": prompt_text}
            )
            raw_output = self.llm_client.chat(
                messages=messages,
                model_name=agent.model,
                temperature=agent.temperature,
                max_output_tokens=agent.max_tokens,
                response_format=response_format,
                prompt_cache_key="prompt_input_cleanup",
            )
            parsed = agent.parse(raw_output)
        except Exception as error:
            raise PromptBuildError(
                "input_cleanup",
                str(error),
            ) from error

        status = str(parsed.get("status", "") or "").strip().lower()
        cleaned_text = str(parsed.get("cleaned_text", "") or "")
        clarification = str(
            parsed.get("clarification_question", "") or ""
        ).strip()

        if status == STATUS_CLARIFICATION_REQUIRED:
            if not clarification:
                raise PromptBuildError(
                    "input_cleanup",
                    "clarification was requested without a question",
                )
            return {
                "status": STATUS_CLARIFICATION_REQUIRED,
                "cleaned_text": "",
                "clarification_question": clarification,
            }

        if status != "clean" or not cleaned_text.strip():
            raise PromptBuildError(
                "input_cleanup",
                "cleanup agent returned an invalid result",
            )

        return {
            "status": "clean",
            "cleaned_text": cleaned_text,
            "clarification_question": "",
        }

    @staticmethod
    def _effective_positive_int(
        explicit: int | None,
        default: int,
        field_name: str,
    ) -> int:
        value = default if explicit is None else explicit
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise PromptBuildError(
                "request_validation",
                f"{field_name} must be a positive integer",
            )
        return value

    @staticmethod
    def _effective_optional_text(
        explicit: str | None,
        stored: Any,
    ) -> str | None:
        value = explicit if explicit is not None else stored
        if value is None:
            return None
        text = str(value).strip()
        return text or None
