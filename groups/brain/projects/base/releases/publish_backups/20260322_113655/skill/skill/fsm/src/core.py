import sys
import os
import re
from yaml_utils import parse_simple_yaml, append_record

def update_state(path, new):
    with open(path) as f: c = f.read()
    c = re.sub(r"workflow_state:\s*[\"\w-]+", f"workflow_state: \"{new}\"", c)
    with open(path, "w") as f: f.write(c)

def check(expr, root):
    if expr.startswith("file_exists"):
        m = re.search(r"\((.*?)\)", expr)
        if m:
            p = m.group(1).strip().strip("\"")
            return os.path.exists(os.path.join(root, p)), f"Missing {p}"
    return True, "OK"

def run(root):
    idx = os.path.join(root, "spec/00_index.yaml")
    wf = os.path.join(root, "spec/workflow.yaml")
    idata = parse_simple_yaml(idx)
    wdata = parse_simple_yaml(wf)
    
    curr = idata.get("spec", {}).get("workflow_state")
    if not curr: return "No State"
    
    steps = wdata.get("workflow", {}).get("steps", {})
    s_conf = None
    s_id = None
    
    for k,v in steps.items():
        if v.get("intent", "").lower() == curr.lower():
            s_conf = v; s_id = k; break
            
    if not s_conf: return f"State {curr} not defined"
    
    for g in s_conf.get("gates", []):
        ok, msg = check(g, root)
        if not ok: return f"Gate Fail: {msg}"
        
    next_id = "S" + str(int(s_id[1:])+1)
    if next_id in steps:
        new = steps[next_id].get("intent").lower()
        update_state(idx, new)
        # --- NEW: Append to RECORD ---
        append_record(root, "FSM Engine", f"Transition {curr} -> {new}", "Success")
        return f"Advanced to {new}"
    return "End"

if __name__ == "__main__":
    print(run(sys.argv[1]))
