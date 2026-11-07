"""Email the next batch of unsent leads, grouped by category, then mark them sent.

Usage:  python send_clinics.py            # send for real
        python send_clinics.py --dry-run  # write preview.html, send nothing, mark nothing
"""
import csv
import datetime
import html
import io
import os
import smtplib
import sys
from collections import defaultdict
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from clinic_store import CATEGORY_ORDER, load_rows, save_rows

BATCH_SIZE = 60
TH = 'padding:8px;border:1px solid #ddd;text-align:left;background:#f2f2f2;'
TD = 'padding:8px;border:1px solid #ddd;'


def group_by_category(batch):
    groups = defaultdict(list)
    for r in batch:
        groups[r['category'] or 'Uncategorized'].append(r)
    order = [c for c in CATEGORY_ORDER if c in groups] + sorted(c for c in groups if c not in CATEGORY_ORDER)
    return [(c, sorted(groups[c], key=lambda r: r['company'].lower())) for c in order]


def build_html(groups, total):
    e = html.escape
    out = ['<html><body style="font-family:Arial,sans-serif;font-size:14px">',
           f'<h2>Brooklyn Mental Health Leads - {total} new</h2>',
           '<p>' + ' &middot; '.join(f'{e(c)} ({len(rs)})' for c, rs in groups) + '</p>']
    for cat, rs in groups:
        out.append(f'<h3 style="margin-top:24px">{e(cat)} ({len(rs)})</h3>')
        out.append('<table cellspacing="0" style="border-collapse:collapse;width:100%">'
                   f'<tr><th style="{TH}">Company</th><th style="{TH}">First</th>'
                   f'<th style="{TH}">Last</th><th style="{TH}">Email</th><th style="{TH}">Website</th></tr>')
        for r in rs:
            site = (f'<a href="{e(r["website"])}">{e(r["website"])}</a>' if r['website'].startswith('http') else '')
            out.append(f'<tr><td style="{TD}">{e(r["company"])}</td><td style="{TD}">{e(r["first"]) or "&mdash;"}</td>'
                       f'<td style="{TD}">{e(r["last"]) or "&mdash;"}</td>'
                       f'<td style="{TD}"><a href="mailto:{e(r["email"])}">{e(r["email"])}</a></td>'
                       f'<td style="{TD}">{site}</td></tr>')
        out.append('</table>')
    out.append('<p style="color:#777;font-size:12px;margin-top:24px">Verify each address before outreach. '
               'Include your postal address and an opt-out line in any cold email.</p></body></html>')
    return '\n'.join(out)


def build_text(groups):
    lines = []
    for cat, rs in groups:
        lines.append(f'\n== {cat} ({len(rs)}) ==')
        lines += [f'{r["company"]} | {r["email"]}' for r in rs]
    return '\n'.join(lines)


def build_csv(batch):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['company', 'first', 'last', 'email', 'category', 'website'])
    for r in batch:
        w.writerow([r['company'], r['first'], r['last'], r['email'], r['category'], r['website']])
    return buf.getvalue()


def compose(sender, recipient, subject, html_body, text_body, csv_data=None):
    msg = MIMEMultipart('mixed')
    msg['Subject'], msg['From'], msg['To'] = subject, sender, recipient
    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(text_body, 'plain', 'utf-8'))
    alt.attach(MIMEText(html_body, 'html', 'utf-8'))
    msg.attach(alt)
    if csv_data:
        part = MIMEApplication(csv_data.encode('utf-8'), Name='leads.csv')
        part['Content-Disposition'] = 'attachment; filename="leads.csv"'
        msg.attach(part)
    return msg


def main():
    dry = '--dry-run' in sys.argv
    sender = os.environ.get('EMAIL_USER')
    password = os.environ.get('EMAIL_PASSWORD')
    recipient = os.environ.get('RECIPIENT_EMAIL')
    if not dry and not (sender and password and recipient):
        print('Error: EMAIL_USER, EMAIL_PASSWORD and RECIPIENT_EMAIL must be set.')
        sys.exit(1)

    rows = load_rows()
    unsent = sorted((r for r in rows if not r['sent_date']),
                    key=lambda r: (r['date_added'] or '', r['company'].lower()))
    batch = unsent[:BATCH_SIZE]
    today = datetime.date.today()
    stamp = today.strftime('%B %d, %Y')

    if batch:
        groups = group_by_category(batch)
        subject = f'Daily Brooklyn Clinic Leads - {stamp} ({len(batch)} new)'
        msg_args = (subject, build_html(groups, len(batch)), build_text(groups), build_csv(batch))
    else:
        subject = f'Brooklyn Clinic Leads - {stamp} (no new leads)'
        note = ('No unsent leads left in clinics_master.csv. Add sites to seed_sites.txt '
                'or set GOOGLE_PLACES_API_KEY to keep the pipeline fed.')
        msg_args = (subject, f'<html><body><p>{note}</p></body></html>', note, None)

    if dry:
        with open('preview.html', 'w', encoding='utf-8') as f:
            f.write(msg_args[1])
        print(f'Dry run: {len(batch)} leads in batch, {len(unsent)} unsent total. Wrote preview.html')
        return

    msg = compose(sender, recipient, *msg_args)
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
    except Exception as e:
        print(f'Error sending email: {e}')
        sys.exit(1)  # fail loudly; leads stay unsent for the next run

    sent = {r['email'] for r in batch}
    for r in rows:
        if r['email'] in sent:
            r['sent_date'] = today.isoformat()
    save_rows(rows)
    print(f'Email sent with {len(batch)} leads; marked as sent.')


if __name__ == '__main__':
    main()
