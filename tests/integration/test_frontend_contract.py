"""Static contract tests for the shared admin frontend helper namespace.

Guards the Task 9C contract:

1. admin.js defines the formal ``window.EMGAdmin`` namespace.
2. Every expected shared helper is exported in the namespace.
3. Every page script obtains shared helpers exclusively from
   ``window.EMGAdmin`` via an explicit ``const { ... } = window.EMGAdmin``
   destructuring header.
4. Page scripts never reference a shared helper that is not part of the
   export contract (prevents regressions such as
   ``ReferenceError: setStatusBadge is not defined``).
5. No page script re-declares a contract helper locally.
6. The flat ``window.*`` compatibility layer is derived from the single
   namespace (``Object.assign(window, window.EMGAdmin)``), so both
   contracts cannot drift apart.

These are deliberately static, structure-specific assertions over the
project's fixed JS file layout. They do not attempt to implement a
JavaScript parser and they do not require Node or a browser.
"""

import re
from pathlib import Path

STATIC_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "easymodelgate" / "web" / "static"
)

ADMIN_JS = STATIC_DIR / "admin.js"
PAGE_SCRIPTS = [
    STATIC_DIR / "login.js",
    STATIC_DIR / "users.js",
    STATIC_DIR / "keys.js",
    STATIC_DIR / "usage.js",
    STATIC_DIR / "overview.js",
    STATIC_DIR / "system.js",
]

# The complete expected export contract for window.EMGAdmin.
EXPECTED_CONTRACT = [
    # Core API
    "adminFetch",
    # Formatting
    "formatNumber",
    "formatTimestamp",
    "formatUptime",
    "formatTokenUsage",
    "formatRpm",
    # Security / DOM text
    "escapeHtml",
    "safeTextContent",
    "setValue",
    "setStatusBadge",
    # Toast
    "showToast",
    "showSuccessToast",
    "showErrorToast",
    "showInfoToast",
    # Modal
    "createModal",
    "confirmModal",
    "alertModal",
    "closeAllModals",
    # Form
    "setButtonLoading",
    "getFormData",
    "clearForm",
    "showFormError",
    "clearFormErrors",
    # Table
    "setTableLoading",
    "setTableEmpty",
    "setTableError",
    "renderTableRows",
    # Clipboard
    "copyToClipboard",
    # Utility
    "debounce",
    # Chart
    "renderLineChart",
    # Request table
    "renderRequestTable",
    "getStatusBadgeHtml",
]

CONTRACT_SET = set(EXPECTED_CONTRACT)
assert len(CONTRACT_SET) == len(EXPECTED_CONTRACT), "contract list has duplicates"

# Identifiers that look like helper references but are never bare-called
# at statement position (they appear as local consts / object properties /
# method chains). Excluded from the bare-reference check.
NON_BARE_IDENTIFIERS = {
    "statusBadge",  # local const in render*Table functions
}

# Host / global objects and JS built-ins that are not shared helpers.
HOST_NAMES = {
    "window", "document", "navigator", "console", "location", "history",
    "fetch", "Promise", "Date", "Math", "JSON", "Object", "Array", "String",
    "Number", "Boolean", "Error", "TypeError", "ReferenceError", "RegExp",
    "Map", "Set", "Symbol", "Proxy", "Reflect", "parseInt", "parseFloat",
    "isNaN", "isFinite", "encodeURIComponent", "decodeURIComponent",
    "encodeURI", "decodeURI", "setTimeout", "clearTimeout", "setInterval",
    "clearInterval", "requestAnimationFrame", "cancelAnimationFrame",
    "FormData", "URLSearchParams", "URL", "AbortController", "AbortSignal",
    "Event", "CustomEvent", "Node", "Element", "HTMLElement", "MutationObserver",
    "localStorage", "sessionStorage", "alert", "confirm", "prompt", "open",
    "close", "atob", "btoa", "structuredClone", "queueMicrotask", "globalThis",
    "undefined", "NaN", "Infinity",
}

