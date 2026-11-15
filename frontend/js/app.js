// frontend/js/app.js
let currentUser = null;

window.addEventListener('DOMContentLoaded', () => {
    const publicView = document.getElementById('view-public');
    if (publicView) publicView.classList.add('active');
});

// This is called automatically by the Google script in index.html
function initAuth() {
    if (typeof google === 'undefined') return; // Keep fallback buttons if Google fails
    
    try {
        google.accounts.id.initialize({
            client_id: "124164127578-2qhjodmcu98cvm9hl70jcqhuid945dh4.apps.googleusercontent.com", 
            callback: handleCredentialResponse
        });
        
        // 1. Clear the fallback buttons
        document.getElementById("google-buttons-container").innerHTML = `
            <div id="google-signin-btn"></div>
            <div id="google-signup-btn"></div>
        `;
        
        // 2. Render the official Google buttons
        google.accounts.id.renderButton(
            document.getElementById("google-signin-btn"),
            { theme: "outline", size: "large", text: "signin_with", width: 220 }
        );

        google.accounts.id.renderButton(
            document.getElementById("google-signup-btn"),
            { theme: "filled_blue", size: "large", text: "signup_with", width: 220 }
        );
    } catch (e) {
        console.error("Google Auth Error:", e);
        // If there's an error, the fallback buttons stay on screen
    }
}

// Alert user if they click the fallback buttons
function manualGoogleAlert() {
    alert("Google Sign-In is currently restricted. Please ensure https://edupointai-frontend.vercel.app is added to your Authorized JavaScript Origins in the Google Cloud Console.");
}

async function handleCredentialResponse(response) {
    showLoading();
    
    try {
        // ✅ FIXED: Using your actual Render backend URL
        const API_BASE = window.EDUPOINT_API_BASE || 'https://edupoint-api.onrender.com'; 
        
        const res = await fetch(`${API_BASE}/api/auth/google`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ credential: response.credential })
        });
        
        if (!res.ok) {
            throw new Error("Server responded with an error");
        }
        
        const data = await res.json();
        
        if (data.ok) {
            currentUser = data.user;
            localStorage.setItem('edupoint_token', data.token);
            
            if (currentUser.role === 'admin') {
                showView('admin');
            } else {
                document.getElementById('welcomeName').textContent = currentUser.name.split(' ')[0];
                showView('welcome');
                setTimeout(() => showView('student'), 10500);
            }
        } else {
            showConnectionError(data.error || "Incorrect email or password.");
        }
    } catch (err) {
        console.error("Login Error:", err);
        showConnectionError("We're temporarily unable to connect. Please try again shortly.");
    } finally {
        hideLoading();
    }
}

function showLoading() {
    const loader = document.getElementById('loadingOverlay');
    if (loader) loader.style.display = 'flex';
}

function hideLoading() {
    const loader = document.getElementById('loadingOverlay');
    if (loader) loader.style.display = 'none';
}

function showConnectionError(msg) {
    const modal = document.getElementById('connectionErrorModal');
    const text = document.getElementById('errorMessageText');
    if (msg) text.textContent = msg;
    if (modal) modal.style.display = 'flex';
}

function hideConnectionError() {
    const modal = document.getElementById('connectionErrorModal');
    if (modal) modal.style.display = 'none';
}

function retryLogin() {
    hideConnectionError();
    // Trigger Google Sign-In again
    if (typeof google !== 'undefined') {
        google.accounts.id.prompt();
    } else {
        location.reload();
    }
}

function showView(viewName) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const target = document.getElementById('view-' + viewName);
    if (target) target.classList.add('active');
    window.scrollTo(0, 0);
}

function logout() {
    localStorage.removeItem('edupoint_token');
    currentUser = null;
    showView('public');
}
