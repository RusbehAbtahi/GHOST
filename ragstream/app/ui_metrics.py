# ragstream/app/ui_metrics.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import html
from dataclasses import dataclass

import streamlit as st
import streamlit.components.v1 as components


@dataclass(frozen=True)
class DemoPath:
    path_id: int
    label: str
    subtitle: str
    accent: str
    soft: str
    glow: str
    nodes: tuple[str, ...]


def _demo_paths() -> dict[int, DemoPath]:
    return {
        1: DemoPath(
            path_id=1,
            label="Path 1 — Requirements Audit",
            subtitle="User request → requirements → trace matrix → engineered prompt",
            accent="#38BDF8",
            soft="#E0F7FF",
            glow="rgba(56, 189, 248, 0.55)",
            nodes=("ROOT", "REQ", "TRACE", "PROMPT"),
        ),
        2: DemoPath(
            path_id=2,
            label="Path 2 — Architecture Trace",
            subtitle="User request → architecture → UML view → engineered prompt",
            accent="#A78BFA",
            soft="#F1EAFE",
            glow="rgba(167, 139, 250, 0.55)",
            nodes=("ROOT", "ARCH", "UML", "PROMPT"),
        ),
        3: DemoPath(
            path_id=3,
            label="Path 3 — Code Review",
            subtitle="User request → code → focused files → engineered prompt",
            accent="#34D399",
            soft="#E8FFF4",
            glow="rgba(52, 211, 153, 0.55)",
            nodes=("ROOT", "CODE", "FILES", "PROMPT"),
        ),
        4: DemoPath(
            path_id=4,
            label="Path 4 — Quality Gate",
            subtitle="User request → tests → validation gate → engineered prompt",
            accent="#FBBF24",
            soft="#FFF7DF",
            glow="rgba(251, 191, 36, 0.58)",
            nodes=("ROOT", "TEST", "QUALITY", "PROMPT"),
        ),
        5: DemoPath(
            path_id=5,
            label="Path 5 — Release Brief",
            subtitle="User request → release → status pack → engineered prompt",
            accent="#FB7185",
            soft="#FFF0F3",
            glow="rgba(251, 113, 133, 0.55)",
            nodes=("ROOT", "RELEASE", "STATUS", "PROMPT"),
        ),
    }


def _node_catalog() -> dict[str, dict[str, str]]:
    return {
        "ROOT": {"title": "User Request", "caption": "incoming task", "x": "50", "y": "8"},
        "REQ": {"title": "Requirements", "caption": "rules · scope", "x": "12", "y": "30"},
        "ARCH": {"title": "Architecture", "caption": "system shape", "x": "31", "y": "30"},
        "CODE": {"title": "Code", "caption": "implementation", "x": "50", "y": "30"},
        "TEST": {"title": "Tests", "caption": "evidence", "x": "69", "y": "30"},
        "RELEASE": {"title": "Release", "caption": "delivery", "x": "88", "y": "30"},
        "TRACE": {"title": "Trace Matrix", "caption": "REQ → code", "x": "16", "y": "56"},
        "UML": {"title": "UML View", "caption": "structure", "x": "34", "y": "56"},
        "FILES": {"title": "File Focus", "caption": "exact sources", "x": "50", "y": "56"},
        "QUALITY": {"title": "Quality Gate", "caption": "checks", "x": "66", "y": "56"},
        "STATUS": {"title": "Status Pack", "caption": "summary", "x": "84", "y": "56"},
        "PROMPT": {"title": "Engineered Prompt", "caption": "LLM-ready", "x": "50", "y": "82"},
    }


def _edge_catalog() -> list[tuple[str, str]]:
    return [
        ("ROOT", "REQ"),
        ("ROOT", "ARCH"),
        ("ROOT", "CODE"),
        ("ROOT", "TEST"),
        ("ROOT", "RELEASE"),
        ("REQ", "TRACE"),
        ("ARCH", "UML"),
        ("CODE", "FILES"),
        ("TEST", "QUALITY"),
        ("RELEASE", "STATUS"),
        ("TRACE", "PROMPT"),
        ("UML", "PROMPT"),
        ("FILES", "PROMPT"),
        ("QUALITY", "PROMPT"),
        ("STATUS", "PROMPT"),
    ]


