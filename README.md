# Automation Watchdog

Real-time health monitoring for AI automation workflows (n8n, Make, Zapier).

## The Problem

AI automations fail silently. Workflows break, APIs timeout, data gets corrupted — and nobody knows until a client complains or data is already corrupted.

## The Solution

A monitoring service that:
- Connects to your automation platform (n8n, Make, Zapier)
- Tracks execution success/failure rates
- Detects silent failures and anomalies
- Alerts you BEFORE data gets corrupted or clients notice

## Features

- **Execution Monitoring**: Track every workflow run, success/failure status
- **Failure Detection**: Instant alerts when workflows fail or timeout
- **Anomaly Detection**: Spot unusual patterns (sudden spike in failures, slow executions)
- **Health Scoring**: Uptime %, reliability metrics per workflow
- **Multi-Channel Alerts**: Slack, Discord, Telegram, email, webhook
- **Historical Trends**: See which workflows are reliable vs problematic

## Quick Start

```bash
# Clone and install
cd automation-watchdog
pip install -r requirements.txt

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml with your n8n/Make/Zapier credentials

# Run monitor
python monitor.py
```

## Supported Platforms

- ✅ **n8n** (self-hosted and cloud)
- 🚧 **Make** (Integromat) - coming soon
- 🚧 **Zapier** - coming soon

## Alert Channels

- ✅ Webhook (Slack, Discord, custom)
- ✅ Email (SMTP)
- 🚧 Telegram
- 🚧 SMS

## Use Cases

**AI Agencies**: Monitor 10-50 client automations, catch failures before clients do
**Solo Builders**: Know when your workflows break without checking constantly
**DevOps Teams**: Add observability to your n8n/Make infrastructure
**SaaS Companies**: Ensure your automation features are reliable for users

## Architecture

```
[Automation Platform] → [Watchdog API] → [Health Analyzer] → [Alert Engine]
       (n8n/Make)         (Python)         (SQLite)          (Webhooks)
```

## License

MIT
