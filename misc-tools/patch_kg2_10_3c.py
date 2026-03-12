#!/usr/bin/env python3

import json
import os
base_dir = "/Users/sramsey/Work/big-files"
input_file = os.path.join(base_dir, "kg2c-2.10.3-v1.0-nodes.jsonl")
output_file = os.path.join(base_dir, "kg2c-2.10.3-v1.1-nodes.jsonl")
with open(input_file, "r", encoding="utf-8") as fi, \
     open(output_file, "w", encoding="utf-8") as fo:
    for lineno, line in enumerate(fi, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON at line {lineno} in {input_file}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"expected JSON object at line {lineno} in {input_file}")
        obj['same_as'] = obj.pop('synonym', [])
        obj['synonym'] = obj.pop('all_names', [])
        if "all_names" in obj:
            raise ValueError("all_names missing in obj")
        assert "same_as" in obj
        assert "synonym" in obj
        json.dump(obj, fo, ensure_ascii=False, separators=(",", ":"))
        fo.write("\n")

