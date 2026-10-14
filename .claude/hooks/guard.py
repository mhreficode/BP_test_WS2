#!/usr/bin/env python3
"""PreToolUse guard for the workshop. Standard library only.

Reads one tool request as JSON on stdin. Exit 0 = allowed. Exit 2 = blocked, with a plain
reason on stderr. Any parse problem blocks (fails closed).

This guard restrains the agent only. It is best effort. A person with an editor or a
terminal can change or bypass it.
"""
import ast
import os
import re
import shlex
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import hooklib as H  # noqa: E402

ZONE_RE = re.compile(r"^# (>>>|<<<) ZONE (C[1-6])\s*$")
ARENA_PY = os.path.join(H.ROOT, "arena", "arena.py")
APP_PY = os.path.join(H.ROOT, "app", "colorlab.py")
TESTS_DIR = os.path.join(H.ROOT, "tests")
GOLDEN_PY = os.path.join(H.ROOT, ".claude", "skills", "golden-dataset", "build_golden.py")

BAD_TOOLS = ("WebFetch", "WebSearch", "NotebookEdit")


class Deny(Exception):
    pass


def deny(text):
    raise Deny(text)


class Ctx(object):
    def __init__(self, event):
        self.event = event
        cwd = event.get("cwd")
        self.cwd = cwd if isinstance(cwd, str) and os.path.isdir(cwd) else H.ROOT
        self.state = H.load_state()
        self.phase = str(self.state.get("phase") or "none")
        self.frame = str(self.state.get("frame") or "")
        self.team = str(self.state.get("team") or "")
        self.branch = str(self.state.get("branch") or "")
        self.owner = H.owner_active(event)

    def cwd_inside(self):
        return H.inside(os.path.realpath(self.cwd))


# ---------- reading ----------------------------------------------------------------------

def sandbox_ok(ctx, parts):
    """The planter may read the sandbox, in the plant phase only."""
    return ctx.phase == "plant" and H.same(parts, H.SANDBOX_PARTS)


def check_read_parts(ctx, parts, what):
    if parts is None:
        deny("Blocked: %s is outside the project folder." % what)
    if H.always_protected(parts):
        deny("Blocked: that file is private. It is never opened.")
    if H.game_protected(parts) and not ctx.owner and not sandbox_ok(ctx, parts):
        deny("Blocked: that part of the game is closed. Ask your question about the rules or the API instead.")


def contains_secret(directory):
    seen = 0
    for base, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in dirs + files:
            seen += 1
            if seen > 6000:
                return False
            rel = H.parts_of(os.path.join(base, name)) if H.inside(os.path.realpath(base)) else (name,)
            if H.always_protected(rel) or H.secret_part((name,)):
                return True
    return False


def check_recursive(ctx, parts, label):
    """A tool that walks a whole folder."""
    if parts is None:
        deny("Blocked: %s is outside the project folder." % label)
    if H.always_protected(parts):
        deny("Blocked: that file is private. It is never opened.")
    if not ctx.owner and (H.game_protected(parts) or H.covers_game_tree(parts)):
        if not (ctx.phase == "plant" and H.starts_with(parts, (".arena", "sandbox"))):
            deny("Blocked: searching here would walk into closed folders. Point it at app/ or tests/.")
    real = os.path.join(H.ROOT, *parts) if parts else H.ROOT
    if os.path.isdir(real) and contains_secret(real):
        deny("Blocked: a private file lives in that folder. Search a smaller folder, such as app/ or tests/.")


def tool_read(ctx, inp):
    path = inp.get("file_path")
    if not isinstance(path, str) or not path:
        deny("Blocked: no file path given.")
    check_read_parts(ctx, H.resolve_literal(path, ctx.cwd), path)


def tool_grep(ctx, inp):
    path = inp.get("path")
    if path is not None and not isinstance(path, str):
        deny("Blocked: bad search path.")
    glob = inp.get("glob")
    if isinstance(glob, str) and ".." in glob.replace("\\", "/").split("/"):
        deny("Blocked: the glob may not leave the folder.")
    parts = H.resolve_literal(path or ".", ctx.cwd)
    check_recursive(ctx, parts, "the search path")


