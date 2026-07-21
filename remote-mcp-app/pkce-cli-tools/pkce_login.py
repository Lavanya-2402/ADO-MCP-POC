import os
import secrets
import hashlib
import base64
import urllib.parse

def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').replace('=', '')

# Generate PKCE verifier and challenge
verifier = base64url_encode(secrets.token_bytes(32))
challenge = base64url_encode(hashlib.sha256(verifier.encode('utf-8')).digest())

# Save verifier to a temporary file
script_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(script_dir, "verifier.txt"), "w") as f:
    f.write(verifier)

tenant_id = "2f2180dc-e652-45f1-b0d5-676060cf1071"
client_id = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
redirect_uri = "https://login.microsoftonline.com/common/oauth2/nativeclient"
scope = "https://mcp.dev.azure.com/.default"

auth_url = (
    f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?"
    f"client_id={client_id}&"
    f"response_type=code&"
    f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
    f"scope={urllib.parse.quote(scope)}&"
    f"code_challenge={challenge}&"
    f"code_challenge_method=S256"
)

print("======================================================================")
print("ACTION REQUIRED: Open this URL in your browser to sign in:")
print(auth_url)
print("======================================================================")
