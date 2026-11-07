import csv
import datetime
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib


def load_clinics_from_csv(filename='clinics_master.csv'):
  """Loads the master clinic list dynamically from a CSV file with duplicate filtering."""
  clinics = []
  seen_emails = set()

  if not os.path.exists(filename):
    print(
        f"Error: The file '{filename}' was not found. Please ensure it is in"
        ' your repository root.'
    )
    return []

  try:
    with open(filename, mode='r', encoding='utf-8') as file:
      reader = csv.DictReader(file)
      for row_num, row in enumerate(reader, start=2):
        email = row.get('email', '').strip().lower()
        company = row.get('company', '').strip()
        first = row.get('first', '').strip()
        last = row.get('last', '').strip()

        if not email:
          print(f'Warning: Skipping row {row_num} ({company}) - missing email.')
          continue

        if email in seen_emails:
          print(
              f'Notice: Filtered out duplicate email entry: {email} (Row'
              f' {row_num})'
          )
          continue

        seen_emails.add(email)
        clinics.append({
            'company': company,
            'first': first,
            'last': last,
            'email': row.get('email', '').strip(),
        })

    print(f'Successfully loaded {len(clinics)} unique clinics from {filename}.')

  except csv.Error as e:
    print(f'CSV Parsing Error in {filename} at line {e.line_num}: {e}')
  except Exception as e:
    print(f'Unexpected error while reading {filename}: {e}')

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
    <h2>Your Daily Brooklyn Mental Health Clinics Directory</h2>
    <p>Here is your fresh batch of verified clinics for today:</p>
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; font-family: Arial, sans-serif; font-size: 14px;">
      <tr style="background-color: #f2f2f2;">
        <th>Name of Company</th>
        <th>First name</th>
        <th>Last name</th>
        <th>Email address</th>
      </tr>
    """
  for c in clinics:
    html += f"""
      <tr>
        <td>{c['company']}</td>
        <td>{c['first']}</td>
        <td>{c['last']}</td>
        <td><a href="mailto:{c['email']}">{c['email']}</a></td>
      </tr>
        """
  html += '</table>'
  return html


def send_email():
  sender_email = os.environ.get('EMAIL_USER')
  sender_password = os.environ.get('EMAIL_PASSWORD')
  recipient_email = os.environ.get('RECIPIENT_EMAIL')

  if not sender_email or not sender_password or not recipient_email:
    print(
        'Error: Missing required environment variables (EMAIL_USER,'
        ' EMAIL_PASSWORD, or RECIPIENT_EMAIL).'
    )
    return

  master_pool = load_clinics_from_csv('clinics_master.csv')
  if not master_pool:
    print('Error: Master clinic pool is empty or invalid. Aborting execution.')
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
  except smtplib.SMTPAuthenticationError:
    print(
        'SMTP Authentication Error: Failed to login. Please verify your'
        ' EMAIL_USER and Gmail App Password.'
    )
  except smtplib.SMTPException as e:
    print(f'An SMTP error occurred while sending the email: {e}')
  except Exception as e:
    print(f'An unexpected error occurred during email transmission: {e}')


if __name__ == '__main__':
  send_email()