def tool_glob(ctx, inp):
    pattern, path = inp.get("pattern"), inp.get("path")
    if not isinstance(pattern, str) or not pattern:
        deny("Blocked: no pattern given.")
    if path is not None and not isinstance(path, str):
        deny("Blocked: bad path.")
    if os.path.isabs(pattern.replace("\\", "/")):
        pat = H.pattern_parts(pattern, ctx.cwd)
    else:
        base = H.resolve_literal(path or ".", ctx.cwd)
        if base is None:
            deny("Blocked: the folder is outside the project folder.")
        comps = pattern.replace("\\", "/").split("/")
        if ".." in comps:
            deny("Blocked: the pattern may not leave the folder.")
        pat = list(base) + [c for c in comps if c not in ("", ".")]
    if pat is None:
        deny("Blocked: that pattern points outside the project folder.")
    if H.pattern_hits(pat, H.GATE_PARTS, True, True) or H.pattern_hits(pat, (".env",), True, True):
        deny("Blocked: that pattern reaches a private file.")
    if not ctx.owner:
        for tree in H.GAME_TREES:
            if H.pattern_hits(pat, tree, True):
                deny("Blocked: that pattern reaches a closed folder. Use a pattern inside app/ or tests/.")


# ---------- writing ----------------------------------------------------------------------

GAME_CONTENT = [".arena", "arena/base", "arena\\base", "refs/arena", "handoff", "colorlab.py",
                "import colorlab", "from colorlab", "8080", "arena.py", "owner_on"]
SAFE_CONTENT = [".claude", "owner_gate", "subprocess", "os.system", "os.popen", "__import__",
                "importlib", "ctypes", "shutil", "rmtree", "os.remove", "os.unlink", "socket",
                "sudo ", "curl ", "wget "]
CALL_RE = re.compile(r"(?<![A-Za-z0-9_.])(eval|exec)\s*\(")
URL_RE = re.compile(r"https?://(?!127\.0\.0\.1|localhost)", re.I)


def scan_test_text(ctx, text):
    low = text.lower()
    for word in SAFE_CONTENT:
        if word in low:
            deny("Blocked: a test may not contain \"%s\". Tests only call the API." % word.strip())
    if CALL_RE.search(text) or URL_RE.search(text):
        deny("Blocked: a test may not run code from text or call other web sites.")
    if not ctx.owner:
        for word in GAME_CONTENT:
            if word in low:
                deny("Blocked: a test may not contain \"%s\". Read the base URL from the "
                     "COLORLAB_URL variable and use only rules.md and the spec." % word)


# ---------- structure check of test files (best effort) ----------------------------------

SAFE_MODULES = {"unittest", "json", "re", "math", "string", "typing", "collections", "itertools",
                "functools", "decimal", "fractions", "textwrap", "copy", "time", "__future__"}
DENY_NAMES = {"__import__", "eval", "exec", "compile", "globals", "locals", "vars", "getattr",
              "setattr", "delattr", "breakpoint", "input", "exit", "quit", "__builtins__", "builtins"}
DENY_ATTRS = {"os", "sys", "subprocess", "builtins", "importlib", "system", "popen", "fork", "modules",
              "discover", "loadTestsFromName", "loadTestsFromNames", "__subclasses__", "__mro__",
              "__bases__", "__globals__", "__builtins__", "__dict__", "__code__", "__loader__",
              "__spec__", "__getattribute__", "__import__", "__base__", "__closure__"}
SCHEME_RE = re.compile(r"^\s*(file|ftp|data|jar)\s*:", re.I)
TESTS_PATH = os.path.join(H.ROOT, "tests")


def helper_exists(name):
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name)) and \
        os.path.isfile(os.path.join(TESTS_PATH, name + ".py"))


def open_problem(ctx, node):
    """Return a reason if this open() call is not a plain read of a literal path."""
    if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
        return "open() needs a plain text path in quotes (no joins, no variables, no f-strings)"
    mode = None
    if len(node.args) > 1:
        mode = node.args[1]
    for kw in node.keywords:
        if kw.arg == "mode":
            mode = kw.value
        if kw.arg in ("opener", "file"):
            return "open() may not use %s" % kw.arg
    if len(node.args) > 2 and not isinstance(node.args[2], ast.Constant):
        return "open() arguments must be plain values"
    if mode is not None and (not isinstance(mode, ast.Constant) or not isinstance(mode.value, str)
                             or any(c not in "rbt" for c in mode.value)):
        return "open() may only read"
    path = node.args[0].value.replace("\\", "/")
    if not path or path.startswith("/") or ".." in path.split("/") or re.match(r"^[A-Za-z]:", path):
        return "open() may only read files inside the project, by a path like app/openapi/color-v1.json"
    parts = H.resolve_literal(path, H.ROOT)
    if parts is None or H.always_protected(parts):
        return "open() may not read that file"
    if not ctx.owner:
        low = path.lower()
        if H.game_protected(parts) or H.same(parts, ("app", "colorlab.py")) or \
                any(w in low for w in ("handoff", "final", "owner_", ".arena", ".git", "arena/base")):
            return "open() may not read that file"
        if not parts or H.norm(parts[0]) not in ("app", "tests"):
            return "open() may read files under app/ (spec, pact, seed) or tests/ only"
    return None


