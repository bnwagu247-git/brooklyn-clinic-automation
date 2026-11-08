"""Find Brooklyn mental health clinic emails, categorize them, store in clinics_master.csv.

Sources:
  1. seed_sites.txt  - clinic websites (one per line) or directories ("dir: <url>")
  2. Google Places   - optional, used when GOOGLE_PLACES_API_KEY is set
Each clinic site is crawled politely (robots.txt, delay, a few contact-type pages).
"""
import datetime
import os
import re
import sys
import time
from urllib import robotparser
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from clinic_store import EMAIL_RE, classify, load_rows, save_rows

BOT_NAME = 'BrooklynLeadsBot'
HEADERS = {
    'User-Agent': os.environ.get('SCRAPER_USER_AGENT') or (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}
FAILURES = []  # (url, reason) collected for the end-of-run summary
DELAY = 1.0
TIMEOUT = 12
MAX_PAGES_PER_SITE = 4
MAX_SITES_PER_RUN = 60
MAX_ENRICH_PER_RUN = 40
MAX_EMAILS_PER_SITE = 3
PLACES_QUERIES_PER_RUN = 3

CONTACT_HINTS = ('contact', 'about', 'team', 'staff', 'people', 'reach', 'connect')
IMG_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js')
JUNK_LOCALS = {'noreply', 'no-reply', 'donotreply', 'do-not-reply', 'webmaster',
               'privacy', 'abuse', 'postmaster', 'sentry', 'user', 'name', 'email'}
JUNK_DOMAINS = {'example.com', 'domain.com', 'email.com', 'yoursite.com', 'sentry.io',
                'wixpress.com', 'sentry-next.wixpress.com', 'mysite.com'}
FREE_MAIL = {'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'aol.com',
             'icloud.com', 'protonmail.com', 'me.com'}
SOCIAL = {'facebook.com', 'instagram.com', 'twitter.com', 'x.com', 'linkedin.com',
          'youtube.com', 'tiktok.com', 'google.com', 'yelp.com', 'apple.com', 'wa.me',
          'psychologytoday.com', 'zocdoc.com', 'healthgrades.com', 'linktr.ee', 'goodtherapy.org'}
GENERIC_LOCALS = {'info', 'contact', 'hello', 'office', 'intake', 'admin', 'admissions',
                  'appointments', 'frontdesk', 'inquiries', 'care', 'support', 'help', 'team'}

PLACES_QUERIES = [
    'mental health clinic in Brooklyn, NY',
    'psychotherapy practice in Brooklyn, NY',
    'psychiatrist in Brooklyn, NY',
    'child and adolescent therapy in Brooklyn, NY',
    'substance abuse treatment in Brooklyn, NY',
    'couples therapy in Brooklyn, NY',
    'trauma therapy EMDR in Brooklyn, NY',
    'autism ADHD evaluation in Brooklyn, NY',
    'community mental health center in Brooklyn, NY',
]


# ---------- helpers ----------
def base_domain(value):
    host = urlparse(value if '//' in value else '//' + value).netloc or value
    host = host.split('@')[-1].split(':')[0].lower()
    parts = host.split('.')
    return '.'.join(parts[-2:]) if len(parts) >= 2 else host


_robots = {}


def allowed(url):
    p = urlparse(url)
    base = f'{p.scheme}://{p.netloc}'
    rp = _robots.get(base)
    if rp is None:
        rp = robotparser.RobotFileParser()
        try:
            r = requests.get(base + '/robots.txt', headers=HEADERS, timeout=8)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])
        _robots[base] = rp
    return rp.can_fetch(BOT_NAME, url)


def fetch_soup(url):
    if not allowed(url):
        print(f'   x {url}: disallowed by robots.txt')
        FAILURES.append((url, 'blocked by robots.txt'))
        return None
    time.sleep(DELAY)
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as e:
        print(f'   x {url}: {e}')
        FAILURES.append((url, type(e).__name__ + ': ' + str(e)[:120]))
        return None
    if r.status_code != 200 or 'html' not in r.headers.get('Content-Type', ''):
        print(f'   x {url}: HTTP {r.status_code}')
        FAILURES.append((url, f'HTTP {r.status_code}'))
        return None
    return BeautifulSoup(r.text, 'html.parser')


