import os
import sys
import json
import urllib.parse
import httpx

if len(sys.argv) < 2:
    print("Usage: python pkce_exchange.py <redirected_url>")
    sys.exit(1)

redirected_url = sys.argv[1]
parsed_url = urllib.parse.urlparse(redirected_url)
query_params = urllib.parse.parse_qs(parsed_url.query)

if "code" not in query_params:
    print("Error: No authorization code found in the URL.")
    sys.exit(1)

code = query_params["code"][0]

# Read saved verifier
script_dir = os.path.dirname(os.path.abspath(__file__))
verifier_path = os.path.join(script_dir, "verifier.txt")
if not os.path.exists(verifier_path):
    print("Error: verifier.txt not found. Run pkce_login.py first.")
    sys.exit(1)

with open(verifier_path, "r") as f:
    verifier = f.read().strip()

tenant_id = "2f2180dc-e652-45f1-b0d5-676060cf1071"
client_id = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
redirect_uri = "https://login.microsoftonline.com/common/oauth2/nativeclient"

token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

payload = {
    "grant_type": "authorization_code",
    "client_id": client_id,
    "code": code,
    "redirect_uri": redirect_uri,
    "code_verifier": verifier
}

print("Exchanging authorization code for access token...")
response = httpx.post(token_url, data=payload)

if response.status_code != 200:
    print(f"Error: Token exchange failed ({response.status_code}): {response.text}")
    sys.exit(1)

token_data = response.json()
access_token = token_data.get("access_token")

# Save token locally inside remote-mcp-app folder
token_json_path = os.path.join(os.path.dirname(script_dir), "token.json")
with open(token_json_path, "w", encoding="utf-8") as f:
    json.dump({
        "access_token": access_token,
        "retrieved_at": "2026-07-21T11:17:38Z"
    }, f, indent=2)

# Clean up verifier
if os.path.exists(verifier_path):
    os.remove(verifier_path)

print("SUCCESS: token.json updated successfully inside remote-mcp-app using PKCE CLI!")
