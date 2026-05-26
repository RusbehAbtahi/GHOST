# ragstream/memory/importers/chatgpt_shared_link_importer_helpers.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any

from ragstream.memory.memory_record import MemoryRecord


CHATGPT_SHARED_LINK_PATTERN = re.compile(
    r"^https://chatgpt\.com/share/[A-Za-z0-9_-]+(?:\?.*)?$"
)

VALID_CHATGPT_ROLES = {"user", "assistant"}


# -----------------------------------------------------------------------------
# Public helper API used by chatgpt_shared_link_importer.py
# -----------------------------------------------------------------------------


def read_chatgpt_shared_link(
    shared_url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 60000,
    wait_after_load_ms: int = 3000,
    wait_for_stable_messages: bool = True,
) -> dict[str, Any]:
    """
    Read a public ChatGPT shared-link page.

    Preferred extraction:
    - DOM message blocks converted to cleaner Markdown.
    - Code blocks are reconstructed as fenced code frames.

    Fallback extraction:
    - embedded page data.
    - full body text if structured extraction fails.
    """
    clean_url = validate_shared_url(shared_url)

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(
            "Playwright is required for ChatGPT shared-link import. "
            "Install it through requirements.txt and run: "
            "python -m playwright install chromium"
        ) from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()

            _goto_with_retry(
                page,
                clean_url,
                timeout_ms=timeout_ms,
                attempts=3,
                wait_between_attempts_ms=2500,
            )

            try:
                page.wait_for_selector(
                    "[data-message-author-role]",
                    timeout=min(20000, int(timeout_ms)),
                )
            except PlaywrightTimeoutError:
                pass

            if int(wait_after_load_ms) > 0:
                page.wait_for_timeout(int(wait_after_load_ms))

            if wait_for_stable_messages:
                _scroll_and_wait_until_messages_are_stable(
                    page,
                    timeout_ms=min(25000, int(timeout_ms)),
                    poll_ms=500,
                    stable_rounds=4,
                    max_scroll_rounds=8,
                )

            dom_messages = _extract_dom_messages_as_markdown(page)
            structured_messages = _extract_structured_messages(page)
            raw_text = _extract_body_text(page)

            selected_messages, extraction_method = _select_best_message_source(
                dom_messages=dom_messages,
                structured_messages=structured_messages,
            )

            if selected_messages:
                return {
                    "shared_url": clean_url,
                    "messages": selected_messages,
                    "raw_text": raw_text,
                    "extraction_method": extraction_method,
                }

            return {
                "shared_url": clean_url,
                "messages": [],
                "raw_text": raw_text,
                "extraction_method": "body_text_fallback",
            }

        finally:
            browser.close()


def messages_to_pairs(
    *,
    messages: list[dict[str, str]],
    raw_text: str,
    shared_url: str,
    title: str,
) -> list[dict[str, str]]:
    """Convert ordered user/assistant messages into Q/A memory pairs."""
    pairs: list[dict[str, str]] = []
    pending_user_parts: list[str] = []
    pending_assistant_parts: list[str] = []

    def flush_pair() -> None:
        nonlocal pending_user_parts
        nonlocal pending_assistant_parts

        input_text = "\n\n".join(pending_user_parts).strip()
        output_text = "\n\n".join(pending_assistant_parts).strip()

        if input_text and output_text:
            pairs.append(
                {
                    "input_text": input_text,
                    "output_text": output_text,
                }
            )

        pending_user_parts = []
        pending_assistant_parts = []

    for message in messages or []:
        role = str(message.get("role", "") or "").strip().lower()
        text = clean_text(str(message.get("text", "") or ""))

        if role not in VALID_CHATGPT_ROLES or not text:
            continue

        if role == "user":
            if pending_user_parts and pending_assistant_parts:
                flush_pair()
            pending_user_parts.append(text)
            continue

        if role == "assistant" and pending_user_parts:
            pending_assistant_parts.append(text)

    if pending_user_parts and pending_assistant_parts:
        flush_pair()

    if pairs:
        return pairs

    clean_raw_text = clean_text(raw_text)
    if clean_raw_text:
        return [
            {
                "input_text": (
                    "Imported ChatGPT shared conversation\n"
                    f"Title: {title}\n"
                    f"Source URL: {shared_url}"
                ),
                "output_text": clean_raw_text,
            }
        ]

    return []


