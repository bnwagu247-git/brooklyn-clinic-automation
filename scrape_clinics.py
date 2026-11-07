import csv
import os
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,'
        ' like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
}

EMAIL_REGEX = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
CONTACT_KEYWORDS = ['contact', 'about', 'team', 'staff', 'reach', 'directory']


def extract_emails_from_url(url):
  """Fetches a web page and extracts all unique valid email addresses."""
  emails = set()
  try:
    response = requests.get(url, headers=HEADERS, timeout=10)
    if response.status_code != 200:
      return emails

    # Search raw text using regex
    found_emails = re.findall(EMAIL_REGEX, response.text)
    for email in found_emails:
      clean_email = email.lower().strip()
      if not clean_email.endswith(
          ('.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp', '.css', '.js')
      ):
        if (
            'example' not in clean_email
            and 'domain' not in clean_email
            and 'sentry' not in clean_email
        ):
          emails.add(clean_email)

    # Search explicit mailto links
    soup = BeautifulSoup(response.text, 'html.parser')
    for a_tag in soup.find_all('a', href=True):
      href = a_tag['href']
      if href.startswith('mailto:'):
        mail = href.replace('mailto:', '').split('?')[0].strip().lower()
        if re.match(EMAIL_REGEX, mail) and 'example' not in mail:
          emails.add(mail)

  except Exception as e:
    print(f'   └─ Could not scan {url}: {e}')

  return emails


def scrape_directory_page(directory_url):
  """Scrapes directory and listing pages for multiple clinic and provider emails."""
  print(f'\nScanning Directory: {directory_url}')
  found_leads = []

  try:
    response = requests.get(directory_url, headers=HEADERS, timeout=10)
    if response.status_code != 200:
      return found_leads

    soup = BeautifulSoup(response.text, 'html.parser')

    # Find all links on the directory page to explore individual clinic sites or cards
    domain = urlparse(directory_url).netloc
    emails_on_page = extract_emails_from_url(directory_url)

    for email in emails_on_page:
      # Derive clean company name from email domain or fallback
      domain_part = email.split('@')[-1]
      comp_name = (
          domain_part.split('.')[0].capitalize() + ' Mental Health Clinic'
      )
      found_leads.append({
          'company': comp_name,
          'first': 'Director',
          'last': 'Intake',
          'email': email,
      })

  except Exception as e:
    print(f'Failed to scan directory {directory_url}: {e}')

  return found_leads


def append_to_master_csv(new_leads, filename='clinics_master.csv'):
  """Appends unique leads, avoiding duplicates."""
  file_exists = os.path.exists(filename)
  existing_emails = set()

  if file_exists:
    with open(filename, mode='r', encoding='utf-8-sig') as f:
      reader = csv.DictReader(f)
      for row in reader:
        for val in row.values():
          if val and '@' in val:
            existing_emails.add(val.strip().lower())

  added_count = 0
  fieldnames = ['company', 'first', 'last', 'email']

  with open(filename, mode='a', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)

    if not file_exists or os.stat(filename).st_size == 0:
      writer.writeheader()

    for lead in new_leads:
      email_clean = lead['email'].lower()
      if email_clean not in existing_emails:
        writer.writerow(lead)
        existing_emails.add(email_clean)
        added_count += 1

  print(
      f'\nSuccessfully added {added_count} new unique leads to {filename}.'
  )


if __name__ == '__main__':
  # Expanded list including Brooklyn mental health directories and practice networks
  target_directories = [
      'https://www.psychologytoday.com/us/therapists/new-york/brooklyn',
      'https://www.brooklynminds.com',
      'https://www.williamsburgtherapygroup.com',
      'https://www.parkslopetherapy.com',
      'https://www.brooklynpsychotherapy.com',
      'https://www.cobblehilltherapy.com',
  ]

  all_discovered_leads = []

  for url in target_directories:
    leads = scrape_directory_page(url)
    for lead in leads:
      all_discovered_leads.append(lead)
      print(
          f"   └─ Discovered: {lead['email']} ({lead['company']})"
      )

  if all_discovered_leads:
    append_to_master_csv(all_discovered_leads)
  else:
    print('\nNo new emails discovered during this run.')