const response = await fetch('http://127.0.0.1:8787/api/oa/login/start', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
  body: '{}'
});
const data = await response.json();
console.log(JSON.stringify(data, null, 2));
if (!response.ok) process.exit(1);
console.log('\nOA login page opened in the tool-managed Edge session. Scan the QR code there and keep that Edge window open.');
