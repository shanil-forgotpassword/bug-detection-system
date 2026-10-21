"""BugLens AI - Intelligent Testing Workspace (Streamlit prototype).

Only one thing is ever executed: the built-in Pytest demo (the add() function
from app_logic.py, or a fixed buggy copy defined below). The app never runs
code that a user types or uploads.
"""

from __future__ import annotations

import base64
import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st

# ----------------------------------------------------------------------
# Paths and settings
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.resolve()
ASSETS_DIR = BASE_DIR / "assets"
CSS_FILE = ASSETS_DIR / "styles.css"
LOGO_FILE = ASSETS_DIR / "buglens-logo.svg"
LOGIC_FILE = BASE_DIR / "app_logic.py"
TEST_FILE = BASE_DIR / "test_app_logic.py"

# Set to False to turn the opening animation off for everyone.
# You can also add ?splash=off to the browser address to skip it once.
SHOW_SPLASH = True

# Fixed, hard-coded buggy example (subtraction instead of addition).
BUGGY_CODE = '''def add(a, b):
    """Return the sum of two numbers."""
    return a - b
'''

# ----------------------------------------------------------------------
# Page definitions
# ----------------------------------------------------------------------
PAGES = {
    "Overview": {"icon": ":material/space_dashboard:"},
    "Coding Workspace": {"icon": ":material/code:"},
    "Test Cases": {
        "icon": ":material/fact_check:",
        "blurb": "Create and manage your own test cases for a function.",
        "note": "For now, the demo uses three predefined test cases. You can see them in the Coding Workspace.",
    },
    "Test Results": {
        "icon": ":material/assessment:",
        "blurb": "Browse the results of every test run in one place.",
        "note": "For now, the result of the latest run appears in the Coding Workspace.",
    },
    "AI Bug Analysis": {
        "icon": ":material/psychology:",
        "blurb": "Get a plain-language explanation of why a test failed, with a suggested fix.",
        "note": "BugLens AI is not connected to an AI model yet, so no analysis is generated.",
    },
    "Tutorials": {
        "icon": ":material/school:",
        "blurb": "Short guided lessons on reading test failures and fixing bugs.",
        "note": "A short preview of the idea is on the Overview page.",
    },
    "Test History": {
        "icon": ":material/history:",
        "blurb": "Review past test runs and compare them over time.",
        "note": "Runs are not saved yet.",
    },
}

NAV_GROUPS = [
    ("Workspace", ["Overview", "Coding Workspace", "Test Cases"]),
    ("Analysis", ["Test Results", "AI Bug Analysis"]),
    ("Learn &amp; Track", ["Tutorials", "Test History"]),
]


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------
def set_page_config() -> None:
    """Must be the first Streamlit call. Uses the logo as the tab icon."""
    try:
        st.set_page_config(
            page_title="BugLens AI",
            page_icon=str(LOGO_FILE),
            layout="wide",
            initial_sidebar_state="expanded",
        )
    except Exception:  # noqa: BLE001 - fall back to a plain emoji icon
        st.set_page_config(
            page_title="BugLens AI",
            page_icon="🔍",
            layout="wide",
            initial_sidebar_state="expanded",
        )


@st.cache_data(show_spinner=False)
def load_css() -> str:
    try:
        return CSS_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


