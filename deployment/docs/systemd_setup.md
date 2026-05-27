# Systemd Service Setup

Install units:

```bash
sudo cp deployment/systemd/bonbon-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bonbon-core bonbon-safety bonbon-dashboard bonbon-monitoring
```

Recommended start order:

1. `bonbon-monitoring`
2. `bonbon-core`
3. `bonbon-safety`
4. `bonbon-navigation`
5. `bonbon-perception`
6. `bonbon-speech`
7. `bonbon-tts`
8. `bonbon-dashboard`
