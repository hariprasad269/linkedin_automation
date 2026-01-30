import os
import re
import sys
import shutil
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv
import PyPDF2
import io

# Fix Windows console encoding for emoji
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Load environment variables
load_dotenv()

# Gmail Safety Settings (configurable via .env)
# These settings help prevent Gmail from blocking your account
DELAY_BETWEEN_EMAILS = int(os.getenv('DELAY_BETWEEN_EMAILS', 5))  # seconds between emails (default: 5)
MAX_EMAILS_PER_HOUR = int(os.getenv('MAX_EMAILS_PER_HOUR', 50))  # Gmail limit is ~100/hour (default: 50 for safety)
MAX_EMAILS_PER_DAY = int(os.getenv('MAX_EMAILS_PER_DAY', 500))  # Gmail limit is ~500/day (default: 500)
BATCH_SIZE = int(os.getenv('BATCH_SIZE', 10))  # emails per batch before break (default: 10)
BATCH_DELAY = int(os.getenv('BATCH_DELAY', 60))  # seconds delay after each batch (default: 60)
MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))  # retry attempts for failed sends (default: 3)
RETRY_DELAY = int(os.getenv('RETRY_DELAY', 30))  # seconds before retry (default: 30)

def extract_emails_from_text(text):
    """Extract email addresses from text using regex"""
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = re.findall(email_pattern, text)
    return list(set(emails))  # Remove duplicates

def extract_emails_from_pdf(file_path):
    """Extract email addresses from PDF file"""
    emails = []
    try:
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text()
            emails = extract_emails_from_text(text)
    except Exception as e:
        print(f"  ⚠️  Error reading PDF {file_path}: {e}")
    return emails

def extract_emails_from_file(file_path):
    """Extract emails from any file type"""
    file_ext = os.path.splitext(file_path)[1].lower()
    emails = []
    
    if file_ext == '.pdf':
        emails = extract_emails_from_pdf(file_path)
    else:
        # Try to read as text file
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
                emails = extract_emails_from_text(text)
        except Exception as e:
            print(f"  ⚠️  Error reading file {file_path}: {e}")
    
    return emails

def load_sent_emails():
    """Load list of already sent emails from sent_emails.txt"""
    print("📋 Loading sent_emails.txt...")
    sent_emails = set()
    if os.path.exists('sent_emails.txt'):
        with open('sent_emails.txt', 'r', encoding='utf-8') as f:
            sent_emails = set(line.strip().lower() for line in f if line.strip())
        print(f"   ✅ Loaded {len(sent_emails)} email(s) from sent_emails.txt")
    else:
        print("   ℹ️  sent_emails.txt not found (will be created)")
    return sent_emails

def save_sent_email(email):
    """Append email to sent_emails.txt"""
    print(f"   💾 Saving {email} to sent_emails.txt...")
    with open('sent_emails.txt', 'a', encoding='utf-8') as f:
        f.write(f"{email.lower()}\n")
    print(f"   ✅ Saved {email} to sent_emails.txt")

def is_gmail_rate_limit_error(error):
    """Check if error is a Gmail rate limit/quota error"""
    error_str = str(error).lower()
    rate_limit_keywords = [
        'quota', 'rate limit', 'too many', 'exceeded', 
        'temporarily blocked', 'suspension', '550', '421',
        'daily sending limit', 'hourly sending limit'
    ]
    return any(keyword in error_str for keyword in rate_limit_keywords)