def _init_metrics_state() -> None:
    if "metrics_demo_active_path" not in st.session_state:
        st.session_state["metrics_demo_active_path"] = 1


def _active_path_id() -> int:
    try:
        value = int(st.session_state.get("metrics_demo_active_path", 1))
    except Exception:
        value = 1

    if value not in _demo_paths():
        value = 1

    return value


def _set_active_path(path_id: int) -> None:
    st.session_state["metrics_demo_active_path"] = int(path_id)


def _render_path_selector() -> DemoPath:
    paths = _demo_paths()
    active_id = _active_path_id()

    st.markdown("### Interactive Flow Demo")

    left, right = st.columns([1.1, 2.9], gap="medium")

    with left:
        selected_path_id = st.number_input(
            "Choose active path",
            min_value=1,
            max_value=5,
            value=active_id,
            step=1,
            key="metrics_demo_path_number",
        )
        _set_active_path(int(selected_path_id))

    active_path = paths[_active_path_id()]

    with right:
        st.markdown(
            f"""
            <div style="
                border:1px solid rgba(30,41,59,0.10);
                border-radius:18px;
                padding:0.75rem 1rem;
                background:linear-gradient(90deg, {active_path.soft}, #ffffff);
                box-shadow:0 8px 22px rgba(15,23,42,0.06);
            ">
                <div style="font-size:1.05rem; font-weight:800; color:#1f2937;">
                    {html.escape(active_path.label)}
                </div>
                <div style="font-size:0.92rem; color:#64748b; margin-top:0.15rem;">
                    {html.escape(active_path.subtitle)}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    return active_path


def _is_active_node(node_id: str, active_path: DemoPath) -> bool:
    return node_id in active_path.nodes


def _is_active_edge(edge: tuple[str, str], active_path: DemoPath) -> bool:
    src, dst = edge
    nodes = list(active_path.nodes)

    for i in range(len(nodes) - 1):
        if nodes[i] == src and nodes[i + 1] == dst:
            return True

    return False


def _edge_svg(
    src_id: str,
    dst_id: str,
    nodes: dict[str, dict[str, str]],
    active: bool,
    active_path: DemoPath,
) -> str:
    src = nodes[src_id]
    dst = nodes[dst_id]

    x1 = float(src["x"])
    y1 = float(src["y"]) + 5.9
    x2 = float(dst["x"])
    y2 = float(dst["y"]) - 5.9

    edge_class = "edge active-edge" if active else "edge"
    stroke = active_path.accent if active else "#CBD5E1"
    width = "1.75" if active else "0.85"

    return (
        f'<path class="{edge_class}" '
        f'd="M {x1} {y1} C {x1} {(y1 + y2) / 2}, {x2} {(y1 + y2) / 2}, {x2} {y2}" '
        f'stroke="{stroke}" stroke-width="{width}" fill="none" />'
    )


def _node_svg(
    node_id: str,
    data: dict[str, str],
    active: bool,
    active_path: DemoPath,
) -> str:
    x = float(data["x"])
    y = float(data["y"])

    title = html.escape(data["title"])
    caption = html.escape(data["caption"])

    if active:
        fill = active_path.soft
        stroke = active_path.accent
        title_color = "#0F172A"
        caption_color = "#334155"
        node_class = "node active-node"
    else:
        fill = "#F8FAFC"
        stroke = "#E2E8F0"
        title_color = "#475569"
        caption_color = "#94A3B8"
        node_class = "node"

    return f"""
    <g class="{node_class}" transform-origin="{x}px {y}px">
        <rect
            x="{x - 8.9}"
            y="{y - 5.0}"
            width="17.8"
            height="10.0"
            rx="5.0"
            fill="{fill}"
            stroke="{stroke}"
            stroke-width="0.9"
        />
        <text
            x="{x}"
            y="{y - 0.9}"
            text-anchor="middle"
            font-size="2.15"
            font-weight="800"
            fill="{title_color}"
        >{title}</text>
        <text
            x="{x}"
            y="{y + 2.25}"
            text-anchor="middle"
            font-size="1.55"
            font-weight="500"
            fill="{caption_color}"
        >{caption}</text>
    </g>
    """


def _legend_card(path_id: int, active_path: DemoPath) -> str:
    paths = _demo_paths()
    path = paths[path_id]

    css_class = "legend-card"
    if path_id == active_path.path_id:
        css_class += " legend-card-active"

    short_name = path.label.replace(f"Path {path_id} — ", "")

    return f"""
    <div class="{css_class}">
        <div class="legend-number">Path {path_id}</div>
        <div class="legend-name">{html.escape(short_name)}</div>
    </div>
    """


def _build_flow_html(active_path: DemoPath) -> str:
    nodes = _node_catalog()
    edges = _edge_catalog()

    svg_edges = "\n".join(
        _edge_svg(
            src_id=edge[0],
            dst_id=edge[1],
            nodes=nodes,
            active=_is_active_edge(edge, active_path),
            active_path=active_path,
        )
        for edge in edges
    )

    svg_nodes = "\n".join(
        _node_svg(
            node_id=node_id,
            data=data,
            active=_is_active_node(node_id, active_path),
            active_path=active_path,
        )
        for node_id, data in nodes.items()
    )

    legend_cards = "\n".join(
        _legend_card(path_id, active_path)
        for path_id in range(1, 6)
    )

    return f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8" />
        <style>
            html, body {{
                margin: 0;
                padding: 0;
                background: transparent;
                font-family:
                    -apple-system,
                    BlinkMacSystemFont,
                    "Segoe UI",
                    Roboto,
                    Helvetica,
                    Arial,
                    sans-serif;
            }}

            .ghost-flow-shell {{
                box-sizing: border-box;
                width: 100%;
                padding: 20px 22px 22px 22px;
                border-radius: 28px;
                background:
                    radial-gradient(circle at 18% 20%, rgba(56,189,248,0.16), transparent 24%),
                    radial-gradient(circle at 82% 28%, rgba(167,139,250,0.14), transparent 25%),
                    radial-gradient(circle at 45% 92%, rgba(52,211,153,0.13), transparent 30%),
                    linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%);
                border: 1px solid rgba(148,163,184,0.24);
                box-shadow:
                    0 24px 58px rgba(15,23,42,0.08),
                    inset 0 1px 0 rgba(255,255,255,0.92);
            }}

            .title-row {{
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                gap: 18px;
                margin-bottom: 12px;
            }}

            .title-main {{
                font-size: 22px;
                font-weight: 850;
                letter-spacing: 0.01em;
                color: #111827;
                line-height: 1.15;
            }}

            .title-sub {{
                margin-top: 5px;
                color: #64748B;
                font-size: 14px;
            }}

            .active-pill {{
                white-space: nowrap;
                font-size: 13px;
                font-weight: 800;
                color: #334155;
                background: {active_path.soft};
                border: 1px solid {active_path.accent};
                border-radius: 999px;
                padding: 8px 14px;
                box-shadow:
                    0 8px 20px rgba(15,23,42,0.07),
                    0 0 18px {active_path.glow};
            }}

            .svg-wrap {{
                width: 100%;
                overflow: hidden;
                border-radius: 22px;
                background:
                    linear-gradient(rgba(148,163,184,0.06) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(148,163,184,0.06) 1px, transparent 1px),
                    rgba(255,255,255,0.78);
                background-size: 28px 28px;
                border: 1px solid rgba(226,232,240,0.95);
            }}

            svg {{
                display: block;
                width: 100%;
                height: 560px;
            }}

            .edge {{
                opacity: 0.72;
                stroke-linecap: round;
            }}

            .active-edge {{
                opacity: 1.0;
                filter: drop-shadow(0 0 3px {active_path.accent});
                stroke-dasharray: 2.8 2.0;
                animation:
                    ghostDash 1.1s linear infinite,
                    ghostEdgePulse 1.55s ease-in-out infinite;
            }}

            .node rect {{
                filter: drop-shadow(0 5px 8px rgba(15,23,42,0.10));
            }}

            .active-node rect {{
                filter:
                    drop-shadow(0 0 7px {active_path.accent})
                    drop-shadow(0 12px 16px rgba(15,23,42,0.14));
                animation: ghostNodePulse 1.55s ease-in-out infinite;
            }}

            @keyframes ghostNodePulse {{
                0% {{
                    opacity: 0.88;
                    transform: scale(1);
                }}
                50% {{
                    opacity: 1.0;
                    transform: scale(1.018);
                }}
                100% {{
                    opacity: 0.88;
                    transform: scale(1);
                }}
            }}

            @keyframes ghostEdgePulse {{
                0% {{
                    opacity: 0.60;
                }}
                50% {{
                    opacity: 1.0;
                }}
                100% {{
                    opacity: 0.60;
                }}
            }}

            @keyframes ghostDash {{
                from {{
                    stroke-dashoffset: 0;
                }}
                to {{
                    stroke-dashoffset: -18;
                }}
            }}

            .legend {{
                display: grid;
                grid-template-columns: repeat(5, minmax(0, 1fr));
                gap: 10px;
                margin-top: 13px;
            }}

            .legend-card {{
                box-sizing: border-box;
                border-radius: 16px;
                padding: 11px 12px;
                border: 1px solid rgba(148,163,184,0.22);
                background: rgba(255,255,255,0.74);
                color: #475569;
                font-size: 12px;
                min-height: 62px;
            }}

            .legend-card-active {{
                border-color: {active_path.accent};
                background: {active_path.soft};
                color: #0F172A;
                box-shadow:
                    0 10px 24px rgba(15,23,42,0.08),
                    0 0 18px {active_path.glow};
            }}

            .legend-number {{
                font-weight: 900;
                margin-bottom: 3px;
            }}

            .legend-name {{
                font-weight: 750;
                line-height: 1.2;
            }}
        </style>
    </head>

    <body>
        <div class="ghost-flow-shell">
            <div class="title-row">
                <div>
                    <div class="title-main">GHOST Pipeline Tree — Interactive Path Demo</div>
                    <div class="title-sub">
                        Select a number from 1 to 5. The active route receives stronger color, glow, and motion.
                    </div>
                </div>
                <div class="active-pill">
                    Active: {html.escape(active_path.label)}
                </div>
            </div>

            <div class="svg-wrap">
                <svg viewBox="0 0 100 92" preserveAspectRatio="xMidYMid meet">
                    {svg_edges}
                    {svg_nodes}
                </svg>
            </div>

            <div class="legend">
                {legend_cards}
            </div>
        </div>
    </body>
    </html>
    """


def _render_flow_chart(active_path: DemoPath) -> None:
    flow_html = _build_flow_html(active_path)
    components.html(flow_html, height=720, scrolling=False)


def render_metrics_tab() -> None:
    """METRICS tab demo with an interactive visual flowchart."""
    _init_metrics_state()

    st.markdown("## Metrics")
    st.info(
        "Demo page: this visualizes how a future GHOST metrics / pipeline cockpit could show active execution paths."
    )

    active_path = _render_path_selector()
    _render_flow_chart(active_path)

    st.markdown("### Selected Path")
    st.markdown(
        f"""
        <div style="
            border-left:5px solid {active_path.accent};
            background:{active_path.soft};
            border-radius:14px;
            padding:0.85rem 1rem;
            margin-top:0.75rem;
            color:#1f2937;
        ">
            <div style="font-weight:850; font-size:1rem;">
                {html.escape(active_path.label)}
            </div>
            <div style="margin-top:0.2rem; color:#475569;">
                {html.escape(active_path.subtitle)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )