"""Shared CSV storage and category logic for the Brooklyn clinic pipeline."""
import csv
import os
import re
import tempfile

FIELDS = ['company', 'first', 'last', 'email', 'category', 'website',
          'source', 'date_added', 'sent_date']

ALIASES = {
    'company': ['company', 'name of company', 'company name', 'clinic'],
    'first': ['first', 'first name', 'first_name'],
    'last': ['last', 'last name', 'last_name', 'las'],
    'email': ['email', 'email address', 'email_address'],
    'category': ['category'],
    'website': ['website', 'url'],
    'source': ['source'],
    'date_added': ['date_added'],
    'sent_date': ['sent_date', 'sent_status'],
}

EMAIL_RE = re.compile(r'[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}', re.I)

# name -> (weight, keywords). Order matters: specific categories come first so
# they win ties against the generic "Psychotherapy & Counseling" bucket.
CATEGORIES = {
    'Psychiatry & Medication Management': (1.0, ['psychiatr', 'medication management', 'prescrib', 'psychopharm']),
    'Substance Use & Addiction': (1.0, ['addiction', 'substance', 'alcohol', 'detox', 'opioid', 'recovery program']),
    'Autism, ADHD & Developmental': (1.0, ['autism', 'adhd', 'developmental', 'neurodiver', 'learning disab']),
    'Trauma & PTSD': (1.0, ['trauma', 'ptsd', 'emdr']),
    'Couples & Relationship': (1.0, ['couples', 'marriage', 'relationship therapy', 'premarital']),
    'Child, Teen & Family': (1.0, ['child', 'adolescent', 'teen', 'pediatric', 'parenting', 'family therapy']),
    'Community & Nonprofit Behavioral Health': (1.0, ['community', 'nonprofit', 'non-profit', 'medicaid', 'case management',
                                                      'supportive housing', 'article 31', 'rehabilitation']),
    'Psychotherapy & Counseling': (0.4, ['psychotherapy', 'therapy', 'counseling', 'therapist', 'psychologist',
                                         'cbt', 'anxiety', 'depression']),
}
CATEGORY_ORDER = list(CATEGORIES) + ['Uncategorized']


def classify(strong_text, body_text):
    """Keyword-score a site. strong_text = title/meta/headings/nav (3x weight)."""
    s, b = strong_text.lower(), body_text.lower()
    best, best_score = 'Uncategorized', 0.0
    for name, (weight, kws) in CATEGORIES.items():
        score = weight * sum(3 * s.count(k) + b.count(k) for k in kws)
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= 2 else 'Uncategorized'


def load_rows(filename='clinics_master.csv'):
    """Load rows with flexible headers; skips invalid and duplicate emails."""
    if not os.path.exists(filename):
        return []
    rows, seen = [], set()
    with open(filename, newline='', encoding='utf-8-sig') as f:
        for raw in csv.DictReader(f):
            norm = {k.strip().lower(): (v or '').strip() for k, v in raw.items() if k}
            row = {field: next((norm[n] for n in names if norm.get(n)), '')
                   for field, names in ALIASES.items()}
            email = row['email'].lower()
            if not EMAIL_RE.fullmatch(email):
                print(f'Skipping row with invalid email: {row["company"]!r} / {row["email"]!r}')
                continue
            if email in seen:
                continue
            row['email'] = email
            seen.add(email)
            rows.append(row)
    return rows


def save_rows(rows, filename='clinics_master.csv'):
    """Rewrite the whole file atomically (no more glued rows)."""
    directory = os.path.dirname(os.path.abspath(filename))
    fd, tmp = tempfile.mkstemp(dir=directory, suffix='.tmp')
    with os.fdopen(fd, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, filename)
