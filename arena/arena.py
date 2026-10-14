#!/usr/bin/env python3
"""arena: the workshop helper for plant-and-hunt rounds. Standard library only.

It wraps git and colorlab so nobody has to type git. Run it from anywhere:
    python arena/arena.py <verb> ...        (Windows: py arena\\arena.py <verb> ...)

Verbs: init, status, phase, hint, serve, plant-start, log-bug, give, take, run-tests,
commit-push, score-round, reveal. Use "<verb> --help" for the details of one verb.
"""
import argparse
import ast
import difflib
import http.client
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARENA = ROOT / ".arena"
STATE = ARENA / "state.json"
BUGS = ARENA / "bugs.json"
BASE = ROOT / "arena" / "base" / "colorlab.py"
APP = ROOT / "app" / "colorlab.py"
SANDBOX = ARENA / "sandbox" / "colorlab.py"
TESTS = ROOT / "tests"
TEAMS = {"A": ("team-a", "handoff-a", "Blue"), "B": ("team-b", "handoff-b", "Orange")}
PHASES = ("learn", "plant", "swap", "hunt", "score", "done")
MAX_BUGS = 2
MAX_LINES = 8
ZONE_RE = re.compile(r"^# (>>>|<<<) ZONE (C[1-6])\s*$")
BANNED = {"time", "random", "os", "sys", "environ", "subprocess", "socket", "open",
          "eval", "exec", "datetime", "__import__", "getenv"}


class Stop(Exception):
    """A plain-language refusal. Printed as is, exit code 1."""


def say(*lines):
    for line in lines:
        print(line)


# ---------- small helpers: files, state, topics ------------------------------------------

def read_json(path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def read_lines(path):
    with open(path, encoding="utf-8", newline=None) as handle:
        return handle.read().replace("\r\n", "\n").split("\n")


def write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))


def load_state():
    state = read_json(STATE)
    if not state:
        raise Stop("Not started. Run: python arena/arena.py init --team A   (or B)")
    return state


def load_topics():
    return dict((t["id"], t) for t in read_json(ROOT / "arena" / "topics.json")["topics"])


def need_topic(name):
    topics = load_topics()
    topic = (name or "").upper()
    if topic not in topics:
        raise Stop("Topic must be one of: %s." % ", ".join(sorted(topics)))
    return topic, topics[topic]


def round_of(topic):
    return (int(topic[1]) + 1) // 2


def need_own(state, topic):
    _, info = need_topic(topic)
    if info["planter"] != state["team"]:
        raise Stop("%s is not yours to plant. Your plant topics: %s."
                   % (topic.upper(), ", ".join(own_topics(state))))
    return info


def own_topics(state):
    return sorted(k for k, v in load_topics().items() if v["planter"] == state["team"])


def load_bugs():
    return read_json(BUGS, [])


# ---------- git --------------------------------------------------------------------------

def git(*args, **kw):
    """Run git in the repo. Returns the completed process (text, or bytes with raw=True)."""
    env = dict(os.environ)
    env.update(kw.get("env") or {})
    try:
        done = subprocess.run(["git", "-C", str(ROOT)] + list(args), env=env,
                              input=kw.get("input"), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=120)
    except FileNotFoundError:
        raise Stop("Git is not installed on this laptop.")
    except subprocess.TimeoutExpired:
        raise Stop("Git took too long. Check the network and try again.")
    if not kw.get("raw"):
        done.stdout = done.stdout.decode("utf-8", "replace")
    done.stderr = done.stderr.decode("utf-8", "replace")
    if kw.get("check", True) and done.returncode != 0:
        lines = done.stderr.strip().splitlines() or ["no details"]
        last = next((x for x in lines if x.startswith(("fatal:", "error:"))), lines[-1])
        raise Stop("%s Git said: %s" % (kw["fail"], last) if kw.get("fail") else "Git said: %s" % last)
    return done


def current_branch():
    return git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def need_branch(state):
    if current_branch() != state["branch"]:
        raise Stop("You are not on your team branch (%s). Run init again to go back." % state["branch"])


def remote_has(branch):
    return git("ls-remote", "--heads", "origin", branch, check=False).stdout.strip() != ""