def build_memory_records(
    *,
    pairs: list[dict[str, str]],
    shared_url: str,
    active_project_name: str | None,
    embedded_files_snapshot: list[str],
) -> list[MemoryRecord]:
    """Build normal MemoryRecord objects from imported Q/A pairs."""
    records: list[MemoryRecord] = []
    previous_record_id: str | None = None
    source = f"chatgpt_shared_link:{shared_url}"

    for pair in pairs:
        input_text = clean_text(str(pair.get("input_text", "") or ""))
        output_text = clean_text(str(pair.get("output_text", "") or ""))

        if not input_text or not output_text:
            continue

        record = MemoryRecord(
            input_text=input_text,
            output_text=output_text,
            source=source,
            parent_id=previous_record_id,
            tag="Green",
            user_keywords=["chatgpt_shared_link"],
            active_project_name=active_project_name,
            embedded_files_snapshot=embedded_files_snapshot,
            retrieval_source_mode="QA",
            direct_recall_key="",
            active_retrieval_brief_title="",
            active_retrieval_brief="",
            active_retrieval_brief_contributor_ids=[],
        )

        records.append(record)
        previous_record_id = record.record_id

    return records


def assign_memory_brief_to_records(
    *,
    records: list[MemoryRecord],
    memory_brief: str,
    memory_brief_title: str,
) -> None:
    """Attach one shared MemoryBrief to all imported records."""
    clean_memory_brief = clean_text(memory_brief)
    clean_memory_brief_title = clean_text(memory_brief_title)

    if not clean_memory_brief:
        return

    contributor_ids = [record.record_id for record in records]
    for record in records:
        record.update_active_retrieval_brief(
            active_retrieval_brief=clean_memory_brief,
            contributor_ids=contributor_ids,
            active_retrieval_brief_title=clean_memory_brief_title,
        )


def persist_records_as_new_history(
    *,
    memory_manager: Any,
    title: str,
    records: list[MemoryRecord],
) -> None:
    """Persist imported records as a new ordinary RAGstream memory history."""
    if memory_manager is None:
        raise ValueError("memory_manager is required.")

    if not records:
        raise ValueError("No MemoryRecord objects were created.")

    memory_manager.start_new_history(title)
    memory_manager.records = list(records)
    memory_manager.pending_activebrief_topic_buffer = {}

    memory_manager.files_root.mkdir(parents=True, exist_ok=True)

    with memory_manager.ragmem_path.open("w", encoding="utf-8") as f:
        for record in memory_manager.records:
            f.write(record.to_ragmem_block())
            f.write("\n")

    memory_manager.b_file_created = True
    memory_manager.save_metainfo()
    memory_manager.refresh_sqlite_index()


def ingest_imported_history(*, memory_ingestion_manager: Any | None) -> dict[str, Any] | None:
    """Run vector ingestion for the imported history when the ingestion layer exists."""
    if memory_ingestion_manager is None:
        return None

    return memory_ingestion_manager.ingest_all()


def validate_shared_url(shared_url: str) -> str:
    """Validate and normalize a ChatGPT shared conversation URL."""
    clean_url = str(shared_url or "").strip()

    if not clean_url:
        raise ValueError("ChatGPT shared link must not be empty.")

    if not CHATGPT_SHARED_LINK_PATTERN.match(clean_url):
        raise ValueError(
            "ChatGPT shared link must match: https://chatgpt.com/share/<conversation-id>"
        )

    return clean_url


def validate_title(title: str) -> str:
    """Validate and normalize the memory history title."""
    clean_title = str(title or "").strip()

    if not clean_title:
        raise ValueError("Import title must not be empty.")

    return clean_title


# -----------------------------------------------------------------------------
# Playwright navigation / extraction internals
# -----------------------------------------------------------------------------