def ast_problem(ctx, text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return "the file is not valid Python, so it could not be checked"
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for al in node.names:
                top = al.name.split(".")[0]
                if top == "os":
                    if al.name != "os" or al.asname:
                        return "import os plainly; use only os.environ"
                elif top == "urllib":
                    if al.name not in ("urllib", "urllib.request", "urllib.parse", "urllib.error"):
                        return "import of %s is not allowed" % al.name
                elif top == "http":
                    if al.name not in ("http", "http.client"):
                        return "import of %s is not allowed" % al.name
                elif top in SAFE_MODULES:
                    pass
                elif not (al.name == top and helper_exists(top)):
                    return "import of %s is not allowed (a helper must already exist in tests/)" % al.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            top = mod.split(".")[0]
            names = [a.name for a in node.names]
            if node.level or "*" in names:
                return "use plain imports, no relative or star imports"
            if top == "os":
                if mod != "os" or names != ["environ"]:
                    return "from os you may import only environ"
            elif top == "urllib":
                if not (mod in ("urllib.request", "urllib.parse", "urllib.error") or
                        (mod == "urllib" and set(names) <= {"request", "parse", "error"})):
                    return "import from %s is not allowed" % mod
            elif top == "http":
                if not (mod == "http.client" or (mod == "http" and set(names) <= {"client", "HTTPStatus"})):
                    return "import from %s is not allowed" % mod
            elif top in SAFE_MODULES:
                pass
            elif not (mod == top and helper_exists(top)):
                return "import from %s is not allowed (a helper must already exist in tests/)" % mod
        elif isinstance(node, ast.Name):
            if node.id in DENY_NAMES:
                return "the name %s is not allowed" % node.id
            par = parent.get(node)
            if node.id == "os" and not (isinstance(par, ast.Attribute) and par.value is node and par.attr == "environ"):
                return "os may only be used as os.environ"
            if node.id == "open" and not (isinstance(par, ast.Call) and par.func is node):
                return "open may only be called directly"
        elif isinstance(node, ast.Attribute):
            if node.attr in DENY_ATTRS:
                return "the attribute .%s is not allowed" % node.attr
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                why = open_problem(ctx, node)
                if why:
                    return why
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if SCHEME_RE.match(node.value):
                return "that kind of address is not allowed"
    return None


def check_test_source(ctx, text, name):
    why = ast_problem(ctx, text)
    if why:
        deny("Blocked: %s: %s. A test may only call the API and read the spec files." % (name, why))


def check_test_file(ctx, real, seen=None):
    """A test file on disk, plus the helper files it imports from tests/."""
    seen = seen if seen is not None else set()
    real = os.path.realpath(real)
    if real in seen:
        return
    if not H.inside(real):
        deny("Blocked: a test file points outside the project folder.")
    seen.add(real)
    try:
        with open(real, encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError):
        deny("Blocked: the test file could not be read, so it is not run.")
    check_test_source(ctx, text, os.path.relpath(real, H.ROOT).replace("\\", "/"))
    for node in ast.walk(ast.parse(text)):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module.split(".")[0]]
        for mod in mods:
            if helper_exists(mod):
                check_test_file(ctx, os.path.join(TESTS_PATH, mod + ".py"), seen)


def check_all_tests(ctx):
    seen, count = set(), 0
    for base, dirs, files in os.walk(TESTS_PATH):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".py"):
                count += 1
                if count > 400:
                    return
                check_test_file(ctx, os.path.realpath(os.path.join(base, name)), seen)


def markers(text):
    return [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ZONE_RE.match(ln)]


def zone_span(lines, zone):
    start = end = None
    for i, line in enumerate(lines):
        hit = ZONE_RE.match(line)
        if hit and hit.group(2) == zone:
            if hit.group(1) == ">>>" and start is None:
                start = i + 1
            elif hit.group(1) == "<<<" and start is not None and end is None:
                end = i
    return (start, end) if start is not None and end is not None else None


def need_zone(ctx):
    if not re.match(r"^C[1-6]$", ctx.frame):
        deny("Blocked: no topic is set. Confirm the topic and run the phase command first.")
    return ctx.frame


def offsets(text, span):
    lines = text.split("\n")
    return (sum(len(x) + 1 for x in lines[:span[0]]), sum(len(x) + 1 for x in lines[:span[1]]))