# The shared-helper names we look for as bare references in page scripts.
SHARED_HELPER_NAMES = sorted(CONTRACT_SET)
_HELPER_ALT = "|".join(re.escape(n) for n in SHARED_HELPER_NAMES)
# Call reference at statement position (start of line after whitespace)
# or after a control-flow / operator boundary, with a '(' following.
BARE_CALL_RE = re.compile(
    r"(?m)(?:^|[;{}]\s*|\b(?:else|return|await|yield|typeof|void|in|of|new|do|try|catch)\b\s*)"
    + r"(?:(?!\b(?:if|for|while|switch|function|class|let|const|var|else|return|await|yield|typeof|void|in|of|new|do|try|catch)\b)"
    + r"[A-Za-z0-9_$\s])*"
    + r"(?<![\w$.])(" + _HELPER_ALT + r")\s*\("
)
# Local declaration of a contract helper inside a page script.
LOCAL_DECL_RE = re.compile(
    r"(?m)^\s*(?:function\s+|const\s+|let\s+|var\s+)(" + _HELPER_ALT + r")\b"
)
# Destructuring header: const { ... } = window.EMGAdmin;
DESTRUCTURE_RE = re.compile(
    r"const\s*\{([^}]*)\}\s*=\s*window\.EMGAdmin\s*;"
)


def _read(path: Path) -> str:
    assert path.exists(), f"missing static file: {path}"
    return path.read_text(encoding="utf-8")


def _strip_comments_and_strings(src: str) -> str:
    """Remove comments and string/template literals to avoid false
    positives from helper names mentioned in comments or markup strings.

    Structural (bracket) layout is preserved so line-anchored checks
    still work.
    """
    out = []
    i, n = 0, len(src)
    state = "code"  # code | line_comment | block_comment | sq | dq | tpl
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == "/" and nxt == "/":
                state = "line_comment"
                i += 2
                continue
            if c == "/" and nxt == "*":
                state = "block_comment"
                i += 2
                continue
            if c == "'":
                state = "sq"
                out.append(" ")
                i += 1
                continue
            if c == '"':
                state = "dq"
                out.append(" ")
                i += 1
                continue
            if c == "`":
                state = "tpl"
                out.append(" ")
                i += 1
                continue
            out.append(c)
            i += 1
        elif state == "line_comment":
            if c == "\n":
                state = "code"
                out.append("\n")
            i += 1
        elif state == "block_comment":
            if c == "*" and nxt == "/":
                state = "code"
                i += 2
                continue
            if c == "\n":
                out.append("\n")
            i += 1
        else:  # string / template literal
            if c == "\\":
                i += 2
                continue
            if (state == "sq" and c == "'") or (state == "dq" and c == '"') or (state == "tpl" and c == "`"):
                state = "code"
            out.append(" " if c != "\n" else "\n")
            i += 1
    return "".join(out)


def _extract_namespace_members(src: str) -> list:
    """Extract member names from the single window.EMGAdmin = { ... } literal."""
    m = re.search(r"window\.EMGAdmin\s*=\s*\{", src)
    assert m, "window.EMGAdmin namespace literal not found in admin.js"
    start = m.end()
    depth = 1
    i = start
    while i < len(src) and depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    body = src[start:i - 1]
    body = _strip_comments_and_strings(body)
    members = []
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        m2 = re.fullmatch(r"([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::|=)?", line)
        assert m2, f"unrecognized namespace member line: {line!r}"
        members.append(m2.group(1))
    return members


def _extract_destructured(path: Path, src: str) -> list:
    m = DESTRUCTURE_RE.search(src)
    assert m, f"{path.name}: no `const {{ ... }} = window.EMGAdmin;` header"
    names = []
    for part in m.group(1).split(","):
        part = part.strip()
        if not part:
            continue
        assert re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", part), (
            f"{path.name}: bad destructured entry {part!r}"
        )
        names.append(part)
    return names


# ---------------------------------------------------------------------------
# admin.js: namespace contract
# ---------------------------------------------------------------------------

def test_admin_js_defines_emgadmin_namespace():
    src = _read(ADMIN_JS)
    members = _extract_namespace_members(src)
    assert members, "window.EMGAdmin is empty"
    assert len(members) == len(set(members)), "duplicate members in window.EMGAdmin"


def test_admin_js_contract_matches_expected_list():
    src = _read(ADMIN_JS)
    members = _extract_namespace_members(src)
    missing = CONTRACT_SET - set(members)
    unexpected = set(members) - CONTRACT_SET
    assert not missing, f"missing from window.EMGAdmin: {sorted(missing)}"
    assert not unexpected, f"unexpected in window.EMGAdmin: {sorted(unexpected)}"


def test_admin_js_compat_layer_derived_from_namespace():
    src = _read(ADMIN_JS)
    assert re.search(
        r"Object\.assign\(\s*window\s*,\s*window\.EMGAdmin\s*\)\s*;", src
    ), "flat window.* compat layer must be derived via Object.assign(window, window.EMGAdmin)"
    # No hand-maintained flat export of a contract helper may coexist.
    for name in SHARED_HELPER_NAMES:
        assert not re.search(rf"(?m)^\s*window\.{name}\s*=", src), (
            f"admin.js: hand-written window.{name} export found; "
            "compat layer must be derived from window.EMGAdmin"
        )


