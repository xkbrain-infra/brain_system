#!/usr/bin/env python3
"""Simple OAuth callback server for brain-google-api"""

import http.server
import socketserver
import urllib.parse
import json
import sys

PORT = 8080

class OAuthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        if 'code' in params:
            code = params['code'][0]
            print(f"\n=== AUTHORIZATION CODE ===\n{code}\n===========================\n")
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Authorization successful!</h1><p>You can close this window and return to the terminal.</p></body></html>")

            # Save code to file for easy retrieval
            with open('/tmp/oauth_code.txt', 'w') as f:
                f.write(code)

            # Also output to stderr so it's visible
            sys.stderr.write(f"\n!!! AUTHORIZATION CODE RECEIVED: {code} !!!\n")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code parameter")

    def log_message(self, format, *args):
        pass  # Suppress logging

print(f"Starting OAuth callback server on http://localhost:{PORT}/callback")
print("Waiting for authorization...")

with socketserver.TCPServer(("", PORT), OAuthHandler) as httpd:
    httpd.handle_request()  # Handle only one request