def code_policy(ctx, real, edits, whole):
    """Edits to app/colorlab.py or the sandbox copy. edits = [(old, new, all)], whole = new text."""
    try:
        with open(real, encoding="utf-8", newline=None) as handle:
            current = handle.read().replace("\r\n", "\n")
    except OSError:
        deny("Blocked: that file cannot be read, so the edit is not checked.")
    if ctx.owner:
        return
    parts = H.parts_of(real)
    is_sandbox = H.same(parts, H.SANDBOX_PARTS)
    if is_sandbox and ctx.phase != "plant":
        deny("Blocked: the sandbox is only for the plant phase.")
    if not is_sandbox and ctx.phase not in ("plant", "hunt"):
        deny("Blocked: app/colorlab.py is edited in the plant or hunt phase only. Current phase: %s." % ctx.phase)
    if is_sandbox or ctx.phase == "plant":
        zone = need_zone(ctx)
        span = zone_span(current.split("\n"), zone)
        if span is None:
            deny("Blocked: the ZONE %s markers are not found in that file." % zone)
        lo, hi = offsets(current, span)
        if whole is not None:
            old_l, new_l = current.split("\n"), whole.replace("\r\n", "\n").split("\n")
            span2 = zone_span(new_l, zone)
            if span2 is None or old_l[:span[0]] != new_l[:span2[0]] or old_l[span[1]:] != new_l[span2[1]:]:
                deny("Blocked: change only the code between the ZONE %s markers." % zone)
            return
        for old, new, every in edits:
            if markers(old) or markers(new) or "ZONE C" in new:
                deny("Blocked: do not touch the ZONE marker lines.")
            hits, at = [], current.find(old)
            while at != -1:
                hits.append(at)
                at = current.find(old, at + 1)
            if not hits or any(h < lo or h + len(old) > hi for h in hits):
                deny("Blocked: change only the code between the ZONE %s markers." % zone)
        return
    # hunt phase on app/colorlab.py: anywhere, but keep the markers
    if whole is not None:
        if markers(whole) != markers(current):
            deny("Blocked: keep the ZONE marker lines as they are.")
        return
    for old, new, every in edits:
        if markers(old) != markers(new):
            deny("Blocked: keep the ZONE marker lines as they are.")


def tool_write(ctx, tool, inp):
    path = inp.get("file_path")
    if not isinstance(path, str) or not path:
        deny("Blocked: no file path given.")
    parts = H.resolve_literal(path, ctx.cwd)
    if parts is None:
        deny("Blocked: that file is outside the project folder.")
    if H.always_protected(parts):
        deny("Blocked: that file is private. It is never changed.")
    if tool == "MultiEdit":
        raw = inp.get("edits")
        if not isinstance(raw, list) or not raw:
            deny("Blocked: no edits given.")
        edits = []
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("old_string"), str) \
                    or not isinstance(item.get("new_string"), str):
                deny("Blocked: the edit could not be read.")
            edits.append((item["old_string"], item["new_string"], bool(item.get("replace_all"))))
        whole = None
    elif tool == "Edit":
        old, new = inp.get("old_string"), inp.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            deny("Blocked: the edit could not be read.")
        edits, whole = [(old, new, bool(inp.get("replace_all")))], None
    else:
        whole = inp.get("content")
        if not isinstance(whole, str):
            deny("Blocked: no content given.")
        edits = []
    texts = [e[1] for e in edits] + ([whole] if whole is not None else [])
    real = os.path.join(H.ROOT, *parts)
    if parts and H.norm(parts[0]) == "tests":
        for text in texts:
            scan_test_text(ctx, text)
        if parts[-1].endswith(".py"):
            final = whole
            if final is None:
                try:
                    with open(real, encoding="utf-8") as handle:
                        final = handle.read()
                except (OSError, UnicodeDecodeError):
                    deny("Blocked: that test file cannot be read, so the edit is not checked.")
                for old, new, every in edits:
                    if old not in final:
                        deny("Blocked: the text to replace was not found, so the edit is not checked.")
                    final = final.replace(old, new) if every else final.replace(old, new, 1)
            check_test_source(ctx, final, "/".join(parts))
        return
    if ctx.owner and parts and H.norm(parts[0]) == "golden":
        if H.norm(parts[-1]).endswith(".py"):
            for text in texts:
                scan_test_text(ctx, text)
        return
    if H.same(parts, ("app", "colorlab.py")) or H.same(parts, H.SANDBOX_PARTS):
        code_policy(ctx, real, edits, whole)
        return
    if parts and H.norm(parts[0]) == ".claude":
        deny("Blocked: the setup folder .claude is not edited by the agent.")
    deny("Blocked: you can edit only tests/ and app/colorlab.py (and the plant sandbox). Not %s."
         % "/".join(parts))


# ---------- shell ------------------------------------------------------------------------

