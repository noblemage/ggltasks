import os
import google.oauth2.credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/tasks']
HOME_DIR = os.path.expanduser('~')
GTASK_DIR = os.path.join(HOME_DIR, '.gtask')
TOKEN_PATH = os.path.join(GTASK_DIR, 'token.json')
CLIENT_SECRETS_PATH = os.path.join(GTASK_DIR, 'client_secrets.json')


def _ensure_dir_exists():
    os.makedirs(GTASK_DIR, exist_ok=True)


def get_credentials():
    _ensure_dir_exists()

    if not os.path.exists(CLIENT_SECRETS_PATH):
        raise FileNotFoundError(
            f"\n\n  Google API credentials not found!\n"
            f"  Expected location: {CLIENT_SECRETS_PATH}\n\n"
            f"  Steps to fix:\n"
            f"  1. Go to https://console.cloud.google.com/\n"
            f"  2. APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID\n"
            f"  3. Application type: Desktop App\n"
            f"  4. Download the JSON file, rename it to 'client_secrets.json'\n"
            f"  5. Move it to: {CLIENT_SECRETS_PATH}\n"
        )

    creds = None
    if os.path.exists(TOKEN_PATH):
        try:
            creds = google.oauth2.credentials.Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception as e:
            print(f"Error loading token.json: {e}. Initiating full re-authentication.")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Token refresh failed: {e}. Initiating full re-authentication.")
                creds = None
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    return creds