def send_email_with_resume(to_email, resume_path, sent_emails, retry_count=0):
    """Send email with resume attachment (with retry logic)"""
    print(f"   🔍 Checking if {to_email} is in sent_emails.txt...")
    email_lower = to_email.lower()
    
    if email_lower in sent_emails:
        print(f"   ⚠️  {to_email} is already in sent_emails.txt - SKIPPING")
        return False
    
    print(f"   ✅ {to_email} is NOT in sent_emails.txt - Proceeding to send...")
    
    if retry_count > 0:
        print(f"   🔄 Retry attempt {retry_count}/{MAX_RETRIES} for {to_email}")
    
    try:
        print(f"   📧 Preparing email for {to_email}...")
        gmail_email = os.getenv('GMAIL_EMAIL')
        gmail_password = os.getenv('GMAIL_PASSWORD')
        your_name = os.getenv('YOUR_NAME')
        your_email = os.getenv('YOUR_EMAIL')
        your_phone = os.getenv('YOUR_PHONE')
        your_linkedin = os.getenv('YOUR_LINKEDIN')
        
        print(f"   🔐 Loading Gmail credentials from .env...")
        if not gmail_email or not gmail_password:
            print("   ❌ GMAIL_EMAIL or GMAIL_PASSWORD not found in .env")
            return False
        print(f"   ✅ Gmail credentials loaded (From: {gmail_email})")
        
        # Get email templates from .env
        print(f"   📝 Loading email templates from .env...")
        email_subject_template = os.getenv('EMAIL_SUBJECT_TEMPLATE', 
            f"Application for QA/Testing Position - {your_name}")
        email_body_template = os.getenv('EMAIL_BODY_TEMPLATE', 
            f"""Dear Hiring Manager,

I hope this email finds you well. I am reaching out to express my interest in QA/Testing opportunities at your organization.

I am {your_name}, a QA professional with 3 years of experience in manual and automation testing. I have expertise in:
- Manual Testing (Functional, Regression, Sanity, Smoke Testing)
- Automation Testing (Selenium with Python)
- Test Case Design and Execution
- Bug Tracking and Reporting (JIRA)
- API Testing

I am actively seeking new opportunities and would love to discuss how my skills can contribute to your team.

Please find my resume attached.

Best regards,
{your_name}
Email: {your_email}
Phone: {your_phone}
LinkedIn: {your_linkedin}""")
        print(f"   ✅ Email templates loaded")
        
        # Format subject (handle placeholders)
        print(f"   🔧 Formatting email subject...")
        subject = email_subject_template
        if '{name}' in subject:
            subject = subject.replace('{name}', your_name or '')
        if '{job_title}' in subject:
            subject = subject.replace('{job_title}', 'QA/Testing')
        print(f"   ✅ Subject: {subject}")
        
        # Format body (handle placeholders and newlines)
        print(f"   🔧 Formatting email body...")
        body = email_body_template
        if '{name}' in body:
            body = body.replace('{name}', your_name or '')
        if '{email}' in body:
            body = body.replace('{email}', your_email or '')
        if '{phone}' in body:
            body = body.replace('{phone}', your_phone or '')
        if '{linkedin}' in body:
            body = body.replace('{linkedin}', your_linkedin or '')
        body = body.replace('\\n', '\n')
        print(f"   ✅ Body formatted ({len(body)} characters)")
        
        # Create email
        print(f"   📨 Creating email message...")
        msg = MIMEMultipart()
        msg['From'] = gmail_email
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        print(f"   ✅ Email message created")
        
        # Attach resume
        print(f"   📎 Attaching resume: {resume_path}...")
        if os.path.exists(resume_path):
            with open(resume_path, 'rb') as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {os.path.basename(resume_path)}'
                )
                msg.attach(part)
            print(f"   ✅ Resume attached: {os.path.basename(resume_path)}")
        else:
            print(f"   ⚠️  Resume file not found: {resume_path}")
        
        # Send email
        print(f"   📤 Connecting to SMTP server (smtp.gmail.com:587)...")
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=30) as server:
            print(f"   🔐 Starting TLS...")
            server.starttls()
            print(f"   🔑 Logging in to Gmail...")
            server.login(gmail_email, gmail_password)
            print(f"   ✅ Logged in successfully")
            print(f"   📮 Sending email to {to_email}...")
            server.send_message(msg)
        
        print(f"   ✅ Email sent successfully to: {to_email}")
        save_sent_email(to_email)
        return True
        
    except smtplib.SMTPRecipientsRefused as e:
        print(f"   ❌ Recipient refused: {to_email} - {e}")
        return False
    except smtplib.SMTPSenderRefused as e:
        print(f"   ❌ Sender refused (check Gmail settings): {e}")
        return False
    except smtplib.SMTPDataError as e:
        error_msg = str(e)
        if is_gmail_rate_limit_error(e):
            print(f"   ⚠️  GMAIL RATE LIMIT ERROR: {error_msg}")
            print(f"   ⏸️  Gmail has temporarily blocked sending. Please wait before retrying.")
            return 'RATE_LIMIT'
        print(f"   ❌ SMTP data error: {error_msg}")
        return False
    except smtplib.SMTPException as e:
        error_msg = str(e)
        if is_gmail_rate_limit_error(e):
            print(f"   ⚠️  GMAIL RATE LIMIT ERROR: {error_msg}")
            print(f"   ⏸️  Gmail has temporarily blocked sending. Please wait before retrying.")
            return 'RATE_LIMIT'
        print(f"   ❌ SMTP error: {error_msg}")
        # Retry on transient errors
        if retry_count < MAX_RETRIES:
            print(f"   ⏳ Waiting {RETRY_DELAY} seconds before retry...")
            time.sleep(RETRY_DELAY)
            return send_email_with_resume(to_email, resume_path, sent_emails, retry_count + 1)
        return False
    except Exception as e:
        error_msg = str(e)
        if is_gmail_rate_limit_error(e):
            print(f"   ⚠️  GMAIL RATE LIMIT ERROR: {error_msg}")
            print(f"   ⏸️  Gmail has temporarily blocked sending. Please wait before retrying.")
            return 'RATE_LIMIT'
        print(f"   ❌ Failed to send email to {to_email}: {error_msg}")
        # Retry on network errors
        if retry_count < MAX_RETRIES and ('timeout' in error_msg.lower() or 'connection' in error_msg.lower()):
            print(f"   ⏳ Waiting {RETRY_DELAY} seconds before retry...")
            time.sleep(RETRY_DELAY)
            return send_email_with_resume(to_email, resume_path, sent_emails, retry_count + 1)
        return False