SAY = {
    "sudo": "No admin commands.", "su": "No admin commands.", "doas": "No admin commands.",
    "curl": "No network tools.", "wget": "No network tools.", "ssh": "No network tools.",
    "scp": "No network tools.", "sftp": "No network tools.", "nc": "No network tools.",
    "ncat": "No network tools.", "netcat": "No network tools.", "telnet": "No network tools.",
    "ftp": "No network tools.", "socat": "No network tools.", "nmap": "No network tools.",
    "rm": "No deleting.", "rmdir": "No deleting.", "shred": "No deleting.", "unlink": "No deleting.",
    "pip": "No installs.", "pip3": "No installs.", "npm": "No installs.", "npx": "No installs.",
    "yarn": "No installs.", "pnpm": "No installs.", "apt": "No installs.", "apt-get": "No installs.",
    "snap": "No installs.", "brew": "No installs.", "conda": "No installs.", "uv": "No installs.",
    "bash": "No shell inside a shell.", "sh": "No shell inside a shell.", "zsh": "No shell inside a shell.",
    "dash": "No shell inside a shell.", "eval": "No shell inside a shell.", "exec": "No shell inside a shell.",
    "source": "No shell inside a shell.", ".": "No shell inside a shell.", "xargs": "No shell inside a shell.",
    "env": "No shell inside a shell.", "nohup": "No shell inside a shell.", "timeout": "No shell inside a shell.",
    "base64": "No encoding tricks.", "xxd": "No encoding tricks.", "openssl": "No encoding tricks.",
    "chmod": "Use the edit tool.", "chown": "Use the edit tool.", "ln": "Use the edit tool.",
    "cp": "Use the edit tool.", "mv": "Use the edit tool.", "tee": "Use the edit tool.",
    "touch": "Use the edit tool.", "dd": "Use the edit tool.", "install": "Use the edit tool.",
    "truncate": "Use the edit tool.", "patch": "Use the edit tool.", "sed": "Use the edit tool.",
    "awk": "Use the edit tool.", "perl": "No inline code.", "ruby": "No inline code.", "node": "No inline code.",
    "diff": "Comparing files is closed in the game.", "cmp": "Comparing files is closed in the game.",
    "comm": "Comparing files is closed in the game.",
}
OWNER_FREE = ("diff", "cmp", "comm")
ALLOWED = {"python", "python3", "py", "ls", "cat", "head", "tail", "grep", "egrep", "fgrep", "rg",
           "find", "wc", "pwd", "echo", "printf", "true", "false", "git", "which", "tree", "sort",
           "uniq", "cut", "tr", "cd", "mkdir", "date", "sleep", "basename", "dirname", "realpath",
           "test", "["}
READERS = {"cat", "head", "tail", "wc", "sort", "uniq", "cut", "ls", "tree", "grep", "egrep",
           "fgrep", "rg", "find", "realpath"}
GAME_WORDS = (".arena", "arena/base", "refs/arena", ".git/", "final/bugs")
SAFE_WORDS = ("owner_gate", "owner_on", ".ssh", "id_rsa", "id_ed25519", ".env")
ENV_URL = re.compile(r"^COLORLAB_URL=https?://(127\.0\.0\.1|localhost):\d{2,5}/?$")


def scan_quotes(cmd):
    """Block expansion tricks outside single quotes: $..., backticks, braces, process substitution."""
    state, i = None, 0
    while i < len(cmd):
        c = cmd[i]
        nxt = cmd[i + 1] if i + 1 < len(cmd) else ""
        if state == "'":
            if c == "'":
                state = None
        elif c == "\\":
            i += 1
        elif state == '"':
            if c == '"':
                state = None
            elif c == "`":
                deny("Blocked: command substitution is not allowed.")
            elif c == "$" and nxt not in ("", " ", '"', "\t"):
                deny("Blocked: variables and $( ) are not allowed in commands.")
        else:
            if c == "'":
                state = "'"
            elif c == '"':
                state = '"'
            elif c == "`":
                deny("Blocked: command substitution is not allowed.")
            elif c == "$" and nxt not in ("", " ", "\t"):
                deny("Blocked: variables and $( ) are not allowed in commands.")
            elif c == "{":
                deny("Blocked: brace expansion is not allowed.")
            elif c in "<>" and nxt == "(":
                deny("Blocked: process substitution is not allowed.")
        i += 1