@st.cache_data(show_spinner=False)
def logo_data_uri() -> str:
    """Return the logo as a data URI so no external image URL is needed."""
    try:
        encoded = base64.b64encode(LOGO_FILE.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:image/svg+xml;base64,{encoded}"


def h(markup: str) -> str:
    """Strip indentation and blank lines so Markdown keeps the HTML block intact."""
    return "\n".join(line.strip() for line in markup.splitlines() if line.strip())


def md(markup: str) -> None:
    st.markdown(h(markup), unsafe_allow_html=True)


def esc(text: str) -> str:
    """Escape text for HTML and protect characters Markdown could reinterpret."""
    return html.escape(text, quote=False).replace(":", "&#58;").replace("$", "&#36;")


# ----------------------------------------------------------------------
# Code and report rendering (plain HTML, no extra dependencies)
# ----------------------------------------------------------------------
TOKEN_RE = re.compile(
    r'(?P<doc>"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\')'
    r'|(?P<str>"[^"\n]*"|\'[^\'\n]*\')'
    r"|(?P<com>#[^\n]*)"
    r"|(?P<kw>\b(?:def|return|from|import|assert|if|else|elif|for|while|in|not|and|or|class|True|False|None)\b)"
    r"|(?P<num>\b\d+(?:\.\d+)?\b)"
)


def highlight_lines(code: str) -> list[str]:
    """Return one HTML string per source line with simple syntax colours."""
    pieces: list[tuple[str, str]] = []
    pos = 0
    for match in TOKEN_RE.finditer(code):
        if match.start() > pos:
            pieces.append(("", code[pos : match.start()]))
        kind = match.lastgroup
        css = {"doc": "str", "str": "str", "com": "com", "kw": "kw", "num": "num"}[kind]
        pieces.append((css, match.group()))
        pos = match.end()
    if pos < len(code):
        pieces.append(("", code[pos:]))

    lines: list[str] = [""]
    for css, text in pieces:
        parts = text.split("\n")
        for index, part in enumerate(parts):
            if index > 0:
                lines.append("")
            if part:
                safe = esc(part)
                lines[-1] += f'<span class="{css}">{safe}</span>' if css else safe
    return lines


def code_panel_html(filename: str, code: str, badge_html: str = "") -> str:
    rows = []
    for number, line in enumerate(highlight_lines(code.rstrip("\n")), start=1):
        rows.append(
            f'<div class="bl-line"><span class="bl-ln">{number}</span>'
            f'<span class="bl-lc">{line or "&nbsp;"}</span></div>'
        )
    head = (
        '<div class="bl-editor"><div class="bl-editor-head">'
        '<span class="bl-dots"><i></i><i></i><i></i></span>'
        f'<span class="bl-file">{esc(filename)}</span><span class="bl-spacer"></span>'
        f'<span class="bl-pill">Python</span>{badge_html}</div><div class="bl-code">'
    )
    return head + "\n".join(rows) + "</div></div>"


def report_class(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("E ") or stripped.startswith("E\t"):
        return "bad"
    if "FAILED" in stripped or "ERROR" in stripped:
        return "bad"
    if "PASSED" in stripped:
        return "ok"
    if stripped.startswith(">"):
        return "warn"
    if stripped.startswith("=") or stripped.startswith("_"):
        return "hdr"
    return "txt"


def report_panel_html(output: str) -> str:
    rows = []
    for line in output.rstrip().splitlines():
        rows.append(
            f'<div class="bl-line"><span class="bl-lc {report_class(line)}">{esc(line) or "&nbsp;"}</span></div>'
        )
    head = (
        '<div class="bl-editor"><div class="bl-editor-head">'
        '<span class="bl-dots"><i></i><i></i><i></i></span>'
        '<span class="bl-file">pytest output</span><span class="bl-spacer"></span>'
        '<span class="bl-pill">Actual output</span></div><div class="bl-report">'
    )
    return head + "\n".join(rows) + "</div></div>"


# ----------------------------------------------------------------------
# The controlled Pytest demonstration
# ----------------------------------------------------------------------
def read_demo_files() -> tuple[str, str]:
    return (
        LOGIC_FILE.read_text(encoding="utf-8"),
        TEST_FILE.read_text(encoding="utf-8"),
    )


def run_demo_tests(use_buggy: bool) -> dict:
    """Run the existing Pytest file against the correct or the fixed buggy code.

    Both the code and the tests come from files/constants that belong to this
    project. Nothing the user types or uploads is ever executed.
    """
    correct_source, test_source = read_demo_files()
    source = BUGGY_CODE if use_buggy else correct_source

    result = {
        "mode": "buggy" if use_buggy else "correct",
        "output": "",
        "returncode": None,
        "cases": {},
        "duration": None,
        "problem": "",
    }

    with tempfile.TemporaryDirectory(prefix="buglens_") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "app_logic.py").write_text(source, encoding="utf-8")
        (tmp_path / "test_app_logic.py").write_text(test_source, encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUTF8"] = "1"
        env.pop("PYTEST_ADDOPTS", None)

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-v", "--tb=short", "--color=no", "-p", "no:cacheprovider"],
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                env=env,
            )
        except subprocess.TimeoutExpired:
            result["problem"] = "The test run took longer than 60 seconds and was stopped."
            return result
        except OSError as error:
            result["problem"] = f"Pytest could not be started: {error}"
            return result

        output = (proc.stdout or "") + (proc.stderr or "")
        result["output"] = output.replace(tmp, "<demo>")
        result["returncode"] = proc.returncode

    for match in re.finditer(r"^\S*?::(\w+)\s+(PASSED|FAILED|ERROR)", result["output"], re.MULTILINE):
        result["cases"][match.group(1)] = match.group(2)

    timing = re.search(r" in ([\d.]+)s", result["output"])
    if timing:
        result["duration"] = timing.group(1)
    return result


def extract_cases(test_source: str) -> list[tuple[str, str]]:
    """List (test name, assertion) pairs from the test file for display."""
    return re.findall(r"def (test_\w+)\(\):\s*\n\s+assert ([^\n]+)", test_source)


# ----------------------------------------------------------------------
# Navigation
# ----------------------------------------------------------------------
def go_to(page: str) -> None:
    st.session_state["page"] = page


def nav_button(label: str, icon: str, key: str, active: bool, on_click, args=()) -> None:
    """Sidebar button with a Material icon (falls back if icons are unsupported)."""
    options = {
        "key": key,
        "type": "primary" if active else "secondary",
        "on_click": on_click,
        "args": args,
    }
    try:
        st.button(label, icon=icon, **options)
    except TypeError:
        st.button(label, **options)


def render_sidebar() -> None:
    current = st.session_state["page"]

    with st.sidebar:
        md(
            f"""
            <div class="bl-brand">
            <img class="bl-brand-logo" src="{logo_data_uri()}" alt="BugLens AI logo"/>
            <div class="bl-brand-text">
            <div class="bl-brand-name">BugLens AI</div>
            <div class="bl-brand-sub">Intelligent Testing Workspace</div>
            </div>
            </div>
            """
        )

        for index, (group, pages) in enumerate(NAV_GROUPS):
            first = " bl-section-first" if index == 0 else ""
            md(f'<div class="bl-section{first}">{group}</div>')
            for page in pages:
                key = "nav_" + page.lower().replace(" ", "_")
                nav_button(page, PAGES[page]["icon"], key, page == current, go_to, (page,))

        md(
            """
            <div class="bl-status">
            <strong><span class="bl-dot"></span><span class="bl-status-text">Prototype status</span></strong>
            <span class="bl-status-text">Python Test Demo is live. Other pages are planned.</span>
            </div>
            """
        )


# ----------------------------------------------------------------------
# Opening animation (plays once per browser session)
# ----------------------------------------------------------------------
def maybe_show_splash() -> None:
    if not SHOW_SPLASH or st.session_state.get("splash_done"):
        return
    st.session_state["splash_done"] = True

    try:
        if str(st.query_params.get("splash", "")).lower() == "off":
            return
    except Exception:  # noqa: BLE001 - query params are optional
        pass

    logo = logo_data_uri()
    md(
        f"""
        <style>
        [data-testid="stMain"] {{ animation: bl-main-in 0.7s ease 1.5s both; }}
        .bl-brand-logo {{ animation: bl-fade-in 0.4s ease 1.9s both; }}
        </style>
        <div class="bl-splash" aria-hidden="true">
        <div class="bl-splash-bg"></div>
        <div class="bl-splash-stack">
        <img class="bl-splash-logo" src="{logo}" alt=""/>
        <div class="bl-splash-name">BugLens AI</div>
        <div class="bl-splash-tag">Find the failure. Understand the cause.</div>
        </div>
        </div>
        """
    )


# ----------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------
def page_overview() -> None:
    md(
        """
        <h1 class="bl-title">Welcome to BugLens AI</h1>
        <p class="bl-sub">Run Pytest checks on a small Python function, see which check failed, and learn why.</p>
        <div class="bl-hero">
        <div>
        <span class="bl-pill bl-pill-blue">Prototype</span>
        <h2>Find the failure. Understand the cause.</h2>
        <p>BugLens AI shows the exact result of each test, so a wrong answer is easy to spot and explain.</p>
        </div>
        <div class="bl-term">
        <div class="bl-term-head">test_app_logic.py</div>
        <div class="bl-term-body">
        <div style="color:#c3cce0">def test_add_positive_numbers():</div>
        <div style="color:#fbbf24">&gt;       assert add(2, 3) == 5</div>
        <div style="color:#f87171">E       assert -1 == 5</div>
        <div style="color:#f87171">FAILED: add(2, 3) returned -1</div>
        </div>
        </div>
        </div>
        """
    )

    left, right = st.columns(2, gap="large")

    with left:
        with st.container(border=True):
            md(
                """
                <div class="bl-proj-title">Python Test Demo</div>
                <p class="bl-p">Tests an addition function with three predefined Pytest cases. Switch between correct and buggy code to see a pass and a failure.</p>
                <span class="bl-pill bl-pill-ok">Available</span>
                <span class="bl-pill bl-pill-warn">Prototype</span>
                <span class="bl-pill">Python</span>
                <span class="bl-pill">Pytest</span>
                <span class="bl-pill">Streamlit</span>
                """
            )
            st.button(
                "Open Coding Workspace",
                key="ov_open_workspace",
                type="primary",
                on_click=go_to,
                args=("Coding Workspace",),
            )

    with right:
        with st.container(border=True):
            md(
                """
                <div class="bl-proj-title">About BugLens AI</div>
                <p class="bl-p">BugLens AI is a testing workspace for learning how failures happen. Today it runs one controlled Pytest demo. AI explanations of failures are planned, but not built yet.</p>
                <p class="bl-p">It does not run code you type or upload.</p>
                """
            )

    left, right = st.columns(2, gap="large")

    with left:
        with st.container(border=True):
            md(
                """
                <div class="bl-proj-title">Getting started</div>
                <ol class="bl-steps">
                <li><b>Open the Coding Workspace</b> from the sidebar.</li>
                <li><b>Choose correct or buggy code</b> to decide which version is tested.</li>
                <li><b>Click Run Tests</b> and read the report.</li>
                </ol>
                """
            )

    with right:
        with st.container(border=True):
            md(
                """
                <div class="bl-proj-title">How a test catches a wrong result</div>
                <p class="bl-p">The test expects <code>add(2, 3)</code> to equal <code>5</code>. In the buggy version, <code>add</code> subtracts, so it returns <code>-1</code>. Pytest compares <code>-1</code> with <code>5</code>, sees they differ, and marks the test as failed. The report shows both values.</p>
                """
            )


def page_workspace() -> None:
    try:
        correct_source, test_source = read_demo_files()
    except OSError as error:
        st.error(f"A demo file is missing: {error}. Keep app_logic.py and test_app_logic.py next to app.py.")
        return

    md(
        """
        <h1 class="bl-title">Coding Workspace</h1>
        <p class="bl-sub">Read-only demo. BugLens AI runs only this built-in example, never code you type or upload.</p>
        """
    )

    mode = st.radio(
        "Code version",
        ["Correct code", "Buggy code"],
        horizontal=True,
        key="ws_mode",
    )
    use_buggy = mode == "Buggy code"

    badge = (
        '<span class="bl-pill bl-pill-bad">Buggy version</span>'
        if use_buggy
        else '<span class="bl-pill bl-pill-ok">Correct version</span>'
    )
    shown_code = BUGGY_CODE if use_buggy else correct_source
    last_run = st.session_state.get("last_run")

    code_col, test_col = st.columns(2, gap="large")

    with code_col:
        md('<div class="bl-h3">Code under test</div>')
        st.markdown(code_panel_html("app_logic.py", shown_code, badge), unsafe_allow_html=True)
        if use_buggy:
            md('<p class="bl-p" style="margin-top:0.7rem">This version subtracts instead of adding.</p>')

    with test_col:
        md('<div class="bl-h3">Predefined test cases</div>')
        rows = []
        for name, assertion in extract_cases(test_source):
            status = last_run["cases"].get(name) if last_run else None
            if status == "PASSED":
                chip = '<span class="bl-pill bl-pill-ok">Passed</span>'
            elif status in ("FAILED", "ERROR"):
                chip = '<span class="bl-pill bl-pill-bad">Failed</span>'
            else:
                chip = '<span class="bl-pill">Not run</span>'
            rows.append(
                '<div class="bl-case"><div class="bl-case-main">'
                f'<span class="bl-case-name">{esc(name)}</span>'
                f'<span class="bl-case-assert">assert {esc(assertion)}</span></div>{chip}</div>'
            )
        header = (
            '<div class="bl-editor"><div class="bl-editor-head">'
            '<span class="bl-dots"><i></i><i></i><i></i></span>'
            '<span class="bl-file">test_app_logic.py</span><span class="bl-spacer"></span>'
            '<span class="bl-pill">Pytest</span></div>'
        )
        st.markdown(header + "\n".join(rows) + "</div>", unsafe_allow_html=True)
        with st.expander("View the full test file"):
            st.code(test_source, language="python")

    st.write("")
    run_clicked = st.button("Run Tests", key="ws_run", type="primary")
    if run_clicked:
        with st.spinner("Running Pytest..."):
            st.session_state["last_run"] = run_demo_tests(use_buggy)
        st.rerun()

    st.write("")
    md('<div class="bl-h3">Test results</div>')
    render_results(last_run)

    st.write("")
    with st.container(border=True):
        md(
            """
            <div class="bl-proj-title">AI Bug Analysis <span class="bl-pill bl-pill-warn" style="margin-left:0.5rem">Planned</span></div>
            <p class="bl-p">After a failed run, this panel will explain the likely cause and suggest a fix. It is not connected to an AI model yet, so nothing is generated here.</p>
            """
        )


def render_results(last_run: dict | None) -> None:
    if not last_run:
        with st.container(border=True):
            md('<p class="bl-p" style="margin:0">No results yet. Choose a code version and click Run Tests.</p>')
        return

    version = "buggy code" if last_run["mode"] == "buggy" else "correct code"

    if last_run["problem"]:
        md(
            f"""
            <div class="bl-banner bl-banner-warn"><div>Pytest did not finish<small>{esc(last_run["problem"])}</small></div></div>
            """
        )
        return

    cases = last_run["cases"]
    passed = sum(1 for status in cases.values() if status == "PASSED")
    failed = sum(1 for status in cases.values() if status in ("FAILED", "ERROR"))
    total = passed + failed

    if last_run["returncode"] == 0 and total > 0:
        banner = (
            f'<div class="bl-banner bl-banner-ok"><div>All {total} tests passed'
            f"<small>Ran against the {version}.</small></div></div>"
        )
    elif failed > 0:
        banner = (
            f'<div class="bl-banner bl-banner-bad"><div>{failed} of {total} tests failed'
            f"<small>Ran against the {version}. Read the report below to see what each test expected.</small></div></div>"
        )
    else:
        banner = (
            '<div class="bl-banner bl-banner-warn"><div>Pytest did not report any test results'
            f"<small>Ran against the {version}. Check the output below.</small></div></div>"
        )

    duration = f"{last_run['duration']}s" if last_run["duration"] else "n/a"
    stats = (
        '<div class="bl-stats">'
        f'<div class="bl-stat"><b>{passed}</b><span>Passed</span></div>'
        f'<div class="bl-stat"><b>{failed}</b><span>Failed</span></div>'
        f'<div class="bl-stat"><b>{duration}</b><span>Duration</span></div>'
        "</div>"
    )
    st.markdown(banner + stats, unsafe_allow_html=True)

    md('<div class="bl-h3">Execution report</div>')
    st.markdown(report_panel_html(last_run["output"]), unsafe_allow_html=True)


def page_planned(page: str) -> None:
    info = PAGES[page]
    md(
        f"""
        <h1 class="bl-title">{page}</h1>
        <div class="bl-planned">
        <span class="bl-pill bl-pill-warn">Planned</span>
        <div class="bl-h3" style="margin-top:0.6rem">Under development</div>
        <p class="bl-p">{info["blurb"]}</p>
        <p class="bl-p" style="margin-bottom:0">{info["note"]}</p>
        </div>
        """
    )
    st.write("")
    st.button(
        "Open Coding Workspace",
        key="planned_go_" + page.lower().replace(" ", "_"),
        on_click=go_to,
        args=("Coding Workspace",),
    )


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> None:
    set_page_config()

    st.session_state.setdefault("page", "Overview")

    css = load_css()
    if css:
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    else:
        st.warning("assets/styles.css was not found, so the default Streamlit look is being used.")

    maybe_show_splash()
    render_sidebar()

    page = st.session_state["page"]
    if page == "Overview":
        page_overview()
    elif page == "Coding Workspace":
        page_workspace()
    else:
        page_planned(page)


main()