def _goto_with_retry(
    page: Any,
    url: str,
    *,
    timeout_ms: int = 60000,
    attempts: int = 3,
    wait_between_attempts_ms: int = 2500,
) -> None:
    """Navigate with retry for temporary browser/network errors."""
    last_error: Exception | None = None

    for attempt in range(1, int(attempts) + 1):
        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(timeout_ms),
            )
            return

        except Exception as exc:
            last_error = exc
            message = str(exc)

            retryable = any(
                token in message
                for token in (
                    "ERR_NETWORK_CHANGED",
                    "ERR_TIMED_OUT",
                    "ERR_CONNECTION_RESET",
                    "ERR_INTERNET_DISCONNECTED",
                    "net::ERR_NETWORK_CHANGED",
                    "net::ERR_TIMED_OUT",
                    "net::ERR_CONNECTION_RESET",
                    "net::ERR_INTERNET_DISCONNECTED",
                )
            )

            if not retryable or attempt >= int(attempts):
                raise

            page.wait_for_timeout(int(wait_between_attempts_ms))

    if last_error is not None:
        raise last_error


def _scroll_and_wait_until_messages_are_stable(
    page: Any,
    *,
    timeout_ms: int = 25000,
    poll_ms: int = 500,
    stable_rounds: int = 4,
    max_scroll_rounds: int = 8,
) -> None:
    """Scroll gently and wait until visible message count stops increasing."""
    try:
        start_ms = int(page.evaluate("Date.now()"))
    except Exception:
        return

    previous_count = -1
    stable_count = 0
    scroll_round = 0

    while True:
        try:
            now_ms = int(page.evaluate("Date.now()"))
        except Exception:
            return

        if now_ms - start_ms > int(timeout_ms):
            return

        try:
            current_count = int(
                page.evaluate(
                    '() => document.querySelectorAll("[data-message-author-role]").length'
                )
            )
        except Exception:
            current_count = 0

        if current_count > 0 and current_count == previous_count:
            stable_count += 1
        else:
            stable_count = 0
            previous_count = current_count

        if current_count > 0 and stable_count >= int(stable_rounds):
            return

        if scroll_round < int(max_scroll_rounds):
            try:
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            scroll_round += 1

        page.wait_for_timeout(int(poll_ms))


