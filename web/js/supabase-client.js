const SUPABASE_URL = 'https://igkiwdqpoeptchabalgn.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlna2l3ZHFwb2VwdGNoYWJhbGduIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMDY2NzAsImV4cCI6MjA5MTY4MjY3MH0.zKv2LVd2bmVe99U9qNL_CZxWxSaKVjXLIhaBM8V617w';

// The UMD build exposes window.supabase with a createClient method
let db;
try {
  const mod = window.supabase;
  if (mod && mod.createClient) {
    db = mod.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  } else if (mod) {
    // Some CDN versions nest it differently
    const keys = Object.keys(mod);
    console.log('supabase module keys:', keys);
    if (mod.default && mod.default.createClient) {
      db = mod.default.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
    }
  } else {
    console.error('window.supabase is undefined — CDN script may not have loaded');
  }
} catch (e) {
  console.error('Supabase init error:', e);
}
// Overwrite the SDK module on window.supabase with the initialized client
window.supabase = db;

function showToast(msg, type = 'success') {
  const t = document.createElement('div');
  t.className = `toast toast-${type}`;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function statusBadge(status) {
  const label = status === 'not_available' ? 'Not Yet' :
                status === 'available' ? 'Available' :
                status === 'blocked' ? 'Blocked' :
                status === 'error' ? 'Error' : status;
  return `<span class="badge badge-${status}">${label}</span>`;
}
