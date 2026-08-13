"""
Agent Activity page — Real agent communication log showing inputs, tools, and outputs.
"""

import streamlit as st
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..'))
from mizan_app.orchestrator import get_activity_log


def show():
    st.markdown('<h1 style="color:#002B5C;font-size:24px;">⚙ Agent Activity</h1>', unsafe_allow_html=True)
    st.markdown('<p style="color:#5A6B7A;margin-bottom:20px;">Real-time communication log showing each agent\'s inputs, tools used, and outputs.</p>', unsafe_allow_html=True)

    log = get_activity_log()

    if not log:
        st.info("⚠️ No agent activity recorded yet. Run an evaluation first from the **Bid Evaluations** page.")
        return

    # ── Timeline View ──
    st.markdown('<h3 style="font-size:16px;color:#002B5C;margin-bottom:16px;">Agent Execution Timeline</h3>', unsafe_allow_html=True)

    for i, entry in enumerate(log):
        ts = entry.get('timestamp', '')
        agent = entry.get('agent', '')
        status = entry.get('status', '')
        inputs = entry.get('inputs', {})
        tool = entry.get('tool', '')
        outputs = entry.get('outputs', {})

        # Time formatting
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(ts)
            time_str = dt.strftime("%H:%M:%S")
        except Exception:
            time_str = ts

        # Status indicator
        if status == 'complete':
            status_icon = '✅'
            border_color = '#2ECC71'
        elif status == 'error':
            status_icon = '❌'
            border_color = '#E74C3C'
        else:
            status_icon = '⏳'
            border_color = '#F39C12'

        elapsed = outputs.get('_elapsed', None)

        st.markdown(f'''
        <div style="background:white;border:1px solid #E8EDF2;border-radius:10px;padding:16px;margin-bottom:12px;border-left:4px solid {border_color};">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
                <span style="font-size:20px;">{status_icon}</span>
                <span style="font-size:13px;color:#8A9BAB;">{time_str}</span>
                <span style="font-weight:600;color:#002B5C;font-size:15px;">{agent}</span>
                {f'<span style="font-size:12px;color:#8A9BAB;">({elapsed}s)</span>' if elapsed else ''}
            </div>
        ''', unsafe_allow_html=True)

        # Tabs for INPUT / TOOL / OUTPUT
        tab1, tab2, tab3 = st.tabs(["📥 INPUT", "🔧 TOOL", "📤 OUTPUT"])

        with tab1:
            st.json(inputs)

        with tab2:
            st.code(tool, language="text")

        with tab3:
            # Show key outputs (exclude private fields)
            display_outputs = {k: v for k, v in outputs.items() if not k.startswith('_')}
            st.json(display_outputs)

        # Arrow to next agent
        if i < len(log) - 1:
            st.markdown('<div style="text-align:center;color:#C8D6E5;font-size:14px;margin:-8px 0;">↓</div>', unsafe_allow_html=True)

    # ── Agent Communication Summary ──
    st.markdown('---')
    st.markdown('<h3 style="font-size:16px;color:#002B5C;margin-bottom:12px;">Agent Communication Flow</h3>', unsafe_allow_html=True)

    st.markdown('''
    ```
    RFP + BID DATA
            ↓
    🔎 Evidence & Retrieval Agent
            ↓
    ✓ Compliance & Screening Agent
            ↓
     ┌──────────────┬──────────────┬──────────────┐
     ↓              ↓              ↓              ↓
    🔧 Technical   💰 Commercial  🦺 HSE        🇦🇪 ICV
     └──────────────┴──────────────┴──────────────┘
            ↓
    ⚠ Risk & Escalation Agent
            ↓
    📝 Recommendation & Report Agent
            ↓
         Procurement Report
            ↓
        👤 Human Approval
    ```
    ''')
    st.markdown('<p style="color:#8A9BAB;font-size:13px;">Each agent passes structured outputs downstream. Agents 3-6 run in parallel.</p>', unsafe_allow_html=True)