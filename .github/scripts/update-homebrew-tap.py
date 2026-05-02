#!/usr/bin/env python3
"""
update-homebrew-tap.py
Post-release script: compute sha256 for all platforms and push Formula + Cask to homebrew-tap.
Usage: python3 update-homebrew-tap.py <version> <pat>
e.g.   python3 update-homebrew-tap.py 0.9.1 ghp_xxx
"""

import sys
import json
import base64
import hashlib
import urllib.request

VERSION = sys.argv[1].lstrip("v")
PAT = sys.argv[2]
TAG = f"v{VERSION}"
BASE_URL = f"https://github.com/unrealandychan/rekipedia-releases/releases/download/{TAG}"
TAP_REPO = "unrealandychan/homebrew-tap"

PLATFORMS = {
    "darwin_amd64": f"{BASE_URL}/rekipedia_darwin_amd64.tar.gz",
    "darwin_arm64": f"{BASE_URL}/rekipedia_darwin_arm64.tar.gz",
    "linux_amd64":  f"{BASE_URL}/rekipedia_linux_amd64.tar.gz",
    "linux_arm64":  f"{BASE_URL}/rekipedia_linux_arm64.tar.gz",
}


def sha256_url(url):
    print(f"  Downloading {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "update-tap/1.0"})
    with urllib.request.urlopen(req) as resp:
        data = resp.read()
    return hashlib.sha256(data).hexdigest()


def gh_get_sha(path):
    url = f"https://api.github.com/repos/{TAP_REPO}/contents/{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {PAT}",
        "Accept": "application/vnd.github.v3+json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())["sha"]
    except Exception:
        return None  # file doesn't exist yet


def gh_put(path, content, sha, message):
    url = f"https://api.github.com/repos/{TAP_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "committer": {"name": "HermesBot", "email": "bot@rekipedia.dev"},
    }
    if sha:
        payload["sha"] = sha
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "Authorization": f"token {PAT}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    return result["commit"]["sha"]


# ── 1. Compute sha256 ──────────────────────────────────────────────────────────
print(f"Computing sha256 for {TAG}...")
shas = {p: sha256_url(u) for p, u in PLATFORMS.items()}
for p, s in shas.items():
    print(f"  {p}: {s}")


# ── 2. Formula (Formula/rekipedia.rb) ────────────────────────────────────────
formula = f"""# typed: false
# frozen_string_literal: true

class Rekipedia < Formula
  desc "Agentic repo-to-wiki — scan any codebase into a structured knowledge base"
  homepage "https://github.com/unrealandychan/rekipedia"
  version "{VERSION}"
  license "MIT"

  on_macos do
    if Hardware::CPU.intel?
      url "{PLATFORMS['darwin_amd64']}"
      sha256 "{shas['darwin_amd64']}"
    end
    if Hardware::CPU.arm?
      url "{PLATFORMS['darwin_arm64']}"
      sha256 "{shas['darwin_arm64']}"
    end
  end

  on_linux do
    if Hardware::CPU.intel? && Hardware::CPU.is_64_bit?
      url "{PLATFORMS['linux_amd64']}"
      sha256 "{shas['linux_amd64']}"
    end
    if Hardware::CPU.arm? && Hardware::CPU.is_64_bit?
      url "{PLATFORMS['linux_arm64']}"
      sha256 "{shas['linux_arm64']}"
    end
  end

  def install
    bin.install "reki"
  end

  test do
    system "#{bin}/reki", "--version"
  end
end
"""

print("\nPushing Formula/rekipedia.rb ...")
sha = gh_get_sha("Formula/rekipedia.rb")
commit = gh_put("Formula/rekipedia.rb", formula, sha, f"chore: bump rekipedia to {TAG}")
print(f"  ✓ commit {commit[:7]}")

print(f"\n✅ Homebrew tap updated to {TAG}")
