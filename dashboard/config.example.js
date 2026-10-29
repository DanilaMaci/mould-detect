// Copy to config.js (gitignored) for live data. Without config.js the dashboard runs on synthetic demo data,
// which is what a public deployment should show. Add ?demo to the URL to force demo mode.
//
// The publishable key is safe in a browser: data is only readable after signing in as a user listed in
// dashboard_viewers. Never put the secret key here.
export const SUPABASE_URL = 'https://your-project.supabase.co';
export const SUPABASE_PUBLISHABLE_KEY = 'your-publishable-key';

// Optional, for the sun's path in the 3D room: rounded coordinates (1 decimal is plenty). Stays in this gitignored
// file, never in the public code.
// export const LATITUDE = 52.0;
// export const LONGITUDE = 0.0;

// Optional: read from the own API (services/api) instead of Supabase. When API_URL is set it is used by default;
// ?supabase in the URL switches back. The read token is visible to anyone who can open this page: local use only.
// export const API_URL = 'http://127.0.0.1:8200';
// export const API_READ_TOKEN = 'your-api-read-token';
