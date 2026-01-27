# Git Setup Guide

Follow these steps to push your code to GitHub/GitLab.

## Step 1: Initialize Git Repository

If you haven't already initialized git:

```bash
git init
```

## Step 2: Check .gitignore

The `.gitignore` file has been created to exclude:
- `.env` (credentials)
- `*.pkl` (cookies)
- `*.log` (logs)
- `emails.txt` and `sent_emails.txt` (sensitive data)
- `*.pdf` (resume files)

**IMPORTANT**: Never commit `.env` file or any files with credentials!

## Step 3: Add Files

Add all files (`.gitignore` will automatically exclude sensitive files):

```bash
git add .
```

Verify what will be committed:

```bash
git status
```

Make sure `.env`, `*.pkl`, `*.log`, `emails.txt`, and `sent_emails.txt` are NOT listed.

## Step 4: Create Initial Commit

```bash
git commit -m "Initial commit: LinkedIn email scraper and auto-emailer"
```

## Step 5: Create Remote Repository

### For GitHub:

1. Go to https://github.com/new
2. Create a new repository (don't initialize with README)
3. Copy the repository URL (e.g., `https://github.com/username/repo-name.git`)

### For GitLab:

1. Go to https://gitlab.com/projects/new
2. Create a new project
3. Copy the repository URL

## Step 6: Add Remote and Push

```bash
# Add remote (replace with your repository URL)
git remote add origin https://github.com/username/repo-name.git

# Rename branch to main (if needed)
git branch -M main

# Push to remote
git push -u origin main
```

## Step 7: Verify

Check your repository online - you should see:
- ✅ `linkedin_email_scraper.py`
- ✅ `README.md`
- ✅ `requirements.txt`
- ✅ `.gitignore`
- ❌ `.env` (should NOT be there)
- ❌ `*.pkl` files (should NOT be there)
- ❌ `*.log` files (should NOT be there)

## Quick Commands Reference

```bash
# Check status
git status

# Add all files
git add .

# Commit changes
git commit -m "Your commit message"

# Push to remote
git push

# Pull latest changes
git pull

# View remote
git remote -v

# Change remote URL
git remote set-url origin NEW_URL
```

## Security Checklist

Before pushing, verify:

- [ ] `.env` file is NOT in git (check with `git status`)
- [ ] `linkedin_cookies.pkl` is NOT in git
- [ ] `emails.txt` is NOT in git
- [ ] `sent_emails.txt` is NOT in git
- [ ] `*.log` files are NOT in git
- [ ] Resume PDF files are NOT in git
- [ ] `.gitignore` is committed and working

## If You Accidentally Committed Sensitive Files

If you already committed `.env` or other sensitive files:

```bash
# Remove from git (but keep local file)
git rm --cached .env
git rm --cached *.pkl
git rm --cached emails.txt
git rm --cached sent_emails.txt

# Update .gitignore
# (already done)

# Commit the removal
git commit -m "Remove sensitive files from git"

# Force push (if already pushed)
git push --force
```

**Note**: If you already pushed sensitive files, they're in git history. Consider:
1. Changing all passwords/credentials
2. Creating a new repository
3. Using `git filter-branch` or `BFG Repo-Cleaner` to remove from history

## Best Practices

1. **Never commit credentials** - Always use `.env` file
2. **Review before committing** - Use `git status` and `git diff`
3. **Use meaningful commit messages**
4. **Keep `.gitignore` updated** - Add new sensitive file patterns as needed
5. **Regular commits** - Commit often with clear messages

## Example Workflow

```bash
# Make changes to code
# ... edit files ...

# Check what changed
git status

# Add changes
git add linkedin_email_scraper.py README.md

# Commit
git commit -m "Add email template support from .env"

# Push
git push
```

---

**Remember**: Your `.env` file contains sensitive credentials. Never commit it or share it publicly!

