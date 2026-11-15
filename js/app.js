// app.js
// Global state
let currentUser = null;
let selectedSubjects = [];
let currentPaymentData = null;

// Initialize on load
window.addEventListener('DOMContentLoaded', () => {
    // Ensure public view is visible if not logged in
    const publicView = document.getElementById('view-public');
    if (publicView) publicView.classList.add('active');
    
    // Fallback: If Google API takes too long or fails, render custom buttons
    setTimeout(() => {
        const container = document.getElementById('google-buttons-container');
        if (container && container.innerHTML.trim() === '') {
            showFallbackButtons();
        }
    }, 2500);
});

// View Management
function showView(viewName) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const target = document.getElementById('view-' + viewName);
    if (target) target.classList.add('active');
    window.scrollTo(0, 0);
}

// Google Auth Callback
function initAuth() {
    if (typeof google === 'undefined') {
        showFallbackButtons();
        return;
    }
    
    try {
        google.accounts.id.initialize({
            // ✅ Your specific Google Client ID has been inserted here
            client_id: "124164127578-2qhjodmcu98cvm9hl70jcqhuid945dh4.apps.googleusercontent.com", 
            callback: handleCredentialResponse
        });
        
        // 1. Sign In Button
        google.accounts.id.renderButton(
            document.getElementById("google-signin-btn"),
            { theme: "outline", size: "large", text: "signin_with", width: 220 }
        );

        // 2. Register / Sign Up Button
        google.accounts.id.renderButton(
            document.getElementById("google-signup-btn"),
            { theme: "filled_blue", size: "large", text: "signup_with", width: 220 }
        );
    } catch (e) {
        console.error("Google Auth Error:", e);
        showFallbackButtons();
    }
}

// Fallback buttons if Google API fails or Client ID is invalid
function showFallbackButtons() {
    const container = document.getElementById('google-buttons-container');
    if (container && container.innerHTML.trim() === '') {
        container.innerHTML = `
            <button class="btn-primary" style="max-width:220px; background:#fff; color:#333; border:1px solid #ddd; display:flex; align-items:center; justify-content:center; gap:10px; font-size:14px; padding:12px; border-radius:8px; cursor:pointer;" onclick="alert('Google Client ID is missing or blocked. Please check your Google Cloud Console.')">
                <img src="https://www.google.com/favicon.ico" width="18" height="18"> Sign In
            </button>
            <button class="btn-primary" style="max-width:220px; background:#2563EB; color:#fff; border:none; display:flex; align-items:center; justify-content:center; gap:10px; font-size:14px; padding:12px; border-radius:8px; cursor:pointer;" onclick="alert('Google Client ID is missing or blocked. Please check your Google Cloud Console.')">
                <img src="https://www.google.com/favicon.ico" width="18" height="18"> Register
            </button>
        `;
    }
}

async function handleCredentialResponse(response) {
    try {
        const res = await fetch('/api/auth/google', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ credential: response.credential })
        });
        const data = await res.json();
        
        if (data.ok) {
            currentUser = data.user;
            if (currentUser.role === 'admin') {
                showView('admin');
            } else {
                document.getElementById('welcomeName').textContent = currentUser.name.split(' ')[0];
                showView('welcome');
                setTimeout(() => showView('student'), 10500); // 10.5s welcome delay
            }
        } else {
            alert('Login failed: ' + data.error);
        }
    } catch (err) {
        console.error(err);
        alert('Login error. Please try again.');
    }
}

// Logout
function logout() {
    fetch('/api/auth/logout', { method: 'POST' }).finally(() => {
        currentUser = null;
        showView('public');
    });
}

// Student UI functions
function filterCourses() { /* implementation */ }
function showCareer(field) { /* implementation */ }
function findScholarships() { /* implementation */ }
function sendChat(msg) { /* implementation */ }
