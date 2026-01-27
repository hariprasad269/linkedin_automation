"""
LinkedIn Email Scraper and Auto-Emailer

This script:
1. Logs into LinkedIn (uses saved cookies after first login)
2. Searches for "manual testing and 3 and @"
3. Filters by "Past 24 hours"
4. Expands each post and extracts email addresses
5. Sends personalized emails via SMTP with resume attachment

Gmail Setup:
- Requires Gmail App Password (not regular password)
- Generate at: https://myaccount.google.com/apppasswords
- Select "Mail" and "Other (Custom name)" -> "LinkedIn Bot"
- Use the 16-character password in gmail_password

Resume:
- Place resume.pdf in the same directory
- Or the script will auto-detect any .pdf file
"""

import time
import re
import os
import pickle
import smtplib
import logging
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import json
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from datetime import datetime
import sys

# Parse .env file to collect all SEARCH_QUERY entries and other env vars
search_queries_list = []  # Store all SEARCH_QUERY values

# Always manually parse .env to get all SEARCH_QUERY entries (dotenv only keeps last one)
if os.path.exists('.env'):
    with open('.env', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key.upper() == 'SEARCH_QUERY':
                    search_queries_list.append(value)
                else:
                    os.environ[key.upper()] = value

# Also try to load python-dotenv for other environment variables (if available)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # Already parsed manually above

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('linkedin_scraper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class LinkedInEmailScraper:
    def __init__(self, linkedin_email=None, linkedin_password=None, gmail_email=None, gmail_password=None):
        self.driver = None
        self.linkedin_email = linkedin_email
        self.linkedin_password = linkedin_password
        
        # Get Gmail credentials from environment if not provided
        self.gmail_email = gmail_email or os.environ.get('GMAIL_EMAIL', None)
        self.gmail_password = gmail_password or os.environ.get('GMAIL_PASSWORD', None)
        
        if not self.gmail_email or not self.gmail_password:
            raise ValueError("Gmail credentials not found. Please set GMAIL_EMAIL and GMAIL_PASSWORD in .env file")
        
        self.cookies_file = "linkedin_cookies.pkl"
        self.setup_driver()
        self.email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        self.posts_data = []
        self.resume_path = "resume.pdf"  # Default resume path
        self.resume_dir = "resumes"  # Directory for generated resumes
        os.makedirs(self.resume_dir, exist_ok=True)
        
        # Personal details - read from environment variables
        self.name = os.environ.get('YOUR_NAME', 'Your Name')
        self.email = os.environ.get('YOUR_EMAIL', '')
        self.phone = os.environ.get('YOUR_PHONE', '')
        self.linkedin = os.environ.get('YOUR_LINKEDIN', '')
        
        # Search queries list (all SEARCH_QUERY entries from .env)
        # Example in .env: Multiple SEARCH_QUERY lines
        if search_queries_list:
            self.search_queries = search_queries_list
        else:
            # Fallback to single query from env or default
            single_query = os.getenv("SEARCH_QUERY", "manual testing AND 3 AND @ AND Bangalore")
            self.search_queries = [single_query]
        
        logger.info(f"Loaded {len(self.search_queries)} search query(ies) from .env")
        
        # Date filter type (can be overridden via .env)
        # Options: "Past 24 hours", "Past week", etc.
        # Example in .env: DATE_FILTER=Past 24 hours
        self.date_filter = os.getenv("DATE_FILTER", "Past 24 hours")
        
        # Maximum posts to process per search query (can be overridden via .env)
        # Example in .env: MAX_POSTS_TO_PROCESS=50
        try:
            self.max_posts_to_process = int(os.getenv("MAX_POSTS_TO_PROCESS", "50"))
        except ValueError:
            self.max_posts_to_process = 50
            logger.warning("Invalid MAX_POSTS_TO_PROCESS value in .env, using default: 50")
        
        # Define filter selectors for each filter type - only working ones
        # User can provide selectors for each filter in .env or we use defaults
        self.filter_selectors_map = {
            "Past 24 hours": [
                # Label elements (new LinkedIn structure) - most reliable
                "//label[contains(text(), 'Past 24 hours')]",
                "//label[normalize-space(text())='Past 24 hours']",
                "label[for*='r1j']",  # Based on the for attribute pattern
                # Legacy selectors (fallback)
                "//a[contains(@class, 'artdeco-pill') and contains(@href, 'past-24h')]",
                "//a[@href and contains(@href, 'past-24h')]"
            ],
            "Past week": [
                # Label elements (new LinkedIn structure) - most reliable
                "//label[contains(text(), 'Past week')]",
                "//label[normalize-space(text())='Past week']",
                "label[for*='r4u']",  # Based on the for attribute pattern
                # User-provided selector from .env (if set)
                os.getenv("PAST_WEEK_SELECTOR", ""),
                # Legacy selectors (fallback)
                "//a[contains(@class, 'artdeco-pill') and contains(@href, 'past-week')]",
                "//a[@href and contains(@href, 'past-week')]"
            ]
        }
        
    def setup_driver(self):
        """Setup Chrome driver with options"""
        logger.debug("Setting up Chrome driver...")
        chrome_options = Options()
        # chrome_options.add_argument('--headless')  # Uncomment for headless mode
        chrome_options.add_argument('--start-maximized')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        try:
            logger.debug("Installing ChromeDriver...")
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.wait = WebDriverWait(self.driver, 20)
            logger.info("Chrome driver setup successful")
        except Exception as e:
            logger.error(f"Error setting up Chrome driver: {e}")
            logger.error(traceback.format_exc())
            raise
        
    def navigate_to_feed_and_check_login(self):
        """Navigate to /feed first, check if login is required"""
        logger.info("Checking current page and login status...")
        print("Checking current page and login status...")
        try:
            # Check current URL first - don't reload if already on feed
            current_url = self.driver.current_url.lower()
            logger.debug(f"Current URL before navigation: {current_url}")
            
            if "feed" in current_url:
                logger.info("Already on /feed page - skipping reload")
                print("Already on /feed page - skipping reload")
                time.sleep(2)  # Just wait a bit for page to be ready
            else:
                logger.info("Navigating to LinkedIn feed...")
                print("Navigating to LinkedIn feed...")
                self.driver.get("https://www.linkedin.com/feed")
                logger.debug(f"Current URL after navigation: {self.driver.current_url}")
                time.sleep(5)  # Wait for page to load
            
            # Check if redirected to login page
            current_url = self.driver.current_url.lower()
            if "login" in current_url or "challenge" in current_url:
                logger.info("Login required - redirecting to login flow")
                print("Login required...")
                return False  # Login needed
            elif "feed" in current_url or "linkedin.com/in/" in current_url:
                logger.info("Already logged in - on feed page")
                print("Already logged in - continuing...")
                return True  # Already logged in
            else:
                logger.warning(f"Unexpected page: {current_url}")
                print(f"On unexpected page: {current_url}")
                return False  # Assume login needed
        except Exception as e:
            logger.error(f"Error navigating to feed: {e}")
            return False
    
    def login_linkedin(self):
        """Login to LinkedIn using credentials or saved cookies"""
        logger.info("Logging into LinkedIn...")
        print("Logging into LinkedIn...")
        try:
            self.driver.get("https://www.linkedin.com/login")
            logger.debug(f"Current URL: {self.driver.current_url}")
            time.sleep(3)
        except Exception as e:
            logger.error(f"Error navigating to LinkedIn login: {e}")
            raise
        
        # Try to load saved cookies first
        if os.path.exists(self.cookies_file):
            logger.debug(f"Found cookies file: {self.cookies_file}")
            try:
                cookies = pickle.load(open(self.cookies_file, "rb"))
                logger.debug(f"Loaded {len(cookies)} cookies")
                for cookie in cookies:
                    try:
                        self.driver.add_cookie(cookie)
                    except Exception as e:
                        logger.debug(f"Could not add cookie: {e}")
                self.driver.refresh()
                time.sleep(5)
                logger.debug(f"After refresh, URL: {self.driver.current_url}")
                
                # Check if login was successful
                if "feed" in self.driver.current_url or "linkedin.com/in/" in self.driver.current_url:
                    logger.info("Logged in using saved cookies")
                    print("Logged in using saved cookies")
                    return True
                else:
                    logger.warning("Cookies loaded but login may have failed")
            except Exception as e:
                logger.error(f"Error loading cookies: {e}")
                logger.error(traceback.format_exc())
        
        # If cookies don't work or don't exist, login with credentials
        if self.linkedin_email and self.linkedin_password:
            logger.info(f"Attempting login with email: {self.linkedin_email}")
            try:
                # Wait for email input field
                email_input = self.wait.until(
                    EC.presence_of_element_located((By.ID, "username"))
                )
                logger.debug("Found email input field")
                
                # Wait for password input field
                password_input = self.wait.until(
                    EC.presence_of_element_located((By.ID, "password"))
                )
                logger.debug("Found password input field")
                
                # Clear and enter email
                email_input.clear()
                email_input.send_keys(self.linkedin_email)
                logger.debug("Entered email")
                time.sleep(1)
                
                # Clear and enter password
                password_input.clear()
                password_input.send_keys(self.linkedin_password)
                logger.debug("Entered password")
                time.sleep(1)
                
                # Find and click sign in button - only working selectors
                signin_button = None
                signin_selectors = [
                    'button.btn__primary--large.from__button--floating[type="submit"][aria-label="Sign in"]',  # WORKING - confirmed in logs
                    'button[type="submit"][aria-label="Sign in"]',  # Fallback
                    'button[type="submit"]'  # Last resort
                ]
                
                for selector in signin_selectors:
                    try:
                        signin_button = self.wait.until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                        )
                        logger.debug(f"Found sign in button with selector: {selector}")
                        break
                    except TimeoutException:
                        continue
                
                if not signin_button:
                    logger.error("Could not find sign in button")
                    # Try pressing Enter as fallback
                    password_input.send_keys(Keys.RETURN)
                    logger.debug("Pressed Enter as fallback")
                else:
                    signin_button.click()
                    logger.debug("Clicked sign in button")
                
                # Wait for login to complete
                time.sleep(5)
                logger.debug(f"After login attempt, URL: {self.driver.current_url}")
                
                # Wait for redirect away from login page
                max_wait = 30
                waited = 0
                while waited < max_wait:
                    current_url = self.driver.current_url
                    if "login" not in current_url.lower():
                        break
                    time.sleep(2)
                    waited += 2
                    logger.debug(f"Waiting for login redirect... ({waited}s)")
                
                current_url = self.driver.current_url
                logger.debug(f"Final URL after login: {current_url}")
                
                # Save cookies after successful login
                if "login" not in current_url.lower() and ("feed" in current_url.lower() or "linkedin.com/in/" in current_url or "linkedin.com/search" in current_url):
                    pickle.dump(self.driver.get_cookies(), open(self.cookies_file, "wb"))
                    logger.info("Logged in successfully and saved cookies")
                    logger.info(f"After login, current URL: {current_url}")
                    print("Logged in successfully and saved cookies")
                    print(f"Current page: {current_url}")
                    return True
                else:
                    logger.warning("Login may have failed - check for captcha or 2FA")
                    print("Login may have failed - check for captcha or 2FA")
                    print(f"Current URL: {current_url}")
                    return False
            except TimeoutException as e:
                logger.error(f"Timeout waiting for login elements: {e}")
                logger.error(traceback.format_exc())
                print(f"Timeout waiting for login elements: {e}")
                return False
            except Exception as e:
                logger.error(f"Error during login: {e}")
                logger.error(traceback.format_exc())
                print(f"Error during login: {e}")
                return False
        else:
            print("No credentials provided and no saved cookies found")
            logger.warning("No credentials or cookies found - manual login required")
            print("Please login manually in the browser window...")
            print("Waiting for login to complete (checking every 5 seconds)...")
            
            # Wait for login to complete by checking URL
            max_wait = 60  # 60 seconds
            waited = 0
            while waited < max_wait:
                time.sleep(5)
                waited += 5
                current_url = self.driver.current_url
                logger.debug(f"Checking login status... URL: {current_url}, waited: {waited}s")
                
                if "login" not in current_url.lower() and ("feed" in current_url.lower() or "linkedin.com/in/" in current_url or "linkedin.com/search" in current_url):
                    logger.info("Login detected!")
                    # Save cookies after successful login
                    try:
                        pickle.dump(self.driver.get_cookies(), open(self.cookies_file, "wb"))
                        logger.info("Saved cookies for future use")
                        print("Login successful! Saved cookies for future use")
                    except Exception as e:
                        logger.error(f"Error saving cookies: {e}")
                    return True
            
            logger.warning(f"Login timeout after {max_wait} seconds")
            print(f"Login timeout - please ensure you're logged in")
            return False
    
    def search_linkedin(self, search_query):
        """Search LinkedIn with the given query"""
        logger.info(f"Searching for: {search_query}")
        print(f"Searching for: {search_query}...")
        try:
            # Always navigate to LinkedIn homepage before each new search to ensure fresh search input
            # This prevents issues with search input retaining previous query value
            current_url = self.driver.current_url.lower()
            logger.debug(f"Current URL before search: {current_url}")
            
            # Navigate to homepage to get fresh search input (unless we're already on homepage)
            if "linkedin.com" not in current_url or "login" in current_url:
                logger.info("Navigating to LinkedIn homepage...")
                self.driver.get("https://www.linkedin.com")
                logger.debug(f"Current URL after navigation: {self.driver.current_url}")
                time.sleep(5)  # Wait longer for page to load
            elif "/search/" in current_url or "/feed" in current_url:
                # If we're on search results or feed page, navigate to homepage for fresh search
                logger.info("Navigating to LinkedIn homepage for fresh search input...")
                self.driver.get("https://www.linkedin.com")
                time.sleep(3)
            else:
                logger.info("Already on LinkedIn homepage - proceeding with search")
                time.sleep(2)  # Just wait a bit
            
            # Check if we're logged in - if not, wait for manual login
            if "login" in self.driver.current_url.lower():
                logger.warning("Still on login page - waiting for manual login...")
                print("Please complete login in the browser window...")
                # Wait up to 60 seconds for login
                for i in range(12):
                    time.sleep(5)
                    self.driver.refresh()
                    if "login" not in self.driver.current_url.lower():
                        logger.info("Login detected!")
                        break
                    logger.debug(f"Still waiting for login... ({i+1}/12)")
                
                if "login" in self.driver.current_url.lower():
                    logger.error("Login timeout - still on login page")
                    return False
            
            # Wait for page to fully load
            time.sleep(3)
            
            # Try multiple selectors for search input (only working ones based on logs)
            search_selectors = [
                'input.search-global-typeahead__input[placeholder="Search"]',  # WORKING - confirmed in logs
                'input.search-global-typeahead__input',  # Fallback
                'input[aria-label="Search"]'  # Fallback
            ]
            
            search_input = None
            for selector in search_selectors:
                try:
                    logger.debug(f"Trying selector: {selector}")
                    search_input = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    logger.info(f"Found search input with selector: {selector}")
                    break
                except TimeoutException:
                    continue
            
            if not search_input:
                logger.error("Could not find search input with any selector")
                print("Search input not found - may need to login manually")
                return False
            
            # Scroll to search input if needed
            self.driver.execute_script("arguments[0].scrollIntoView(true);", search_input)
            time.sleep(1)
            
            # Click and enter search query - ensure input is completely cleared
            try:
                # First, try to clear using JavaScript (most reliable)
                self.driver.execute_script("arguments[0].value = '';", search_input)
                self.driver.execute_script("arguments[0].setAttribute('value', '');", search_input)
                
                # Click to focus
                search_input.click()
                time.sleep(0.5)
                
                # Clear input multiple ways to ensure it's empty
                search_input.clear()
                # Use Ctrl+A to select all and delete
                search_input.send_keys(Keys.CONTROL + "a")
                search_input.send_keys(Keys.DELETE)
                search_input.send_keys(Keys.BACKSPACE * 50)  # Extra backspaces to clear any remaining text
                # Clear again
                search_input.clear()
                time.sleep(0.5)
                
                # Verify input is empty before entering new query
                current_value = search_input.get_attribute('value') or ''
                if current_value:
                    logger.debug(f"Input still has value after clear: {current_value}, using JavaScript to clear...")
                    # Use JavaScript to forcefully clear
                    self.driver.execute_script("arguments[0].value = '';", search_input)
                    self.driver.execute_script("arguments[0].setAttribute('value', '');", search_input)
                    # Try clearing again
                    search_input.send_keys(Keys.CONTROL + "a")
                    search_input.send_keys(Keys.DELETE)
                    search_input.clear()
                
                # Verify it's empty one more time
                final_value = search_input.get_attribute('value') or ''
                if final_value:
                    logger.warning(f"Input still has value after all clearing attempts: {final_value}")
                    # Force clear with JavaScript one more time
                    self.driver.execute_script("arguments[0].value = '';", search_input)
                
                # Now enter the new query
                search_input.send_keys(search_query)
                logger.debug(f"Entered search query: {search_query}")
                time.sleep(2)
                search_input.send_keys(Keys.RETURN)
                print(f"Searching for: {search_query}")
                time.sleep(5)
                logger.debug(f"After search, URL: {self.driver.current_url}")
            except Exception as e:
                logger.error(f"Error interacting with search input: {e}")
                logger.error(traceback.format_exc())
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error in search_linkedin: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def check_no_results(self):
        """Check if the page shows 'No results' message"""
        try:
            # Wait a bit for page to load
            time.sleep(2)
            
            # Check for various "No results" indicators
            no_results_indicators = [
                "No results",
                "No results found",
                "We couldn't find any results",
                "Try different keywords",
                "No matching results",
                "Your search didn't match any results"
            ]
            
            page_text = self.driver.page_source.lower()
            page_text_visible = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            
            for indicator in no_results_indicators:
                if indicator.lower() in page_text or indicator.lower() in page_text_visible:
                    logger.info(f"Found 'No results' indicator: {indicator}")
                    print(f"No results found for this search query")
                    return True
            
            # Also check for specific LinkedIn "no results" elements
            try:
                no_results_elements = self.driver.find_elements(By.XPATH, 
                    "//*[contains(text(), 'No results') or contains(text(), 'no results') or contains(text(), 'No matching results')]")
                if no_results_elements:
                    for elem in no_results_elements:
                        if elem.is_displayed():
                            logger.info("Found visible 'No results' element on page")
                            print(f"No results found for this search query")
                            return True
            except:
                pass
            
            return False
        except Exception as e:
            logger.debug(f"Error checking for no results: {e}")
            return False
    
    def click_date_filter(self):
        """Click on date filter based on filter type from .env"""
        try:
            logger.info("Waiting for search results page to load before clicking filter...")
            time.sleep(5)  # Wait longer for page to load
            
            # Get filter selectors based on filter type from .env
            filter_name = self.date_filter
            filter_selectors = self.filter_selectors_map.get(filter_name, [])
            
            if not filter_selectors:
                logger.warning(f"No selectors configured for filter: {filter_name}")
                print(f"Filter '{filter_name}' not configured - continuing without filter")
                return False
            
            # Filter out empty selectors (from .env if not set)
            filter_selectors = [s for s in filter_selectors if s and s.strip()]
            
            if not filter_selectors:
                logger.warning(f"No valid selectors for filter: {filter_name}")
                print(f"No selectors found for '{filter_name}' - continuing without filter")
                return False
            
            logger.info(f"Trying to click '{filter_name}' filter with {len(filter_selectors)} selectors")
            print(f"Clicking on '{filter_name}' filter...")
            
            # First, try to find all filter elements on the page for debugging
            try:
                # Check for label elements (new structure)
                all_labels = self.driver.find_elements(By.TAG_NAME, "label")
                label_candidates = [label for label in all_labels if "24" in label.text or "past" in label.text.lower()]
                logger.debug(f"Found {len(label_candidates)} potential filter labels with '24' or 'past' in text")
                for i, label in enumerate(label_candidates[:5]):  # Log first 5
                    try:
                        logger.debug(f"  Label Candidate {i+1}: text='{label.text[:50]}', for='{label.get_attribute('for')}'")
                    except:
                        pass
                
                # Also check links (legacy structure)
                all_links = self.driver.find_elements(By.TAG_NAME, "a")
                filter_candidates = [link for link in all_links if "24" in link.text or "24h" in link.text.lower() or "past" in link.text.lower()]
                logger.debug(f"Found {len(filter_candidates)} potential filter links with '24' or 'past' in text")
                for i, link in enumerate(filter_candidates[:5]):  # Log first 5
                    try:
                        logger.debug(f"  Link Candidate {i+1}: text='{link.text[:50]}', href='{link.get_attribute('href')[:100] if link.get_attribute('href') else 'None'}'")
                    except:
                        pass
            except Exception as e:
                logger.debug(f"Could not find filter candidates for debugging: {e}")
            
            for selector_idx, selector in enumerate(filter_selectors):
                try:
                    logger.debug(f"Trying selector {selector_idx+1}/{len(filter_selectors)}: {selector[:100]}")
                    
                    # Try CSS selector first (if starts with a. or . or # or label)
                    if selector.startswith("a.") or selector.startswith(".") or selector.startswith("#") or selector.startswith("label"):
                        filter_element = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                    else:
                        # XPath selector
                        filter_element = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.XPATH, selector))
                        )
                    
                    # Check if element is visible
                    if not filter_element.is_displayed():
                        logger.debug(f"Filter element found but not visible with selector: {selector[:50]}")
                        continue
                    
                    # Scroll to element
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", filter_element)
                    time.sleep(1)
                    
                    # For label elements, try to find and click the associated input first
                    if filter_element.tag_name.lower() == "label":
                        try:
                            # Get the 'for' attribute to find the associated input
                            for_attr = filter_element.get_attribute("for")
                            if for_attr:
                                # Try to find the input/radio button associated with this label
                                try:
                                    associated_input = self.driver.find_element(By.ID, for_attr)
                                    if associated_input.is_displayed():
                                        logger.debug(f"Found associated input for label: {for_attr}")
                                        # Click the input instead of the label
                                        self.driver.execute_script("arguments[0].click();", associated_input)
                                        logger.info(f"Successfully clicked associated input for label with selector: {selector[:50]}")
                                        clicked = True
                                    else:
                                        # Input not visible, click label directly
                                        clicked = False
                                except:
                                    # No associated input found, click label directly
                                    clicked = False
                            else:
                                clicked = False
                            
                            if not clicked:
                                # Click the label directly
                                try:
                                    filter_element.click()
                                    logger.info(f"Successfully clicked label using regular click with selector: {selector[:50]}")
                                except Exception as e:
                                    logger.debug(f"Regular click failed: {e}, trying JavaScript click")
                                    self.driver.execute_script("arguments[0].click();", filter_element)
                                    logger.info(f"Successfully clicked label using JavaScript click with selector: {selector[:50]}")
                        except Exception as e:
                            logger.debug(f"Error handling label click: {e}, trying direct click")
                            try:
                                filter_element.click()
                            except:
                                self.driver.execute_script("arguments[0].click();", filter_element)
                    else:
                        # For non-label elements (links, buttons), use standard click
                        try:
                            WebDriverWait(self.driver, 3).until(EC.element_to_be_clickable(filter_element))
                        except:
                            logger.debug("Element not clickable, trying JavaScript click anyway")
                        
                        try:
                            filter_element.click()
                            logger.info(f"Successfully clicked filter using regular click with selector: {selector[:50]}")
                        except Exception as e:
                            logger.debug(f"Regular click failed: {e}, trying JavaScript click")
                            self.driver.execute_script("arguments[0].click();", filter_element)
                            logger.info(f"Successfully clicked filter using JavaScript click with selector: {selector[:50]}")
                    
                    print(f"Clicked on '{filter_name}' filter")
                    logger.info(f"Clicked {filter_name} filter successfully")
                    
                    # Wait for page to load after clicking filter
                    logger.info("Waiting for page to load after filter click...")
                    print("Waiting for page to load...")
                    time.sleep(5)  # Initial wait
                    
                    # Wait for page load indicator or content to update
                    try:
                        WebDriverWait(self.driver, 15).until(
                            lambda d: d.execute_script("return document.readyState") == "complete"
                        )
                        # Additional wait for LinkedIn content to load
                        time.sleep(5)  # Increased wait for search results to load
                        
                        # Wait for search results to appear (check for any result containers including new structure)
                        try:
                            WebDriverWait(self.driver, 15).until(
                                lambda d: len(d.find_elements(By.CSS_SELECTOR, "div[data-view-name='feed-full-update'], div[data-chameleon-result-urn], li.reusable-search__result-container, div.fie-impression-container, div[data-urn*='urn:li:activity']")) > 0
                            )
                            logger.info("Search results/posts detected after filter click")
                            time.sleep(3)  # Additional wait for posts to fully render
                        except:
                            logger.warning("No search results detected yet, but continuing...")
                            time.sleep(5)  # Wait anyway
                        
                        logger.info("Page loaded successfully after filter click")
                        print("Page loaded, continuing...")
                    except:
                        logger.warning("Timeout waiting for page load, continuing anyway")
                        time.sleep(5)  # Increased wait
                    
                    return True
                except (TimeoutException, NoSuchElementException) as e:
                    logger.debug(f"Selector {selector_idx+1} failed: {e}")
                    continue
                except Exception as e:
                    logger.debug(f"Unexpected error with selector {selector_idx+1}: {e}")
                    continue
            
            print(f"'{filter_name}' filter not found - continuing without filter")
            logger.warning(f"Could not find {filter_name} filter with any of {len(filter_selectors)} selectors, continuing anyway")
            return False
        except Exception as e:
            logger.error(f"Error clicking filter: {e}")
            logger.error(traceback.format_exc())
            print("Error finding filter - continuing anyway")
            return False
    
    def extract_email(self, text):
        """Extract first valid email from text (for backward compatibility)"""
        emails = self.extract_all_emails(text)
        return emails[0] if emails else None
    
    def extract_all_emails(self, text):
        """Extract all valid emails from text"""
        logger.debug(f"Extracting all emails from text (length: {len(text) if text else 0})")
        if not text:
            logger.debug("No text provided for email extraction")
            return []
            
        # First try direct extraction
        emails = self.email_pattern.findall(text)
        logger.debug(f"Found {len(emails)} potential emails: {emails}")
        
        if emails:
            # Filter out common false positives
            valid_emails = [e for e in emails if not any(x in e.lower() for x in ['example.com', 'test.com', 'domain.com', 'email.com'])]
            if valid_emails:
                # Remove duplicates while preserving order
                seen = set()
                unique_emails = []
                for email in valid_emails:
                    email_lower = email.lower()
                    if email_lower not in seen:
                        seen.add(email_lower)
                        unique_emails.append(email)
                logger.info(f"Extracted {len(unique_emails)} valid emails: {unique_emails}")
                return unique_emails
            # If no valid emails after filtering, use all found emails (remove duplicates)
            seen = set()
            unique_emails = []
            for email in emails:
                email_lower = email.lower()
                if email_lower not in seen:
                    seen.add(email_lower)
                    unique_emails.append(email)
            logger.debug(f"Using {len(unique_emails)} emails found: {unique_emails}")
            return unique_emails
        
        # Try to clean common email obfuscation patterns
        cleaned = text
        
        # Replace common obfuscations
        replacements = [
            (r'\s+@\s+', '@'),
            (r'\s+at\s+', '@'),
            (r'\s+\[at\]\s+', '@'),
            (r'\s+\(at\)\s+', '@'),
            (r'\s+\[dot\]\s+', '.'),
            (r'\s+\(dot\)\s+', '.'),
            (r'\s+\.\s+', '.'),
            (r'\[at\]', '@'),
            (r'\(at\)', '@'),
            (r'\[dot\]', '.'),
            (r'\(dot\)', '.'),
        ]
        
        for pattern, replacement in replacements:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        
        # Try extraction again
        emails = self.email_pattern.findall(cleaned)
        if emails:
            valid_emails = [e for e in emails if not any(x in e.lower() for x in ['example.com', 'test.com', 'domain.com', 'email.com'])]
            if valid_emails:
                # Remove duplicates
                seen = set()
                unique_emails = []
                for email in valid_emails:
                    email_lower = email.lower()
                    if email_lower not in seen:
                        seen.add(email_lower)
                        unique_emails.append(email)
                return unique_emails
            # Remove duplicates
            seen = set()
            unique_emails = []
            for email in emails:
                email_lower = email.lower()
                if email_lower not in seen:
                    seen.add(email_lower)
                    unique_emails.append(email)
            return unique_emails
        
        return []
    
    def expand_post(self, post_element):
        """Click on ...more button to expand post content"""
        try:
            # Try multiple selectors for "more" button - only working ones
            more_selectors = [
                ".//span[contains(text(), 'more')]",  # WORKING - confirmed in logs
                ".//button[.//span[contains(text(), 'more')]]",  # Fallback
                ".//button[contains(@aria-label, 'more')]"  # Last resort
            ]
            
            for selector in more_selectors:
                try:
                    more_button = post_element.find_element(By.XPATH, selector)
                    if more_button.is_displayed():
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", more_button)
                        time.sleep(0.5)
                        # Try clicking the button/span directly
                        try:
                            more_button.click()
                        except:
                            # If direct click fails, try JavaScript click
                            self.driver.execute_script("arguments[0].click();", more_button)
                        logger.debug("Clicked 'more' button to expand post")
                        time.sleep(2)
                        return True
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.debug(f"Error with selector {selector}: {e}")
                    continue
        except Exception as e:
            logger.debug(f"Error expanding post: {e}")
        return False
    
    def get_post_content(self, post_element):
        """Extract full text content from post"""
        try:
            # Try multiple selectors for post content - only working ones
            content_selectors = [
                ".update-components-text",
                ".feed-shared-inline-show-more-text",
                ".feed-shared-text-view",
                "[data-test-id='post-text']"
            ]
            
            for selector in content_selectors:
                try:
                    content_elem = post_element.find_element(By.CSS_SELECTOR, selector)
                    text = content_elem.text
                    if text and len(text.strip()) > 10:
                        logger.debug(f"Extracted content using selector: {selector}, length: {len(text)}")
                        return text.strip()
                except NoSuchElementException:
                    continue
            
            # Fallback: try to get all text from post element
            try:
                all_text = post_element.text
                if all_text and len(all_text.strip()) > 10:
                    logger.debug(f"Extracted content using fallback method, length: {len(all_text)}")
                    return all_text.strip()
            except:
                pass
            
            logger.debug("No content found in post")
            return ""
        except Exception as e:
            logger.error(f"Error extracting post content: {e}")
            return ""
    
    def get_post_author(self, post_element):
        """Extract author name from post"""
        try:
            author_elem = post_element.find_element(
                By.CSS_SELECTOR, 
                ".update-components-actor__title .hoverable-link-text"
            )
            return author_elem.text.strip()
        except NoSuchElementException:
            return "Unknown"
    
    def is_post_liked(self, post_element):
        """Check if post is already liked"""
        try:
            # Check for liked state indicators - check for "Reaction button state: reacted" or similar
            like_selectors = [
                "button[aria-label*='Reaction button state: reacted']",
                "button[aria-label*='Reaction button state: like']",
                "button[aria-pressed='true'][aria-label*='Like']",
                "button[aria-pressed='true'][aria-label*='React']",
                ".reactions-react-button button[aria-pressed='true']",
                "button.react-button__trigger[aria-pressed='true']",
                "button[data-view-name='reaction-button'][aria-label*='reacted']"
            ]
            
            for selector in like_selectors:
                try:
                    like_button = post_element.find_element(By.CSS_SELECTOR, selector)
                    if like_button.is_displayed():
                        logger.debug("Post is already liked")
                        return True
                except NoSuchElementException:
                    continue
            
            # Also check for filled/liked icon
            try:
                liked_icon = post_element.find_element(By.CSS_SELECTOR, "img[data-test-reactions-icon-type='LIKE'][alt='like']")
                # If we find the icon, check if it's the filled version (liked) or outline (not liked)
                # This is a fallback check
                return False  # Default to not liked if we can't determine
            except NoSuchElementException:
                pass
            
            return False
        except Exception as e:
            logger.debug(f"Error checking if post is liked: {e}")
            return False
    
    def click_like_button(self, post_element):
        """Click the like button on a post"""
        try:
            # First check if already liked
            if self.is_post_liked(post_element):
                logger.info("Post is already liked, skipping like action")
                print("Post already liked")
                return True
            
            # Try multiple selectors for like button - only working ones
            # Based on: <button data-view-name="reaction-button" aria-label="Reaction button state: no reaction">
            like_selectors = [
                # Primary selectors based on the actual HTML structure
                "button[data-view-name='reaction-button'][aria-label*='no reaction']",
                "button[data-view-name='reaction-button']",
                "button[aria-label*='Reaction button state: no reaction']",
                # Legacy selectors (fallback)
                "button[aria-pressed='false'][aria-label*='Like']",
                "button[aria-label*='Like']"
            ]
            
            # Also try finding via SVG with id="thumbs-up-outline-small" (find parent button)
            try:
                svg_element = post_element.find_element(By.CSS_SELECTOR, "svg#thumbs-up-outline-small")
                like_button_via_svg = svg_element.find_element(By.XPATH, "./ancestor::button[1]")
                if like_button_via_svg:
                    logger.debug("Found like button via SVG parent")
                    # Check if already liked
                    aria_label = like_button_via_svg.get_attribute('aria-label') or ''
                    if 'reacted' not in aria_label.lower() and 'no reaction' in aria_label.lower():
                        if like_button_via_svg.is_displayed() and like_button_via_svg.is_enabled():
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", like_button_via_svg)
                            time.sleep(0.3)
                            try:
                                self.driver.execute_script("arguments[0].click();", like_button_via_svg)
                                logger.info("Clicked like button successfully (via SVG)")
                                print("Liked the post")
                                time.sleep(0.5)
                                return True
                            except:
                                like_button_via_svg.click()
                                logger.info("Clicked like button successfully (via SVG, regular click)")
                                print("Liked the post")
                                time.sleep(0.5)
                                return True
            except NoSuchElementException:
                pass
            except Exception as e:
                logger.debug(f"Error finding like button via SVG: {e}")
            
            for selector in like_selectors:
                try:
                    # Try to find within post element first
                    like_button = post_element.find_element(By.CSS_SELECTOR, selector)
                    
                    # Double check it's not already liked
                    aria_label = like_button.get_attribute('aria-label') or ''
                    if 'reacted' in aria_label.lower() or 'like' in aria_label.lower() and 'no reaction' not in aria_label.lower():
                        logger.debug("Button shows as already liked")
                        return True
                    
                    if like_button.get_attribute('aria-pressed') == 'true':
                        logger.debug("Button shows as already liked (aria-pressed=true)")
                        return True
                    
                    # Check if button contains "Like" text and is not reacted
                    try:
                        button_text = like_button.text.lower()
                        if 'like' in button_text and ('reacted' not in aria_label.lower() and 'no reaction' in aria_label.lower()):
                            logger.debug(f"Found like button with text: {button_text}")
                    except:
                        pass
                    
                    if like_button.is_displayed() and like_button.is_enabled():
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", like_button)
                        time.sleep(0.3)  # Small wait for scroll
                        # Try JavaScript click first (more reliable)
                        try:
                            self.driver.execute_script("arguments[0].click();", like_button)
                            logger.info("Clicked like button successfully (JavaScript click)")
                            print("Liked the post")
                            time.sleep(0.5)  # Wait for like to register
                            return True
                        except:
                            # Fallback to regular click
                            try:
                                like_button.click()
                                logger.info("Clicked like button successfully (regular click)")
                                print("Liked the post")
                                time.sleep(0.5)  # Wait for like to register
                                return True
                            except Exception as e:
                                logger.debug(f"Both click methods failed: {e}")
                                continue
                except NoSuchElementException:
                    continue
                except Exception as e:
                    logger.debug(f"Error with selector {selector}: {e}")
                    continue
            
            logger.debug("Like button not found in post element")
            return False
        except Exception as e:
            logger.error(f"Error clicking like button: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def _is_browser_connection_error(self, error):
        """Check if error is a browser connection error that should trigger moving to next query"""
        error_str = str(error).lower()
        return any(keyword in error_str for keyword in [
            'connection', 'refused', 'maxretry', 'timeout', 'no such window', 
            'session', 'target machine actively refused', 'winerror 10061'
        ])
    
    def _wait_for_posts_to_load(self, current_post_count, max_wait_seconds=10):
        """
        Wait for new posts to load after scrolling.
        Returns True if new posts loaded, False if timeout or no new posts.
        """
        logger.debug(f"Waiting for posts to load (current count: {current_post_count})...")
        start_time = time.time()
        last_post_count = current_post_count
        
        while time.time() - start_time < max_wait_seconds:
            try:
                # Check for posts using the same selectors as main loop
                post_selectors = [
                    "div[data-view-name='feed-full-update']",
                    "div[role='list'] > div[data-view-name='feed-full-update']",
                    "li.reusable-search__result-container",
                    "div[data-chameleon-result-urn]",
                    "div.fie-impression-container",
                    "div[data-urn*='urn:li:activity']"
                ]
                
                current_posts = []
                for selector in post_selectors:
                    try:
                        found_posts = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if found_posts:
                            # Filter valid posts
                            for p in found_posts:
                                try:
                                    if p.is_displayed() or len(p.text.strip()) > 0:
                                        current_posts.append(p)
                                except:
                                    pass
                            if current_posts:
                                break
                    except:
                        continue
                
                current_count = len(current_posts)
                
                # Check if posts are still loading (count is increasing)
                if current_count > last_post_count:
                    logger.debug(f"Posts loading... count increased from {last_post_count} to {current_count}")
                    last_post_count = current_count
                    time.sleep(1)  # Wait a bit more for content to fully render
                    continue
                
                # Check if posts have finished loading (count stable for 2 seconds)
                if current_count > current_post_count:
                    # Wait a bit more to ensure content is fully rendered
                    time.sleep(2)
                    # Verify posts are still there and have content
                    final_posts = []
                    for selector in post_selectors:
                        try:
                            found_posts = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            if found_posts:
                                for p in found_posts:
                                    try:
                                        if p.is_displayed() or len(p.text.strip()) > 0:
                                            final_posts.append(p)
                                    except:
                                        pass
                                if final_posts:
                                    break
                        except:
                            continue
                    
                    if len(final_posts) > current_post_count:
                        logger.debug(f"Posts fully loaded! Count: {current_post_count} -> {len(final_posts)}")
                        return True
                
                # Check if page is still loading (scroll height changing)
                scroll_height = self.driver.execute_script("return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);")
                time.sleep(0.5)  # Small delay
                new_scroll_height = self.driver.execute_script("return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);")
                
                if new_scroll_height > scroll_height:
                    logger.debug("Page height still increasing - content loading...")
                    time.sleep(1)
                    continue
                
                # If count hasn't changed and page height is stable, posts are loaded
                if current_count == last_post_count:
                    time.sleep(1)  # One more check
                    if current_count > current_post_count:
                        logger.debug(f"Posts loaded! Count: {current_post_count} -> {current_count}")
                        return True
                    elif current_count == current_post_count:
                        # No new posts loaded
                        logger.debug(f"No new posts loaded (still {current_count})")
                        return False
                
            except Exception as e:
                if self._is_browser_connection_error(e):
                    raise
                logger.debug(f"Error checking post load status: {e}")
                time.sleep(0.5)
        
        # Timeout reached
        final_count = last_post_count
        if final_count > current_post_count:
            logger.debug(f"Timeout reached but posts loaded: {current_post_count} -> {final_count}")
            return True
        else:
            logger.debug(f"Timeout reached, no new posts loaded (still {current_post_count})")
            return False
    
    def process_posts(self, send_immediately=True):
        """
        Process posts - check if liked, find emails, send immediately if not already sent
        
        Args:
            send_immediately: If True, send emails immediately when found. If False, only save to file.
        """
        if send_immediately:
            print("Processing posts (checking liked status, finding emails, sending immediately)...")
            print(f"Maximum posts to process: {self.max_posts_to_process}")
        else:
            print("Processing posts (checking liked status, finding emails, saving to file only)...")
            print(f"Maximum posts to process: {self.max_posts_to_process}")
        logger.info(f"Starting to process posts - send_immediately={send_immediately}, max_posts={self.max_posts_to_process}")
        
        # Load already sent emails
        sent_emails_file = 'sent_emails.txt'
        sent_emails_set = set()
        if os.path.exists(sent_emails_file):
            try:
                with open(sent_emails_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            sent_emails_set.add(line.lower())
                logger.info(f"Loaded {len(sent_emails_set)} already sent emails")
                print(f"Found {len(sent_emails_set)} emails already sent (will skip)")
            except Exception as e:
                logger.warning(f"Error reading sent_emails.txt: {e}")
        
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        processed_posts = set()
        scroll_attempts = 0
        max_scroll_attempts = 200  # Increased limit for more scrolling
        max_posts_to_process = self.max_posts_to_process  # Maximum posts to process (from .env)
        posts_per_batch = 10  # Check batches of 10 posts
        posts_checked_in_batch = 0
        emails_found_in_batch = 0
        total_emails_sent = 0
        consecutive_no_new_posts = 0  # Track consecutive scroll attempts with no new posts
        max_consecutive_no_new_posts = 5  # If no new posts after 5 consecutive attempts, move to next query
        
        while scroll_attempts < max_scroll_attempts:
            try:
                # Wait a bit for page to load
                time.sleep(2)
                
                # Find all post containers - try multiple selectors (for both feed and search results)
                # Note: LinkedIn search results show posts in a different structure than feed
                post_selectors = [
                    # Search results page selectors (most specific first) - working ones
                    "div[data-view-name='feed-full-update']",  # Key selector for search results posts
                    "div[role='list'] > div[data-view-name='feed-full-update']",  # Posts in list container
                    # Alternative search result selectors
                    "li.reusable-search__result-container",
                    "div[data-chameleon-result-urn]",
                    # Feed page selectors
                    "div.fie-impression-container",
                    "div[data-urn*='urn:li:activity']"
                ]
                
                posts = []
                for selector in post_selectors:
                    try:
                        found_posts = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if found_posts:
                            # For search results, check if posts have actual content instead of just size
                            # Search results posts might have 0x0 size but still be valid
                            filtered_posts = []
                            for p in found_posts:
                                try:
                                    # Check if element has text content or is displayed
                                    is_displayed = p.is_displayed()
                                    has_text = len(p.text.strip()) > 0
                                    size = p.size
                                    # Accept if: displayed OR has text OR has reasonable size
                                    if is_displayed or has_text or (size['height'] > 50 or size['width'] > 200):
                                        filtered_posts.append(p)
                                except Exception as e:
                                    # Check if it's a browser connection error
                                    if self._is_browser_connection_error(e):
                                        logger.error(f"Browser connection error while filtering posts: {e}")
                                        print(f"\n[ERROR] Browser connection lost - moving to next SEARCH_QUERY")
                                        raise
                                    # If we can't check, include it anyway (non-critical error)
                                    filtered_posts.append(p)
                            
                            if filtered_posts:
                                posts = filtered_posts
                        logger.info(f"Found {len(posts)} posts using selector: {selector}")
                        print(f"Found {len(posts)} posts using selector: {selector}")
                        consecutive_no_new_posts = 0  # Reset counter when posts are found
                        break   
                    except Exception as e:
                        if self._is_browser_connection_error(e):
                            logger.error(f"Browser connection error during post filtering: {e}")
                            print(f"\n[ERROR] Browser connection lost - moving to next SEARCH_QUERY")
                            raise
                        logger.debug(f"Error during post filtering (non-critical): {e}")
                        continue
                
                if not posts:
                    # Debug: Log what's actually on the page
                    try:
                        current_url = self.driver.current_url
                        page_source_length = len(self.driver.page_source)
                        logger.debug(f"Current URL: {current_url}, Page source length: {page_source_length}")
                        
                        # Try to find posts with data-view-name attribute (search results structure)
                        feed_posts = self.driver.find_elements(By.CSS_SELECTOR, "div[data-view-name='feed-full-update']")
                        logger.debug(f"Found {len(feed_posts)} divs with data-view-name='feed-full-update'")
                        
                        # Try to find any divs with data attributes
                        all_divs = self.driver.find_elements(By.TAG_NAME, "div")
                        data_attr_divs = [d for d in all_divs if d.get_attribute("data-urn") or d.get_attribute("data-chameleon-result-urn")]
                        logger.debug(f"Found {len(data_attr_divs)} divs with data attributes")
                        
                        # Try to find any list items
                        all_lis = self.driver.find_elements(By.TAG_NAME, "li")
                        logger.debug(f"Found {len(all_lis)} list items on page")
                        
                        # Check for role="list" containers
                        list_containers = self.driver.find_elements(By.CSS_SELECTOR, "div[role='list']")
                        logger.debug(f"Found {len(list_containers)} divs with role='list'")
                    except Exception as e:
                        if self._is_browser_connection_error(e):
                            logger.error(f"Browser connection error during debug logging: {e}")
                            print(f"\n[ERROR] Browser connection lost - moving to next SEARCH_QUERY")
                            raise
                        logger.debug(f"Error during debug logging: {e}")
                    
                    logger.warning("No posts found with any selector")
                    
                    # On first few attempts, wait longer and scroll more
                    try:
                        if scroll_attempts < 5:
                            logger.info(f"Waiting longer and scrolling more (attempt {scroll_attempts + 1})...")
                            # Scroll multiple times to trigger lazy loading
                            for _ in range(3):
                                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                                time.sleep(2)
                        else:
                            # Scroll to load more
                            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                            time.sleep(3)
                    except Exception as scroll_error:
                        if self._is_browser_connection_error(scroll_error):
                            logger.error(f"Scrolling failed due to browser connection error: {scroll_error}")
                            print(f"\n[ERROR] Browser connection lost during scrolling - moving to next SEARCH_QUERY")
                            raise
                        else:
                            logger.debug(f"Scrolling error (non-critical): {scroll_error}")
                    
                    scroll_attempts += 1
                    continue
                
                print(f"Found {len(posts)} posts, checking for emails...")
                logger.info(f"Found {len(posts)} posts")
                
                # Check if we've already reached max posts limit before processing this batch
                if len(processed_posts) >= max_posts_to_process:
                    logger.info(f"Reached maximum limit of {max_posts_to_process} posts")
                    print(f"\nReached maximum limit of {max_posts_to_process} posts - stopping")
                    break
                
                new_posts_processed = 0
                reached_max_posts = False
                posts_before_processing = len(processed_posts)
                for post in posts:
                    try:
                        # Get unique identifier for post
                        try:
                            post_id = post.get_attribute('id') or post.get_attribute('data-urn')
                            if not post_id:
                                # Try to get some text to create hash
                                try:
                                    post_text = post.text[:50] if post.text else str(post.location)
                                    post_id = hash(post_text)
                                except Exception as e:
                                    if self._is_browser_connection_error(e):
                                        logger.error(f"Browser connection error getting post ID: {e}")
                                        print(f"\n[ERROR] Browser connection lost - moving to next SEARCH_QUERY")
                                        raise
                                    post_id = hash(str(post.location))
                        except Exception as e:
                            if self._is_browser_connection_error(e):
                                logger.error(f"Browser connection error getting post attributes: {e}")
                                print(f"\n[ERROR] Browser connection lost - moving to next SEARCH_QUERY")
                                raise
                            # Non-critical error, skip this post
                            continue
                        
                        if post_id in processed_posts:
                            continue
                        
                        # Check if we've reached max posts limit
                        if len(processed_posts) >= max_posts_to_process:
                            logger.info(f"Reached maximum limit of {max_posts_to_process} posts")
                            print(f"\nReached maximum limit of {max_posts_to_process} posts - stopping")
                            reached_max_posts = True
                            break
                        
                        processed_posts.add(post_id)
                        new_posts_processed += 1
                        posts_checked_in_batch += 1
                        
                        logger.debug(f"Processing new post: {post_id} ({len(processed_posts)}/{max_posts_to_process})")
                        
                        # Scroll to post to ensure it's visible
                        try:
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", post)
                        except Exception as e:
                            if self._is_browser_connection_error(e):
                                logger.error(f"Scrolling to post failed due to browser connection error: {e}")
                                print(f"\n[ERROR] Browser connection lost while scrolling to post - moving to next SEARCH_QUERY")
                                raise  # Re-raise to be caught by outer exception handler
                            else:
                                logger.debug(f"Error scrolling to post (non-critical): {e}")
                        
                        # STEP 1: Check if post is already liked FIRST
                        # If liked → ignore post and move to next post
                        is_already_liked = self.is_post_liked(post)
                        
                        if is_already_liked:
                            logger.info(f"Post {post_id} is already liked - ignoring post and moving to next")
                            print(f"Post already liked - ignoring and moving to next")
                            continue  # Move to next post
                        
                        # STEP 2: Post is NOT liked - proceed with processing
                        # Expand post to see full content (click "more" button)
                        expanded = self.expand_post(post)
                        if expanded:
                            logger.debug("Post expanded successfully (clicked 'more')")
                        
                        # STEP 3: Quick check if email exists in post
                        # Get post text quickly to check for emails (don't extract full content yet)
                        try:
                            post_text = post.text
                        except Exception as e:
                            if self._is_browser_connection_error(e):
                                logger.error(f"Browser connection error getting post text: {e}")
                                print(f"\n[ERROR] Browser connection lost - moving to next SEARCH_QUERY")
                                raise
                            post_text = ""
                        
                        # Quick email check using regex on post text
                        quick_email_check = self.email_pattern.findall(post_text) if post_text else []
                        
                        # If no email found, move to next post (skip reading full content)
                        if not quick_email_check:
                            logger.debug(f"No email found in post - moving to next post")
                            print(f"No email in post - moving to next")
                            continue  # Move to next post
                        
                        # STEP 4: Email found - now extract full content and process
                        author = self.get_post_author(post)
                        content = self.get_post_content(post)
                        
                        if not content or len(content.strip()) < 10:
                            # Fallback to post text if content extraction failed
                            content = post_text
                            if not content or len(content.strip()) < 10:
                                logger.debug(f"Post by {author} has no content or too short, skipping")
                                continue
                        
                        logger.debug(f"Post by {author}: Content length = {len(content)}")
                        
                        # STEP 5: Extract ALL emails from post content
                        emails = self.extract_all_emails(content)
                        
                        # STEP 6: Process emails (we know emails exist from quick check)
                        if emails:
                            emails_found_in_batch += len(emails)
                            logger.info(f"Found {len(emails)} email(s) in post by {author}: {emails}")
                            try:
                                print(f"\nFound {len(emails)} email(s)! Post by {author}: {', '.join(emails)}")
                            except UnicodeEncodeError:
                                safe_author = author.encode('ascii', 'ignore').decode()
                                safe_emails = [e.encode('ascii', 'ignore').decode() for e in emails]
                                print(f"\nFound {len(emails)} email(s)! Post by {safe_author}: {', '.join(safe_emails)}")
                            
                            # STEP 6: Like the post (after finding emails)
                            post_liked = False
                            print("  -> Liking the post...")
                            liked = self.click_like_button(post)
                            if liked:
                                post_liked = True
                                logger.info("Successfully liked the post")
                            else:
                                logger.warning("Could not like the post, continuing anyway")
                            
                            # STEP 7: Process each email found
                            for email in emails:
                                # STEP 7a: Check if email is already in sent_emails.txt
                                if email.lower() in sent_emails_set:
                                    print(f"  -> Email {email} already in sent_emails.txt - ignoring")
                                    logger.info(f"Email {email} already sent - ignoring")
                                    continue  # Ignore this email, move to next email
                                
                                # STEP 7b: Email not in sent_emails.txt - save and send
                                # Save email to file
                                self.save_email_to_file(email, author, content)
                                
                                # Send email immediately if enabled
                                if send_immediately:
                                    print(f"  -> Sending email to {email}...")
                                    try:
                                        resume_path = r"C:\Users\Hari\OneDrive\Desktop\a\l\G_HARI_PRASAD_QA.pdf"
                                        if not os.path.exists(resume_path):
                                            print(f"  [WARNING] Resume not found at {resume_path}")
                                            logger.warning(f"Resume not found: {resume_path}")
                                        
                                        # Send email with resume attachment
                                        self.send_email_smtp(author, content, email)
                                        total_emails_sent += 1
                                        logger.info(f"Successfully sent email to {email}")
                                        print(f"  [SUCCESS] Email sent successfully to {email}")
                                        
                                        # Add to sent_emails.txt
                                        self.add_to_sent_emails(sent_emails_file, email)
                                        sent_emails_set.add(email.lower())  # Add to set to avoid duplicates in same run
                                        
                                        post_data = {
                                            'author': author,
                                            'content': content[:1000],
                                            'email': email,
                                            'has_email': True,
                                            'email_sent': True,
                                            'liked': post_liked
                                        }
                                        self.posts_data.append(post_data)
                                        
                                    except smtplib.SMTPAuthenticationError as e:
                                        logger.error(f"SMTP Authentication failed: {e}")
                                        print(f"  [ERROR] Gmail authentication failed - check App Password")
                                        print("Stopping email sending due to authentication error")
                                        break
                                    except Exception as e:
                                        logger.error(f"Failed to send email to {email}: {e}")
                                        logger.error(traceback.format_exc())
                                        print(f"  [ERROR] Failed to send email to {email}: {e}")
                                        # Still save post data
                                        post_data = {
                                            'author': author,
                                            'content': content[:1000],
                                            'email': email,
                                            'has_email': True,
                                            'email_sent': False,
                                            'liked': post_liked
                                        }
                                        self.posts_data.append(post_data)
                                else:
                                    # Just save to file, don't send
                                    print(f"  -> Email {email} saved to file (scrape_only mode)")
                                    post_data = {
                                        'author': author,
                                        'content': content[:1000],
                                        'email': email,
                                        'has_email': True,
                                        'email_sent': False,
                                        'liked': post_liked
                                    }
                                    self.posts_data.append(post_data)
                        else:
                            logger.debug(f"No email found in post by {author}")
                            print(f"No email in post by {author} - skipping")
                    
                    except Exception as e:
                        if self._is_browser_connection_error(e):
                            logger.error(f"Browser connection error processing post: {e}")
                            logger.error(traceback.format_exc())
                            print(f"\n[ERROR] Browser connection lost - moving to next SEARCH_QUERY")
                            raise  # Re-raise to move to next query
                        logger.error(f"Error processing post: {e}")
                        logger.error(traceback.format_exc())
                        continue
                
                # Check if we've reached max posts limit (break outer loop)
                if reached_max_posts or len(processed_posts) >= max_posts_to_process:
                    logger.info(f"Reached maximum limit of {max_posts_to_process} posts")
                    print(f"\nReached maximum limit of {max_posts_to_process} posts - stopping")
                    break
                
                # Check if we've checked a batch of 10 posts
                if posts_checked_in_batch >= posts_per_batch:
                    print(f"\n--- Checked {posts_checked_in_batch} posts in this batch ---")
                    print(f"Emails found: {emails_found_in_batch}, Emails sent: {total_emails_sent}")
                    
                    # If no emails found in this batch, continue to next batch
                    if emails_found_in_batch == 0:
                        print("No emails found in this batch - moving to next 10 posts...")
                        logger.info(f"No emails found in batch of {posts_checked_in_batch} posts - continuing")
                    else:
                        # Reset batch counter for next batch
                        emails_found_in_batch = 0
                    
                    posts_checked_in_batch = 0
                
                # Reset consecutive_no_new_posts counter if we processed new posts
                if new_posts_processed > 0:
                    consecutive_no_new_posts = 0
                
                if new_posts_processed == 0:
                    consecutive_no_new_posts += 1
                    logger.debug(f"No new posts found in this scroll (consecutive: {consecutive_no_new_posts}/{max_consecutive_no_new_posts})")
                    
                    # If no new posts found after multiple consecutive attempts, move to next query
                    if consecutive_no_new_posts >= max_consecutive_no_new_posts:
                        logger.warning(f"No new posts found after {consecutive_no_new_posts} consecutive scroll attempts - moving to next SEARCH_QUERY")
                        print(f"\n[INFO] Scrolling stopped making progress after {consecutive_no_new_posts} attempts - moving to next SEARCH_QUERY")
                        break
                    
                    # If no new posts found after multiple attempts, try scrolling more aggressively
                    if scroll_attempts > 10 and scroll_attempts % 5 == 0:
                        logger.info("No new posts found - trying more aggressive scrolling...")
                        try:
                            # Scroll multiple times to trigger lazy loading
                            for _ in range(3):
                                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                                time.sleep(2)
                            # Also try scrolling by smaller increments
                            current_scroll = self.driver.execute_script("return window.pageYOffset;")
                            self.driver.execute_script(f"window.scrollTo(0, {current_scroll + 1000});")
                            time.sleep(2)
                        except Exception as scroll_error:
                            if self._is_browser_connection_error(scroll_error):
                                logger.error(f"Aggressive scrolling failed due to browser connection error: {scroll_error}")
                                print(f"\n[ERROR] Browser connection lost during aggressive scrolling - moving to next SEARCH_QUERY")
                                raise
                            else:
                                logger.debug(f"Aggressive scrolling error (non-critical): {scroll_error}")
                
                # Scroll down to load more posts - try multiple scrolling methods
                logger.debug("Scrolling to load more posts...")
                try:
                    # Get current scroll position and page dimensions
                    current_scroll = self.driver.execute_script("return window.pageYOffset || window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;")
                    scroll_height = self.driver.execute_script("return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, document.body.offsetHeight, document.documentElement.offsetHeight, document.body.clientHeight, document.documentElement.clientHeight);")
                    viewport_height = self.driver.execute_script("return window.innerHeight || document.documentElement.clientHeight || document.body.clientHeight;")
                    
                    logger.debug(f"Current scroll: {current_scroll}, Scroll height: {scroll_height}, Viewport: {viewport_height}")
                    
                    # Only scroll if content is taller than viewport
                    if scroll_height > viewport_height:
                        # Try multiple scrolling methods
                        scroll_methods = [
                            "window.scrollTo(0, document.body.scrollHeight);",
                            "window.scrollTo(0, document.documentElement.scrollHeight);",
                            "document.documentElement.scrollTop = document.documentElement.scrollHeight;",
                            "document.body.scrollTop = document.body.scrollHeight;",
                            f"window.scrollBy(0, {scroll_height - current_scroll});",
                            f"window.scrollTo(0, {scroll_height});"
                        ]
                        
                        for method in scroll_methods:
                            try:
                                self.driver.execute_script(method)
                                time.sleep(0.5)  # Small delay between attempts
                                # Check if scrolling worked
                                new_scroll_check = self.driver.execute_script("return window.pageYOffset || window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;")
                                if new_scroll_check > current_scroll:
                                    logger.debug(f"Scrolling successful with method: {method[:50]}...")
                                    break
                            except:
                                continue
                        
                        # Wait for posts to fully load after scrolling
                        posts_before_scroll = len(processed_posts)
                        posts_loaded = self._wait_for_posts_to_load(posts_before_scroll, max_wait_seconds=10)
                        if posts_loaded:
                            logger.debug("New posts loaded after scrolling")
                        else:
                            logger.debug("No new posts loaded after scrolling, continuing...")
                    else:
                        logger.debug(f"Page height ({scroll_height}) <= viewport ({viewport_height}) - no scrolling needed")
                except Exception as scroll_error:
                    if self._is_browser_connection_error(scroll_error):
                        logger.error(f"Scrolling failed due to browser connection error: {scroll_error}")
                        print(f"\n[ERROR] Browser connection lost during scrolling - moving to next SEARCH_QUERY")
                        logger.info("Moving to next SEARCH_QUERY due to scrolling failure")
                        raise  # Re-raise to be caught by outer exception handler
                    else:
                        logger.warning(f"Scrolling error (non-critical): {scroll_error}")
                        # Continue for non-critical errors
                
                # Check for "Load more" button and click it to load more posts
                # This is more reliable than just scrolling for LinkedIn search results
                try:
                    # Multiple selectors to find the Load more button
                    load_more_selectors = [
                        "//button[contains(., 'Load more')]",  # XPath - contains text anywhere in button
                        "//button[contains(text(), 'Load more')]",  # XPath - direct text
                        "//span[contains(text(), 'Load more')]/ancestor::button",  # XPath - find span then button
                        "button:contains('Load more')",  # CSS (if supported)
                        "//button[@type='button' and contains(., 'Load more')]",  # XPath with type
                    ]
                    
                    load_more_clicked = False
                    for selector in load_more_selectors:
                        try:
                            if selector.startswith("//"):
                                load_more_buttons = self.driver.find_elements(By.XPATH, selector)
                            else:
                                # Try CSS selector
                                try:
                                    load_more_buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                                except:
                                    continue
                            
                            for btn in load_more_buttons:
                                try:
                                    # Check if button is visible and enabled
                                    if not btn.is_displayed() or not btn.is_enabled():
                                        continue
                                    
                                    # Get button text to verify
                                    btn_text = btn.text.strip().lower()
                                    if 'load more' not in btn_text:
                                        continue
                                    
                                    logger.info("Found 'Load more' button - scrolling to it and clicking")
                                    print("[INFO] Found 'Load more' button - clicking to load more posts")
                                    
                                    # Scroll button into view
                                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", btn)
                                    time.sleep(1)
                                    
                                    # Try clicking with JavaScript if regular click fails
                                    try:
                                        btn.click()
                                    except:
                                        self.driver.execute_script("arguments[0].click();", btn)
                                    
                                    logger.info("Clicked 'Load more' button - waiting for posts to load...")
                                    print("[INFO] Waiting for new posts to load after clicking 'Load more'...")
                                    
                                    # Wait longer for posts to fully load after clicking Load more
                                    posts_before_click = len(processed_posts)
                                    time.sleep(3)  # Initial wait for loading to start
                                    
                                    # Wait for posts to load with longer timeout
                                    posts_loaded = self._wait_for_posts_to_load(posts_before_click, max_wait_seconds=15)
                                    
                                    if posts_loaded:
                                        logger.info("New posts loaded after clicking 'Load more' button")
                                        print("[INFO] New posts loaded successfully!")
                                        consecutive_no_new_posts = 0  # Reset counter
                                    else:
                                        logger.warning("No new posts detected after clicking 'Load more' button")
                                        print("[WARNING] No new posts detected - may need to scroll more")
                                    
                                    load_more_clicked = True
                                    break
                                except Exception as btn_error:
                                    if self._is_browser_connection_error(btn_error):
                                        raise
                                    logger.debug(f"Error clicking load more button: {btn_error}")
                                    continue
                            
                            if load_more_clicked:
                                break
                        except Exception as selector_error:
                            if self._is_browser_connection_error(selector_error):
                                raise
                            logger.debug(f"Error with selector {selector}: {selector_error}")
                            continue
                    
                    if not load_more_clicked:
                        logger.debug("No 'Load more' button found or clickable at this time")
                except Exception as e:
                    if self._is_browser_connection_error(e):
                        logger.error(f"Browser connection error checking for load more button: {e}")
                        raise
                    logger.debug(f"Error checking for load more button: {e}")
                
                # Check if new content loaded
                try:
                    new_height = self.driver.execute_script("return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight, document.body.offsetHeight, document.documentElement.offsetHeight);")
                    new_scroll = self.driver.execute_script("return window.pageYOffset || window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;")
                    
                    logger.debug(f"After scroll - Height: {new_height}, Scroll position: {new_scroll}, Last height: {last_height}, Current scroll: {current_scroll}")
                    
                    if new_height == last_height and new_scroll == current_scroll:
                        # Check if we're at the top (scroll position is 0 or very small)
                        if new_scroll <= 10 and new_height > 500:
                            # We're at the top but page has content - try to scroll down
                            logger.debug(f"At top of page (scroll: {new_scroll}) but height is {new_height} - forcing scroll")
                            try:
                                # Force scroll by pixels
                                self.driver.execute_script("window.scrollBy(0, 500);")
                                time.sleep(1)
                                # Try scrolling to a specific position
                                self.driver.execute_script("window.scrollTo(0, 500);")
                                # Wait for posts to load after forced scroll
                                posts_before_forced = len(processed_posts)
                                self._wait_for_posts_to_load(posts_before_forced, max_wait_seconds=5)
                            except:
                                pass
                        
                        # Check if we're actually at the bottom
                        if new_scroll + 100 >= new_height:
                            logger.info("No more posts to load - reached end")
                            print("No more posts to load - reached end of feed")
                            break
                        else:
                            # Height didn't change and we're not at bottom - increment counter
                            consecutive_no_new_posts += 1
                            logger.debug(f"Height didn't change but not at bottom (consecutive: {consecutive_no_new_posts}/{max_consecutive_no_new_posts})")
                            
                            # If scrolling stopped making progress, move to next query
                            if consecutive_no_new_posts >= max_consecutive_no_new_posts:
                                logger.warning(f"Scrolling stopped making progress after {consecutive_no_new_posts} attempts - moving to next SEARCH_QUERY")
                                print(f"\n[INFO] Scrolling stopped making progress - moving to next SEARCH_QUERY")
                                break
                            
                            # Try scrolling again with different methods
                            logger.debug("Height didn't change but not at bottom - trying alternative scrolling methods")
                            try:
                                # Try multiple scrolling methods
                                scroll_attempts_list = [
                                    "window.scrollTo(0, document.body.scrollHeight);",
                                    "window.scrollTo(0, document.documentElement.scrollHeight);",
                                    f"window.scrollBy(0, 500);",  # Scroll by 500px
                                    f"window.scrollBy(0, 1000);",  # Scroll by 1000px
                                    "document.documentElement.scrollTop = document.documentElement.scrollHeight;"
                                ]
                                
                                for scroll_cmd in scroll_attempts_list:
                                    try:
                                        self.driver.execute_script(scroll_cmd)
                                        time.sleep(1)
                                        # Check if it worked
                                        check_scroll = self.driver.execute_script("return window.pageYOffset || window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;")
                                        if check_scroll > new_scroll:
                                            logger.debug(f"Alternative scrolling method worked: {scroll_cmd[:50]}")
                                            # Wait for posts to load after successful scroll
                                            posts_before_alt = len(processed_posts)
                                            self._wait_for_posts_to_load(posts_before_alt, max_wait_seconds=5)
                                            break
                                    except:
                                        continue
                                
                                # Final wait after all scroll attempts
                                posts_before_final = len(processed_posts)
                                self._wait_for_posts_to_load(posts_before_final, max_wait_seconds=3)
                            except Exception as scroll_error:
                                if self._is_browser_connection_error(scroll_error):
                                    logger.error(f"Scrolling failed due to browser connection error: {scroll_error}")
                                    print(f"\n[ERROR] Browser connection lost during scrolling - moving to next SEARCH_QUERY")
                                    raise
                    else:
                        # Height changed or scroll position changed - reset counter
                        consecutive_no_new_posts = 0
                except Exception as scroll_error:
                    if self._is_browser_connection_error(scroll_error):
                        logger.error(f"Failed to check scroll position due to browser connection error: {scroll_error}")
                        print(f"\n[ERROR] Browser connection lost - moving to next SEARCH_QUERY")
                        raise
                    else:
                        # Non-critical error, continue
                        logger.debug(f"Non-critical error checking scroll: {scroll_error}")
                
                last_height = new_height
                
                scroll_attempts += 1
                
            except Exception as e:
                if self._is_browser_connection_error(e):
                    logger.error(f"Browser connection error in process_posts: {e}")
                    logger.error(traceback.format_exc())
                    print(f"\n[ERROR] Browser connection lost - will move to next SEARCH_QUERY")
                    raise  # Re-raise to be caught by run() method
                else:
                    logger.error(f"Error in process_posts loop: {e}")
                    logger.error(traceback.format_exc())
                    break
        
        print(f"\n=== Processing Summary ===")
        print(f"Total posts processed: {len(processed_posts)}")
        posts_with_email = sum(1 for p in self.posts_data if p['has_email'])
        emails_sent = sum(1 for p in self.posts_data if p.get('email_sent', False))
        print(f"Posts with emails found: {posts_with_email}")
        print(f"Emails sent successfully: {emails_sent}")
        logger.info(f"Processing complete. Total posts: {len(processed_posts)}, Posts with emails: {posts_with_email}, Emails sent: {emails_sent}")
    
    def extract_keywords_from_post(self, post_content):
        """Extract relevant keywords and skills from post content"""
        logger.debug(f"Extracting keywords from post (length: {len(post_content)})")
        post_lower = post_content.lower()
        keywords = {
            'manual_testing': ['manual testing', 'manual test', 'functional testing', 'regression testing'],
            'automation': ['automation', 'automated testing'],
            'api_testing': ['api testing', 'rest api', 'soap', 'api test'],
            'qa': ['qa', 'quality assurance', 'testing', 'test engineer'],
            'selenium': ['selenium'],
            'playwright': ['playwright'],
            'postman': ['postman'],
            'pytest': ['pytest', 'py-test'],
            'jira': ['jira', 'bug tracking'],
            'sql': ['sql', 'database', 'queries'],
            'agile': ['agile', 'scrum', 'sdlc'],
            'python': ['python'],
            'ecommerce': ['e-commerce', 'shopify', 'ecommerce'],
            'crm': ['crm', 'salesforce', 'zoho'],
            'ai': ['ai', 'chatbot', 'artificial intelligence']
        }
        
        found_keywords = []
        for key, terms in keywords.items():
            if any(term in post_lower for term in terms):
                found_keywords.append(key)
        
        logger.debug(f"Found keywords: {found_keywords}")
        return found_keywords
    
    def generate_resume_pdf(self, post_content, author, output_filename):
        """Generate customized resume PDF based on post content"""
        keywords = self.extract_keywords_from_post(post_content)
        
        # Create PDF
        doc = SimpleDocTemplate(output_filename, pagesize=letter)
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=20,
            textColor='#0066CC',
            spaceAfter=12,
            alignment=TA_CENTER
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor='#0066CC',
            spaceAfter=6,
            spaceBefore=12
        )
        
        # Header
        story.append(Paragraph(self.name, title_style))
        story.append(Spacer(1, 0.1*inch))
        contact_info = f"{self.email} | {self.phone} | {self.linkedin}"
        story.append(Paragraph(contact_info, styles['Normal']))
        story.append(Spacer(1, 0.2*inch))
        
        # Professional Summary
        story.append(Paragraph("PROFESSIONAL SUMMARY", heading_style))
        summary_text = """With over 3 years of experience, my background encompasses a robust skill set in Quality Assurance and various operational specializations. My core expertise lies in QA and Testing, where I have successfully performed functional, regression, and API testing across web and system applications."""
        story.append(Paragraph(summary_text, styles['Normal']))
        story.append(Spacer(1, 0.1*inch))
        
        # Technical Skills - Customized based on post
        story.append(Paragraph("TECHNICAL SKILLS", heading_style))
        
        skills_sections = []
        
        # QA & Testing Skills
        qa_skills = []
        if 'manual_testing' in keywords:
            qa_skills.append("Manual Testing (Functional, Regression, Integration)")
        if 'automation' in keywords or 'selenium' in keywords or 'playwright' in keywords:
            qa_skills.append("Automation Testing (Selenium, Playwright, Pytest)")
        if 'api_testing' in keywords or 'postman' in keywords:
            qa_skills.append("API Testing (REST/SOAP APIs, Postman)")
        if 'sql' in keywords:
            qa_skills.append("SQL & Database Testing")
        if 'jira' in keywords:
            qa_skills.append("Bug Tracking (JIRA, ADO)")
        if 'agile' in keywords:
            qa_skills.append("SDLC & Agile Methodologies")
        
        if qa_skills:
            skills_sections.append("QA & Testing: " + ", ".join(qa_skills))
        
        # Tools & Technologies
        tools = []
        if 'selenium' in keywords:
            tools.append("Selenium")
        if 'playwright' in keywords:
            tools.append("Playwright")
        if 'python' in keywords:
            tools.append("Python")
        if 'pytest' in keywords:
            tools.append("Pytest")
        if 'postman' in keywords:
            tools.append("Postman")
        if 'jira' in keywords:
            tools.append("JIRA")
        if 'sql' in keywords:
            tools.append("SQL")
        
        if tools:
            skills_sections.append("Tools & Technologies: " + ", ".join(tools))
        
        # Additional Skills
        additional = []
        if 'ecommerce' in keywords:
            additional.append("E-commerce Operations (Shopify)")
        if 'crm' in keywords:
            additional.append("CRM Management (Salesforce, Zoho Bigin)")
        if 'ai' in keywords:
            additional.append("AI-driven Testing (Chatbot Testing)")
        
        if additional:
            skills_sections.append("Additional Expertise: " + ", ".join(additional))
        
        # Default skills if no keywords matched
        if not skills_sections:
            skills_sections = [
                "QA & Testing: Manual Testing, Automation Testing (Selenium, Playwright, Pytest), API Testing (Postman)",
                "Tools & Technologies: Selenium, Playwright, Python, Pytest, Postman, JIRA, SQL",
                "Additional Expertise: E-commerce Operations (Shopify), CRM Management (Salesforce, Zoho Bigin), AI-driven Testing"
            ]
        
        for skill_section in skills_sections:
            story.append(Paragraph(skill_section, styles['Normal']))
        
        story.append(Spacer(1, 0.1*inch))
        
        # Professional Experience
        story.append(Paragraph("PROFESSIONAL EXPERIENCE", heading_style))
        
        exp_text = """
        <b>QA Engineer</b> | ContactSwing AI<br/>
        • Performed functional, regression, and API testing across web and system applications<br/>
        • Contributed to AI-driven chatbot testing initiatives<br/>
        • Utilized Selenium, Playwright, and Pytest for automation testing<br/>
        • Managed bug tracking and test case management using JIRA<br/>
        • Collaborated in Agile/Scrum environments following SDLC best practices<br/><br/>
        
        <b>Operations Specialist</b> | E-commerce & CRM<br/>
        • Managed e-commerce operations on Shopify platform<br/>
        • Administered CRM systems (Salesforce, Zoho Bigin)<br/>
        • Handled customer support systems (Zendesk administration)<br/>
        • Optimized processes and ensured seamless operations across business functions
        """
        story.append(Paragraph(exp_text, styles['Normal']))
        story.append(Spacer(1, 0.1*inch))
        
        # Education (if space allows)
        story.append(Paragraph("EDUCATION", heading_style))
        edu_text = "Bachelor's Degree in [Your Field]<br/>Relevant coursework: Software Testing, Quality Assurance, Database Management"
        story.append(Paragraph(edu_text, styles['Normal']))
        
        # Build PDF
        doc.build(story)
        print(f"Generated customized resume: {output_filename}")
        return output_filename
    
    def customize_resume_for_post(self, post_content, author):
        """Generate or select resume based on post content"""
        # Generate unique filename based on author and timestamp
        safe_author = "".join(c for c in author if c.isalnum() or c in (' ', '-', '_')).strip()[:30]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        resume_filename = os.path.join(self.resume_dir, f"resume_{safe_author}_{timestamp}.pdf")
        
        try:
            # Generate customized resume
            return self.generate_resume_pdf(post_content, author, resume_filename)
        except Exception as e:
            print(f"Error generating resume: {e}")
            # Fallback to default resume if exists
            if os.path.exists(self.resume_path):
                return self.resume_path
            # Try to find any PDF resume
            pdf_files = [f for f in os.listdir('.') if f.endswith('.pdf')]
            if pdf_files:
                return pdf_files[0]
            return None
    
    def customize_email_body(self, author, post_content):
        """Create email body from template in .env file"""
        # Get email body template from environment variable
        email_body_template = os.environ.get('EMAIL_BODY_TEMPLATE', None)
        
        if not email_body_template:
            # Fallback to default template if not set in .env
            email_body_template = """Hi,

I hope this email finds you well.

I am writing to express my strong interest in this job opportunity. With over 3 years of experience, my background encompasses a robust skill set in Quality Assurance and various operational specializations, which I believe could be highly valuable to your team.

My core expertise lies in QA and Testing, where I have successfully performed functional, regression, and API testing across web and system applications. I am proficient in both manual and automation testing using tools such as Selenium, Playwright, Pytest, Postman, and JIRA, and I have a solid understanding of SDLC and Agile methodologies.

Attached is my updated resume, which details my professional journey and accomplishments. I am confident that my technical skills, problem-solving abilities, and commitment to quality would allow me to contribute effectively to your organization's goals.

I would welcome the opportunity to discuss how my qualifications align with your needs. Please feel free to contact me at {phone} or reply to this email at your earliest convenience.

Thank you for considering my application. I look forward to hearing from you.

Warm regards,

{name}
{linkedin}
{phone}"""
            logger.warning("EMAIL_BODY_TEMPLATE not found in .env, using default template")
        else:
            # Convert \n escape sequences to actual newlines (for .env file format)
            email_body_template = email_body_template.replace('\\n', '\n')
        
        # Format the template with personal details
        email_body = email_body_template.format(
            phone=self.phone if self.phone else 'your contact number',
            name=self.name,
            linkedin=self.linkedin if self.linkedin else '',
            email=self.email if self.email else 'your email'
        )
        
        return email_body
    
    def send_email_smtp(self, author, post_content, recipient_email):
        """Send email via SMTP with customized resume attachment"""
        logger.info(f"Sending email to {recipient_email} for post by {author}")
        print(f"Sending email to {recipient_email}...")
        
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.gmail_email
            msg['To'] = recipient_email
            
            # Get email subject template from environment variable
            email_subject_template = os.environ.get('EMAIL_SUBJECT_TEMPLATE', None)
            
            if email_subject_template:
                # Use template from .env with placeholders
                # Extract job title keywords for dynamic subject
                subject_keywords = []
                if 'manual' in post_content.lower():
                    subject_keywords.append("Manual Testing")
                if 'automation' in post_content.lower():
                    subject_keywords.append("Automation")
                if 'qa' in post_content.lower():
                    subject_keywords.append("QA")
                if 'testing' in post_content.lower():
                    subject_keywords.append("Testing")
                
                # Format subject template
                job_title = '/'.join(subject_keywords) if subject_keywords else "QA/Testing"
                msg['Subject'] = email_subject_template.format(
                    job_title=job_title,
                    name=self.name
                )
            else:
                # Fallback to default subject generation
                subject_keywords = []
                if 'manual' in post_content.lower():
                    subject_keywords.append("Manual Testing")
                if 'automation' in post_content.lower():
                    subject_keywords.append("Automation")
                if 'qa' in post_content.lower():
                    subject_keywords.append("QA")
                
                if subject_keywords:
                    msg['Subject'] = f"Application for {'/'.join(subject_keywords)} Position - {self.name}"
                else:
                    msg['Subject'] = f"Application for QA/Testing Position - {self.name}"
                logger.warning("EMAIL_SUBJECT_TEMPLATE not found in .env, using default subject")
            
            # Create customized email body
            email_body = self.customize_email_body(author, post_content)
            msg.attach(MIMEText(email_body, 'plain'))
            
            # Attach fixed resume PDF
            resume_path = r"C:\Users\Hari\OneDrive\Desktop\a\l\G_HARI_PRASAD_QA.pdf"
            logger.debug(f"Using fixed resume path: {resume_path}")
            if resume_path and os.path.exists(resume_path):
                try:
                    logger.debug(f"Attaching resume: {resume_path}")
                    with open(resume_path, "rb") as attachment:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(attachment.read())
                    
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename= {os.path.basename(resume_path)}'
                    )
                    msg.attach(part)
                    logger.info(f"Customized resume attached: {resume_path}")
                    print(f"Customized resume attached: {resume_path}")
                except Exception as e:
                    logger.error(f"Error attaching resume: {e}")
                    logger.error(traceback.format_exc())
                    print(f"Error attaching resume: {e}")
            else:
                logger.warning("Resume not attached - file not found")
                print("Warning: Resume not attached - file not found")
            
            # Connect to Gmail SMTP server
            logger.debug("Connecting to Gmail SMTP server...")
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            logger.debug("Logging into Gmail...")
            server.login(self.gmail_email, self.gmail_password)
            logger.info("Gmail login successful")
            
            # Send email
            logger.debug("Sending email...")
            text = msg.as_string()
            server.sendmail(self.gmail_email, recipient_email, text)
            server.quit()
            
            logger.info(f"Email sent successfully to {recipient_email}")
            print(f"Email sent successfully to {recipient_email}")
            time.sleep(2)  # Rate limiting
            
        except smtplib.SMTPAuthenticationError:
            print(f"\nERROR: SMTP Authentication failed!")
            print("Gmail requires App Password for SMTP access.")
            print("Steps to generate App Password:")
            print("1. Go to: https://myaccount.google.com/apppasswords")
            print("2. Select 'Mail' and 'Other (Custom name)'")
            print("3. Enter 'LinkedIn Bot' as name")
            print("4. Copy the 16-character password")
            print("5. Update gmail_password in the script with the App Password")
            raise
        except Exception as e:
            print(f"Error sending email to {recipient_email}: {e}")
            raise
    
    def save_email_to_file(self, email, author, content):
        """Save email and post context to emails.txt"""
        emails_file = 'emails.txt'
        try:
            # Check if email already exists in file
            existing_emails = set()
            if os.path.exists(emails_file):
                with open(emails_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('EMAIL:'):
                            existing_email = line.split('EMAIL:')[1].strip()
                            existing_emails.add(existing_email)
            
            # Only add if not already present
            if email not in existing_emails:
                with open(emails_file, 'a', encoding='utf-8') as f:
                    f.write(f"EMAIL: {email}\n")
                    f.write(f"AUTHOR: {author}\n")
                    f.write(f"CONTENT: {content[:500]}\n")  # First 500 chars
                    f.write("-" * 80 + "\n")
                logger.info(f"Saved email {email} to {emails_file}")
                print(f"Saved email: {email} (from {author})")
            else:
                logger.debug(f"Email {email} already exists in {emails_file}, skipping")
        except Exception as e:
            logger.error(f"Error saving email to file: {e}")
    
    def send_emails_from_file(self, emails_file='emails.txt'):
        """Read emails from file and send personalized emails"""
        if not os.path.exists(emails_file):
            logger.warning(f"Emails file {emails_file} not found")
            print(f"No emails file found: {emails_file}")
            return
        
        emails_data = []
        current_email = {}
        
        try:
            with open(emails_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    if line.startswith('EMAIL:'):
                        if current_email:
                            emails_data.append(current_email)
                        current_email = {'email': line.split('EMAIL:')[1].strip()}
                        i += 1
                    elif line.startswith('AUTHOR:'):
                        if current_email:
                            # AUTHOR line might have author name repeated, take first occurrence
                            author_line = line.split('AUTHOR:')[1].strip()
                            # If next line is also author name (duplicate), skip it
                            if i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].strip().startswith('CONTENT:'):
                                next_line = lines[i + 1].strip()
                                if not next_line.startswith('-') and len(next_line) < 50:
                                    # Likely duplicate author name, use first one
                                    current_email['author'] = author_line.split('\n')[0].strip()
                                    i += 2  # Skip duplicate line
                                    continue
                            current_email['author'] = author_line.split('\n')[0].strip()
                        i += 1
                    elif line.startswith('CONTENT:'):
                        if current_email:
                            # CONTENT can span multiple lines until separator
                            content_parts = [line.split('CONTENT:')[1].strip()]
                            i += 1
                            # Read all lines until separator
                            while i < len(lines):
                                next_line = lines[i].strip()
                                if next_line.startswith('-') and len(next_line) > 50:
                                    break
                                if not next_line.startswith('EMAIL:') and not next_line.startswith('AUTHOR:'):
                                    content_parts.append(next_line)
                                i += 1
                            current_email['content'] = '\n'.join(content_parts)
                            continue  # Don't increment i again
                    elif line.startswith('-') and len(line) > 50:
                        if current_email:
                            emails_data.append(current_email)
                            current_email = {}
                    i += 1
            
            # Add last email if exists
            if current_email:
                emails_data.append(current_email)
            
            logger.info(f"Found {len(emails_data)} emails in {emails_file}")
            print(f"\nFound {len(emails_data)} emails to process")
            
            # Load already sent emails from sent_emails.txt
            sent_emails_file = 'sent_emails.txt'
            sent_emails_set = set()
            if os.path.exists(sent_emails_file):
                try:
                    with open(sent_emails_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                sent_emails_set.add(line.lower())
                    logger.info(f"Loaded {len(sent_emails_set)} already sent emails from {sent_emails_file}")
                    print(f"Found {len(sent_emails_set)} emails already sent (will skip)")
                except Exception as e:
                    logger.warning(f"Error reading sent_emails.txt: {e}")
            
            sent_count = 0
            failed_count = 0
            skipped_count = 0
            
            for idx, email_data in enumerate(emails_data, 1):
                email = email_data.get('email')
                author = email_data.get('author', 'Unknown')
                content = email_data.get('content', '')
                
                if not email:
                    continue
                
                # Check if email was already sent
                if email.lower() in sent_emails_set:
                    print(f"\n[{idx}/{len(emails_data)}] Skipping {email} - already sent")
                    logger.info(f"Skipping {email} - already in sent_emails.txt")
                    skipped_count += 1
                    continue
                
                print(f"\n[{idx}/{len(emails_data)}] Processing: {email}")
                print(f"Author: {author}")
                print(f"Content preview: {content[:100] if content else 'No content'}...")
                logger.info(f"Sending email to {email} (from post by {author})")
                logger.debug(f"Post content length: {len(content) if content else 0}")
                
                try:
                    # Check if fixed resume exists
                    resume_path = r"C:\Users\Hari\OneDrive\Desktop\a\l\G_HARI_PRASAD_QA.pdf"
                    if os.path.exists(resume_path):
                        print(f"Using resume: {os.path.basename(resume_path)}")
                        logger.info(f"Resume found: {resume_path}")
                    else:
                        print(f"Warning: Resume not found at {resume_path}")
                        logger.warning(f"Resume not found: {resume_path}")
                    
                    # Send email with resume attachment
                    self.send_email_smtp(author, content, email)
                    sent_count += 1
                    logger.info(f"Successfully sent email to {email}")
                    print(f"Email sent successfully to {email}")
                    
                    # Add to sent_emails.txt
                    self.add_to_sent_emails(sent_emails_file, email)
                    sent_emails_set.add(email.lower())  # Add to set to avoid duplicates in same run
                    
                    # Mark as sent in emails.txt file
                    self.mark_email_sent(emails_file, email)
                    
                except smtplib.SMTPAuthenticationError as e:
                    logger.error(f"SMTP Authentication failed: {e}")
                    print(f"ERROR: Gmail authentication failed - check App Password")
                    print("Stopping email sending due to authentication error")
                    break
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Failed to send email to {email}: {e}")
                    logger.error(traceback.format_exc())
                    print(f"ERROR: Failed to send email to {email}: {e}")
            
            print(f"\n=== Email Sending Summary ===")
            print(f"Total emails: {len(emails_data)}")
            print(f"Sent successfully: {sent_count}")
            print(f"Skipped (already sent): {skipped_count}")
            print(f"Failed: {failed_count}")
            
        except Exception as e:
            logger.error(f"Error reading emails file: {e}")
            logger.error(traceback.format_exc())
            print(f"ERROR: Failed to read emails file: {e}")
    
    def add_to_sent_emails(self, sent_emails_file, email):
        """Add email to sent_emails.txt file"""
        try:
            # Check if email already exists
            if os.path.exists(sent_emails_file):
                with open(sent_emails_file, 'r', encoding='utf-8') as f:
                    existing_emails = {line.strip().lower() for line in f if line.strip() and not line.strip().startswith('#')}
                if email.lower() in existing_emails:
                    logger.debug(f"Email {email} already in sent_emails.txt")
                    return
            
            # Append email to sent_emails.txt
            with open(sent_emails_file, 'a', encoding='utf-8') as f:
                f.write(f"{email}\n")
            logger.info(f"Added {email} to {sent_emails_file}")
        except Exception as e:
            logger.error(f"Error adding email to sent_emails.txt: {e}")
    
    def mark_email_sent(self, emails_file, email):
        """Mark an email as sent in the file"""
        try:
            # Read all lines
            with open(emails_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Update lines to mark email as sent
            updated_lines = []
            for i, line in enumerate(lines):
                if line.startswith('EMAIL:') and email in line:
                    # Check if next lines don't already have SENT marker
                    if i + 1 < len(lines) and 'SENT:' not in lines[i + 1]:
                        updated_lines.append(line)
                        updated_lines.append(f"SENT: YES\n")
                        continue
                updated_lines.append(line)
            
            # Write back
            with open(emails_file, 'w', encoding='utf-8') as f:
                f.writelines(updated_lines)
                
        except Exception as e:
            logger.debug(f"Could not mark email as sent in file: {e}")
    
    def save_results(self, filename='linkedin_results.json'):
        """Save results to JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.posts_data, f, indent=2, ensure_ascii=False)
        print(f"Results saved to {filename}")
    
    def run(self, scrape_only=False, send_only=False):
        """
        Main execution flow
        
        Args:
            scrape_only: Only scrape emails and save to file, don't send
            send_only: Only send emails from file, don't scrape
        """
        try:
            if send_only:
                # Phase 2: Send emails from file
                print("=== Phase 2: Sending Emails from File ===")
                self.send_emails_from_file()
                return
            
            # Phase 1: Scrape emails
            print("=== Phase 1: Scraping Emails from LinkedIn ===")
            print(f"Found {len(self.search_queries)} search query(ies) to process\n")
            
            # First navigate to /feed and check if login is needed (only once)
            is_logged_in = self.navigate_to_feed_and_check_login()
            
            if not is_logged_in:
                # Login required - do login
                if not self.login_linkedin():
                    print("Failed to login to LinkedIn")
                    return
                # After login, check if we're already on feed - don't reload if we are
                current_url = self.driver.current_url.lower()
                if "feed" not in current_url:
                    logger.info("Navigating to feed after login...")
                    self.driver.get("https://www.linkedin.com/feed")
                    time.sleep(3)
                else:
                    logger.info("Already on feed page after login - skipping navigation")
                    print("Already on feed page - continuing...")
                    time.sleep(2)
            
            # Iterate through all search queries
            total_posts_processed = 0
            total_emails_found = 0
            total_emails_sent = 0
            
            for query_idx, search_query in enumerate(self.search_queries, 1):
                print(f"\n{'='*60}")
                print(f"Query {query_idx}/{len(self.search_queries)}: {search_query}")
                print(f"{'='*60}\n")
                logger.info(f"Processing search query {query_idx}/{len(self.search_queries)}: {search_query}")
                
                try:
                    # Search LinkedIn using current query (one query at a time)
                    if not self.search_linkedin(search_query):
                        print(f"Failed to search for: {search_query}")
                        logger.warning(f"Failed to search for query: {search_query}")
                        continue
                    
                    # Click date filter based on .env setting (continue even if it fails)
                    filter_clicked = self.click_date_filter()
                    if not filter_clicked:
                        print("Warning: Could not click filter, but continuing to process posts anyway")
                        time.sleep(3)  # Give page time to settle
                    
                    # Check if "No results" is shown - if yes, skip to next query
                    if self.check_no_results():
                        print(f"No results found for query: {search_query} - moving to next query")
                        logger.info(f"No results found for query: {search_query} - skipping to next")
                        continue
                    
                    # Process all posts (checks liked status, finds emails, sends immediately if not already sent)
                    posts_before = len(self.posts_data)
                    # Process posts - if browser connection fails, exception will be caught and we'll move to next query
                    try:
                        self.process_posts(send_immediately=not scrape_only)
                    except Exception as process_error:
                        # Check if it's a browser connection error using helper method
                        if self._is_browser_connection_error(process_error):
                            logger.error(f"Browser connection error during post processing: {process_error}")
                            print(f"\n[ERROR] Browser connection lost - moving to next SEARCH_QUERY")
                            print(f"Skipping remaining posts for query: {search_query}")
                            # Continue to next query
                            continue
                        else:
                            # Re-raise other errors
                            raise
                    posts_after = len(self.posts_data)
                    
                    query_posts = posts_after - posts_before
                    query_emails = sum(1 for p in self.posts_data[posts_before:] if p['has_email'])
                    query_sent = sum(1 for p in self.posts_data[posts_before:] if p.get('email_sent', False))
                    
                    total_posts_processed += query_posts
                    total_emails_found += query_emails
                    total_emails_sent += query_sent
                    
                    print(f"\nQuery Summary:")
                    print(f"  Posts processed: {query_posts}")
                    print(f"  Emails found: {query_emails}")
                    print(f"  Emails sent: {query_sent}")
                    
                    # Small delay between queries
                    if query_idx < len(self.search_queries):
                        print(f"\nWaiting 3 seconds before next query...")
                        time.sleep(3)
                        
                except Exception as e:
                    logger.error(f"Error processing query '{search_query}': {e}")
                    logger.error(traceback.format_exc())
                    print(f"Error processing query '{search_query}': {e}")
                    print("Continuing with next query...")
                    continue
            
            # Save results after all queries
            self.save_results()
            
            print(f"\n{'='*60}")
            print("=== Overall Processing Summary ===")
            print(f"{'='*60}")
            print(f"Total queries processed: {len(self.search_queries)}")
            print(f"Total posts processed: {total_posts_processed}")
            print(f"Total emails found: {total_emails_found}")
            print(f"Total emails sent: {total_emails_sent}")
            print(f"Emails saved to: emails.txt")
            print(f"{'='*60}\n")
            
            # Note: Emails are now sent immediately during processing
            # The send_emails_from_file() method is still available for manual re-sending if needed
            
        except Exception as e:
            logger.error(f"Error in main execution: {e}")
            logger.error(traceback.format_exc())
            print(f"Error in main execution: {e}")
        finally:
            try:
                if sys.stdin.isatty():
                    input("Press Enter to close browser...")
                else:
                    print("Closing browser in 5 seconds...")
                    time.sleep(5)
            except EOFError:
                print("Closing browser...")
            finally:
                if self.driver:
                    self.driver.quit()
                    logger.info("Browser closed")

if __name__ == "__main__":
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='LinkedIn Email Scraper')
    parser.add_argument('--email', '-e', help='LinkedIn email')
    parser.add_argument('--password', '-p', help='LinkedIn password')
    parser.add_argument('--scrape-only', action='store_true', help='Only scrape emails, don\'t send')
    parser.add_argument('--send-only', action='store_true', help='Only send emails from file, don\'t scrape')
    args = parser.parse_args()
    
    # Get LinkedIn credentials from user (or use saved cookies)
    print("LinkedIn Login:")
    print("(Press Enter to use saved cookies from previous session)")
    
    linkedin_email = None
    linkedin_password = None
    
    # Priority 1: Command line arguments
    if args.email:
        linkedin_email = args.email
        linkedin_password = args.password if args.password else ""
        print(f"Using credentials from command line: {linkedin_email}")
    
    # Priority 2: Environment variables (including from .env file)
    if not linkedin_email:
        # Try LINKEDIN_EMAIL first, then try 'email' from .env
        linkedin_email = os.environ.get('LINKEDIN_EMAIL', None) or os.environ.get('EMAIL', None)
        linkedin_password = os.environ.get('LINKEDIN_PASSWORD', None) or os.environ.get('PASSWORD', None)
        if linkedin_email:
            print(f"Using credentials from .env/environment variables: {linkedin_email}")
    
    # Priority 3: Interactive input
    if not linkedin_email:
        # Check if running in interactive mode
        if sys.stdin.isatty():
            try:
                linkedin_email = input("Enter LinkedIn email: ").strip()
                linkedin_password = ""
                if linkedin_email:
                    linkedin_password = input("Enter LinkedIn password: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nNon-interactive mode - using saved cookies")
                linkedin_email = None
                linkedin_password = None
        else:
            # Non-interactive mode - use saved cookies
            print("Non-interactive mode detected - will use saved cookies if available")
            print("To provide credentials, use: python linkedin_email_scraper.py --email your_email --password your_password")
            print("Or set environment variables: LINKEDIN_EMAIL and LINKEDIN_PASSWORD")
    
    # Gmail credentials are hardcoded but can be changed
    # Get Gmail credentials from environment
    gmail_email = os.environ.get('GMAIL_EMAIL', None)
    gmail_password = os.environ.get('GMAIL_PASSWORD', None)
    
    if not gmail_email or not gmail_password:
        print("ERROR: Gmail credentials not found in .env file")
        print("Please set GMAIL_EMAIL and GMAIL_PASSWORD in your .env file")
        sys.exit(1)
    
    scraper = LinkedInEmailScraper(
        linkedin_email=linkedin_email if linkedin_email else None,
        linkedin_password=linkedin_password if linkedin_password else None,
        gmail_email=gmail_email,
        gmail_password=gmail_password
    )
    
    # Run based on mode
    if args.send_only:
        scraper.run(send_only=True)
    elif args.scrape_only:
        scraper.run(scrape_only=True)
    else:
        scraper.run()  # Both scrape and send