def decode_cf(hexstr):
    """Decode Cloudflare's email obfuscation (data-cfemail)."""
    key = int(hexstr[:2], 16)
    return ''.join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))


def clean_email(e):
    e = e.lower().strip('.,;:<>()[]"\' ')
    if not EMAIL_RE.fullmatch(e) or e.endswith(IMG_EXT):
        return None
    local, domain = e.rsplit('@', 1)
    if local in JUNK_LOCALS or domain in JUNK_DOMAINS:
        return None
    if len(domain.rsplit('.', 1)[1]) > 6:  # catches "...orgCall" glue
        return None
    return e


def extract_emails(soup):
    """Emails from mailto links, Cloudflare-protected spans, JSON-LD and visible text.
    NOTE: removes script/style tags from the soup."""
    found = set()
    for a in soup.find_all('a', href=True):
        if a['href'].lower().startswith('mailto:'):
            found.update(EMAIL_RE.findall(unquote(a['href'][7:].split('?')[0])))
    for el in soup.select('[data-cfemail]'):
        try:
            found.add(decode_cf(el['data-cfemail']))
        except ValueError:
            pass
    for s in soup.find_all('script', type='application/ld+json'):
        found.update(EMAIL_RE.findall(s.get_text()))
    for s in soup(['script', 'style', 'noscript']):
        s.decompose()
    found.update(EMAIL_RE.findall(soup.get_text(' ', strip=True)))
    return {e for e in map(clean_email, found) if e}


def site_name(soup, url):
    meta = soup.find('meta', property='og:site_name')
    if meta and meta.get('content', '').strip():
        return meta['content'].strip()
    stem = base_domain(url).split('.')[0]
    if soup.title and soup.title.string:
        parts = [p.strip() for p in re.split(r'\s[|\-\u2013\u2014\u2022:]\s', soup.title.string.strip()) if p.strip()]
        for p in parts:
            if stem in re.sub(r'[^a-z0-9]', '', p.lower()):
                return p
        if parts:
            return parts[0]
    return stem.title()


def strong_text(soup):
    bits = []
    if soup.title and soup.title.string:
        bits.append(soup.title.string)
    meta = soup.find('meta', attrs={'name': 'description'})
    if meta and meta.get('content'):
        bits.append(meta['content'])
    bits += [t.get_text(' ', strip=True) for t in soup.find_all(['h1', 'h2', 'nav'])]
    return ' '.join(bits)


def crawl_site(url, max_pages=MAX_PAGES_PER_SITE):
    home = fetch_soup(url)
    if home is None:
        return None
    name, strong = site_name(home, url), strong_text(home)
    dom = base_domain(url)
    todo = []
    for a in home.find_all('a', href=True):
        link = urljoin(url, a['href']).split('#')[0]
        p = urlparse(link)
        if (p.scheme in ('http', 'https') and base_domain(p.netloc) == dom
                and link not in todo and link.rstrip('/') != url.rstrip('/')
                and any(h in (link + ' ' + a.get_text(' ')).lower() for h in CONTACT_HINTS)):
            todo.append(link)
    pages = [home] + [s for s in (fetch_soup(l) for l in todo[:max_pages - 1]) if s is not None]
    emails, texts = set(), []
    for page in pages:
        emails |= extract_emails(page)
        texts.append(page.get_text(' ', strip=True))
    body = ' '.join(texts)
    brooklyn = 'brooklyn' in body.lower() or bool(re.search(r'\b112[0-5]\d\b', body))
    return {'name': name, 'emails': emails, 'strong': strong, 'body': body[:20000], 'brooklyn': brooklyn}


def pick_emails(emails, url):
    dom = base_domain(url)
    own = [e for e in emails if base_domain(e.split('@')[1]) == dom]
    pool = own or [e for e in emails if e.split('@')[1] in FREE_MAIL]
    pool.sort(key=lambda e: (e.split('@')[0] not in GENERIC_LOCALS, e))
    return pool[:MAX_EMAILS_PER_SITE]


