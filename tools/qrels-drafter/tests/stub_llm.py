"""Deterministic stand-in for the local instruct model in hermetic tests.

Reads the prompt from stdin exactly like the real llama.cpp runner and answers
with valid JSON. It never copies target wording, so the anti-copy guard passes.
"""

import hashlib
import json
import re
import sys

prompt = sys.stdin.read()

if "TASK: grade" in prompt:
    keys = re.findall(r"^\[(c\d+)\]", prompt, re.MULTILINE)
    grades = [{"candidate": key, "grade": 3 if index == 0 else 0} for index, key in enumerate(keys)]
    print(json.dumps({"grades": grades}))
else:
    category = re.search(r"^TASK: (\w+)$", prompt, re.MULTILINE)
    anchor = re.search(r"^ANCHOR: (\S+)$", prompt, re.MULTILINE)
    if not category or not anchor:
        print("{}")
        sys.exit(0)
    token = hashlib.sha256(anchor.group(1).encode("utf-8")).hexdigest()[:10]
    print(json.dumps({"query": f"{category.group(1)} paraphrase zq{token} harbour lantern"}))
