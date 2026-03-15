import subprocess
import os
import sys
import datetime
import uuid

def log_to_timeline(project_root, action, result, context_link=None):
    timeline_path = os.path.join(project_root, "RECORD/timeline.md")
    if not os.path.exists(timeline_path): return
    timestamp = datetime.datetime.now().isoformat()
    
    display_result = result
    if context_link:
        # Format as Markdown link if context exists
        display_result = f"[{result}]({context_link})"

    with open(timeline_path, "a") as f:
        line = f"| {timestamp} | Agent | {action} | {display_result} |" + "\n"
        f.write(line)

def run_in_sandbox(image, project_root, command):
    container_name = f"agent-sandbox-{uuid.uuid4().hex[:8]}"
    
    # Ensure logs directory exists
    logs_dir = os.path.join(project_root, "RECORD/logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    # Generate log filename
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"exec_{timestamp_str}_{uuid.uuid4().hex[:6]}.log"
    log_path = os.path.join(logs_dir, log_filename)
    
    # Relative path for the markdown link
    rel_log_path = os.path.join("RECORD/logs", log_filename)

    try:
        # 1. Start Container (Silent)
        subprocess.run(["docker", "run", "-d", "--name", container_name, image, "tail", "-f", "/dev/null"], check=True, capture_output=True)
        
        # 2. Copy code into container (Silent)
        subprocess.run(["docker", "cp", f"{project_root}/.", f"{container_name}:/app"], check=True, capture_output=True)
        
        # 3. Exec Command (Captured)
        p = subprocess.run(["docker", "exec", "-w", "/app", container_name, "sh", "-c", command], capture_output=True, text=True)
        
        # 4. Copy everything back (Silent)
        subprocess.run(["docker", "cp", f"{container_name}:/app/.", project_root], check=True, capture_output=True)
        
        # Write full output to log file
        with open(log_path, "w") as f:
            f.write(f"Command: {command}\n")
            f.write(f"Timestamp: {datetime.datetime.now().isoformat()}\n")
            f.write(f"Exit Code: {p.returncode}\n")
            f.write("-" * 20 + " STDOUT " + "-" * 20 + "\n")
            f.write(p.stdout)
            f.write("\n" + "-" * 20 + " STDERR " + "-" * 20 + "\n")
            f.write(p.stderr)
        
        # Log Result to Timeline
        status = "Success" if p.returncode == 0 else f"Failed ({p.returncode})"
        log_to_timeline(project_root, f"Docker Exec: {command}", status, context_link=rel_log_path)
        
        # Return summary instead of full output
        return f"Execution complete. Output saved to {rel_log_path}"
    
    except Exception as e:
        # Fallback logging for crashes
        err_msg = str(e)
        try:
            log_to_timeline(project_root, f"Docker Exec Error: {command}", "CRASH")
        except:
            pass # If even logging fails
        return f"Execution Crashed: {err_msg}"
        
    finally:
        # 5. Cleanup (Silent)
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

if __name__ == "__main__":
    if len(sys.argv) >= 4:
        print(run_in_sandbox(sys.argv[1], sys.argv[2], sys.argv[3]))