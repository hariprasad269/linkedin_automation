# LinkedIn Email Scraper and Auto-Emailer

An automated LinkedIn job search tool that scrapes job posts, extracts email addresses, and sends personalized emails with your resume attachment.

## 📋 Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Output Files](#output-files)
- [Troubleshooting](#troubleshooting)
- [Important Notes](#important-notes)

## ✨ Features

- **Automated LinkedIn Login**: Uses saved cookies after first login to avoid repeated authentication
- **Multiple Search Queries**: Process multiple search queries from `.env` file
- **Date Filtering**: Filter posts by "Past 24 hours" or "Past week"
- **Email Extraction**: Automatically extracts email addresses from post content
- **Auto-Email Sending**: Sends personalized emails via Gmail SMTP with resume attachment
- **Duplicate Prevention**: Tracks sent emails to avoid duplicates
- **Smart Scrolling**: Automatically scrolls and clicks "Load more" buttons to load all posts
- **Error Recovery**: Automatically moves to next search query if scrolling fails
- **Post Processing**: Expands collapsed posts, extracts full content, and checks if already liked
- **Resume Generation**: Can generate PDF resumes with your details

## 🔧 Prerequisites

1. **Python 3.7+** installed on your system
2. **Google Chrome** browser installed
3. **Gmail Account** with App Password enabled (see Gmail Setup below)
4. **LinkedIn Account** credentials

### Gmail App Password Setup

1. Go to [Google Account Settings](https://myaccount.google.com/)
2. Navigate to **Security** → **2-Step Verification** (enable if not already)
3. Go to **App Passwords**: https://myaccount.google.com/apppasswords
4. Select:
   - **App**: Mail
   - **Device**: Other (Custom name) → Enter "LinkedIn Bot"
5. Click **Generate** and copy the 16-character password
6. Use this password in your `.env` file for `GMAIL_PASSWORD`

## 📦 Installation

1. **Clone or download this repository**

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

   Required packages:
   - `selenium>=4.15.0` - Web automation
   - `webdriver-manager>=4.0.0` - Chrome driver management
   - `reportlab>=4.0.0` - PDF generation

3. **Create `.env` file** (see Configuration section below)
   - Copy the example configuration
   - Fill in all required credentials and personal details
   - **Important**: Never commit `.env` to version control

4. **Place your resume**:
   - Place `resume.pdf` in the project root directory
   - Or the script will auto-detect any `.pdf` file in the directory

## ⚙️ Configuration

Create a `.env` file in the project root with the following configuration:

### Required Settings

```env
# LinkedIn Credentials
LINKEDIN_EMAIL=your_linkedin_email@example.com
LINKEDIN_PASSWORD=your_linkedin_password

# Gmail Credentials (for sending emails)
# Use Gmail App Password (16 characters) - NOT your regular password
# Generate at: https://myaccount.google.com/apppasswords
GMAIL_EMAIL=your_gmail@gmail.com
GMAIL_PASSWORD=your_16_char_app_password

# Personal Details (used in email signature and resume)
YOUR_NAME=Your Full Name
YOUR_EMAIL=your_email@example.com
YOUR_PHONE=your_phone_number
YOUR_LINKEDIN=https://www.linkedin.com/in/your-profile

# Email Subject Template
# Placeholders: {job_title} - extracted from post (e.g., "Manual Testing/Automation/QA")
#               {name} - your name from YOUR_NAME
# Example: "Application for {job_title} Position - {name}"
EMAIL_SUBJECT_TEMPLATE=Application for {job_title} Position - {name}

# Email Body Template
# Placeholders: {name}, {email}, {phone}, {linkedin} - from personal details above
# Use \n for new lines (keep as single line in .env)
# Example below - customize as needed
EMAIL_BODY_TEMPLATE=Hi,\n\nI hope this email finds you well.\n\nI am writing to express my strong interest in this job opportunity...\n\nWarm regards,\n\n{name}\n{linkedin}\n{phone}
```

### Optional Settings

```env
# Date Filter - Filter posts by time period
# Options: "Past 24 hours", "Past week", "Past month"
DATE_FILTER=Past 24 hours

# Maximum number of posts to process per search query
# Set to 0 for unlimited (not recommended)
MAX_POSTS_TO_PROCESS=20

# Custom CSS selector for "Past week" filter (if default doesn't work)
# Only needed if DATE_FILTER=Past week and default selector fails
PAST_WEEK_SELECTOR=#MukfIQbWTJSc\\/m5TDTOy7g\\=\\= > div > ul.reusable-search__entity-cluster--quick-filter-action-container > li:nth-child(3) > a
```

### Search Queries

Add multiple `SEARCH_QUERY` lines to search for different job postings. The script will process all active (uncommented) queries.

**Basic Search Query Format:**
```env
SEARCH_QUERY=keyword1 AND keyword2 AND @ AND location
```

**Examples:**

```env
# Simple queries
SEARCH_QUERY=selenium AND 3 AND @ AND Hyderabad AND python
SEARCH_QUERY=selenium AND 3 AND @ AND Bangalore AND python
SEARCH_QUERY=selenium AND 3 AND @ AND Chennai AND python
SEARCH_QUERY=selenium AND 3 AND @ AND Remote AND python

# Complex queries with OR conditions
SEARCH_QUERY=("manual testing" OR "manual tester") AND 3 AND @
SEARCH_QUERY="manual testing" AND 3 AND @ AND (Hyderabad OR Bangalore OR Chennai)
SEARCH_QUERY="manual testing" AND ("3 years" OR 3yr OR "3+") AND @

# Queries with specific keywords
SEARCH_QUERY="manual testing" AND 3 AND @ AND ("hiring" OR "urgent" OR "immediate")
SEARCH_QUERY=("manual testing" OR ManualTesting) AND 3 AND @ AND (openings OR vacancy)
```

**Search Query Tips:**
- Use `AND` to require all terms
- Use `OR` (in parentheses) for alternatives
- Use quotes for exact phrases: `"manual testing"`
- Use `@` to find posts with email addresses
- Combine location, skills, and experience: `skill AND years AND @ AND location`

**To disable a query**, comment it out with `#`:
```env
# SEARCH_QUERY=old_query_here
```

## 🚀 Usage

### Basic Usage

Run the script:
```bash
python linkedin_email_scraper.py
```

### Scrape Only Mode (No Email Sending)

To only scrape emails without sending:
```bash
python linkedin_email_scraper.py --scrape-only
```

### Send Emails from File

To send emails from a previously scraped `emails.txt` file:
```bash
python linkedin_email_scraper.py --send-only
```

## 📁 Output Files

The script creates several output files:

### 1. `emails.txt`
Contains all extracted email addresses with post details:
```
EMAIL: example@company.com
AUTHOR: John Doe
CONTENT: Job posting content here...
---
```

### 2. `sent_emails.txt`
Tracks all email addresses that have been sent emails (one per line). Prevents duplicate emails.

### 3. `linkedin_scraper.log`
Detailed log file with all operations, errors, and debugging information.

### 4. `linkedin_cookies.pkl`
Saved LinkedIn session cookies. After first login, the script uses this to avoid repeated logins.

### 5. `resumes/` directory
Contains generated PDF resumes (if resume generation is enabled).

## 🔍 How It Works

1. **Login**: 
   - First run: Logs into LinkedIn and saves cookies
   - Subsequent runs: Uses saved cookies for faster login

2. **Search**:
   - For each `SEARCH_QUERY` in `.env`:
     - Searches LinkedIn with the query
     - Applies date filter (Past 24 hours/week)
     - Scrolls through results and clicks "Load more" buttons

3. **Post Processing**:
   - Expands collapsed posts (clicks "more" button)
   - Extracts full post content
   - Checks if post is already liked
   - Extracts email addresses using regex pattern

4. **Email Sending**:
   - For each unique email found:
     - Checks if already sent (from `sent_emails.txt`)
     - Generates personalized email
     - Attaches resume PDF
     - Sends via Gmail SMTP
     - Records in `sent_emails.txt`

5. **Error Handling**:
   - If scrolling fails → moves to next search query
   - If browser connection lost → moves to next search query
   - Logs all errors for debugging

## 🐛 Troubleshooting

### Chrome Driver Issues

**Error**: `ChromeDriver not found` or version mismatch

**Solution**: The script uses `webdriver-manager` which auto-downloads the correct ChromeDriver. Make sure Chrome browser is up to date.

### Login Issues

**Error**: Login fails or requires manual verification

**Solution**: 
- Delete `linkedin_cookies.pkl` and try again
- Make sure credentials in `.env` are correct
- LinkedIn may require 2FA - complete it manually on first run

### No Posts Found

**Possible causes**:
- Search query too specific
- Date filter too restrictive
- LinkedIn changed their HTML structure

**Solution**:
- Try broader search queries
- Change `DATE_FILTER` to "Past week"
- Check `linkedin_scraper.log` for errors

### Email Sending Fails

**Error**: `SMTP Authentication failed` or `Gmail credentials not found`

**Solution**:
- Make sure you're using Gmail App Password (not regular password)
- Verify `GMAIL_EMAIL` and `GMAIL_PASSWORD` are set in `.env`
- Check that App Password is correctly copied (16 characters, no spaces)
- Enable 2-Step Verification on your Google account first
- Regenerate App Password if needed: https://myaccount.google.com/apppasswords

### Missing Personal Details

**Error**: Email signature shows placeholder values

**Solution**:
- Make sure all personal details are set in `.env`:
  - `YOUR_NAME`
  - `YOUR_EMAIL`
  - `YOUR_PHONE`
  - `YOUR_LINKEDIN`
- These are used in the email signature and resume

### Scrolling Stops Working

**Error**: Script gets stuck scrolling

**Solution**: The script now automatically:
- Detects when scrolling stops making progress
- Moves to next search query after 5 consecutive attempts with no new posts
- Clicks "Load more" buttons when available

### Browser Connection Lost

**Error**: `Connection refused` or `No such window`

**Solution**: The script automatically:
- Detects browser connection errors
- Moves to next search query
- Logs the error for review

## ⚠️ Important Notes

### Rate Limiting
- LinkedIn may rate limit or block accounts with excessive automation
- Use reasonable `MAX_POSTS_TO_PROCESS` values (20-50 recommended)
- Add delays between operations (already built-in)

### Email Sending Limits
- Gmail has daily sending limits (~500 emails/day for free accounts)
- The script tracks sent emails to avoid duplicates
- Check `sent_emails.txt` to see what's been sent

### LinkedIn Terms of Service
- This tool is for personal use only
- Respect LinkedIn's Terms of Service
- Don't use for spam or bulk messaging
- Use responsibly and ethically

### Privacy & Security
- **All credentials are stored in `.env` file** - keep it secure and never commit it to version control
- No credentials are hardcoded in the script - everything reads from `.env`
- Cookies are saved locally in `linkedin_cookies.pkl`
- Personal information (name, email, phone, LinkedIn) is also in `.env`
- Add `.env` and `*.pkl` to `.gitignore` if using version control

### Best Practices
1. **Start Small**: Test with 1-2 search queries first
2. **Monitor Logs**: Check `linkedin_scraper.log` regularly
3. **Update Queries**: Keep search queries relevant and specific
4. **Resume Quality**: Ensure your resume PDF is professional and up-to-date
5. **Email Content**: Review and customize email templates in the script
6. **Security**: Never share your `.env` file or commit it to version control
7. **Credentials**: Use App Passwords for Gmail, not your regular password
8. **Personal Info**: Keep your personal details (name, phone, etc.) accurate in `.env`

## 📝 Environment Variables Summary

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `LINKEDIN_EMAIL` | Yes | Your LinkedIn email address | `user@example.com` |
| `LINKEDIN_PASSWORD` | Yes | Your LinkedIn password | `yourpassword` |
| `GMAIL_EMAIL` | Yes | Gmail address for sending emails | `your@gmail.com` |
| `GMAIL_PASSWORD` | Yes | Gmail App Password (16 characters) | `abcd efgh ijkl mnop` |
| `YOUR_NAME` | Yes | Your full name (for email signature) | `John Doe` |
| `YOUR_EMAIL` | Yes | Your contact email (for email signature) | `john@example.com` |
| `YOUR_PHONE` | Yes | Your phone number (for email signature) | `+1234567890` |
| `YOUR_LINKEDIN` | Yes | Your LinkedIn profile URL | `https://www.linkedin.com/in/johndoe` |
| `EMAIL_SUBJECT_TEMPLATE` | No | Email subject template with placeholders | `Application for {job_title} Position - {name}` |
| `EMAIL_BODY_TEMPLATE` | No | Email body template with placeholders | (see .env example) |
| `DATE_FILTER` | No | Time filter for posts | `Past 24 hours` |
| `MAX_POSTS_TO_PROCESS` | No | Max posts per query | `20` |
| `PAST_WEEK_SELECTOR` | No | Custom CSS selector for "Past week" filter | (see .env example) |
| `SEARCH_QUERY` | Yes* | Search query (can have multiple) | `selenium AND 3 AND @` |

*At least one `SEARCH_QUERY` must be active (uncommented)

### Personal Details Variables

The following variables are used in the email signature and resume:
- `YOUR_NAME`: Your full name as it appears in professional communications
- `YOUR_EMAIL`: Your contact email (can be same as LinkedIn email or different)
- `YOUR_PHONE`: Your phone number (include country code if international)
- `YOUR_LINKEDIN`: Your complete LinkedIn profile URL

### Email Template Variables

Customize your email content with these templates:

**EMAIL_SUBJECT_TEMPLATE**: 
- Placeholders: `{job_title}` (auto-extracted from post), `{name}` (from YOUR_NAME)
- Example: `Application for {job_title} Position - {name}`
- If not set, uses default: `Application for QA/Testing Position - {name}`

**EMAIL_BODY_TEMPLATE**:
- Placeholders: `{name}`, `{email}`, `{phone}`, `{linkedin}` (from personal details)
- Use `\n` for new lines (keep as single line in .env)
- Example:
  ```
  EMAIL_BODY_TEMPLATE=Hi,\n\nI hope this email finds you well.\n\nI am writing to express my interest...\n\nWarm regards,\n\n{name}\n{phone}
  ```
- If not set, uses default professional email template

## 🔄 Script Workflow

```
Start
  ↓
Load .env configuration
  ↓
Initialize Chrome browser
  ↓
Login to LinkedIn (or use saved cookies)
  ↓
For each SEARCH_QUERY:
  ├─ Search LinkedIn
  ├─ Apply date filter
  ├─ Scroll and load posts
  ├─ Click "Load more" buttons
  ├─ Extract emails from posts
  └─ Send emails (if not scrape-only)
  ↓
Save results to files
  ↓
End
```

## 📞 Support

For issues or questions:
1. Check `linkedin_scraper.log` for detailed error messages
2. Review this README for common solutions
3. Ensure all prerequisites are met
4. Verify `.env` configuration is correct

## 📄 License

This project is for personal use only. Use responsibly and in accordance with LinkedIn's Terms of Service.

---

**Happy Job Hunting! 🚀**