# ---------- discovery ----------
def directory_links(url):
    """Outbound links of a directory page, treated as candidate clinic sites."""
    soup = fetch_soup(url)
    if soup is None:
        return []
    skip = SOCIAL | {base_domain(url)}
    out = []
    for a in soup.find_all('a', href=True):
        p = urlparse(urljoin(url, a['href']))
        if p.scheme in ('http', 'https') and base_domain(p.netloc) not in skip:
            root = f'{p.scheme}://{p.netloc}/'
            if root not in out:
                out.append(root)
    return out


def load_seeds(path='seed_sites.txt'):
    targets = {}
    if not os.path.exists(path):
        return targets
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            if line.lower().startswith('dir:'):
                for link in directory_links(line[4:].strip()):
                    targets.setdefault(link, False)
            else:
                targets.setdefault(line if line.startswith('http') else 'https://' + line, False)
    return targets


def places_discover(api_key):
    """Google Places (New) Text Search -> {website_root: True}. Requires billing enabled."""
    start = datetime.date.today().toordinal() % len(PLACES_QUERIES)
    queries = [PLACES_QUERIES[(start + i) % len(PLACES_QUERIES)] for i in range(PLACES_QUERIES_PER_RUN)]
    headers = {'Content-Type': 'application/json', 'X-Goog-Api-Key': api_key,
               'X-Goog-FieldMask': 'places.displayName,places.websiteUri,places.formattedAddress,nextPageToken'}
    sites = {}
    for q in queries:
        token = None
        for _ in range(3):
            body = {'textQuery': q, 'pageSize': 20}
            if token:
                body['pageToken'] = token
            try:
                r = requests.post('https://places.googleapis.com/v1/places:searchText',
                                  json=body, headers=headers, timeout=20)
            except requests.RequestException as e:
                print(f'Places error: {e}')
                break
            if r.status_code != 200:
                print(f'Places HTTP {r.status_code}: {r.text[:200]}')
                break
            data = r.json()
            for p in data.get('places', []):
                site = p.get('websiteUri')
                if site and 'brooklyn' in p.get('formattedAddress', '').lower():
                    sites[f'{urlparse(site).scheme}://{urlparse(site).netloc}/'] = True
            token = data.get('nextPageToken')
            if not token:
                break
    print(f'Places discovery found {len(sites)} Brooklyn websites.')
    return sites



OPEN_BASE = 'https://api.openplacesapi.com'
BROOKLYN_CENTER = (40.65, -73.95)
OPEN_TERMS = ['mental health', 'psychologist', 'psychiatrist', 'counseling',
              'psychotherapy', 'substance abuse', 'addiction treatment']


def open_places_discover(api_key):
    """Open Places API (openplacesapi.com): browse mental-health categories around Brooklyn.
    Returns {website_root: trusted_brooklyn}. Free plan: 10,000 calls/month, no card.
    Set OPEN_PLACES_CATEGORIES="slug1,slug2" to override the automatic category lookup."""
    cats = [c.strip() for c in os.environ.get('OPEN_PLACES_CATEGORIES', '').split(',') if c.strip()]
    if not cats:
        for term in OPEN_TERMS:  # /v1/categories is public and does not count against quota
            try:
                r = requests.get(f'{OPEN_BASE}/v1/categories', params={'q': term, 'limit': 1}, timeout=20)
                found = r.json().get('categories', []) if r.status_code == 200 else []
            except (requests.RequestException, ValueError):
                found = []
            if found and found[0]['category'] not in cats:
                cats.append(found[0]['category'])
    print(f'Open Places categories: {cats}')
    # rotate through the first 1,000 places per category over 10 days (2 pages of 50 per run)
    start = (datetime.date.today().toordinal() % 10) * 100
    headers = {'Authorization': f'Bearer {api_key}'}
    sites = {}
    for cat in cats:
        for offset in (start, start + 50):
            params = {'category': cat, 'lat': BROOKLYN_CENTER[0], 'lon': BROOKLYN_CENTER[1],
                      'radius_mi': 10, 'limit': 50, 'offset': offset,
                      'sort': 'distance', 'min_confidence': 0.5}
            try:
                r = requests.get(f'{OPEN_BASE}/v1/places', params=params, headers=headers, timeout=30)
            except requests.RequestException as e:
                print(f'Open Places error: {e}')
                break
            if r.status_code != 200:
                print(f'Open Places HTTP {r.status_code}: {r.text[:200]}')
                break
            results = r.json().get('results', [])
            for p in results:
                site = p.get('website')
                loc = ((p.get('address') or {}).get('locality') or '').lower()
                if not site or p.get('operating_status') not in (None, 'operational'):
                    continue
                if loc and loc not in ('brooklyn', 'new york', 'new york city', 'nyc'):
                    continue
                parsed = urlparse(site if '//' in site else '//' + site)
                root = f"{parsed.scheme or 'https'}://{parsed.netloc}/"
                sites[root] = sites.get(root, False) or loc == 'brooklyn'
            if len(results) < 50:
                break
    print(f'Open Places found {len(sites)} candidate websites.')
    return sites


