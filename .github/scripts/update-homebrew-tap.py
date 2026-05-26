#!/usr/bin/env python3
"""
update-homebrew-tap.py
Post-release script: read sha256 from goreleaser's checksums.txt and push Formula to homebrew-tap.
Usage: python3 update-homebrew-tap.py <version>
e.g.   python3 update-homebrew-tap.py 0.9.1
"""

import base64
import json
import os
import sys
import urllib.request

VERSION = sys.argv[1].lstrip("v")
PAT = os.environ["HOMEBREW_TAP_TOKEN"]
TAG = f"v{VERSION}"
BASE_URL = f"https://github.com/unrealandychan/rekipedia/releases/download/{TAG}"
TAP_REPO = "unrealandychan/homebrew-tap"

PLATFORMS = {
    "darwin_amd64": f"{BASE_URL}/rekipedia_darwin_amd64.tar.gz",
    "darwin_arm64": f"{BASE_URL}/rekipedia_darwin_arm64.tar.gz",
    "linux_amd64":  f"{BASE_URL}/rekipedia_linux_amd64.tar.gz",
    "linux_arm64":  f"{BASE_URL}/rekipedia_linux_arm64.tar.gz",
}

CHECKSUM_KEYS = {
    "darwin_amd64": "rekipedia_darwin_amd64.tar.gz",
    "darwin_arm64": "rekipedia_darwin_arm64.tar.gz",
    "linux_amd64":  "rekipedia_linux_amd64.tar.gz",
    "linux_arm64":  "rekipedia_linux_arm64.tar.gz",
}


def read_checksums_from_dist():
    """Read sha256 from goreleaser's dist/checksums.txt (no download needed)."""
    checksums_path = os.path.join(os.path.dirname(__file__), "..", "..", "go", "dist", "checksums.txt")
    checksums_path = os.path.normpath(checksums_path)
    shas = {}
    print(f"Reading checksums from {checksums_path} ...")
    with open(checksums_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Format: <sha256>  <filename>
            parts = line.split(None, 1)
            if len(parts) == 2:
                sha, filename = parts
                for platform, key in CHECKSUM_KEYS.items():
                    if filename == key:
                        shas[platform] = sha
                        print(f"  {platform}: {sha}")
    return shas


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


# ── 1. Read sha256 from dist/checksums.txt ────────────────────────────────────
shas = read_checksums_from_dist()
missing = [p for p in CHECKSUM_KEYS if p not in shas]
if missing:
    raise RuntimeError(f"Missing checksums for: {missing}")


# ── 2. Formula (Formula/rekipedia.rb) ────────────────────────────────────────
formula = rf"""# typed: false
# frozen_string_literal: true

class Rekipedia < Formula
  desc "Agentic repo-to-wiki — scan any codebase into a structured knowledge base"
  homepage "https://github.com/unrealandychan/rekipedia"
  version "{VERSION}"
  license :cannot_represent

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
    system "\#{bin}/reki", "--version"
  end
end
"""

print("\nPushing Formula/rekipedia.rb ...")
sha = gh_get_sha("Formula/rekipedia.rb")
commit = gh_put("Formula/rekipedia.rb", formula, sha, f"chore: bump rekipedia to {TAG}")
print(f"  ✓ commit {commit[:7]}")

print(f"\n✅ Homebrew tap updated to {TAG}")