def _extract_dom_messages_as_markdown(page: Any) -> list[dict[str, str]]:
    """Extract visible message DOM and reconstruct cleaner Markdown/code frames."""
    script = r'''
    () => {
        const nodes = Array.from(document.querySelectorAll("[data-message-author-role]"));

        function normalizeLanguage(value) {
            const raw = String(value || "").trim().toLowerCase();
            if (!raw) return "";

            const cleaned = raw
                .replace(/^language-/, "")
                .replace(/^lang-/, "")
                .replace(/[^a-z0-9#+.-]/g, "");

            const aliases = {
                py: "python",
                python3: "python",
                sh: "bash",
                shell: "bash",
                zsh: "bash",
                ps1: "powershell",
                yml: "yaml",
                js: "javascript",
                ts: "typescript",
                md: "markdown",
                docker: "dockerfile"
            };

            return aliases[cleaned] || cleaned;
        }

        function detectLanguage(codeText, preNode, codeNode) {
            const candidates = [];

            if (codeNode) candidates.push(codeNode.getAttribute("data-language"));
            if (codeNode) candidates.push(codeNode.getAttribute("class"));
            if (preNode) candidates.push(preNode.getAttribute("data-language"));
            if (preNode) candidates.push(preNode.getAttribute("class"));

            for (const candidate of candidates) {
                const text = String(candidate || "");
                const match = text.match(/(?:language-|lang-)([a-zA-Z0-9#+.-]+)/);
                if (match) return normalizeLanguage(match[1]);
                const direct = normalizeLanguage(text);
                if (direct && direct.length <= 20) return direct;
            }

            const code = String(codeText || "").trim();

            if (/^FROM\s+\S+/m.test(code) || /^RUN\s+/m.test(code) || /^CMD\s+\[/m.test(code)) {
                return "dockerfile";
            }
            if (/^\s*def\s+\w+\s*\(/m.test(code) || /^\s*class\s+\w+/m.test(code) || /^\s*import\s+\w+/m.test(code) || /^\s*from\s+\w+/m.test(code)) {
                return "python";
            }
            if (/^\s*\{[\s\S]*\}\s*$/.test(code) || /^\s*\[[\s\S]*\]\s*$/.test(code)) {
                return "json";
            }
            if (/^\s*<\?xml/m.test(code) || /^\s*<[^>]+>/m.test(code)) {
                return "xml";
            }
            if (/^\s*(git|python|pip|pytest|streamlit|docker|aws|cd|ls|mkdir|rm|cp|mv)\b/m.test(code)) {
                return "bash";
            }
            if (/^\s*SELECT\s+/im.test(code) || /^\s*INSERT\s+/im.test(code) || /^\s*UPDATE\s+/im.test(code)) {
                return "sql";
            }

            return "";
        }

        function labelForLanguage(language) {
            if (!language) return "Code frame";

            const labels = {
                python: "Code frame: Python",
                bash: "Code frame: Bash",
                powershell: "Code frame: PowerShell",
                json: "Code frame: JSON",
                yaml: "Code frame: YAML",
                javascript: "Code frame: JavaScript",
                typescript: "Code frame: TypeScript",
                dockerfile: "Code frame: Dockerfile",
                markdown: "Code frame: Markdown",
                html: "Code frame: HTML",
                css: "Code frame: CSS",
                xml: "Code frame: XML",
                sql: "Code frame: SQL"
            };

            return labels[language] || `Code frame: ${language.charAt(0).toUpperCase()}${language.slice(1)}`;
        }

        function removeUiNoise(root) {
            const selectors = [
                "button",
                "svg",
                "[role='button']",
                "[aria-label*='Copy']",
                "[data-testid*='copy']",
                ".sr-only"
            ];

            for (const selector of selectors) {
                for (const item of Array.from(root.querySelectorAll(selector))) {
                    item.remove();
                }
            }
        }

        function convertInlineCode(root) {
            for (const codeNode of Array.from(root.querySelectorAll("code"))) {
                if (codeNode.closest("pre")) continue;

                const text = codeNode.innerText || codeNode.textContent || "";
                if (!text.trim()) continue;

                codeNode.replaceWith(document.createTextNode("`" + text.trim() + "`"));
            }
        }

        function convertCodeBlocks(root) {
            for (const preNode of Array.from(root.querySelectorAll("pre"))) {
                const codeNode = preNode.querySelector("code");
                const codeText = (codeNode ? codeNode.innerText : preNode.innerText) || "";
                const cleanCode = codeText.replace(/\n*Copy code\n*/gi, "").trim();

                if (!cleanCode) {
                    preNode.remove();
                    continue;
                }

                const language = detectLanguage(cleanCode, preNode, codeNode);
                const label = labelForLanguage(language);
                const fenceLanguage = language || "";
                const markdownBlock = `\n\n${label}\n\n\`\`\`${fenceLanguage}\n${cleanCode}\n\`\`\`\n\n`;

                preNode.replaceWith(document.createTextNode(markdownBlock));
            }
        }

        return nodes.map((node) => {
            const clone = node.cloneNode(true);
            removeUiNoise(clone);
            convertCodeBlocks(clone);
            convertInlineCode(clone);

            return {
                role: node.getAttribute("data-message-author-role") || "",
                text: clone.innerText || clone.textContent || ""
            };
        });
    }
    '''

    try:
        raw_messages = page.evaluate(script)
    except Exception:
        raw_messages = []

    return _normalize_messages(raw_messages)


