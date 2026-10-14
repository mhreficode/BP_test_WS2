"""Shared helpers for the workshop hooks. Standard library only.

No network, no subprocess, no deletes. The only file these hooks write is
.arena/owner_on (a session flag), and only from prompt_gate.py.
These hooks restrain the agent. They are best effort, not a lock.
"""
import fnmatch
import hashlib
import hmac
import json
import os
import string

HOOKS_DIR = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.realpath(os.path.join(HOOKS_DIR, "..", ".."))
ARENA_DIR = os.path.join(ROOT, ".arena")
STATE_FILE = os.path.join(ARENA_DIR, "state.json")
FLAG_FILE = os.path.join(ARENA_DIR, "owner_on")
GATE_FILE = os.path.join(HOOKS_DIR, "owner_gate.json")

# Folders the agent may not read (game gates). Owner mode lifts these.
GAME_TREES = [(".arena",), ("arena", "base"), (".git",), ("final",)]
# Never lifted, not even in owner mode.
GATE_PARTS = (".claude", "hooks", "owner_gate.json")
SECRET_NAMES = [".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*",
                "id_ed25519*", "id_ecdsa*", "*.token", "credentials*", ".netrc",
                ".npmrc", ".pypirc", "*.secret", "secrets*", "*.kdbx"]
SECRET_DIRS = (".ssh", ".aws", ".gnupg", ".kube")
SANDBOX_PARTS = (".arena", "sandbox", "colorlab.py")

EDGE = string.punctuation + "“”‘’«»…"


def norm(path):
    return os.path.normcase(path)


def inside(real):
    r, root = norm(real), norm(ROOT)
    return r == root or r.startswith(root + os.sep)


def parts_of(real):
    rel = os.path.relpath(real, ROOT)
    return () if rel == "." else tuple(rel.replace("\\", "/").split("/"))


def same(a, b):
    return tuple(norm(x) for x in a) == tuple(norm(x) for x in b)


def starts_with(parts, tree):
    return len(parts) >= len(tree) and same(parts[:len(tree)], tree)


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def load_state():
    state = load_json(STATE_FILE, {})
    return state if isinstance(state, dict) else {}


def read_event():
    import sys
    data = json.loads(sys.stdin.read())
    if not isinstance(data, dict):
        raise ValueError("event is not an object")
    return data


def session_of(event):
    sid = event.get("session_id")
    return sid if isinstance(sid, str) and sid else "nosession"


def owner_active(event):
    """True if the session flag exists, is a plain file in .arena and names this session."""
    try:
        if os.path.islink(FLAG_FILE) or not os.path.isfile(FLAG_FILE):
            return False
        if not inside(os.path.realpath(FLAG_FILE)):
            return False
        with open(FLAG_FILE, encoding="utf-8") as handle:
            return handle.read(300).strip() == session_of(event)
    except OSError:
        return False


# ---------- owner check (hash only, nothing is ever printed) -----------------------------

def token_matches(token, gate):
    n, r, p = int(gate["n"]), int(gate["r"]), int(gate["p"])
    derived = hashlib.scrypt(token.encode("utf-8"), salt=bytes.fromhex(gate["salt"]),
                             n=n, r=r, p=p, dklen=int(gate["dklen"]),
                             maxmem=128 * r * (n + p + 2) * 2)
    return hmac.compare_digest(derived, bytes.fromhex(gate["hash"]))


def prompt_matches(prompt):
    """Look only at the first and the last word. At most two hash calls."""
    words = prompt.split()
    if not words:
        return False
    gate = load_json(GATE_FILE)
    if not isinstance(gate, dict):
        return False
    tried = []
    for word in (words[0], words[-1]):
        word = word.strip(EDGE)
        if word and len(word) <= 256 and word not in tried:
            tried.append(word)
    hit = False
    for word in tried[:2]:
        if token_matches(word, gate):
            hit = True
    return hit


# ---------- path matching ----------------------------------------------------------------

def has_meta(token):
    return any(c in token for c in "*?[")


def resolve_literal(token, cwd):
    """Real path parts of a literal path inside the repo, or None when it points outside."""
    tok = token.replace("\\", "/")
    if tok.startswith("~") or not tok:
        return None
    full = tok if os.path.isabs(tok) else os.path.join(cwd, tok)
    real = os.path.realpath(full)
    return parts_of(real) if inside(real) else None


def pattern_parts(token, cwd):
    """Path components of a glob token relative to the repo, or None if unsafe."""
    tok = token.replace("\\", "/")
    comps = tok.split("/")
    if ".." in comps or tok.startswith("~"):
        return None
    if os.path.isabs(tok):
        root = ROOT.replace("\\", "/")
        if tok == root or tok.startswith(root + "/"):
            return [c for c in tok[len(root):].split("/") if c not in ("", ".")]
        return None
    real = os.path.realpath(cwd)
    if not inside(real):
        return None
    return list(parts_of(real)) + [c for c in comps if c not in ("", ".")]


def _comp_match(name, pat, dots):
    if not dots and name.startswith(".") and not pat.startswith("."):
        return False
    return fnmatch.fnmatchcase(norm(name), norm(pat))


def pattern_hits(pat, tree, dots, exact=False):
    """Can a path matching the pattern be equal to, or inside, the tree?
    With exact=True the tree is a single file: only an equal path counts."""
    def go(i, j):
        if j == len(tree):
            return (not exact) or all(c == "**" for c in pat[i:])
        if i == len(pat):
            return False
        if pat[i] == "**":
            return go(i + 1, j) or (
                (dots or not tree[j].startswith(".")) and go(i, j + 1))
        return _comp_match(tree[j], pat[i], dots) and go(i + 1, j + 1)
    return go(0, 0)


def secret_part(parts):
    if any(norm(p) in SECRET_DIRS for p in parts):
        return True
    if not parts:
        return False
    return any(fnmatch.fnmatchcase(norm(parts[-1]), pat) for pat in SECRET_NAMES)


def always_protected(parts):
    """Never lifted: the owner gate file and secret files."""
    return same(parts, GATE_PARTS) or secret_part(parts)


def game_protected(parts):
    return any(starts_with(parts, tree) for tree in GAME_TREES)


def covers_game_tree(parts):
    """A recursive tool started at 'parts' would walk into a game tree."""
    return any(len(parts) <= len(tree) and same(parts, tree[:len(parts)]) for tree in GAME_TREES)
