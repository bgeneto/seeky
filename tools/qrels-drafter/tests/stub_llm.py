"""Deterministic stand-in for the local instruct model in hermetic tests.

Reads the prompt on stdin exactly like the real runner, answers in the language
the prompt asks for, and never copies target wording, so the language gate and
the anti-copy guard both pass.
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
    language = re.search(r"^LANGUAGE: (\S+)$", prompt, re.MULTILINE)
    if not category or not anchor or not language:
        print("{}")
        sys.exit(0)
    token = hashlib.sha256(anchor.group(1).encode("utf-8")).hexdigest()[:10]
    words = {
        "pt": "consulta manutenção preventiva trimestral",
        "en": "maintenance schedule evaluation quarterly",
    }
    root = language.group(1).split("-")[0]
    print(json.dumps({"query": f"{words.get(root, words['en'])} zq{token}"}))
