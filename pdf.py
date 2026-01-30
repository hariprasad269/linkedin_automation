import os
import io
import re
import sys
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import pickle
import PyPDF2
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Fix Windows console encoding for emoji
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Load environment variables
load_dotenv()

# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def authenticate_google_drive():
    """Authenticate and return Google Drive service"""
    creds = None
    
    # Get script directory and parent directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    
    # Look for token.pickle in script directory or parent directory
    token_file = os.path.join(script_dir, 'token.pickle')
    if not os.path.exists(token_file):
        token_file = os.path.join(parent_dir, 'token.pickle')
    
    # Token file stores user's access and refresh tokens
    if os.path.exists(token_file):
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)
    
    # If no valid credentials, let user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Look for credentials.json in script directory or parent directory
            creds_file = os.path.join(script_dir, 'credentials.json')
            if not os.path.exists(creds_file):
                creds_file = os.path.join(parent_dir, 'credentials.json')
            
            if not os.path.exists(creds_file):
                print("ERROR: credentials.json not found!")
                print(f"Please download credentials.json from Google Cloud Console")
                print(f"Expected locations: {os.path.join(script_dir, 'credentials.json')} or {os.path.join(parent_dir, 'credentials.json')}")
                sys.exit(1)
            
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save credentials for next run
        with open(token_file, 'wb') as token:
            pickle.dump(creds, token)
    
    return build('drive', 'v3', credentials=creds)

def extract_emails_from_pdf(pdf_content):
    """Extract email addresses from PDF content"""
    emails = set()
    
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
        
        # Extract text from all pages
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        
        # Find all email addresses using regex
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        found_emails = re.findall(email_pattern, text)
        emails.update(found_emails)
        
    except Exception as e:
        print(f"Error extracting emails from PDF: {e}")
    
    return list(emails)

def load_sent_emails():
    """Load list of already sent emails from sent_emails.txt"""
    sent_emails = set()
    
    # Look for sent_emails.txt in parent directory (where main script is)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    sent_file = os.path.join(parent_dir, 'sent_emails.txt')
    
    if os.path.exists(sent_file):
        with open(sent_file, 'r', encoding='utf-8') as f:
            sent_emails = set(line.strip().lower() for line in f if line.strip())
    
    return sent_emails

def save_sent_email(email):
    """Append email to sent_emails.txt"""
    # Look for sent_emails.txt in parent directory (where main script is)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    sent_file = os.path.join(parent_dir, 'sent_emails.txt')
    
    with open(sent_file, 'a', encoding='utf-8') as f:
        f.write(f"{email}\n")

def send_cold_email(to_email):
    """Send cold email using Gmail SMTP"""
    try:
        gmail_email = os.getenv('GMAIL_EMAIL')
        gmail_password = os.getenv('GMAIL_PASSWORD')
        your_name = os.getenv('YOUR_NAME')
        your_email = os.getenv('YOUR_EMAIL')
        your_phone = os.getenv('YOUR_PHONE')
        your_linkedin = os.getenv('YOUR_LINKEDIN')
        
        # Create email
        msg = MIMEMultipart()
        msg['From'] = gmail_email
        msg['To'] = to_email
        msg['Subject'] = f"Application for QA/Testing Position - {your_name}"
        
        # Email body
        body = f"""
Dear Hiring Manager,

I hope this email finds you well. I am reaching out to express my interest in QA/Testing opportunities at your organization.

I am {your_name}, a QA professional with 3 years of experience in manual and automation testing. I have expertise in:
- Manual Testing (Functional, Regression, Sanity, Smoke Testing)
- Automation Testing (Selenium with Python)
- Test Case Design and Execution
- Bug Tracking and Reporting (JIRA)
- API Testing

I am actively seeking new opportunities and would love to discuss how my skills can contribute to your team.

Please find my resume attached or available upon request.

Best regards,
{your_name}
Email: {your_email}
Phone: {your_phone}
LinkedIn: {your_linkedin}
"""
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Send email
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(gmail_email, gmail_password)
            server.send_message(msg)
        
        print(f"✅ Email sent to: {to_email}")
        save_sent_email(to_email)
        return True
        
    except Exception as e:
        print(f"❌ Failed to send email to {to_email}: {e}")
        return False

def process_google_drive_folder(folder_id):
    """
    Process all PDF files in a Google Drive folder
    Extract emails and send cold emails if not already sent
    """
    print("🔐 Authenticating with Google Drive...")
    service = authenticate_google_drive()
    
    print(f"📁 Fetching PDFs from folder: {folder_id}")
    
    # Load already sent emails
    sent_emails = load_sent_emails()
    print(f"📧 Already sent to {len(sent_emails)} emails")
    
    # Query for PDF files in the folder
    query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
    results = service.files().list(
        q=query,
        fields="files(id, name)",
        pageSize=100
    ).execute()
    
    files = results.get('files', [])
    
    if not files:
        print("❌ No PDF files found in the folder")
        return
    
    print(f"📄 Found {len(files)} PDF files")
    
    # Process each PDF
    for idx, file in enumerate(files, 1):
        file_id = file['id']
        file_name = file['name']
        
        print(f"\n[{idx}/{len(files)}] Processing: {file_name}")
        
        try:
            # Download PDF content
            request = service.files().get_media(fileId=file_id)
            pdf_content = io.BytesIO()
            downloader = MediaIoBaseDownload(pdf_content, request)
            
            done = False
            while not done:
                status, done = downloader.next_chunk()
            
            # Extract emails from PDF
            pdf_content.seek(0)
            emails = extract_emails_from_pdf(pdf_content.read())
            
            if not emails:
                print(f"  ⚠️  No emails found in {file_name}")
                continue
            
            print(f"  📧 Found {len(emails)} email(s): {', '.join(emails)}")
            
            # Send cold email to each extracted email
            for email in emails:
                email_lower = email.lower()
                
                if email_lower in sent_emails:
                    print(f"  ⏭️  Skipping {email} (already sent)")
                    continue
                
                print(f"  📤 Sending cold email to: {email}")
                if send_cold_email(email):
                    sent_emails.add(email_lower)
                
        except Exception as e:
            print(f"  ❌ Error processing {file_name}: {e}")
            continue
    
    print("\n✅ Processing complete!")

if __name__ == "__main__":
    # Get folder ID from environment variable or use default
    FOLDER_ID = os.getenv('GOOGLE_DRIVE_FOLDER_ID', None)
    
    if not FOLDER_ID or FOLDER_ID == "YOUR_GOOGLE_DRIVE_FOLDER_ID":
        print("=" * 60)
        print("Google Drive PDF Email Extractor & Cold Emailer")
        print("=" * 60)
        print("\nERROR: Google Drive Folder ID not set!")
        print("\nTo use this script:")
        print("1. Set GOOGLE_DRIVE_FOLDER_ID in your .env file")
        print("2. Get the folder ID from the folder URL:")
        print("   https://drive.google.com/drive/folders/FOLDER_ID")
        print("   (The FOLDER_ID is the part after '/folders/')")
        print("\n3. You also need credentials.json from Google Cloud Console:")
        print("   - Go to: https://console.cloud.google.com/")
        print("   - Create a project and enable Google Drive API")
        print("   - Create OAuth 2.0 credentials")
        print("   - Download credentials.json and place it in the project root")
        sys.exit(1)
    
    print("=" * 60)
    print("Google Drive PDF Email Extractor & Cold Emailer")
    print("=" * 60)
    
    process_google_drive_folder(FOLDER_ID)