def _extract_structured_messages(page: Any) -> list[dict[str, str]]:
    """Extract fallback messages from embedded JSON-like page state."""
    script = r'''
    () => {
        const roots = [];

        function safePush(value) {
            if (value !== undefined && value !== null) roots.push(value);
        }

        safePush(window.__NEXT_DATA__);
        safePush(window.__remixContext);
        safePush(window.__reactRouterContext);
        safePush(window.__NUXT__);
        safePush(window.__APOLLO_STATE__);

        for (const scriptNode of Array.from(document.querySelectorAll("script"))) {
            const text = scriptNode.textContent || "";
            const trimmed = text.trim();
            if (!trimmed) continue;

            if (scriptNode.type === "application/json" || trimmed.startsWith("{") || trimmed.startsWith("[")) {
                try { safePush(JSON.parse(trimmed)); } catch (e) {}
            }
        }

        const out = [];
        const seen = new Set();

        function contentToText(content) {
            if (!content) return "";
            if (typeof content === "string") return content;
            if (Array.isArray(content)) return content.map(contentToText).filter(Boolean).join("\n");
            if (typeof content !== "object") return "";
            if (typeof content.text === "string") return content.text;
            if (typeof content.value === "string") return content.value;
            if (Array.isArray(content.parts)) return content.parts.map(contentToText).filter(Boolean).join("\n");
            if (Array.isArray(content.content)) return content.content.map(contentToText).filter(Boolean).join("\n");
            if (typeof content.content === "string") return content.content;
            return "";
        }

        function visit(value) {
            if (!value || typeof value !== "object") return;
            if (seen.has(value)) return;
            seen.add(value);

            const role = value?.author?.role || value?.message?.author?.role || value?.node?.message?.author?.role || "";
            const message = value?.message || value?.node?.message || value;
            const content = message?.content || message?.text || value?.content || value?.text || null;
            const text = contentToText(content);

            if ((role === "user" || role === "assistant") && text && text.trim()) {
                out.push({role, text: text.trim()});
            }

            if (Array.isArray(value)) {
                for (const item of value) visit(item);
            } else {
                for (const key of Object.keys(value)) visit(value[key]);
            }
        }

        for (const root of roots) visit(root);
        return out;
    }
    '''

    try:
        raw_messages = page.evaluate(script)
    except Exception:
        raw_messages = []

    return _normalize_messages(raw_messages)


def _select_best_message_source(
    *,
    dom_messages: list[dict[str, str]],
    structured_messages: list[dict[str, str]],
) -> tuple[list[dict[str, str]], str]:
    """Prefer DOM Markdown when message coverage is comparable; otherwise use larger source."""
    dom_count = len(dom_messages or [])
    structured_count = len(structured_messages or [])

    if dom_count <= 0 and structured_count <= 0:
        return [], ""

    if dom_count >= structured_count:
        return dom_messages, "dom_markdown_codeframe"

    if dom_count >= 2 and structured_count - dom_count <= 2:
        return dom_messages, "dom_markdown_codeframe"

    return structured_messages, "embedded_author_role"


def _extract_body_text(page: Any) -> str:
    try:
        text = page.locator("body").inner_text(timeout=10000)
    except Exception:
        return ""

    return clean_text(text)


def _normalize_messages(raw_messages: Any) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    for item in raw_messages or []:
        if not isinstance(item, dict):
            continue

        role = str(item.get("role", "") or "").strip().lower()
        text = clean_text(str(item.get("text", "") or ""))

        if role not in VALID_CHATGPT_ROLES:
            continue

        if not text:
            continue

        messages.append(
            {
                "role": role,
                "text": text,
            }
        )

    return _dedupe_consecutive_messages(messages)


def _dedupe_consecutive_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Remove only consecutive duplicates; repeated later turns remain valid."""
    result: list[dict[str, str]] = []
    previous_key: tuple[str, str] | None = None

    for message in messages:
        role = str(message.get("role", "") or "").strip().lower()
        text = clean_text(str(message.get("text", "") or ""))

        if role not in VALID_CHATGPT_ROLES or not text:
            continue

        key = (role, text)
        if key == previous_key:
            continue

        result.append({"role": role, "text": text})
        previous_key = key

    return result


def clean_text(text: str) -> str:
    """Normalize imported text and remove common shared-page UI noise."""
    value = str(text or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")

    noise_lines = {
        "copy",
        "copy code",
        "copied",
        "edit",
        "share",
        "regenerate",
        "open in app",
        "chatgpt can make mistakes. check important info.",
    }

    cleaned_lines: list[str] = []
    for line in value.split("\n"):
        stripped = line.strip()
        if stripped.lower() in noise_lines:
            continue
        cleaned_lines.append(line)

    value = "\n".join(cleaned_lines)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()