def split_segments(tokens):
    segs, cur, redirects = [], [], []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t and all(ch in "();<>|&" for ch in t):
            if t in (";", "&&", "||", "|", "|&", "(", ")"):
                if cur:
                    segs.append(cur)
                cur = []
            elif t == "&":
                deny("Blocked: background jobs are not allowed.")
            elif t in (">", ">>", "&>", "&>>"):
                if cur and cur[-1] in ("1", "2"):
                    cur.pop()
                target = tokens[i + 1] if i + 1 < len(tokens) else ""
                if target != "/dev/null":
                    deny("Blocked: writing files from the shell is not allowed. Use the edit tool.")
                i += 1
            elif t in (">&", "<&"):
                if cur and cur[-1] in ("1", "2"):
                    cur.pop()
                target = tokens[i + 1] if i + 1 < len(tokens) else ""
                if not (target.isdigit() or target == "-"):
                    deny("Blocked: writing files from the shell is not allowed. Use the edit tool.")
                i += 1
            elif t == "<":
                if i + 1 >= len(tokens):
                    deny("Blocked: bad redirect.")
                redirects.append(tokens[i + 1])
                i += 1
            else:
                deny("Blocked: that shell syntax is not allowed.")
        else:
            cur.append(t)
        i += 1
    if cur:
        segs.append(cur)
    return segs, redirects


def check_path_token(ctx, tok, cwd):
    """One path-like argument of a read command."""
    if H.has_meta(tok):
        pat = H.pattern_parts(tok, cwd)
        if pat is None:
            deny("Blocked: that path pattern is outside the project folder or unclear.")
        if H.pattern_hits(pat, H.GATE_PARTS, False, True) or H.pattern_hits(pat, (".env",), False, True):
            deny("Blocked: that pattern reaches a private file.")
        if not ctx.owner:
            for tree in H.GAME_TREES:
                if H.pattern_hits(pat, tree, False):
                    deny("Blocked: that pattern reaches a closed folder.")
        return None
    parts = H.resolve_literal(tok, cwd)
    check_read_parts(ctx, parts, tok)
    return parts


def recursive_flags(cmd, flags):
    if cmd in ("rg", "find", "tree"):
        return True
    if cmd == "ls":
        return any(f == "--recursive" or (not f.startswith("--") and "R" in f) for f in flags)
    if cmd in ("grep", "egrep", "fgrep"):
        return any(f in ("--recursive", "--dereference-recursive") or
                   (f.startswith("-") and not f.startswith("--") and ("r" in f or "R" in f))
                   for f in flags)
    return False


def check_reader(ctx, cmd, args, cwd):
    """Returns the set of token indexes handled as paths."""
    flags = [a for a in args if a.startswith("-") and len(a) > 1]
    skip = set()
    paths = []
    if cmd in ("grep", "egrep", "fgrep", "rg"):
        has_e = False
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("-e", "--regexp", "-f", "--file"):
                has_e = True
                skip.add(i + 1)
                i += 1
            elif a.startswith("-") and len(a) > 1:
                pass
            else:
                paths.append(i)
            i += 1
        if not has_e and paths:
            skip.add(paths[0])
    elif cmd == "find":
        for i, a in enumerate(args):
            if a.startswith("-") or a in ("(", ")", "!"):
                break
            paths.append(i)
        for bad in ("-exec", "-execdir", "-ok", "-delete", "-fprint", "-fls", "-fprintf", "-okdir"):
            if bad in args:
                deny("Blocked: find may only list. Not %s." % bad)
    else:
        paths = [i for i, a in enumerate(args) if not (a.startswith("-") and len(a) > 1)]
    handled = set()
    walked = []
    for i in paths:
        if i in skip:
            continue
        if cmd in ("head", "tail") and args[i].lstrip("+-").isdigit():
            continue
        if cmd == "cut" and re.match(r"^[\d,\-]+$", args[i]):
            continue
        handled.add(i)
        parts = check_path_token(ctx, args[i], cwd)
        if parts is not None:
            walked.append(parts)
    if recursive_flags(cmd, flags):
        starts = walked or [H.resolve_literal(".", cwd)]
        for parts in starts:
            check_recursive(ctx, parts, "the folder")
    return handled


def check_python(ctx, args, cwd):
    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "-":
        a = args[i]
        if a in ("-u", "-B", "-O", "--version", "-V") or re.match(r"^-3(\.\d+)?$", a):
            i += 1
        elif a == "-m":
            if i + 1 < len(args) and args[i + 1] == "unittest":
                check_all_tests(ctx)
                return
            deny("Blocked: python -m is limited to unittest.")
        else:
            deny("Blocked: no inline code. Run a file in tests/, or use arena/arena.py.")
    if i >= len(args):
        if args and args[-1] in ("--version", "-V"):
            return
        deny("Blocked: python needs a script. Use arena/arena.py or a file in tests/.")
    script = args[i]
    if script == "-":
        deny("Blocked: no inline code. Run a file in tests/, or use arena/arena.py.")
    real = os.path.realpath(script if os.path.isabs(script) else os.path.join(cwd, script))
    if H.norm(real) in (H.norm(ARENA_PY), H.norm(APP_PY)):
        if H.norm(real) == H.norm(ARENA_PY) and i + 1 < len(args) and args[i + 1] == "_run":
            deny("Blocked: that arena command is for the tool itself.")
        if H.norm(real) == H.norm(ARENA_PY) and i + 1 < len(args) and args[i + 1] == "run-tests":
            check_all_tests(ctx)
        return
    if H.inside(real) and H.norm(real).startswith(H.norm(TESTS_DIR) + os.sep) and real.endswith(".py"):
        check_test_file(ctx, real)
        return
    if ctx.owner and H.norm(real) == H.norm(GOLDEN_PY):
        return
    deny("Blocked: you may run arena/arena.py, app/colorlab.py or a test file in tests/ only.")