NET = "Git could not finish talking to the shared repo."


# ---------- zones ------------------------------------------------------------------------

def zone_span(lines, zone):
    """(first, end) line indexes of the zone body, markers excluded. None if broken."""
    start = end = None
    for i, line in enumerate(lines):
        hit = ZONE_RE.match(line)
        if hit and hit.group(2) == zone:
            if hit.group(1) == ">>>" and start is None:
                start = i + 1
            elif hit.group(1) == "<<<" and start is not None and end is None:
                end = i
    return (start, end) if start is not None and end is not None else None


def need_span(lines, zone, what):
    span = zone_span(lines, zone)
    if span is None:
        raise Stop("The ZONE %s markers are missing or broken in %s." % (zone, what))
    return span


def zone_body(lines, zone, what="the file"):
    a, b = need_span(lines, zone, what)
    return lines[a:b]


def with_zone(lines, zone, body):
    a, b = need_span(lines, zone, "the file")
    return lines[:a] + list(body) + lines[b:]


def apply_ops(body, ops):
    out = list(body)
    for i1, i2, new in sorted(ops, key=lambda o: (o[0], o[1]), reverse=True):
        out[i1:i2] = new
    return out


def diff_ops(old, new):
    """Changed spans as (i1, i2, replacement lines) and the number of changed lines."""
    ops, count = [], 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag != "equal":
            ops.append([i1, i2, new[j1:j2]])
            count += max(i2 - i1, j2 - j1)
    return ops, count


def build_text(zone, ops):
    base = read_lines(BASE)
    return with_zone(base, zone, apply_ops(zone_body(base, zone, "the base"), ops))


# ---------- running colorlab -------------------------------------------------------------

