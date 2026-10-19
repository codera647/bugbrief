import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const python = resolve(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
if (!existsSync(python)) {
  console.error('Create the Python .venv first. See README.md.');
  process.exit(1);
}
const api = spawn(python, ['-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', '8000'], { cwd: resolve(root, 'backend'), stdio: 'inherit', windowsHide: true });
const ui = spawn(process.execPath, [resolve(root, 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1'], { cwd: resolve(root, 'frontend'), stdio: 'inherit', windowsHide: true });
let stopping = false;
const stop = () => { if (stopping) return; stopping = true; api.kill(); ui.kill(); };
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
for (const child of [api, ui]) {
  child.on('error', error => { console.error(error.message); stop(); process.exitCode = 1; });
  child.on('exit', code => { stop(); if (code) process.exitCode = code; });
}
