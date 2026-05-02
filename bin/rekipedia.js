#!/usr/bin/env node
// rekipedia npm shim
// Delegates to the Python package (installed via uv or pip).
// Security: uses execFileSync with an explicit args array — never shell:true
//           or string interpolation of user-supplied values.

"use strict";

const { execFileSync } = require("child_process");

const args = process.argv.slice(2);

function tryRun(cmd, cmdArgs) {
  try {
    execFileSync(cmd, cmdArgs, { stdio: "inherit" });
    return true;
  } catch (err) {
    if (err.status !== undefined) {
      // Command ran but exited non-zero — propagate exit code
      process.exit(err.status);
    }
    // Command not found (ENOENT) — return false to try next strategy
    return false;
  }
}

// Strategy 1: uvx (preferred — no global install needed)
if (tryRun("uvx", ["rekipedia", ...args])) process.exit(0);

// Strategy 2: python -m rekipedia (already pip-installed)
if (tryRun("python3", ["-m", "rekipedia", ...args])) process.exit(0);
if (tryRun("python", ["-m", "rekipedia", ...args])) process.exit(0);

// No viable runtime found
console.error(
  [
    "",
    "rekipedia: could not find a Python runtime to run the tool.",
    "",
    "Please install one of:",
    "  uv  (recommended) — https://docs.astral.sh/uv/getting-started/installation/",
    "  pip install rekipedia",
    "",
  ].join("\n")
);
process.exit(1);
