import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

import re
from core.overleaf_import import _download, _github_zip_url

url = "https://www.overleaf.com/latex/templates/harshibars-resume/sbcyynmtpnyd"
data, final = _download(url)
text = data.decode("utf-8", errors="ignore")

print("Searching download links in HTML page...")
links = re.findall(r'href=["\']([^"\']+)["\']', text)
for link in links:
    if any(k in link.lower() for k in ["download", "zip", "github", "raw", "project", "open"]):
        print(" ->", link)

# Also check for GitHub repos mentioned in text
gh = set(re.findall(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text))
print("GitHub repos found:", gh)
for g in gh:
    zip_u = _github_zip_url(g)
    print(" -> GitHub Zip URL:", zip_u)
