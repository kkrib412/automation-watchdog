#!/usr/bin/env python3
"""
Test script to verify n8n API connection.
"""

import yaml
import requests
from pathlib import Path

def test_connection():
    """Test connection to n8n API."""
    
    # Load config
    config_path = Path('config.yaml')
    if not config_path.exists():
        print("❌ config.yaml not found!")
        print("   Copy config.example.yaml to config.yaml and update with your settings")
        return False
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    base_url = config['n8n']['base_url'].rstrip('/')
    api_key = config['n8n']['api_key']
    
    print(f"🔍 Testing connection to {base_url}...")
    
    headers = {
        'Accept': 'application/json',
        'X-N8N-API-KEY': api_key
    }
    
    try:
        # Test API connection
        response = requests.get(f"{base_url}/api/v1/workflows", headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        workflows = data.get('data', [])
        
        print(f"✅ Connected successfully!")
        print(f"📊 Found {len(workflows)} workflows")
        
        if workflows:
            print("\nWorkflows:")
            for wf in workflows[:5]:
                active = "✓" if wf.get('active') else "✗"
                print(f"  [{active}] {wf['name']} (ID: {wf['id']})")
            if len(workflows) > 5:
                print(f"  ... and {len(workflows) - 5} more")
        
        # Test executions endpoint
        print(f"\n🔍 Testing executions endpoint...")
        response = requests.get(f"{base_url}/api/v1/executions", headers=headers, params={'limit': 5}, timeout=10)
        response.raise_for_status()
        
        exec_data = response.json()
        executions = exec_data.get('data', [])
        
        print(f"✅ Executions endpoint works!")
        print(f"📊 Found {len(executions)} recent executions")
        
        if executions:
            print("\nRecent executions:")
            for ex in executions[:5]:
                status_emoji = "✅" if ex['status'] == 'success' else "❌" if ex['status'] == 'error' else "⚠️"
                print(f"  {status_emoji} {ex.get('workflowName', 'Unknown')} - {ex['status']}")
        
        print("\n🎉 All tests passed! You're ready to run the watchdog.")
        print("   Run: python monitor.py")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Connection failed!")
        print(f"   Could not connect to {base_url}")
        print(f"   Make sure n8n is running and accessible")
        return False
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print(f"❌ Authentication failed!")
            print(f"   Check your API key in config.yaml")
        else:
            print(f"❌ HTTP error: {e}")
        return False
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == '__main__':
    test_connection()
