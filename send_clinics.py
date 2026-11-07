import csv
import datetime
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib


def get_field_value(row, possible_keys):
  """Utility to match flexible CSV headers (case-insensitive)."""
  for key in possible_keys:
    for csv_header in row.keys():
      if csv_header and csv_header.strip().lower() == key.lower():
        return row[csv_header].strip()
  return ''


def load_clinics_from_csv(filename='clinics_master.csv'):
  """Loads the master clinic list dynamically from a CSV file with flexible headers and duplicate filtering."""
  clinics = []
  seen_emails = set()

  if not os.path.exists(filename):
    print(f"Error: The file '{filename}' was not found.")
    return []

  try:
    with open(filename, mode='r', encoding='utf-8-sig') as file:
      reader = csv.DictReader(file)
      for row_num, row in enumerate(reader, start=2):
        email = get_field_value(row, ['email', 'email address', 'email_address'])
        company = get_field_value(
            row, ['company', 'name of company', 'company name', 'clinic']
        )
        first = get_field_value(row, ['first', 'first name', 'first_name'])
        last = get_field_value(row, ['last', 'last name', 'last_name'])

        if not email:
          print(
              f'Warning: Skipping row {row_num} ({company or "Unknown"}) -'
              ' missing email.'
          )
          continue

        email_clean = email.lower()
        if email_clean in seen_emails:
          print(f'Notice: Filtered duplicate email: {email_clean} (Row {row_num})')
          continue

        seen_emails.add(email_clean)
        clinics.append({
            'company': company or 'N/A',
            'first': first or 'N/A',
            'last': last or 'N/A',
            'email': email,
        })

    print(f'Successfully loaded {len(clinics)} unique clinics from {filename}.')

  except Exception as e:
    print(f'Error while reading {filename}: {e}')

  return clinics


def get_daily_clinics(pool, batch_size=60):
  """Picks a unique rotating batch of clinics based on the day of the year."""
  if not pool:
    return []

  day_of_year = datetime.date.today().timetuple().tm_yday
  start_idx = (day_of_year * batch_size) % len(pool)
  batch = []

  actual_batch_size = min(batch_size, len(pool))
  for i in range(actual_batch_size):
    idx = (start_idx + i) % len(pool)
    batch.append(pool[idx])

  return batch


def generate_html_table(clinics):
  if not clinics:
    return '<p>No clinics available to display for today.</p>'

  html = """
  <html>
    <body>
      <h2>Your Daily Brooklyn Mental Health Clinics Directory</h2>
      <p>Here is your fresh batch of verified clinics for today:</p>
      <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; font-family: Arial, sans-serif; font-size: 14px; width: 100%;">
        <thead>
          <tr style="background-color: #f2f2f2; text-align: left;">
            <th style="padding: 8px; border: 1px solid #ddd;">Name of Company</th>
            <th style="padding: 8px; border: 1px solid #ddd;">First name</th>
            <th style="padding: 8px; border: 1px solid #ddd;">Last name</th>
            <th style="padding: 8px; border: 1px solid #ddd;">Email address</th>
          </tr>
        </thead>
        <tbody>
  """
  for c in clinics:
    html += f"""
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd;">{c['company']}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{c['first']}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{c['last']}</td>
            <td style="padding: 8px; border: 1px solid #ddd;"><a href="mailto:{c['email']}">{c['email']}</a></td>
          </tr>
    """
  html += """
        </tbody>
      </table>
    </body>
  </html>
  """
  return html


def send_email():
  sender_email = os.environ.get('EMAIL_USER')
  sender_password = os.environ.get('EMAIL_PASSWORD')
  recipient_email = os.environ.get('RECIPIENT_EMAIL')

  if not sender_email or not sender_password or not recipient_email:
    print('Error: Missing required environment variables.')
    return

  master_pool = load_clinics_from_csv('clinics_master.csv')
  if not master_pool:
    print('Error: Master clinic pool is empty or invalid.')
    return

  clinics = get_daily_clinics(master_pool, 60)
  html_content = generate_html_table(clinics)

  msg = MIMEMultipart('alternative')
  msg['Subject'] = (
      'Daily Brooklyn Clinic Leads -'
      f" {datetime.date.today().strftime('%B %d, %Y')}"
  )
  msg['From'] = sender_email
  msg['To'] = recipient_email
  msg.attach(MIMEText(html_content, 'html'))

  try:
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
      server.login(sender_email, sender_password)
      server.sendmail(sender_email, recipient_email, msg.as_string())
    print('Daily clinic email sent successfully!')
  except Exception as e:
    print(f'Error sending email: {e}')


if __name__ == '__main__':
  send_email()