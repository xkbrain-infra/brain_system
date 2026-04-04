import os
import sys
import datetime
from yaml_utils import append_record

def create_sub_workflow(parent_root, task_id, assignee):
    base_dir = os.path.join(parent_root, "memory/subtasks", task_id)
    spec_dir = os.path.join(base_dir, "SPEC")
    record_dir = os.path.join(base_dir, "RECORD")
    
    os.makedirs(spec_dir, exist_ok=True)
    os.makedirs(record_dir, exist_ok=True)
    
    # 1. spec/00_index.yaml
    with open(os.path.join(spec_dir, "00_index.yaml"), "w") as f:
        f.write(f"spec:\n  id: SUB-{task_id}\n  owner: {assignee}\n  workflow_state: alignment\nruntime:\n  current_state: alignment\n")
        
    # 2. spec/workflow.yaml (Default)
    with open(os.path.join(spec_dir, "workflow.yaml"), "w") as f:
        f.write("workflow:\n  steps:\n    S1:\n      intent: Alignment\n      gates: []\n    S5:\n      intent: Implementation\n      required_env: docker_sandbox\n")
        
    # 3. RECORD Files
    with open(os.path.join(record_dir, "timeline.md"), "w") as f:
        f.write("# Timeline\n| Timestamp | Actor | Action | Result |\n|---|---|---|---|")
    
    # --- NEW: Log to Parent & Child ---
    append_record(parent_root, "Dispatcher", f"Created Subtask {task_id}", f"Path: {base_dir}")
    append_record(base_dir, "Dispatcher", "Initialization", "Project Created")
        
    return f"Success: Created sub-workflow at {base_dir} with SPEC and RECORD"

if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(1)
    print(create_sub_workflow(sys.argv[1], sys.argv[2], sys.argv[3]))