def move_file_to_sent_folder(file_path, emails_folder):
    """Move file from Emails folder to sentemilspdf folder"""
    try:
        file_name = os.path.basename(file_path)
        parent_dir = os.path.dirname(os.path.abspath(emails_folder))
        sent_folder = os.path.join(parent_dir, 'sentemilspdf')
        
        # Create sentemilspdf folder if it doesn't exist
        os.makedirs(sent_folder, exist_ok=True)
        
        dest_path = os.path.join(sent_folder, file_name)
        
        # Handle duplicate filenames
        if os.path.exists(dest_path):
            base, ext = os.path.splitext(file_name)
            counter = 1
            while os.path.exists(dest_path):
                new_name = f"{base}_{counter}{ext}"
                dest_path = os.path.join(sent_folder, new_name)
                counter += 1
        
        shutil.move(file_path, dest_path)
        print(f"  ✅ Moved: {file_name} → sentemilspdf/{os.path.basename(dest_path)}")
        return True
    except Exception as e:
        print(f"  ❌ Failed to move {os.path.basename(file_path)}: {e}")
        return False

def process_emails_folder(emails_folder='Emails', resume_path='G_HARI_PRASAD_QA.pdf'):
    """
    Process all files in Emails folder, extract emails, and send emails with resume
    """
    if not os.path.exists(emails_folder):
        print(f"❌ Folder '{emails_folder}' not found!")
        return
    
    if not os.path.exists(resume_path):
        print(f"❌ Resume file '{resume_path}' not found!")
        return
    
    print("=" * 60)
    print("Email Scraper & Sender")
    print("=" * 60)
    print(f"📁 Scanning folder: {emails_folder}")
    print(f"📄 Resume: {resume_path}\n")
    
    print("🔒 Gmail Safety Settings:")
    print(f"   ⏱️  Delay between emails: {DELAY_BETWEEN_EMAILS} seconds")
    print(f"   📊 Max emails per hour: {MAX_EMAILS_PER_HOUR}")
    print(f"   📅 Max emails per day: {MAX_EMAILS_PER_DAY}")
    print(f"   📦 Batch size: {BATCH_SIZE} emails")
    print(f"   ⏸️  Batch delay: {BATCH_DELAY} seconds")
    print(f"   🔄 Max retries: {MAX_RETRIES}")
    print()
    
    # Load already sent emails
    print("\n" + "=" * 60)
    print("STEP 1: Loading sent_emails.txt")
    print("=" * 60)
    sent_emails = load_sent_emails()
    print(f"📧 Total emails already sent: {len(sent_emails)}")
    if len(sent_emails) > 0:
        print(f"   Sample emails: {', '.join(list(sent_emails)[:5])}")
    print()
    
    # Get all files in Emails folder
    print("=" * 60)
    print("STEP 2: Scanning Emails folder")
    print("=" * 60)
    print(f"📁 Scanning folder: {emails_folder}")
    all_files = []
    for root, dirs, files in os.walk(emails_folder):
        for file in files:
            file_path = os.path.join(root, file)
            all_files.append(file_path)
    
    if not all_files:
        print("❌ No files found in Emails folder")
        return
    
    print(f"📄 Found {len(all_files)} file(s) to process")
    for idx, file_path in enumerate(all_files, 1):
        print(f"   {idx}. {os.path.basename(file_path)}")
    print()
    
    print("=" * 60)
    print("STEP 3: Extracting emails from files")
    print("=" * 60)
    all_extracted_emails = set()
    file_to_emails = {}  # Track which emails came from which file
    
    # Extract emails from all files
    for idx, file_path in enumerate(all_files, 1):
        file_name = os.path.basename(file_path)
        print(f"\n[{idx}/{len(all_files)}] Processing: {file_name}")
        print(f"   📄 Reading file: {file_path}")
        
        emails = extract_emails_from_file(file_path)
        
        if emails:
            print(f"   📧 Found {len(emails)} email(s) in this file:")
            for email in emails:
                print(f"      - {email}")
            all_extracted_emails.update(emails)
            # Track emails per file (normalize to lowercase for comparison)
            file_to_emails[file_path] = set(email.lower() for email in emails)
        else:
            print(f"   ⚠️  No emails found in this file")
            # Files with no emails will be moved immediately
            file_to_emails[file_path] = set()
    
    print(f"\n📊 Summary: Total unique emails found across all files: {len(all_extracted_emails)}")
    if all_extracted_emails:
        print(f"   Emails: {', '.join(sorted(all_extracted_emails))}")
    
    if not all_extracted_emails:
        print("\n❌ No emails to send")
        # Move files with no emails
        print(f"\n📦 Moving files with no emails to sentemilspdf folder...")
        for file_path in all_files:
            if file_path in file_to_emails and len(file_to_emails[file_path]) == 0:
                move_file_to_sent_folder(file_path, emails_folder)
        return
    
    # Send emails with rate limiting
    print("\n" + "=" * 60)
    print("STEP 4: Sending emails (with rate limiting)")
    print("=" * 60)
    print(f"📤 Processing {len(all_extracted_emails)} unique email(s)...")
    print(f"⚠️  Rate limits: {MAX_EMAILS_PER_HOUR}/hour, {MAX_EMAILS_PER_DAY}/day\n")
    
    sent_count = 0
    skipped_count = 0
    failed_count = 0
    rate_limited = False
    
    # Track sending times for rate limiting
    send_times = []
    start_time = datetime.now()
    
    emails_to_send = sorted([e for e in all_extracted_emails if e.lower() not in sent_emails])
    
    if not emails_to_send:
        print("✅ All emails already sent - nothing to do!")
    else:
        print(f"📧 Will attempt to send {len(emails_to_send)} new email(s)\n")
    
    for idx, email in enumerate(emails_to_send, 1):
        email_lower = email.lower()
        
        # Check hourly limit
        current_time = datetime.now()
        # Remove send times older than 1 hour
        send_times = [t for t in send_times if (current_time - t).total_seconds() < 3600]
        
        if len(send_times) >= MAX_EMAILS_PER_HOUR:
            wait_time = 3600 - (current_time - send_times[0]).total_seconds()
            print(f"\n⚠️  HOURLY LIMIT REACHED ({MAX_EMAILS_PER_HOUR} emails)")
            print(f"⏸️  Waiting {int(wait_time)} seconds before continuing...")
            time.sleep(wait_time)
            send_times = []  # Reset after wait
        
        # Check daily limit (approximate - based on start time)
        hours_elapsed = (current_time - start_time).total_seconds() / 3600
        if hours_elapsed < 24 and sent_count >= MAX_EMAILS_PER_DAY:
            print(f"\n⚠️  DAILY LIMIT REACHED ({MAX_EMAILS_PER_DAY} emails)")
            print(f"⏸️  Please run again tomorrow or increase MAX_EMAILS_PER_DAY in .env")
            break
        
        # Batch processing - add delay after each batch
        if idx > 1 and (idx - 1) % BATCH_SIZE == 0:
            print(f"\n📦 Batch of {BATCH_SIZE} emails completed")
            print(f"⏸️  Taking a {BATCH_DELAY} second break before next batch...")
            time.sleep(BATCH_DELAY)
        
        print(f"\n[{idx}/{len(emails_to_send)}] Processing email: {email}")
        print(f"   🔍 Checking sent_emails.txt for: {email}")
        
        if email_lower in sent_emails:
            print(f"   ⏭️  SKIPPING {email} - Already in sent_emails.txt")
            skipped_count += 1
            continue
        
        print(f"   ✅ {email} is NOT in sent_emails.txt - Will send email")
        result = send_email_with_resume(email, resume_path, sent_emails)
        
        if result == 'RATE_LIMIT':
            print(f"\n🚨 GMAIL RATE LIMIT DETECTED!")
            print(f"⏸️  Stopping email sending to prevent account blocking")
            print(f"💡 Recommendation: Wait 1-2 hours before resuming")
            rate_limited = True
            break
        elif result:
            sent_emails.add(email_lower)
            sent_count += 1
            send_times.append(current_time)
            print(f"   ✅ Successfully processed: {email}")
            
            # Add delay between emails (except for the last one)
            if idx < len(emails_to_send):
                print(f"   ⏳ Waiting {DELAY_BETWEEN_EMAILS} seconds before next email...")
                time.sleep(DELAY_BETWEEN_EMAILS)
        else:
            failed_count += 1
            print(f"   ❌ Failed to process: {email}")
            
            # Still add delay even on failure
            if idx < len(emails_to_send):
                print(f"   ⏳ Waiting {DELAY_BETWEEN_EMAILS} seconds before next email...")
                time.sleep(DELAY_BETWEEN_EMAILS)
    
    if rate_limited:
        print(f"\n⚠️  Process stopped due to Gmail rate limiting")
        print(f"   📤 Sent: {sent_count} emails before stopping")
        print(f"   ⏭️  Skipped: {skipped_count} emails")
        print(f"   ❌ Failed: {failed_count} emails")
        print(f"   📧 Remaining: {len(emails_to_send) - sent_count - skipped_count - failed_count} emails")
    
    # Reload sent_emails to include newly sent ones
    print("\n" + "=" * 60)
    print("STEP 5: Reloading sent_emails.txt")
    print("=" * 60)
    sent_emails = load_sent_emails()
    print(f"📧 Total emails in sent_emails.txt now: {len(sent_emails)}")
    print()
    
    # Move files where all emails have been sent
    print("=" * 60)
    print("STEP 6: Moving processed files to sentemilspdf folder")
    print("=" * 60)
    print(f"📦 Checking which files can be moved...\n")
    moved_count = 0
    for idx, file_path in enumerate(all_files, 1):
        file_name = os.path.basename(file_path)
        print(f"[{idx}/{len(all_files)}] Checking file: {file_name}")
        
        if file_path in file_to_emails:
            file_emails = file_to_emails[file_path]
            print(f"   📧 Emails from this file: {len(file_emails)}")
            
            if len(file_emails) == 0:
                print(f"   ✅ File has no emails - Will move to sentemilspdf folder")
                if move_file_to_sent_folder(file_path, emails_folder):
                    moved_count += 1
            else:
                # Check if all emails from this file are in sent_emails (already lowercase)
                unsent_emails = [e for e in file_emails if e not in sent_emails]
                if len(unsent_emails) == 0:
                    print(f"   ✅ All {len(file_emails)} email(s) from this file have been sent - Will move to sentemilspdf folder")
                    if move_file_to_sent_folder(file_path, emails_folder):
                        moved_count += 1
                else:
                    print(f"   ⏸️  {len(unsent_emails)} email(s) from this file not yet sent - Keeping file")
                    print(f"      Unsent emails: {', '.join(unsent_emails)}")
        print()
    
    print("=" * 60)
    print("✅ FINAL SUMMARY")
    print("=" * 60)
    print(f"   📤 Emails sent in this run: {sent_count}")
    print(f"   ⏭️  Emails skipped (already sent): {skipped_count}")
    if 'failed_count' in locals():
        print(f"   ❌ Emails failed: {failed_count}")
    print(f"   📧 Total unique emails found: {len(all_extracted_emails)}")
    print(f"   📦 Files moved to sentemilspdf folder: {moved_count}")
    print(f"   📋 Total emails in sent_emails.txt: {len(sent_emails)}")
    if rate_limited:
        print(f"   ⚠️  Process stopped due to rate limiting")
    print("=" * 60)

if __name__ == "__main__":
    # You can customize these paths
    EMAILS_FOLDER = "Emails"
    RESUME_PATH = "G_HARI_PRASAD_QA.pdf"
    
    process_emails_folder(EMAILS_FOLDER, RESUME_PATH)

