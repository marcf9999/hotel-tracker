const SUPABASE_URL = 'https://igkiwdqpoeptchabalgn.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlna2l3ZHFwb2VwdGNoYWJhbGduIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMDY2NzAsImV4cCI6MjA5MTY4MjY3MH0.zKv2LVd2bmVe99U9qNL_CZxWxSaKVjXLIhaBM8V617w';

// The UMD build exposes window.supabase with a createClient method
let db;
if (window.supabase && window.supabase.createClient) {
  db = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
} else {
  console.error('Supabase CDN not loaded. window.supabase =', window.supabase);
  console.error('Available keys:', window.supabase ? Object.keys(window.supabase) : 'undefined');
}
const supabase = db;

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