def own_head():
    try:
        with open(os.path.join(H.ROOT, ".git", "HEAD"), encoding="utf-8") as handle:
            line = handle.read().strip()
    except OSError:
        return ""
    return line[len("ref: refs/heads/"):] if line.startswith("ref: refs/heads/") else ""


def check_push(ctx, rest):
    flags = [a for a in rest if a.startswith("-")]
    pos = [a for a in rest if not a.startswith("-")]
    for f in flags:
        if f not in ("-u", "--set-upstream"):
            deny("Blocked: no force push, no delete, no extra push options. Plain push of your team branch only.")
    for a in pos:
        if a.startswith("+") or ":" in a:
            deny("Blocked: push your team branch by plain name. No refspecs.")
    if not ctx.branch:
        deny("Blocked: no team yet, so no push.")
    if len(pos) == 2 and pos[0] == "origin" and pos[1] == ctx.branch:
        return
    if len(pos) == 0 or pos == ["origin"]:
        if own_head() == ctx.branch:
            return
        deny("Blocked: you are not on your team branch (%s)." % ctx.branch)
    deny("Blocked: you may push only your own team branch (%s)." % ctx.branch)


LOG_FLAGS = {"--oneline", "--graph", "--decorate", "--stat", "--no-color", "--abbrev-commit"}
OWNER_GIT = {"diff", "show", "log", "blame", "stash", "reflog", "cat-file", "ls-tree", "ls-files",
             "rev-list", "show-ref", "grep", "checkout", "switch", "branch", "fetch", "for-each-ref"}


def check_git(ctx, args, cwd):
    if not args:
        return
    if args[0].startswith("-"):
        deny("Blocked: git options before the command are not allowed.")
    sub, rest = args[0], args[1:]
    for a in rest:
        if a in ("-c", "-C") or a.startswith(("--git-dir", "--work-tree", "--exec-path")):
            deny("Blocked: that git option is not allowed.")
    if sub in ("config", "remote"):
        deny("Blocked: git %s is not allowed." % sub)
    if sub == "push":
        return check_push(ctx, rest)
    if ctx.owner and sub in OWNER_GIT:
        if sub == "branch" and any(a in ("-d", "-D", "--delete", "-m", "-M", "-f", "--force") for a in rest):
            deny("Blocked: no branch delete or rename.")
        return
    if sub == "status":
        return
    if sub == "add":
        for a in rest:
            if a in ("-f", "--force"):
                deny("Blocked: no forced add.")
            if not a.startswith("-"):
                parts = H.resolve_literal(a, cwd)
                if parts is None or H.always_protected(parts) or (parts and H.game_protected(parts)):
                    deny("Blocked: that path may not be added.")
        return
    if sub == "commit":
        if re.search("co-" "authored-by|signed-off-by", " ".join(rest), re.I):
            deny("Blocked: no co-author or sign-off lines in commit messages.")
        i = 0
        while i < len(rest):
            a = rest[i]
            if a in ("-m", "--message", "-am"):
                i += 1
            elif a in ("-a", "--all", "--allow-empty", "-q", "--quiet") or a.startswith("--message="):
                pass
            else:
                deny("Blocked: commit with a plain message only (-m).")
            i += 1
        return
    if sub == "log":
        for a in rest:
            if a in LOG_FLAGS or re.match(r"^(-n\d*|-\d+|--max-count=\d+)$", a):
                continue
            deny("Blocked: git log may only show the short list of your own branch.")
        return
    if sub == "branch":
        if all(a in ("--show-current", "--list") for a in rest):
            return
        deny("Blocked: git branch may only show the current branch.")
    if sub == "rev-parse":
        if rest and all(a in ("--abbrev-ref", "--show-toplevel", "--is-inside-work-tree", "--short", "HEAD") for a in rest):
            return
        deny("Blocked: git rev-parse is limited to HEAD and the top folder.")
    if sub == "pull":
        pos = [a for a in rest if not a.startswith("-")]
        if all(a in ("--ff-only", "-q") for a in rest if a.startswith("-")) and \
                (not pos or pos == ["origin"] or pos == ["origin", ctx.branch]):
            return
        deny("Blocked: pull your own team branch only.")
    deny("Blocked: git %s is not available in the game. Use arena/arena.py for sharing code." % sub)


