const response = await fetch('http://127.0.0.1:8787/api/oa/login/test-live', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
  body: '{}'
});
const data = await response.json();
console.log(JSON.stringify(data, null, 2));
process.exit(response.ok && data.ok ? 0 : 1);
