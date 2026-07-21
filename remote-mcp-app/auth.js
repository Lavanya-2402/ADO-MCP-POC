const https = require('https');
const fs = require('fs');
const http = require('http');
const crypto = require('crypto');
const querystring = require('querystring');
const { exec } = require('child_process');

const tenantId = "2f2180dc-e652-45f1-b0d5-676060cf1071";
const clientId = "04b07795-8ddb-461a-bbee-02f9e1bf7b46";
const redirectUri = "http://localhost:8400/";
const scope = "https://mcp.dev.azure.com/.default";
const path = require('path');
const configPath = path.join(__dirname, 'token.json');

function base64url(buffer) {
  return buffer.toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');
}

const verifier = base64url(crypto.randomBytes(32));
const challenge = base64url(crypto.createHash('sha256').update(verifier).digest());

const server = http.createServer((req, res) => {
  const urlObj = new URL(req.url, `http://${req.headers.host}`);
  const code = urlObj.searchParams.get('code');
  
  if (code) {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end("<html><body style='font-family:sans-serif;text-align:center;padding-top:50px;'><h2>Authentication Successful!</h2><p>You can close this window now.</p></body></html>");
    
    server.close();
    exchangeCode(code);
  } else {
    res.writeHead(400);
    res.end("No code received.");
  }
});

server.listen(8400, () => {
  const authUrl = `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/authorize?` +
    `client_id=${clientId}&` +
    `response_type=code&` +
    `redirect_uri=${encodeURIComponent(redirectUri)}&` +
    `scope=${encodeURIComponent(scope)}&` +
    `code_challenge=${challenge}&` +
    `code_challenge_method=S256`;

  console.log("======================================================================");
  console.log("ACTION REQUIRED: Open this URL in your browser to sign in:");
  console.log(authUrl);
  console.log("======================================================================");
  
  exec(`start "" "${authUrl}"`);
});

function exchangeCode(code) {
  const postData = querystring.stringify({
    grant_type: "authorization_code",
    client_id: clientId,
    code: code,
    redirect_uri: redirectUri,
    code_verifier: verifier
  });

  const options = {
    hostname: 'login.microsoftonline.com',
    path: `/${tenantId}/oauth2/v2.0/token`,
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Content-Length': Buffer.byteLength(postData)
    }
  };

  const req = https.request(options, (res) => {
    let body = '';
    res.on('data', (chunk) => body += chunk);
    res.on('end', () => {
      const parsed = JSON.parse(body);
      if (res.statusCode === 200) {
        const token = parsed.access_token;
        console.log("Token retrieved successfully!");

        const tokenData = {
          "access_token": token,
          "retrieved_at": new Date().toISOString()
        };
        fs.writeFileSync(configPath, JSON.stringify(tokenData, null, 2), 'utf8');
        console.log("SUCCESS: token.json updated successfully inside remote-mcp-app!");
        process.exit(0);
      } else {
        console.error("Token exchange failed:", parsed);
        process.exit(1);
      }
    });
  });

  req.on('error', (e) => {
    console.error(e);
    process.exit(1);
  });
  req.write(postData);
  req.end();
}
