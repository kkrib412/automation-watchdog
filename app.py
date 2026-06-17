#!/usr/bin/env python3
"""Automation Watchdog - Web Dashboard"""

import os
import sys
import sqlite3
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from flask import Flask, render_template, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitor import AutomationWatchdog

app = Flask(__name__)

# Global watchdog instance
watchdog = None
monitor_thread = None


def get_db():
    """Get database connection."""
    db_path = "watchdog.db"
    if watchdog:
        db_path = watchdog.db_path
    
    # Ensure database exists
    if not Path(db_path).exists():
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS executions (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                workflow_name TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                stopped_at TEXT,
                duration_seconds REAL,
                error_message TEXT,
                execution_url TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                message TEXT NOT NULL,
                sent_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    
    return sqlite3.connect(db_path)


def init_watchdog():
    """Initialize watchdog in background and create database."""
    global watchdog, monitor_thread
    
    # Initialize database first
    db_path = "watchdog.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            stopped_at TEXT,
            duration_seconds REAL,
            error_message TEXT,
            execution_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            message TEXT NOT NULL,
            sent_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Database initialized")
    
    # Start watchdog if config exists
    config_path = Path("config.yaml")
    if config_path.exists():
        try:
            watchdog = AutomationWatchdog("config.yaml")
            monitor_thread = threading.Thread(target=watchdog.run, daemon=True)
            monitor_thread.start()
            print("✅ Watchdog started in background")
        except Exception as e:
            print(f"⚠️  Watchdog startup failed: {e}")
    else:
        print("⚠️  No config.yaml found - running in demo mode")


@app.route("/")
def index():
    """Main dashboard page."""
    return render_template("dashboard.html")


@app.route("/api/overview")
def api_overview():
    """Get dashboard overview data."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Total executions in last 24h
        since = (datetime.now() - timedelta(hours=24)).isoformat()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'waiting' THEN 1 ELSE 0 END) as waiting
            FROM executions
            WHERE started_at >= ?
        """, (since,))
        
        row = cursor.fetchone()
        total, success, failed, waiting = row if row else (0, 0, 0, 0)
        
        # Success rate
        success_rate = (success / total * 100) if total > 0 else 0
        
        # Unique workflows
        cursor.execute("""
            SELECT COUNT(DISTINCT workflow_id) 
            FROM executions 
            WHERE started_at >= ?
        """, (since,))
        workflow_count = cursor.fetchone()[0] or 0
        
        # Recent alerts (last 24h)
        cursor.execute("""
            SELECT COUNT(*) 
            FROM alerts 
            WHERE sent_at >= ?
        """, (since,))
        alert_count = cursor.fetchone()[0] or 0
        
        # Average execution time
        cursor.execute("""
            SELECT AVG(duration_seconds) 
            FROM executions 
            WHERE started_at >= ? AND duration_seconds IS NOT NULL
        """, (since,))
        avg_duration = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return jsonify({
            "total_executions": total,
            "success_count": success,
            "failed_count": failed,
            "waiting_count": waiting,
            "success_rate": round(success_rate, 1),
            "workflow_count": workflow_count,
            "alert_count": alert_count,
            "avg_duration": round(avg_duration, 2),
            "period": "Last 24 hours"
        })
        
    except Exception as e:
        print(f"Error in api_overview: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/workflows")
def api_workflows():
    """Get workflow health data."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get all workflows with their recent stats
        cursor.execute("""
            SELECT 
                workflow_id,
                workflow_name,
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
                AVG(duration_seconds) as avg_duration,
                MAX(started_at) as last_run,
                (SELECT status FROM executions e2 
                 WHERE e2.workflow_id = e1.workflow_id 
                 ORDER BY started_at DESC LIMIT 1) as last_status
            FROM executions e1
            GROUP BY workflow_id, workflow_name
            ORDER BY last_run DESC
        """)
        
        workflows = []
        for row in cursor.fetchall():
            wf_id, name, total, success, errors, avg_dur, last_run, last_status = row
            
            # Calculate health score (0-100)
            if total > 0:
                success_rate = (success / total) * 100
                health_score = min(100, success_rate)
            else:
                health_score = 0
            
            # Determine status
            if last_status == "error":
                status = "unhealthy"
            elif health_score < 70:
                status = "degraded"
            elif health_score >= 90:
                status = "healthy"
            else:
                status = "warning"
            
            workflows.append({
                "id": wf_id,
                "name": name,
                "total_runs": total,
                "success_count": success,
                "error_count": errors,
                "success_rate": round((success / total * 100) if total > 0 else 0, 1),
                "health_score": round(health_score, 1),
                "avg_duration": round(avg_dur or 0, 2),
                "last_run": last_run,
                "last_status": last_status,
                "status": status
            })
        
        conn.close()
        return jsonify(workflows)
        
    except Exception as e:
        print(f"Error in api_workflows: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/executions")
def api_executions():
    """Get recent executions."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                id, workflow_id, workflow_name, status, 
                started_at, stopped_at, duration_seconds,
                error_message, execution_url
            FROM executions
            ORDER BY started_at DESC
            LIMIT 100
        """)
        
        executions = []
        for row in cursor.fetchall():
            executions.append({
                "id": row[0],
                "workflow_id": row[1],
                "workflow_name": row[2],
                "status": row[3],
                "started_at": row[4],
                "stopped_at": row[5],
                "duration_seconds": row[6],
                "error_message": row[7],
                "execution_url": row[8]
            })
        
        conn.close()
        return jsonify(executions)
        
    except Exception as e:
        print(f"Error in api_executions: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/alerts")
def api_alerts():
    """Get recent alerts."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, workflow_id, alert_type, message, sent_at
            FROM alerts
            ORDER BY sent_at DESC
            LIMIT 50
        """)
        
        alerts = []
        for row in cursor.fetchall():
            alerts.append({
                "id": row[0],
                "workflow_id": row[1],
                "alert_type": row[2],
                "message": row[3],
                "sent_at": row[4]
            })
        
        conn.close()
        return jsonify(alerts)
        
    except Exception as e:
        print(f"Error in api_alerts: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/trends")
def api_trends():
    """Get execution trends over time."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get hourly stats for last 24h
        cursor.execute("""
            SELECT 
                strftime('%Y-%m-%d %H:00', started_at) as hour,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as failed
            FROM executions
            WHERE started_at >= datetime('now', '-24 hours')
            GROUP BY hour
            ORDER BY hour ASC
        """)
        
        trends = []
        for row in cursor.fetchall():
            trends.append({
                "hour": row[0],
                "total": row[1],
                "success": row[2],
                "failed": row[3]
            })
        
        conn.close()
        return jsonify(trends)
        
    except Exception as e:
        print(f"Error in api_trends: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/status")
def api_status():
    """Get system status."""
    return jsonify({
        "watchdog_running": watchdog is not None and monitor_thread is not None,
        "database_exists": Path("watchdog.db").exists(),
        "config_exists": Path("config.yaml").exists(),
        "timestamp": datetime.now().isoformat()
    })


if __name__ == "__main__":
    init_watchdog()
    print("\nDashboard: http://localhost:8502")
    app.run(host="0.0.0.0", port=8502, debug=False)
