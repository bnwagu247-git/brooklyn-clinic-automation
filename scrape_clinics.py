import csv
import os
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests

# Set user-agent to prevent requests from being blocked by standard web firewalls
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,'
        ' like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
}

# Regex pattern to identify standard email addresses
EMAIL_REGEX = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

# Keywords used to discover relevant contact pages on target websites
CONTACT_KEYWORDS = ['contact', 'about', 'get-in-touch', 'team', 'staff']


def extract_emails_from_url(url):
  """Fetches a web page and extracts all unique email addresses."""
  emails = set()
  try:
    response = requests.get(url, headers=HEADERS, timeout=8)
    if response.status_code != 200:
      return emails

    soup = BeautifulSoup(response.text, 'html.parser')

    # 1. Search text content using regex
    found_emails = re.findall(EMAIL_REGEX, response.text)
    for email in found_emails:
      # Filter out common false-positive static asset extensions
      if not email.lower().endswith(('.png', '.jpg', '.jpeg', '.svg', '.gif')):
        emails.add(email.lower())

    # 2. Search mailto: links explicitly in HTML
    for a_tag in soup.find_all('a', href=True):
      href = a_tag['href']
      if href.startswith('mailto:'):
        clean_email = href.replace('mailto:', '').split('?')[0].strip().lower()
        if re.match(EMAIL_REGEX, clean_email):
          emails.add(clean_email)

  except Exception as e:
    print(f'   └─ Could not scan {url}: {e}')

  return emails


def find_contact_pages(base_url, html_content):
  """Finds internal contact or about page links from a home page HTML."""
  contact_links = set()
  soup = BeautifulSoup(html_content, 'html.parser')
  domain = urlparse(base_url).netloc

  for a_tag in soup.find_all('a', href=True):
    href = a_tag['href']
    full_url = urljoin(base_url, href)

    # Ensure link stays on the same target clinic website
    if urlparse(full_url).netloc == domain:
      if any(keyword in href.lower() for keyword in CONTACT_KEYWORDS):
        contact_links.add(full_url)

  return list(contact_links)[:3]  # Limit to top 3 matching contact pages


def scrape_clinic_website(website_url):
  """Scans both home and contact pages of a single clinic site for email addresses."""
  print(f'\nScanning: {website_url}')
  found_emails = set()

  try:
    response = requests.get(website_url, headers=HEADERS, timeout=8)
    if response.status_code == 200:
      # Scan home page
      home_emails = extract_emails_from_url(website_url)
      found_emails.update(home_emails)

      # Find and scan contact pages
      contact_pages = find_contact_pages(website_url, response.text)
      for page_url in contact_pages:
        contact_emails = extract_emails_from_url(page_url)
        found_emails.update(contact_emails)

  except Exception as e:
    print(f'Failed to connect to {website_url}: {e}')

  return list(found_emails)


def append_to_master_csv(new_leads, filename='clinics_master.csv'):
  """Appends new, unique scraped clinic leads into clinics_master.csv."""
  file_exists = os.path.exists(filename)
  existing_emails = set()

  # Load existing emails to avoid adding duplicates
  if file_exists:
    with open(filename, mode='r', encoding='utf-8') as f:
      reader = csv.DictReader(f)
      for row in reader:
        email = row.get('email', '').strip().lower()
        if email:
          existing_emails.add(email)

  added_count = 0
  fieldnames = ['company', 'first', 'last', 'email']

  with open(filename, mode='a', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)

    # Write header if starting a new CSV file
    if not file_exists or os.stat(filename).st_size == 0:
      writer.writeheader()

    for lead in new_leads:
      email_clean = lead['email'].lower()
      if email_clean not in existing_emails:
        writer.writerow(lead)
        existing_emails.add(email_clean)
        added_count += 1

  print(
      f'\nSuccessfully appended {added_count} new unique clinic leads to'
      f' {filename}.'
  )


# --- Example Execution Routine ---
if __name__ == '__main__':
  # Target list of candidate Brooklyn clinic websites to crawl
  target_websites = [
      'https://www.brooklyncenterforchilddevelopment.com',
      'https://www.brooklynminds.com',
      'https://www.counselingcenterofbrooklyn.com',
  ]

  discovered_leads = []

  for site in target_websites:
    emails = scrape_clinic_website(site)
    if emails:
      company_name = (
          urlparse(site).netloc.replace('www.', '').split('.')[0].capitalize()
      )
      for email in emails:
        discovered_leads.append({
            'company': f'{company_name} Mental Health',
            'first': 'Director',
            'last': 'Intake',
            'email': email,
        })
        print(f'   └─ Found Email: {email}')

  if discovered_leads:
    append_to_master_csv(discovered_leads)
  else:
    print('\nNo new emails discovered during this run.')