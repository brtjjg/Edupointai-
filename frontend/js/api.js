window.EDUPOINT_API = window.EDUPOINT_API
  || (location.hostname === "localhost" ? "http://localhost:5000"
                                        : "https://edupoint-api.onrender.com");

const TOKEN_KEY = "edupoint_token";
const getToken  = () => localStorage.getItem(TOKEN_KEY);
const setToken  = t  => localStorage.setItem(TOKEN_KEY, t);
const clearToken= () => localStorage.removeItem(TOKEN_KEY);

async function api(path, opts = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  const t = getToken();
  if (t) headers["Authorization"] = "Bearer " + t;
  const r = await fetch(window.EDUPOINT_API + path, { ...opts, headers });
  let data = {};
  try { data = await r.json(); } catch (_) {}
  if (r.status === 401) { clearToken(); }
  if (!r.ok) throw Object.assign(new Error(data.error || ("HTTP " + r.status)), { status: r.status, data });
  return data;
}

async function requireAuth() {
  if (!getToken()) { location.href = "/login.html"; return null; }
  try { return await api("/api/me"); }
  catch (_) { clearToken(); location.href = "/login.html"; return null; }
}

function logout() { api("/api/logout", { method: "POST" }).catch(()=>{}).finally(() => {
  clearToken(); location.href = "/index.html";
});}
