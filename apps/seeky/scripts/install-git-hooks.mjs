// Points Git at the repository's versioned hooks (.githooks/) so the
// pre-commit format check runs for every contributor. Runs from the npm
// `prepare` script; it never fails an install. core.hooksPath replaces
// .git/hooks, so .githooks/ also carries the Git LFS hooks.
import { execFileSync } from "node:child_process";

const HOOKS_PATH = ".githooks";

function git(args) {
  return execFileSync("git", args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  }).trim();
}

try {
  if (process.env.CI) {
    process.exit(0);
  }
  const root = git(["rev-parse", "--show-toplevel"]);
  let current = "";
  try {
    current = git(["-C", root, "config", "--local", "core.hooksPath"]);
  } catch {
    // Unset: `git config` exits non-zero.
  }
  if (current === HOOKS_PATH) {
    process.exit(0);
  }
  if (current !== "") {
    console.warn(
      `[hooks] core.hooksPath is already "${current}"; leaving it unchanged. ` +
        `Run "git config core.hooksPath ${HOOKS_PATH}" to use Seeky's hooks.`,
    );
    process.exit(0);
  }
  git(["-C", root, "config", "--local", "core.hooksPath", HOOKS_PATH]);
  console.log(`[hooks] Git hooks enabled from ${HOOKS_PATH}/`);
} catch {
  // Not a Git checkout (for example a source archive) or Git not installed.
}