def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def call(port, method, path, body=None):
    """One request. Returns (status, X-Seed-Version header, decoded body)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        safe = urllib.parse.quote(path, safe="/?&=%:+,;@!$'()*~-._#[]")
        data = body.encode("utf-8") if body else None
        conn.request(method, safe, body=data,
                     headers={"Content-Type": "application/json"} if data else {})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", "replace")
        try:
            decoded = json.loads(raw)
        except ValueError:
            decoded = raw
        return resp.status, resp.getheader("X-Seed-Version"), decoded
    finally:
        conn.close()


class Running(object):
    """Start a colorlab file on a free local port; stop it on exit. ok is False if it fails."""

    def __init__(self, path, port=None):
        self.path, self.port, self.proc, self.ok = Path(path), port or free_port(), None, False

    def __enter__(self):
        env = dict((k, v) for k, v in os.environ.items() if not k.startswith("COLORLAB_"))
        env["COLORLAB_PORT"] = str(self.port)
        self.proc = subprocess.Popen([sys.executable, str(self.path)], env=env,
                                     cwd=str(self.path.parent), stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        end = time.time() + 10
        while time.time() < end and self.proc.poll() is None and not self.ok:
            try:
                self.ok = call(self.port, "GET", "/health")[0] == 200
            except (OSError, http.client.HTTPException):
                time.sleep(0.1)
        return self

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.port

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def parse_trigger(text):
    parts = (text or "").strip().split(None, 2)
    if len(parts) < 2 or parts[0].upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH") \
            or not parts[1].startswith("/"):
        raise Stop('The trigger must look like: "GET /colors/BP1001" (method, path, optional body).')
    return {"method": parts[0].upper(), "path": parts[1], "body": parts[2] if len(parts) > 2 else ""}


def ask(path, trigger):
    with Running(path) as run:
        if not run.ok:
            return None
        status, seed, body = call(run.port, trigger["method"], trigger["path"], trigger["body"])
        return {"status": status, "seedVersion": seed, "body": body}


# ---------- test runs --------------------------------------------------------------------

def run_suite(colorlab, tests_dir):
    """Start colorlab, run every test file in tests_dir. Returns {test id: ok|fail|error}."""
    out = ARENA / "run_result.json"
    if out.exists():
        out.unlink()
    with Running(colorlab) as run:
        if not run.ok:
            raise Stop("The app does not start. Fix that first.")
        env = dict(os.environ, COLORLAB_URL=run.url)
        try:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "_run",
                            str(tests_dir), str(out)], env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=300)
        except subprocess.TimeoutExpired:
            return {"(run)": "error"}
    return read_json(out, {"(run)": "error"})


def runner(tests_dir, out_file):
    """Hidden verb: discover and run the tests, write one result per test as JSON."""
    results = {}

    class Rec(unittest.TextTestResult):
        def addSuccess(self, test):
            results[test.id()] = "ok"
        def addFailure(self, test, err):
            results[test.id()] = "fail"
        def addError(self, test, err):
            results[test.id()] = "error"
        def addSkip(self, test, reason):
            results[test.id()] = "skip"
        def addSubTest(self, test, subtest, err):
            if err is not None:
                results[test.id()] = "fail"

    sys.path.insert(0, tests_dir)
    suite = unittest.defaultTestLoader.discover(tests_dir, pattern="test*.py", top_level_dir=tests_dir)
    unittest.TextTestRunner(stream=io.StringIO(), resultclass=Rec).run(suite)
    write_json(Path(out_file), results)


def has_tests(tests_dir):
    return tests_dir.exists() and any(tests_dir.rglob("test*.py"))


def tally(results):
    return (sum(1 for v in results.values() if v == "ok"),
            sorted(k.split(".")[-1] for k, v in results.items() if v in ("fail", "error")))


# ---------- verbs ------------------------------------------------------------------------

def cmd_init(a):
    team = a.team.upper()
    branch, _, default_name = TEAMS[team]
    state = read_json(STATE)
    if state and state["team"] != team:
        raise Stop("This laptop already plays team %s. Delete the .arena folder to switch." % state["team"])
    if not (ROOT / ".git").exists() or git("rev-parse", "--is-inside-work-tree", check=False).stdout.strip() != "true":
        raise Stop("This folder is not a git clone. Clone the shared repo with git, then open a terminal in that folder.")
    if "origin" not in git("remote", check=False).stdout.split():
        raise Stop("This clone has no link to the shared repo (no remote called origin). Clone the shared repo again.")
    git("fetch", "origin", fail=NET)
    if git("rev-parse", "--verify", "--quiet", "refs/heads/" + branch, check=False).returncode == 0:
        git("checkout", branch)
        if remote_has(branch):
            git("pull", "--ff-only", "origin", branch, check=False)
    elif remote_has(branch):
        git("checkout", "-b", branch, "--track", "origin/" + branch)
    else:
        git("checkout", "-b", branch)
        git("push", "-u", "origin", branch, fail="Branch made here, but the push failed. " + NET)
    state = state or {"frame": "", "phase": "learn", "hints_left": 2, "round": 0}
    state.update(team=team, branch=branch, name=a.name or state.get("name") or default_name)
    write_json(STATE, state)
    say("You are team %s (%s) on branch %s." % (team, state["name"], branch),
        "Next: set the phase, for example: phase learn --topic %s" % own_topics(state)[0])


def cmd_status(a):
    state = read_json(STATE)
    if not state:
        say("Not started. Run: python arena/arena.py init --team A   (or B)")
        return
    bugs = load_bugs()
    counts = ", ".join("%s %d of %d" % (t, sum(1 for b in bugs if b["topic"] == t), MAX_BUGS)
                       for t in own_topics(state))
    say("Team %s (%s), branch %s. Phase: %s, topic %s, round %s, hints left %s."
        % (state["team"], state["name"], state["branch"], state["phase"],
           state["frame"] or "-", state["round"], state["hints_left"]),
        "Bugs logged: %s." % counts)


def set_phase(state, phase, topic):
    if (phase, topic) != (state["phase"], state["frame"]) and phase == "hunt":
        state["hints_left"] = 2
    state.update(phase=phase, frame=topic or state["frame"])
    if topic:
        state["round"] = round_of(topic)
    write_json(STATE, state)


def cmd_phase(a):
    state = load_state()
    topic = None
    if a.topic:
        topic, info = need_topic(a.topic)
        mine = info["planter"] == state["team"]
        if a.phase == "plant" and not mine:
            raise Stop("%s is not yours to plant. Your plant topics: %s." % (topic, ", ".join(own_topics(state))))
        if a.phase in ("swap", "hunt") and mine:
            raise Stop("%s is your own topic. In %s you work on the other team's topic." % (topic, a.phase))
    set_phase(state, a.phase, topic)
    say("Phase is now %s%s (round %s). Hints left: %s."
        % (a.phase, " for " + state["frame"] if state["frame"] else "", state["round"], state["hints_left"]))


def cmd_hint(a):
    state = load_state()
    left = int(state.get("hints_left", 0))
    if left <= 0:
        raise Stop("No hints left in this round. Keep going with your own tests.")
    state["hints_left"] = left - 1
    write_json(STATE, state)
    say("Hint used. Hints left: %d." % state["hints_left"])


def cmd_serve(a):
    pidfile = ARENA / "serve.pid"
    if a.stop:
        pid = int(pidfile.read_text()) if pidfile.exists() else None
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            pidfile.unlink()
            say("App stopped.")
        else:
            say("No app was started by this tool.")
        return
    target = SANDBOX if a.against == "sandbox" else APP
    if not target.exists():
        raise Stop("There is nothing to serve yet (%s is missing)." % target.name)
    try:
        if call(a.port, "GET", "/health")[0] == 200:
            say("An app already answers on http://127.0.0.1:%d. Stop it first." % a.port)
            return
    except (OSError, http.client.HTTPException):
        pass
    env = dict((k, v) for k, v in os.environ.items() if not k.startswith("COLORLAB_"))
    env["COLORLAB_PORT"] = str(a.port)
    ARENA.mkdir(exist_ok=True)
    flags = {"creationflags": 0x00000208} if os.name == "nt" else {"start_new_session": True}
    with open(ARENA / "serve.log", "w") as log:
        proc = subprocess.Popen([sys.executable, str(target)], env=env, cwd=str(target.parent),
                                stdout=log, stderr=log, **flags)
    for _ in range(100):
        try:
            if call(a.port, "GET", "/health")[0] == 200:
                pidfile.write_text(str(proc.pid))
                say("App is running on http://127.0.0.1:%d (%s)." % (a.port, a.against),
                    "Stop it with: python arena/arena.py serve --stop")
                return
        except (OSError, http.client.HTTPException):
            time.sleep(0.1)
    proc.kill()
    raise Stop("The app did not start. See .arena/serve.log.")


def cmd_plant_start(a):
    state = load_state()
    topic = a.topic.upper()
    need_own(state, topic)
    made = sum(1 for b in load_bugs() if b["topic"] == topic)
    if made >= MAX_BUGS:
        raise Stop("%s already has %d bugs. That is the limit." % (topic, MAX_BUGS))
    need_span(read_lines(BASE), topic, "the base")
    SANDBOX.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BASE, SANDBOX)
    set_phase(state, "plant", topic)
    say("Sandbox ready for %s: .arena/sandbox/colorlab.py. Your own app/ is not touched." % topic,
        "Change at most %d lines between the ZONE %s markers, then run log-bug." % (MAX_LINES, topic))


def cmd_log_bug(a):
    state = load_state()
    topic = a.topic.upper()
    need_own(state, topic)
    if state["phase"] != "plant":
        raise Stop("Not in the plant phase. Run: phase plant --topic %s" % topic)
    bugs = load_bugs()
    mine = [b for b in bugs if b["topic"] == topic]
    if len(mine) >= MAX_BUGS:
        raise Stop("%s already has %d bugs. That is the limit." % (topic, MAX_BUGS))
    if not SANDBOX.exists():
        raise Stop("No sandbox yet. Run: plant-start %s" % topic)
    trigger = parse_trigger(a.trigger)
    base, new = read_lines(BASE), read_lines(SANDBOX)
    a1, b1 = need_span(base, topic, "the base")
    span = zone_span(new, topic)
    if span is None:
        raise Stop("Not saved: the ZONE %s markers in the sandbox are broken." % topic)
    if base[:a1] != new[:span[0]] or base[b1:] != new[span[1]:]:
        raise Stop("Not saved: you changed code outside ZONE %s. Only edit between its markers." % topic)
    body_old, body_new = base[a1:b1], new[span[0]:span[1]]
    ops, count = diff_ops(body_old, body_new)
    if not ops:
        raise Stop("Not saved: nothing changed in ZONE %s." % topic)
    if count > MAX_LINES:
        raise Stop("Not saved: %d lines changed, the limit is %d. Make the bug smaller." % (count, MAX_LINES))
    try:
        tree = ast.parse("\n".join(body_new))
    except SyntaxError:
        raise Stop("Not saved: the zone is not valid Python.")
    known = set(getattr(n, "id", None) or getattr(n, "attr", None)
                for n in ast.walk(ast.parse("\n".join(body_old))))
    for node in ast.walk(tree):
        used = getattr(node, "id", None) or getattr(node, "attr", None)
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (used in BANNED and used not in known):
            raise Stop("Not saved: a bug may not use imports, time, random, files or the environment.")
    for bug in mine:
        for o in bug["ops"]:
            if any(o[0] <= p[1] and p[0] <= o[1] for p in ops):
                raise Stop("Not saved: that overlaps your first bug. Change a different spot.")
    clean = ask(BASE, trigger)
    bad = ask(SANDBOX, trigger)
    if clean is None:
        raise Stop("The clean app does not start. Tell Mohammad.")
    if bad is None:
        raise Stop("Not saved: the app does not start with your change.")
    if bad == clean:
        raise Stop("Not saved: that request gets the same answer with and without your bug. "
                   "Pick a request where the answer differs.")
    patch = "\n".join(difflib.unified_diff(body_old, body_new, "clean", "bug", lineterm=""))
    bugs.append({"id": "%s-%s-%d" % (state["team"], topic, len(mine) + 1), "topic": topic,
                 "zone": topic, "rule": a.rule or "/".join(load_topics()[topic]["rules"]),
                 "description": a.note, "trigger": trigger, "clean_answer": clean,
                 "buggy_answer": bad, "patch": patch, "ops": ops, "round": round_of(topic)})
    write_json(BUGS, bugs)
    shutil.copyfile(BASE, SANDBOX)
    say("Saved bug %d of %d for %s. The sandbox is reset to the clean code."
        % (len(mine) + 1, MAX_BUGS, topic),
        "Plant the next one, or run: give %s" % topic)


def cmd_give(a):
    state = load_state()
    topic = a.topic.upper()
    need_own(state, topic)
    mine = [b for b in load_bugs() if b["topic"] == topic]
    if not mine:
        raise Stop("No bug is logged for %s yet. Plant and log %d first." % (topic, MAX_BUGS))
    if len(mine) != MAX_BUGS:
        raise Stop("%s has %d of %d bugs logged. Log exactly %d before you give it."
                   % (topic, len(mine), MAX_BUGS, MAX_BUGS))
    base = read_lines(BASE)
    zone = apply_ops(zone_body(base, topic, "the base"), [o for b in mine for o in b["ops"]])
    given = ARENA / "given"
    write_lines(given / (topic + ".zone"), zone)
    index = ARENA / "handoff.index"
    if index.exists():
        index.unlink()
    env = {"GIT_INDEX_FILE": str(index)}
    if not git("config", "user.name", check=False).stdout.strip():
        env.update(GIT_AUTHOR_NAME="arena", GIT_AUTHOR_EMAIL="arena@local",
                   GIT_COMMITTER_NAME="arena", GIT_COMMITTER_EMAIL="arena@local")
    for path in sorted(given.glob("*.zone")):
        blob = git("hash-object", "-w", "--stdin", input=path.read_bytes(), raw=True).stdout.decode().strip()
        git("update-index", "--add", "--cacheinfo", "100644,%s,zones/%s" % (blob, path.name), env=env)
    tree = git("write-tree", env=env).stdout.strip()
    commit = git("commit-tree", tree, "-m", "handoff", env=env).stdout.strip()
    index.unlink()
    handoff = TEAMS[state["team"]][1]
    git("push", "--force", "origin", "%s:refs/heads/%s" % (commit, handoff), fail=NET)
    say("Handed over %s (%d bugs) to the other team." % (topic, len(mine)),
        "They can now take it. Nothing else of your code was shared.")


def cmd_take(a):
    state = load_state()
    topic, info = need_topic(a.topic)
    if info["planter"] == state["team"]:
        raise Stop("%s is your own topic. Take one from the other team: %s."
                   % (topic, ", ".join(sorted(k for k, v in load_topics().items() if v["planter"] != state["team"]))))
    if state["phase"] not in ("swap", "hunt"):
        raise Stop("Not in swap or hunt. Run: phase swap --topic %s" % topic)
    other = "B" if state["team"] == "A" else "A"
    handoff = TEAMS[other][1]
    if not remote_has(handoff):
        raise Stop("The other team has not handed over anything yet. Ask them to run give.")
    git("fetch", "origin", "+refs/heads/%s:refs/arena/%s" % (handoff, handoff), fail=NET)
    got = git("cat-file", "blob", "refs/arena/%s:zones/%s.zone" % (handoff, topic), check=False, raw=True)
    if got.returncode != 0:
        raise Stop("The other team has not handed over %s yet. Ask them to run give." % topic)
    theirs = got.stdout.decode("utf-8").replace("\r\n", "\n").split("\n")
    app = read_lines(APP)
    now = zone_body(app, topic, "app/colorlab.py")
    taken = ARENA / "taken" / (topic + ".zone")
    known = [zone_body(read_lines(BASE), topic, "the base")]
    if taken.exists():
        known.append(read_lines(taken))
    if now not in known and not a.force:
        raise Stop("You already changed %s in your app. To replace your work, run: take %s --force"
                   % (topic, topic))
    new = with_zone(app, topic, theirs)
    try:
        ast.parse("\n".join(new))
    except SyntaxError:
        raise Stop("The handed-over %s does not run. Tell Mohammad." % topic)
    write_lines(APP, new)
    write_lines(taken, theirs)
    set_phase(state, state["phase"], topic)
    say("Took %s from the other team. Your app now holds their version of it." % topic,
        "Nothing is shown. Write tests from rules.md and the spec to find what is wrong.")


def cmd_run_tests(a):
    state = load_state()
    if not has_tests(TESTS):
        say("There are no tests in tests/ yet.")
        return
    target = SANDBOX if a.against == "sandbox" else APP
    results = run_suite(target, TESTS)
    ok, failed = tally(results)
    say("Ran %d tests: %d passed, %d failed." % (len(results), ok, len(failed)))
    if failed:
        say("Failed: " + ", ".join(failed[:12]) + (" ..." if len(failed) > 12 else ""))


def cmd_commit_push(a):
    state = load_state()
    need_branch(state)
    git("add", "app", "tests")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        say("Nothing new to save.")
        return
    msg = a.message or "Round %s work, team %s" % (state["round"], state["team"])
    git("commit", "-m", msg, fail="Git does not know who you are. Ask Mohammad to set the git name and email.")
    git("push", "-u", "origin", state["branch"], fail="Saved here, but the push failed. " + NET)
    say("Saved and pushed to %s." % state["branch"])


def cmd_score_round(a):
    state = load_state()
    topic = a.topic.upper()
    need_own(state, topic)
    mine = [b for b in load_bugs() if b["topic"] == topic]
    if not mine:
        raise Stop("No bug is logged for %s yet." % topic)
    hunter = TEAMS["B" if state["team"] == "A" else "A"][0]
    if not remote_has(hunter):
        say("%s: caught 0 of %d, false alarms 0. The other team has not pushed tests yet." % (topic, len(mine)))
        return
    git("fetch", "origin", "+refs/heads/%s:refs/arena/%s" % (hunter, hunter), fail=NET)
    work = ARENA / "score"
    shutil.rmtree(str(work), ignore_errors=True)
    names = git("ls-tree", "-r", "--name-only", "refs/arena/" + hunter, "tests/").stdout.split("\n")
    for name in [n for n in names if n and not n.endswith(".gitkeep")]:
        blob = git("cat-file", "blob", "refs/arena/%s:%s" % (hunter, name), raw=True).stdout
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    tests = work / "tests"
    if not has_tests(tests):
        say("%s: caught 0 of %d, false alarms 0. The other team has not pushed tests yet." % (topic, len(mine)))
        return
    clean = run_suite(BASE, tests)
    good = set(k for k, v in clean.items() if v == "ok")
    caught = 0
    for bug in mine:
        build = work / ("build_" + bug["id"]) / "colorlab.py"
        write_lines(build, build_text(topic, bug["ops"]))
        results = run_suite(build, tests)
        if any(results.get(k) in ("fail", "error") for k in good):
            caught += 1
    alarms = len(clean) - len(good) - sum(1 for v in clean.values() if v == "skip")
    scores = read_json(ARENA / "scores.json", {})
    scores[topic] = {"caught": caught, "of": len(mine), "false_alarms": alarms}
    write_json(ARENA / "scores.json", scores)
    say("%s: caught %d of %d, false alarms %d." % (topic, caught, len(mine), alarms))


def cmd_reveal(a):
    state = load_state()
    need_branch(state)
    bugs = load_bugs()
    if not bugs:
        raise Stop("There is no bug log on this laptop. Only the planting laptop can reveal.")
    target = ROOT / "final" / ("bugs_%s.json" % state["team"])
    write_json(target, bugs)
    git("add", "final")
    if git("diff", "--cached", "--quiet", check=False).returncode != 0:
        git("commit", "-m", "Bug log of team %s" % state["team"],
            fail="Git does not know who you are. Ask Mohammad to set the git name and email.")
    git("push", "-u", "origin", state["branch"], fail="Saved here, but the push failed. " + NET)
    say("Bug log of team %s (%d bugs) is pushed to %s." % (state["team"], len(bugs), state["branch"]))


# ---------- command line -----------------------------------------------------------------

def build_parser():
    top = argparse.ArgumentParser(prog="arena", description=__doc__.split("\n")[0])
    sub = top.add_subparsers(dest="verb", metavar="verb")

    def add(name, fn, text):
        p = sub.add_parser(name, help=text, description=text)
        p.set_defaults(fn=fn)
        return p

    p = add("init", cmd_init, "Join your team branch and start. Needs --team.")
    p.add_argument("--team", required=True, type=str.upper, choices=["A", "B"])
    p.add_argument("--name", help="your team name (default Blue for A, Orange for B)")
    add("status", cmd_status, "Show team, phase, topic and logged bugs.")
    p = add("phase", cmd_phase, "Set the phase. Use --topic for the frame you work in.")
    p.add_argument("phase", choices=PHASES)
    p.add_argument("--topic", help="C1 to C6")
    add("hint", cmd_hint, "Use one hint (2 per hunt round).")
    p = add("serve", cmd_serve, "Run the app in the background (default port 8080).")
    p.add_argument("--against", choices=["app", "sandbox"], default="app")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--stop", action="store_true", help="stop the app started by serve")
    p = add("plant-start", cmd_plant_start, "Make a sandbox of one topic to plant a bug in.")
    p.add_argument("topic")
    p = add("log-bug", cmd_log_bug, "Check and save the bug you planted in the sandbox.")
    p.add_argument("--topic", required=True)
    p.add_argument("--note", required=True, help="what the bug does, in your words")
    p.add_argument("--trigger", required=True, help='one request that shows it, e.g. "GET /colors/BP1001"')
    p.add_argument("--rule", help="rule id the clean answer follows, e.g. R04")
    p = add("give", cmd_give, "Hand your planted topic to the other team.")
    p.add_argument("topic")
    p = add("take", cmd_take, "Take the other team's planted topic into your app.")
    p.add_argument("topic")
    p.add_argument("--force", action="store_true", help="replace your own edits in that topic")
    p = add("run-tests", cmd_run_tests, "Run the tests in tests/ against the app.")
    p.add_argument("--against", choices=["app", "sandbox"], default="app")
    p = add("commit-push", cmd_commit_push, "Save app/ and tests/ on your team branch.")
    p.add_argument("--message")
    p = add("score-round", cmd_score_round, "Planter laptop: count what the other team's tests catch.")
    p.add_argument("--topic", required=True)
    add("reveal", cmd_reveal, "Push your bug log to your team branch (Frame D).")
    hidden = sub.add_parser("_run")
    hidden.add_argument("tests_dir")
    hidden.add_argument("out_file")
    hidden.set_defaults(fn=lambda a: runner(a.tests_dir, a.out_file))
    return top


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        parser.print_help()
        return 0
    try:
        args.fn(args)
    except Stop as stop:
        print(stop)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
