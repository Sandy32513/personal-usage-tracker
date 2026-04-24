# Git Setup Instructions

## Your GitHub Info
- **User ID:** Sandy32513
- **Email:** Santhosh.k0104@gmail.com
- **Repo:** https://github.com/Sandy32513/personal-usage-tracker

---

## Quick Push Commands (Copy-Paste All)

Open PowerShell and run:

```powershell
cd C:\Users\SANDY_1\Downloads\personal-usage-tracker-main

git config --global user.name "Sandy32513"
git config --global user.email "Santhosh.k0104@gmail.com"

git add .
git commit -m "Your message here"
git push origin main
```

---

## Common Commands

| Task | Command |
|-----|---------|
| Check status | `git status` |
| Stage all | `git add .` |
| Commit | `git commit -m "message"` |
| Push | `git push origin main` |
| Pull | `git pull origin main` |
| View history | `git log --oneline -5` |

---

## Troubleshooting

### GH007 Error (Email Privacy)
If push fails:
1. Go to: https://github.com/settings/emails
2. Enable "Keep my email address private"
3. Use the noreply email shown

### Authentication Error
1. Go to: https://github.com/settings/tokens
2. Generate Classic Token
3. Use token as password when prompted

---

## Notes
- Project already has .gitignore
- Remote origin is already configured
- Run from project folder: `cd C:\Users\SANDY_1\Downloads\personal-usage-tracker-main`