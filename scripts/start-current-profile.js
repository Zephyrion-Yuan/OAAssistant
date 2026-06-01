import { spawn } from 'node:child_process';
import process from 'node:process';

const child = spawn('npm.cmd', ['start'], {
  cwd: process.cwd(),
  env: {
    ...process.env,
    MEGANT_EDGE_PROFILE_MODE: 'current'
  },
  stdio: 'inherit',
  shell: true
});

child.on('exit', (code) => {
  process.exit(code ?? 0);
});