def test_admin_js_defines_all_contract_helpers():
    src = _strip_comments_and_strings(_read(ADMIN_JS))
    for name in SHARED_HELPER_NAMES:
        assert re.search(rf"(?m)^\s*(?:async\s+)?function\s+{name}\s*\(", src), (
            f"admin.js: shared helper {name} is exported but not defined"
        )


# ---------------------------------------------------------------------------
# page scripts: explicit namespace usage
# ---------------------------------------------------------------------------

def test_page_scripts_exist_and_use_explicit_destructuring():
    for path in PAGE_SCRIPTS:
        src = _read(path)
        names = _extract_destructured(path, src)
        assert names, f"{path.name}: destructuring header is empty"
        assert len(names) == len(set(names)), (
            f"{path.name}: duplicate identifiers in destructuring header: "
            f"{[n for n in set(names) if names.count(n) > 1]}"
        )
        outside = set(names) - CONTRACT_SET
        assert not outside, (
            f"{path.name}: destructures symbols not in export contract: {sorted(outside)}"
        )


def test_page_scripts_do_not_reference_unexported_helpers():
    """Every bare call of a contract-helper-shaped identifier in a page
    script must be bound by that script's destructuring header, and every
    shared helper the script calls must be part of the export contract.

    Catches the original Task 9C failure mode: a page calling a shared
    helper (setStatusBadge, setValue, renderLineChart, ...) that the
    shared module does not export.
    """
    for path in PAGE_SCRIPTS:
        src = _strip_comments_and_strings(_read(path))
        destructured = set(_extract_destructured(path, src))
        for m in BARE_CALL_RE.finditer(src):
            name = m.group(1)
            assert name in CONTRACT_SET, (
                f"{path.name}:{src[:m.start()].count(chr(10)) + 1}: "
                f"bare reference to shared helper {name} not in export contract"
            )
            assert name in destructured, (
                f"{path.name}:{src[:m.start()].count(chr(10)) + 1}: "
                f"bare call of {name}() is not bound via window.EMGAdmin "
                "destructuring (implicit global dependency)"
            )


def test_page_scripts_do_not_locally_redeclare_contract_helpers():
    for path in PAGE_SCRIPTS:
        src = _strip_comments_and_strings(_read(path))
        for m in LOCAL_DECL_RE.finditer(src):
            name = m.group(1)
            line = src[: m.start()].count("\n") + 1
            # The destructuring header itself declares these names.
            if line <= 60 and re.match(
                r"(?m)^\s*const\s*\{", src[: m.start()]
            ) and DESTRUCTURE_RE.search(src[: m.end() + 30]):
                continue
            raise AssertionError(
                f"{path.name}:{line}: local declaration of shared helper "
                f"{name}() duplicates the EMGAdmin contract; migrate it to "
                "window.EMGAdmin and remove the local copy"
            )


def test_page_scripts_only_reference_contract_helpers():
    """Reverse direction: any shared-helper name appearing in a page script
    must be destructured there (no half-wired helpers)."""
    for path in PAGE_SCRIPTS:
        src = _strip_comments_and_strings(_read(path))
        destructured = set(_extract_destructured(path, src))
        referenced = set(BARE_CALL_RE.findall(src))
        undeclared = referenced - destructured
        assert not undeclared, (
            f"{path.name}: references shared helpers not in its destructuring "
            f"header: {sorted(undeclared)}"
        )


# ---------------------------------------------------------------------------
# structural sanity: no implicit-global fallback, no inline script risk
# ---------------------------------------------------------------------------

def test_no_page_script_defines_its_own_emgadmin():
    for path in PAGE_SCRIPTS:
        src = _read(path)
        assert "window.EMGAdmin =" not in src.replace("window.EMGAdmin;", ""), (
            f"{path.name}: page script must not define window.EMGAdmin"
        )


def test_templates_load_scripts_as_external_files_only():
    """CSP guard: admin templates reference only external <script src>
    files; no inline script or inline event handler is introduced."""
    templates_dir = STATIC_DIR.parent / "templates"
    for tpl in sorted(templates_dir.glob("*.html")):
        text = tpl.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)", text, re.I), (
            f"{tpl.name}: inline <script> detected"
        )
        assert not re.search(r"\son[a-z]+\s*=", text, re.I), (
            f"{tpl.name}: inline event handler detected"
        )
