#!/usr/bin/env python3
"""
Automation Watchdog - Monitor AI automation workflows for failures and anomalies.
"""

import yaml
import requests
import sqlite3
import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('watchdog.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AutomationWatchdog:
    """Main watchdog class that monitors automation workflows."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize watchdog with configuration."""
        self.config = self._load_config(config_path)
        self.db_path = self.config['storage']['db_path']
        self._init_database()
        
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file."""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def _init_database(self):
        """Initialize SQLite database for storing execution history."""
        conn = sqlite3.connect(self.db_path)
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
        logger.info("Database initialized")
    
    def fetch_n8n_executions(self) -> List[Dict]:
        """Fetch recent executions from n8n API."""
        base_url = self.config['n8n']['base_url'].rstrip('/')
        api_key = self.config['n8n']['api_key']
        lookback_minutes = self.config['n8n']['lookback_minutes']
        
        # Calculate time window
        since = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        
        headers = {
            'Accept': 'application/json',
            'X-N8N-API-KEY': api_key
        }
        
        # Fetch executions
        url = f"{base_url}/api/v1/executions"
        params = {
            'limit': 100,
            'includeData': 'true'
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            executions = data.get('data', [])
            logger.info(f"Fetched {len(executions)} executions from n8n")
            
            # Filter by time window
            recent_executions = []
            for exec_data in executions:
                started_at = datetime.fromisoformat(
                    exec_data['startedAt'].replace('Z', '+00:00')
                )
                if started_at >= since:
                    recent_executions.append(exec_data)
            
            logger.info(f"Found {len(recent_executions)} executions in last {lookback_minutes} minutes")
            return recent_executions
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch executions from n8n: {e}")
            return []
    
    def process_execution(self, execution: Dict) -> None:
        """Process a single execution and store in database."""
        exec_id = execution['id']
        workflow_id = execution['workflowId']
        workflow_name = execution.get('workflowName', 'Unknown')
        status = execution['status']
        started_at = execution['startedAt']
        stopped_at = execution.get('stoppedAt')
        
        # Calculate duration
        duration = None
        if stopped_at:
            start = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            stop = datetime.fromisoformat(stopped_at.replace('Z', '+00:00'))
            duration = (stop - start).total_seconds()
        
        # Extract error message
        error_message = None
        if status == 'error':
            error_message = execution.get('data', {}).get('resultData', {}).get('error', {}).get('message', 'Unknown error')
        
        # Build execution URL
        base_url = self.config['n8n']['base_url'].rstrip('/')
        execution_url = f"{base_url}/execution/{exec_id}"
        
        # Store in database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if already exists
        cursor.execute('SELECT id FROM executions WHERE id = ?', (exec_id,))
        if cursor.fetchone():
            conn.close()
            return  # Already processed
        
        cursor.execute('''
            INSERT INTO executions 
            (id, workflow_id, workflow_name, status, started_at, stopped_at, duration_seconds, error_message, execution_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (exec_id, workflow_id, workflow_name, status, started_at, stopped_at, duration, error_message, execution_url))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Stored execution {exec_id} for workflow '{workflow_name}' (status: {status})")
        
        # Check for alerts
        if status == 'error':
            self.send_alert(workflow_id, workflow_name, 'failure', error_message, execution_url)
        elif duration and self._is_slow_execution(workflow_id, duration):
            self.send_alert(workflow_id, workflow_name, 'slow', f"Execution took {duration:.1f}s", execution_url)
    
    def _is_slow_execution(self, workflow_id: str, duration: float) -> bool:
        """Check if execution is significantly slower than average."""
        multiplier = self.config['health']['slow_execution_multiplier']
        sample_size = self.config['health']['sample_size']
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get average duration for this workflow
        cursor.execute('''
            SELECT AVG(duration_seconds) 
            FROM executions 
            WHERE workflow_id = ? AND duration_seconds IS NOT NULL
            ORDER BY started_at DESC 
            LIMIT ?
        ''', (workflow_id, sample_size))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            avg_duration = result[0]
            return duration > (avg_duration * multiplier)
        
        return False
    
    def send_alert(self, workflow_id: str, workflow_name: str, alert_type: str, 
                   error: str, execution_url: str) -> None:
        """Send alert via configured channels."""
        # Check cooldown
        cooldown = self.config['alerts']['cooldown_seconds']
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT sent_at FROM alerts 
            WHERE workflow_id = ? AND alert_type = ?
            ORDER BY sent_at DESC LIMIT 1
        ''', (workflow_id, alert_type))
        
        result = cursor.fetchone()
        if result:
            last_sent = datetime.fromisoformat(result[0])
            if (datetime.now() - last_sent).total_seconds() < cooldown:
                logger.info(f"Skipping alert for {workflow_name} (cooldown active)")
                conn.close()
                return
        
        # Prepare message
        message_template = self.config['webhook']['message']
        message = message_template.format(
            workflow_name=workflow_name,
            status=alert_type.upper(),
            error=error or 'No error details',
            timestamp=datetime.now().isoformat(),
            execution_url=execution_url
        )
        
        # Send webhook
        if self.config['webhook']['enabled']:
            self._send_webhook(message)
        
        # Store alert
        cursor.execute('''
            INSERT INTO alerts (workflow_id, alert_type, message)
            VALUES (?, ?, ?)
        ''', (workflow_id, alert_type, message))
        
        conn.commit()
        conn.close()
        
        logger.warning(f"Alert sent: {alert_type} for workflow '{workflow_name}'")
    
    def _send_webhook(self, message: str) -> None:
        """Send alert via webhook (Slack/Discord/custom)."""
        webhook_url = self.config['webhook']['url']
        
        payload = {
            'text': message,  # Slack
            'content': message  # Discord
        }
        
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Webhook sent successfully")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send webhook: {e}")
    
    def run(self):
        """Main monitoring loop."""
        logger.info("🚀 Automation Watchdog started")
        logger.info(f"Monitoring n8n at {self.config['n8n']['base_url']}")
        logger.info(f"Polling every {self.config['n8n']['poll_interval']}s")
        
        while True:
            try:
                executions = self.fetch_n8n_executions()
                
                for execution in executions:
                    self.process_execution(execution)
                
                time.sleep(self.config['n8n']['poll_interval'])
                
            except KeyboardInterrupt:
                logger.info("Watchdog stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(10)


if __name__ == '__main__':
    import sys
    
    config_path = sys.argv[1] if len(sys.argv) > 1 else 'config.yaml'
    
    if not Path(config_path).exists():
        logger.error(f"Config file not found: {config_path}")
        logger.info("Copy config.example.yaml to config.yaml and update with your settings")
        sys.exit(1)
    
    watchdog = AutomationWatchdog(config_path)
    watchdog.run()
