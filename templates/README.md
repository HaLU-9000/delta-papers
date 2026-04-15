# digest scheduler templates

Cross-platform scheduler templates for the `digest` skill. `scripts/scheduler.py`
owns substitution and file installation — **do not edit these templates or the
generated artifacts by hand.**

## Layout

```
templates/
├── launchd/    # macOS — LaunchAgents plist templates
│   ├── morning-digest.plist.template
│   └── digest-inbox.plist.template
├── cron/       # Linux — crontab fragment templates (BEGIN/END markers)
│   ├── morning-digest.cron.template
│   └── digest-inbox.cron.template
└── windows/    # Windows — PowerShell wrappers invoked by Task Scheduler
    ├── morning-digest.ps1.template
    └── digest-inbox.ps1.template
```

The legacy `plist/` directory at the skill root is retained for backwards
compatibility; new code should read from `templates/launchd/`.

## Substitution placeholders

| Placeholder | Meaning |
|---|---|
| `{HOME}` | user home dir (POSIX) |
| `{CLAUDE_BIN}` | absolute path to the `claude` CLI |
| `{HOUR}` / `{MINUTE}` | 0–23 / 0–59 |
| `{INTERVAL_SEC}` / `{INTERVAL_MIN}` | polling interval |
| `{LABEL_PREFIX}` | launchd label prefix, default `com.delta-papers` |

`scripts/scheduler.py` performs the substitution and installs the rendered
files into the platform-appropriate location. These template files must not
be edited manually.
