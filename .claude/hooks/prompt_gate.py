#!/usr/bin/env python3
"""SessionStart and UserPromptSubmit hook for the workshop. Standard library only.

It adds the team state to the context of the agent. It never prints or stores a prompt.
If anything goes wrong it fails open: it prints a plain note and exits 0.
"""
import json
import os
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import hooklib as H  # noqa: E402

NO_TEAM = ("No team yet. Ask: Which team are you: Blue or Orange? Then ask which frame and step "
           "the board is on. Then run arena.py init.")
FAIL_NOTE = ("The game helper could not read its notes. Ask the team which team they are and "
             "which frame they are on, then go on.")


def clean(value, limit=24):
    return re.sub(r"[^A-Za-z0-9_\-]", "", str(value))[:limit]


def state_line():
    state = H.load_state()
    if not state.get("team"):
        return NO_TEAM
    return "TEAM=%s BRANCH=%s FRAME=%s PHASE=%s HINTS_LEFT=%s" % (
        clean(state.get("team")), clean(state.get("branch")), clean(state.get("frame") or "none"),
        clean(state.get("phase") or "none"), clean(state.get("hints_left", 0)))


def write_flag(event):
    os.makedirs(H.ARENA_DIR, exist_ok=True)
    if os.path.islink(H.FLAG_FILE) or not H.inside(os.path.realpath(H.ARENA_DIR)):
        return False
    with open(H.FLAG_FILE, "w", encoding="utf-8") as handle:
        handle.write(H.session_of(event))
    return True


def clear_flag():
    """Switch owner mode off by emptying the flag (no delete)."""
    try:
        if os.path.isfile(H.FLAG_FILE) and not os.path.islink(H.FLAG_FILE) \
                and H.inside(os.path.realpath(H.FLAG_FILE)):
            with open(H.FLAG_FILE, "w", encoding="utf-8") as handle:
                handle.write("")
    except OSError:
        pass


def stop_word(prompt):
    words = prompt.split()
    return bool(words) and "ownerstop" in (words[0].strip(H.EDGE), words[-1].strip(H.EDGE))


def emit(name, text):
    sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": name,
                                                        "additionalContext": text}}))


def main():
    name = "UserPromptSubmit"
    try:
        event = H.read_event()
        name = event.get("hook_event_name") if event.get("hook_event_name") in (
            "SessionStart", "UserPromptSubmit") else name
        lines = [state_line()]
        if name == "SessionStart":
            clear_flag()
        if name == "UserPromptSubmit":
            prompt = event.get("prompt")
            if isinstance(prompt, str) and stop_word(prompt):
                clear_flag()
            elif isinstance(prompt, str) and not H.owner_active(event):
                try:
                    if H.prompt_matches(prompt) and write_flag(event):
                        pass
                except Exception:
                    pass
        if H.owner_active(event):
            lines.append("OWNER_MODE_ON")
        emit(name, "\n".join(lines))
    except Exception:
        emit(name, FAIL_NOTE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
