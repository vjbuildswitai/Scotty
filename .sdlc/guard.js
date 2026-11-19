#!/usr/bin/env node
// SDLC guard - one script behind Claude Code hooks, git hooks and CI.
// Modes: claude | session | pre-commit | pre-push | ci-diff <base-ref> | install
// Config: .sdlc/config.json   Test lock: .sdlc/test-lock   Kit: D:/Projects/sdlc-kit
'use strict';
const fs = require('fs'), path = require('path'), cp = require('child_process');

function sh(cmd) { try { return cp.execSync(cmd, { stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: 64 * 1024 * 1024 }).toString(); } catch { return ''; } }
const ROOT = sh('git rev-parse --show-toplevel').trim() || process.cwd();
function readJSON(p) { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return {}; } }
const CFG = Object.assign({
  protectedBranches: ['main'], deployPatterns: [], secretPaths: [], allowSecretPaths: [],
  secretPatterns: [], verify: ''
}, readJSON(path.join(ROOT, '.sdlc', 'config.json')));

function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function glob2re(g) {
  const re = g.split('').map(ch => '.+^${}()|[]\\'.includes(ch) ? '\\' + ch : ch).join('')
    .replace(/\*\*\//g, '\u0000').replace(/\*\*/g, '\u0001').replace(/\*/g, '[^/]*').replace(/\?/g, '[^/]')
    .replace(/\u0000/g, '(?:.*/)?').replace(/\u0001/g, '.*');
  return new RegExp('^' + re + '$', 'i');
}
function real(p) {
  let cur = path.resolve(p); const rest = [];
  while (!fs.existsSync(cur)) { rest.unshift(path.basename(cur)); const up = path.dirname(cur); if (up === cur) break; cur = up; }
  try { cur = fs.realpathSync.native(cur); } catch {}
  return path.join(cur, ...rest);
}
const REAL_ROOT = real(ROOT);
function rel(p) {
  if (!p) return '';
  const r = path.isAbsolute(p) ? path.relative(REAL_ROOT, real(p)) : p;
  return r.split(path.sep).join('/').replace(/^\.\//, '');
}
function matchAny(file, globs) {
  const base = file.split('/').pop();
  return (globs || []).some(g => { const re = glob2re(g); return re.test(file) || (!g.includes('/') && re.test(base)); });
}
const isSecretPath = f => matchAny(f, CFG.secretPaths) && !matchAny(f, CFG.allowSecretPaths);
function lockedTests() {
  try { return fs.readFileSync(path.join(ROOT, '.sdlc', 'test-lock'), 'utf8').split(/\r?\n/).map(s => s.trim()).filter(s => s && !s.startsWith('#')); }
  catch { return []; }
}
const isLocked = f => lockedTests().some(l => f === l || glob2re(l).test(f));
const SECRET_RES = [
  /sk-ant-[A-Za-z0-9_-]{20,}/, /\bsk-(?:proj-)?[A-Za-z0-9]{32,}/, /\bAKIA[0-9A-Z]{16}\b/,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/, /\bgh[pousr]_[A-Za-z0-9]{30,}/, /\bxox[baprs]-[A-Za-z0-9-]{10,}/,
  /\bAIza[0-9A-Za-z_-]{35}\b/
].concat((CFG.secretPatterns || []).map(s => new RegExp(s)));
const findSecret = text => SECRET_RES.find(r => r.test(text));
const releaseOk = cmd => process.env.SDLC_RELEASE_OK === '1' || /\bSDLC_RELEASE_OK\s*=\s*['"]?1/.test(cmd || '');
const testsUnlocked = () => process.env.SDLC_UNLOCK_TESTS === '1';

function block(msg) { process.stderr.write('[sdlc-guard] BLOCKED: ' + msg + '\n'); process.exit(2); }

// ---- Claude Code PreToolUse hook: stdin is the tool call as JSON ----
function claude() {
  let ev = {};
  try { ev = JSON.parse(fs.readFileSync(0, 'utf8') || '{}'); } catch { return; }
  const tool = ev.tool_name || '', ti = ev.tool_input || {};
  if (/^(Edit|Write|MultiEdit|NotebookEdit)$/.test(tool)) {
    const f = rel(ti.file_path || ti.notebook_path || '');
    if (f && isSecretPath(f)) block(`${f} is a secrets file. VJ edits it by hand; never through Claude.`);
    if (f && isLocked(f) && !testsUnlocked()) block(`${f} is locked in .sdlc/test-lock (test-first fix). Fix the code, not the test.`);
    const added = [ti.content, ti.new_string, ti.new_source].concat((ti.edits || []).map(e => e.new_string)).filter(Boolean).join('\n');
    const hit = findSecret(added);
    if (hit) block(`the new text looks like a secret (${hit}). Keys belong in .env or the server environment, never in code.`);
    return;
  }
  if (tool === 'Bash' || tool === 'PowerShell') {
    const c = String(ti.command || '');
    if (releaseOk(c)) return;
    if (/\bgit\b[^\n;&|]*\bpush\b/.test(c)) {
      if (/(\s--force\b|\s-f\b|\s--force-with-lease\b)/.test(c)) block("force-push needs VJ's OK. After he approves, rerun with SDLC_RELEASE_OK=1.");
      const hit = CFG.protectedBranches.find(b => new RegExp('(^|[\\s:/+])' + esc(b) + '(\\s|$)').test(c.split(/\bpush\b/)[1] || ''));
      if (hit) block(`push to protected branch "${hit}" needs VJ's OK. Push a feature branch and open a PR instead.`);
    }
    for (const p of CFG.deployPatterns || []) {
      if (new RegExp(p, 'i').test(c)) block(`this looks like a production deploy (matches "${p}"). Needs VJ's explicit OK in the chat; then rerun with SDLC_RELEASE_OK=1.`);
    }
  }
}

// ---- git pre-commit: runs for every committer (Claude Code, Desktop Commander, VJ) ----
function preCommit() {
  const files = sh('git diff --cached --name-only --diff-filter=ACMR').split('\n').map(s => s.trim()).filter(Boolean);
  const secrets = files.filter(isSecretPath);
  if (secrets.length) block('secrets files staged: ' + secrets.join(', ') + '. Unstage (git restore --staged <file>) and add them to .gitignore.');
  if (!testsUnlocked()) {
    const locked = files.filter(isLocked);
    if (locked.length) block('locked test files changed: ' + locked.join(', ') + '. A test-first fix must not edit its own test (SDLC_UNLOCK_TESTS=1 with VJ\'s OK).');
  }
  scanDiff(sh('git diff --cached -U0 --no-color'));
}

function scanDiff(diff) {
  let file = '';
  for (const line of diff.split('\n')) {
    if (line.startsWith('+++ ')) { file = line.replace(/^\+\+\+ (b\/)?/, ''); continue; }
    if (!line.startsWith('+') || isSecretPathAllowed(file)) continue;
    const hit = findSecret(line);
    if (hit) block(`${file}: an added line looks like a secret (${hit}): ${line.slice(0, 90)}`);
  }
}
const isSecretPathAllowed = f => matchAny(f, CFG.allowSecretPaths);

// ---- git pre-push: stdin has "<local ref> <local sha> <remote ref> <remote sha>" per line ----
function prePush() {
  if (releaseOk('')) return;
  const lines = (fs.readFileSync(0, 'utf8') || '').split(/\r?\n/).filter(Boolean);
  for (const l of lines) {
    const [, lsha, rref] = l.split(' ');
    const b = (rref || '').replace(/^refs\/heads\//, '');
    if (CFG.protectedBranches.includes(b) && !/^0+$/.test(lsha || '')) {
      block(`push to protected branch "${b}" needs VJ's OK. Open a PR from a feature branch, or after his OK: SDLC_RELEASE_OK=1 git push ...`);
    }
  }
}

// ---- CI: same checks over a whole PR, server side ----
function ciDiff(base) {
  const range = `${base || 'origin/main'}...HEAD`;
  const files = sh(`git diff --name-only --diff-filter=ACMR ${range}`).split('\n').map(s => s.trim()).filter(Boolean);
  const secrets = files.filter(isSecretPath);
  if (secrets.length) block('secrets files in this PR: ' + secrets.join(', '));
  scanDiff(sh(`git diff -U0 --no-color ${range}`));
  console.log(`[sdlc-guard] ci-diff OK (${files.length} files checked against ${range})`);
}

// Git config for this checkout only: linked worktrees get --worktree config, so other checkouts keep their hooks.
function isLinkedWorktree() {
  const gd = sh('git rev-parse --absolute-git-dir').trim(), cd = sh('git rev-parse --git-common-dir').trim();
  return !!gd && !!cd && path.resolve(ROOT, gd) !== path.resolve(ROOT, cd);
}
function setGitCfg(k, v) {
  if (isLinkedWorktree()) { sh('git config extensions.worktreeConfig true'); sh(`git config --worktree ${k} "${v}"`); }
  else sh(`git config ${k} "${v}"`);
}

// ---- install: point git at .githooks (once per clone; SessionStart does it automatically) ----
function install(quiet) {
  const cur = sh('git config --get core.hooksPath').trim();
  if (cur && cur !== '.githooks' && !sh('git config --get sdlc.chainHooksPath').trim()) setGitCfg('sdlc.chainHooksPath', cur);
  if (!cur && CFG.chainHooks) setGitCfg('sdlc.chainHooksPath', CFG.chainHooks);
  if (cur !== '.githooks') setGitCfg('core.hooksPath', '.githooks');
  if (!quiet) console.log('[sdlc-guard] git hooks active (core.hooksPath=.githooks)');
}

// ---- SessionStart: make sure hooks are on and remind the session of the rules ----
function session() {
  install(true);
  const lock = lockedTests();
  const out = [
    'SDLC rules for this repo (see CLAUDE.md "How we build"):',
    '- Plan first: docs/plans/<date>-<slug>.md, VJ approves before code.',
    `- Work on a feature branch; protected: ${CFG.protectedBranches.join(', ')}.`,
    `- Done = verified: ${CFG.verify || 'see CLAUDE.md'} (paste the output).`,
    '- Deploys and protected pushes need VJ\'s OK (SDLC_RELEASE_OK=1 after he approves).'
  ];
  if (lock.length) out.push('- Locked tests (test-first fix in progress): ' + lock.join(', '));
  console.log(out.join('\n'));
}

const [mode, arg] = process.argv.slice(2);
({ claude, session, 'pre-commit': preCommit, 'pre-push': prePush, 'ci-diff': () => ciDiff(arg), install: () => install(arg === '--quiet') }[mode] || (() => {
  console.error('usage: guard.js claude|session|pre-commit|pre-push|ci-diff <base>|install'); process.exit(1);
}))();