def check_segment(ctx, seg, state):
    toks = list(seg)
    while toks and ENV_URL.match(toks[0]):
        toks.pop(0)
    if not toks:
        return
    cmd_raw, args = toks[0], toks[1:]
    if "/" in cmd_raw or "\\" in cmd_raw:
        deny("Blocked: write the command by its plain name (for example python3).")
    cmd = cmd_raw.lower()
    if cmd.endswith(".exe"):
        cmd = cmd[:-4]
    if cmd in SAY and not (ctx.owner and cmd in OWNER_FREE):
        deny("Blocked: %s is not allowed here. %s" % (cmd_raw, SAY[cmd]))
    if cmd not in ALLOWED and not (ctx.owner and cmd in OWNER_FREE):
        deny("Blocked: %s is not on the list of commands for this workshop." % cmd_raw)
    handled = set()
    cwd = state["cwd"]
    if cmd in ("python", "python3", "py"):
        check_python(ctx, args, cwd)
    elif cmd == "git":
        check_git(ctx, args, cwd)
    elif cmd == "cd":
        if len(args) != 1:
            deny("Blocked: cd needs one folder inside the project.")
        parts = H.resolve_literal(args[0], cwd)
        if parts is None:
            deny("Blocked: that folder is outside the project folder.")
        if parts and (H.starts_with(parts, (".claude",)) or (not ctx.owner and (
                H.game_protected(parts) or H.starts_with(parts, ("arena",))))):
            deny("Blocked: you may not work inside that folder. Stay in the project folder, app/ or tests/.")
        state["cwd"] = os.path.join(H.ROOT, *parts) if parts else H.ROOT
        handled = {0}
    elif cmd == "mkdir":
        for i, a in enumerate(args):
            if a.startswith("-"):
                continue
            parts = H.resolve_literal(a, cwd)
            if parts is None or not parts or not (
                    H.norm(parts[0]) == "tests" or (ctx.owner and H.norm(parts[0]) == "golden")):
                deny("Blocked: mkdir only inside tests/.")
            handled.add(i)
    elif cmd in READERS:
        handled = check_reader(ctx, cmd, args, cwd)
    elif cmd in ("diff", "cmp", "comm"):
        for i, a in enumerate(args):
            if not a.startswith("-"):
                check_path_token(ctx, a, cwd)
                handled.add(i)
    # last line of defence: closed words in any other argument
    for i, a in enumerate(args):
        if i in handled:
            continue
        low = a.replace("\\", "/").lower()
        for word in SAFE_WORDS:
            if word in low:
                deny("Blocked: that text points at a private or closed file.")
        if not ctx.owner:
            for word in GAME_WORDS:
                if word in low:
                    deny("Blocked: that text points at a closed part of the game.")


def tool_bash(ctx, inp):
    cmd = inp.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        deny("Blocked: no command given.")
    if not ctx.cwd_inside():
        deny("Blocked: the shell is outside the project folder.")
    scan_quotes(cmd)
    flat = cmd.replace("\r\n", "\n").replace("\n", " ; ")
    try:
        lex = shlex.shlex(flat, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        deny("Blocked: the command could not be read (quotes do not match).")
    segs, redirects = split_segments(tokens)
    state = {"cwd": os.path.realpath(ctx.cwd)}
    for target in redirects:
        check_path_token(ctx, target, state["cwd"])
    for seg in segs:
        check_segment(ctx, seg, state)


# ---------- entry ------------------------------------------------------------------------

def decide(event):
    tool, inp = event.get("tool_name"), event.get("tool_input")
    if not isinstance(tool, str) or not isinstance(inp, dict):
        deny("Blocked: the tool request could not be read.")
    ctx = Ctx(event)
    if tool in BAD_TOOLS or tool.startswith("mcp__"):
        deny("Blocked: %s is not available in this workshop." % tool)
    if tool == "Read":
        tool_read(ctx, inp)
    elif tool == "Grep":
        tool_grep(ctx, inp)
    elif tool == "Glob":
        tool_glob(ctx, inp)
    elif tool == "LS":
        path = inp.get("path")
        if not isinstance(path, str):
            deny("Blocked: no path given.")
        check_read_parts(ctx, H.resolve_literal(path, ctx.cwd), path)
    elif tool in ("Edit", "Write", "MultiEdit"):
        tool_write(ctx, tool, inp)
    elif tool == "Bash":
        tool_bash(ctx, inp)


def main():
    try:
        decide(H.read_event())
    except Deny as why:
        sys.stderr.write(str(why) + "\n")
        return 2
    except Exception:
        sys.stderr.write("Blocked: the guard could not read this request, so it stops here.\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
