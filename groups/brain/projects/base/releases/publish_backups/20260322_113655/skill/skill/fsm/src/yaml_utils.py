import os
import datetime

def parse_simple_yaml(path):
    data = {}
    stack = [(data, -1)]
    try:
        with open(path, "r") as f: lines = f.readlines()
    except: return {}
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"): continue
        indent = len(line) - len(stripped)
        if ":" in stripped:
            parts = stripped.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if val.startswith('"'): val = val[1:-1]
            if val.startswith("'"): val = val[1:-1]
            while stack and stack[-1][1] >= indent: stack.pop()
            parent = stack[-1][0]
            if val:
                if val.startswith("["):
                    content = val[1:-1]
                    items = [x.strip().strip('"').strip("'") for x in content.split(",") if x.strip()]
                    parent[key] = items
                else: parent[key] = val
            else:
                new = {}
                parent[key] = new
                stack.append((new, indent))
    return data

def append_record(project_root, actor, action, result):
    path = os.path.join(project_root, "RECORD/timeline.md")
    if not os.path.exists(path): return
    ts = datetime.datetime.now().isoformat()
    line = f"| {ts} | {actor} | {action} | {result} |\n"
    with open(path, "a") as f: f.write(line)