import psutil
import time
import os
import multiprocessing
from collections import defaultdict
from datetime import datetime

# Simple in-memory store for metrics (for demonstration)
METRICS_STORE = defaultdict(int)
START_TIME = time.time()
PROCESS_START_TIMES = {}
RESTART_COUNT = 0

def get_process_info():
    current_process = psutil.Process()
    workers = []
    
    try:
        # First, try to get the parent process if we're a worker
        parent = current_process.parent()
        if parent and "waitress" in parent.name().lower():
            # We're a Waitress worker, get all our siblings
            main_process = parent
            worker_processes = parent.children()
        else:
            # We're the main process, get all children
            main_process = current_process
            worker_processes = current_process.children()

        # Get all Waitress worker processes
        for proc in worker_processes:
            try:
                if "waitress" in proc.name().lower() or (parent and proc.ppid() == parent.pid):
                    cpu_percent = proc.cpu_percent(interval=0.1)
                    memory_percent = proc.memory_percent()
                    
                    worker_info = {
                        'pid': proc.pid,
                        'cpu_percent': cpu_percent,
                        'memory_percent': memory_percent,
                        'status': proc.status(),
                        'create_time': datetime.fromtimestamp(proc.create_time()).isoformat(),
                        'name': proc.name(),
                        'threads': proc.num_threads(),
                        'connections': len(proc.connections()),
                    }
                    workers.append(worker_info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                continue

        return {
            'main_pid': main_process.pid,
            'main_name': main_process.name(),
            'workers': workers,
            'worker_count': len(workers),
            'cpu_cores': multiprocessing.cpu_count(),
            'total_threads': sum(worker['threads'] for worker in workers) + main_process.num_threads(),
            'total_connections': sum(worker['connections'] for worker in workers) + len(main_process.connections())
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        return {
            'main_pid': current_process.pid,
            'main_name': current_process.name(),
            'workers': [],
            'worker_count': 0,
            'cpu_cores': multiprocessing.cpu_count(),
            'total_threads': current_process.num_threads(),
            'total_connections': len(current_process.connections()),
            'error': str(e)
        }

def get_system_metrics():
    return {
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_usage': psutil.disk_usage('/').percent,
        'open_files': len(psutil.Process().open_files()),
        'connections': len(psutil.Process().connections()),
        'load_avg': psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None
    }

def record_metrics(request, response, duration):
    METRICS_STORE['total_requests'] += 1
    METRICS_STORE[f"{request.method}_requests"] += 1
    METRICS_STORE[f"status_{response.status_code}"] += 1
    METRICS_STORE['total_duration'] += duration

    # Record process information
    current_process = psutil.Process()
    pid = current_process.pid
    
    if pid not in PROCESS_START_TIMES:
        PROCESS_START_TIMES[pid] = time.time()
        global RESTART_COUNT
        RESTART_COUNT += 1

def get_metrics():
    uptime = time.time() - START_TIME
    process_uptime = time.time() - min(PROCESS_START_TIMES.values()) if PROCESS_START_TIMES else 0

    metrics = dict(METRICS_STORE)
    metrics.update({
        'uptime_seconds': uptime,
        'process_uptime_seconds': process_uptime,
        'restart_count': RESTART_COUNT,
        'process_info': get_process_info(),
        'system_metrics': get_system_metrics()
    })
    
    return metrics
