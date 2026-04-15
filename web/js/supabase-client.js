var SUPABASE_URL = 'https://igkiwdqpoeptchabalgn.supabase.co';
var SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlna2l3ZHFwb2VwdGNoYWJhbGduIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzYxMDY2NzAsImV4cCI6MjA5MTY4MjY3MH0.zKv2LVd2bmVe99U9qNL_CZxWxSaKVjXLIhaBM8V617w';

// Initialize Supabase client — wrapped in IIFE to avoid var/const collision
// with the CDN's top-level `var supabase = ...`
(function () {
  var mod = window.supabase;
  if (mod && mod.createClient) {
    window.supabase = mod.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  } else if (mod && mod.default && mod.default.createClient) {
    window.supabase = mod.default.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  } else {
    console.error('Supabase SDK not loaded — window.supabase:', mod);
    window.supabase = null;
  }
})();

function showToast(msg, type) {
  type = type || 'success';
  var t = document.createElement('div');
  t.className = 'toast toast-' + type;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(function () { t.remove(); }, 3000);
}

function formatDate(iso) {
  if (!iso) return '\u2014';
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatDateTime(iso) {
  if (!iso) return '\u2014';
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function statusBadge(status) {
  var label = status === 'not_available' ? 'Not Yet' :
              status === 'available' ? 'Available' :
              status === 'blocked' ? 'Blocked' :
              status === 'error' ? 'Error' : status;
  return '<span class="badge badge-' + status + '">' + label + '</span>';
}

// Booking window: max days in advance each source allows
var BOOKING_WINDOWS = {
  marriott: 354,
  windsurfer: 365,
  airbnb: 365
};

function getBookingWindowInfo(hotel) {
  var maxDays = BOOKING_WINDOWS[hotel.source] || 365;
  var today = new Date();
  today.setHours(0, 0, 0, 0);
  var checkin = new Date(hotel.checkin_date + 'T00:00:00');
  var daysUntilCheckin = Math.ceil((checkin - today) / 86400000);

  // The date when this checkin opens for booking
  var opensOn = new Date(checkin);
  opensOn.setDate(opensOn.getDate() - maxDays);

  var isBookable = daysUntilCheckin <= maxDays;
  var daysUntilOpen = Math.ceil((opensOn - today) / 86400000);

  return {
    isBookable: isBookable,
    opensOn: opensOn,
    daysUntilOpen: isBookable ? 0 : daysUntilOpen,
    maxDays: maxDays
  };
}

function bookingWindowBadge(hotel) {
  var info = getBookingWindowInfo(hotel);
  if (info.isBookable) return '';
  var opensStr = info.opensOn.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return '<span class="badge badge-window">Opens ' + opensStr + '</span>';
}

function bookingWindowDetail(hotel) {
  var info = getBookingWindowInfo(hotel);
  if (info.isBookable) {
    return '<span style="color:var(--green);">Within booking window (' + info.maxDays + '-day limit)</span>';
  }
  var opensStr = info.opensOn.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  return '<span style="color:var(--yellow);">Opens for booking ' + opensStr + ' (' + info.daysUntilOpen + ' days away)</span>';
}
