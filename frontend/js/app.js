// frontend/js/app.js
let currentUser = null;

window.addEventListener('DOMContentLoaded', () => {
    const publicView = document.getElementById('view-public');
    if (publicView) publicView.classList.add('active');
});

function initAuth() {
    if (typeof google === 'undefined') return; 
    
    try {
        google.accounts.id.initialize({
            client_id: "124164127578-2qhjodmcu98cvm9hl70jcqhuid945dh4.apps.googleusercontent.com", 
            callback: handleCredentialResponse
        });
        
        document.getElementById("google-buttons-container").innerHTML = `
            <div id="google-signin-btn"></div>
            <div id="google-signup-btn"></div>
        `;
        
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
    }
}

// This is called when the grey fallback button is clicked
function manualGoogleAlert() {
    showConnectionError("Google Sign-In is temporarily restricted on this domain. Please contact support to activate your account.");
}

async function handleCredentialResponse(response) {
    showLoading();
    
    try {
        const API_BASE = window.EDUPOINT_API_BASE || 'https://edupoint-api.onrender.com'; 
        
        const res = await fetch(`${API_BASE}/api/auth/google`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ credential: response.credential })
        });
        
        if (!res.ok) throw new Error("Server responded with an error");
        
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
    // Update the text to match the specific error
    if (text) {
        text.innerHTML = msg; 
    }
    if (modal) modal.style.display = 'flex';
}

function hideConnectionError() {
    const modal = document.getElementById('connectionErrorModal');
    if (modal) modal.style.display = 'none';
}

function retryLogin() {
    hideConnectionError();
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
