"""Projects API - Query task_manager for project data.

Provides endpoints to view project status, task progress, and active tasks
from brain_task_manager via direct file access (more reliable than IPC for read-only queries).
"""

import json
import time
import os
from typing import Any
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/projects", tags=["projects"])

# Task manager data paths — 以 config 为准: brain/infrastructure/config/brain_task_manager/brain_task_manager.json → data_dir
TASK_MANAGER_DATA_DIR = "/xkagent_infra/runtime/data/brain_task_manager"
TASKS_FILE = os.path.join(TASK_MANAGER_DATA_DIR, "tasks.json")
SPECS_FILE = os.path.join(TASK_MANAGER_DATA_DIR, "specs.json")


def load_tasks() -> list[dict]:
    """Load tasks from task_manager JSON file.

    Returns:
        List of task dictionaries.
    """
    try:
        if not os.path.exists(TASKS_FILE):
            return []

        with open(TASKS_FILE) as f:
            data = json.load(f)

        tasks_dict = data.get("tasks", {})
        tasks_list = []

        for task_id, task in tasks_dict.items():
            if isinstance(task, dict):
                task["id"] = task_id
                tasks_list.append(task)

        return tasks_list

    except (json.JSONDecodeError, IOError) as e:
        return []


def load_specs() -> list[dict]:
    """Load specs from task_manager JSON file.

    Returns:
        List of spec dictionaries.
    """
    try:
        if not os.path.exists(SPECS_FILE):
            return []

        with open(SPECS_FILE) as f:
            data = json.load(f)

        specs_dict = data.get("specs", {})
        specs_list = []

        for spec_id, spec in specs_dict.items():
            if isinstance(spec, dict):
                spec["id"] = spec_id
                specs_list.append(spec)

        return specs_list

    except (json.JSONDecodeError, IOError) as e:
        return []


@router.get("/list")
async def get_projects() -> dict[str, Any]:
    """Get all projects with status and progress.

    Returns:
        JSON with projects list, task counts, and completion stats.
    """
    try:
        tasks = load_tasks()

        # Group by project (group field represents project)
        project_map = {}
        for task in tasks:
            proj_name = task.get("group") or task.get("spec_id") or "default"
            if proj_name not in project_map:
                project_map[proj_name] = {
                    "name": proj_name,
                    "tasks": [],
                    "total": 0,
                    "completed": 0,
                    "in_progress": 0,
                    "pending": 0,
                }

            status = task.get("status", "pending")
            project_map[proj_name]["tasks"].append(task)
            project_map[proj_name]["total"] += 1

            if status == "completed":
                project_map[proj_name]["completed"] += 1
            elif status == "in_progress":
                project_map[proj_name]["in_progress"] += 1
            else:
                project_map[proj_name]["pending"] += 1

        projects = []
        for name, data in project_map.items():
            total = data["total"]
            completed = data["completed"]
            progress = (completed / total * 100) if total > 0 else 0

            projects.append({
                "name": name,
                "total_tasks": total,
                "completed": completed,
                "in_progress": data["in_progress"],
                "pending": data["pending"],
                "progress": round(progress, 1),
                "status": "active" if data["in_progress"] > 0 else ("completed" if progress == 100 else "pending"),
            })

        # Sort by name
        projects.sort(key=lambda x: x["name"])

        return {
            "timestamp": int(time.time()),
            "projects": projects,
            "count": len(projects),
            "source": "task_manager_file",
        }

    except Exception as e:
        return {
            "timestamp": int(time.time()),
            "projects": [],
            "count": 0,
            "source": "error",
            "error": str(e)[:100],
        }


@router.get("/tasks")
async def get_tasks(project: str = None, status: str = None) -> dict[str, Any]:
    """Get tasks with optional filtering.

    Args:
        project: Filter by project name (group)
        status: Filter by task status (pending/in_progress/completed)

    Returns:
        JSON with task list.
    """
    try:
        tasks = load_tasks()

        # Apply filters
        filtered = tasks
        if project:
            filtered = [t for t in filtered if (t.get("group") or t.get("spec_id") or "default") == project]
        if status:
            filtered = [t for t in filtered if t.get("status") == status]

        # Sort by updated_at descending
        filtered.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

        return {
            "timestamp": int(time.time()),
            "tasks": filtered,
            "count": len(filtered),
            "source": "task_manager_file",
        }

    except Exception as e:
        return {
            "timestamp": int(time.time()),
            "tasks": [],
            "count": 0,
            "source": "error",
            "error": str(e)[:100],
        }


@router.get("/summary")
async def get_summary() -> dict[str, Any]:
    """Get overall project summary statistics.

    Returns:
        JSON with summary stats across all projects.
    """
    try:
        tasks = load_tasks()

        # Calculate stats
        total = len(tasks)
        completed = sum(1 for t in tasks if t.get("status") == "completed")
        in_progress = sum(1 for t in tasks if t.get("status") == "in_progress")
        pending = sum(1 for t in tasks if t.get("status") == "pending")

        # Get unique projects (groups)
        projects = set()
        for t in tasks:
            proj = t.get("group") or t.get("spec_id") or "default"
            projects.add(proj)

        # Count active today (updated in last 24 hours)
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=1)).isoformat()
        active_today = sum(1 for t in tasks if t.get("updated_at", "") > cutoff)

        return {
            "timestamp": int(time.time()),
            "total_projects": len(projects),
            "total_tasks": total,
            "completed": completed,
            "in_progress": in_progress,
            "pending": pending,
            "active_today": active_today,
            "source": "task_manager_file",
        }

    except Exception as e:
        return {
            "timestamp": int(time.time()),
            "total_projects": 0,
            "total_tasks": 0,
            "completed": 0,
            "in_progress": 0,
            "pending": 0,
            "active_today": 0,
            "source": "error",
            "error": str(e)[:100],
        }


@router.get("/specs")
async def get_specs(group: str = None, stage: str = None) -> dict[str, Any]:
    """Get specs with optional filtering.

    Args:
        group: Filter by group name
        stage: Filter by stage

    Returns:
        JSON with spec list.
    """
    try:
        specs = load_specs()

        # Apply filters
        filtered = specs
        if group:
            filtered = [s for s in filtered if s.get("group") == group]
        if stage:
            filtered = [s for s in filtered if s.get("stage") == stage]

        return {
            "timestamp": int(time.time()),
            "specs": filtered,
            "count": len(filtered),
            "source": "task_manager_file",
        }

    except Exception as e:
        return {
            "timestamp": int(time.time()),
            "specs": [],
            "count": 0,
            "source": "error",
            "error": str(e)[:100],
        }
