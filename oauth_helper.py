# oauth_helper.py
#
# Run this once to get your LinkedIn access token.
# It opens a browser, you approve the OAuth flow, and it prints the token.
# Copy the token into your .env file.
#
# Usage: python oauth_helper.py

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
import webbrowser
import requests
import os

load_dotenv()

CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:8000/callback"
SCOPES = "openid profile w_member_social"

if not CLIENT_ID or not CLIENT_SECRET:
    print("Error: LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be set in your .env file.")
    print("Create a LinkedIn app at https://www.linkedin.com/developers/apps/new")
    exit(1)

auth_url = (
    f"https://www.linkedin.com/oauth/v2/authorization"
    f"?response_type=code&client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT_URI}"
    f"&scope={SCOPES}"
)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = parse_qs(urlparse(self.path).query).get("code", [None])[0]
        if code:
            r = requests.post("https://www.linkedin.com/oauth/v2/accessToken", data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            })
            token = r.json().get("access_token")
            sub = r.json().get("sub")
            print(f"\nLinkedIn response: {r.status_code}")
            print(f"\n✓ LINKEDIN_ACCESS_TOKEN={token}")
            if sub:
                print(f"✓ LINKEDIN_PERSON_URN=urn:li:person:{sub}")
            print("\nCopy these values into your .env file.")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Token retrieved. You can close this window.")
        else:
            print("No code received in callback.")
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass

print("Opening LinkedIn authorization page...")
webbrowser.open(auth_url)
print("Waiting for OAuth callback on localhost:8000 ...")
HTTPServer(("localhost", 8000), Handler).handle_request()