# ---------- main ----------
def main():
    today = datetime.date.today().isoformat()
    rows = load_rows()
    existing = {r['email'] for r in rows}

    # 1) Backfill category/website for rows that don't have one yet
    enriched = 0
    for r in rows:
        if r['category'] or enriched >= MAX_ENRICH_PER_RUN:
            continue
        domain = r['email'].split('@')[1]
        site = r['website'] or ('' if domain in FREE_MAIL else f'https://{domain}/')
        info = crawl_site(site, max_pages=1) if site else None
        r['website'] = site
        if not site:
            r['category'] = 'Uncategorized'
            continue
        if info is None:
            print(f"Could not load {site or r['email']}; will retry next run")
            continue
        r['category'] = classify(info['strong'], info['body'])
        enriched += 1
        print(f"Categorized {r['company']}: {r['category']}")

    # 2) Build crawl queue
    targets = load_seeds()
    key = os.environ.get('GOOGLE_PLACES_API_KEY')
    if key:
        for url, trusted in places_discover(key).items():
            targets.setdefault(url, trusted)
    okey = os.environ.get('OPEN_PLACES_API_KEY')
    if okey:
        for url, trusted in open_places_discover(okey).items():
            targets.setdefault(url, trusted)
    known = {base_domain(r['email'].split('@')[1]) for r in rows} | {base_domain(r['website']) for r in rows if r['website']}
    queue = []
    for url, trusted in targets.items():
        d = base_domain(url)
        if d in known or d in SOCIAL:
            continue
        known.add(d)
        queue.append((url, trusted))
    queue = queue[:MAX_SITES_PER_RUN]

    # 3) Crawl
    scanned = failed = added = 0
    for url, trusted in queue:
        print(f'\nScanning {url}')
        scanned += 1
        info = crawl_site(url)
        if info is None:
            failed += 1
            continue
        if not (trusted or info['brooklyn']):
            print('   - no Brooklyn signal, skipped')
            continue
        emails = pick_emails(info['emails'], url)
        if not emails:
            print('   - no usable emails')
            continue
        category = classify(info['strong'], info['body'])
        for e in emails:
            if e in existing:
                continue
            existing.add(e)
            rows.append({'company': info['name'], 'first': '', 'last': '', 'email': e,
                         'category': category, 'website': url, 'source': 'scraper',
                         'date_added': today, 'sent_date': ''})
            added += 1
            print(f"   + {e} [{category}]")

    save_rows(rows)
    summary = (f'Scraper: {scanned} sites scanned, {failed} failed, {added} new leads, '
               f'{enriched} existing rows categorized. Master now has {len(rows)} leads.')
    if FAILURES:
        summary += '\nFailures:\n' + '\n'.join(f'  - {u}: {why}' for u, why in FAILURES[:20])
    print('\n' + summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(summary + '\n')
    if scanned and failed == scanned:
        sys.exit(1)  # everything failed: surface it in the workflow


if __name__ == '__main__':
    main()
