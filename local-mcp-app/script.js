// Theme Management
const themeToggleBtn = document.getElementById('theme-toggle');
const htmlElement = document.documentElement;

// Load initial theme (default to dark)
const savedTheme = localStorage.getItem('theme') || 'dark';
htmlElement.setAttribute('data-theme', savedTheme);

themeToggleBtn.addEventListener('click', () => {
    const currentTheme = htmlElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    htmlElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
});

// Simple Markdown Parser for beautiful chat presentation
function parseMarkdown(text) {
    if (!text) return '';
    
    let html = text;
    
    // Escape HTML special chars to prevent script injection but preserve basic markup later
    html = html
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
        
    // Code blocks: ```code```
    html = html.replace(/```([\s\S]+?)```/g, (match, code) => {
        return `<pre><code>${code.trim()}</code></pre>`;
    });
    
    // Inline code: `code`
    html = html.replace(/`([^`\n]+?)`/g, '<code>$1</code>');
    
    // Bold text: **text**
    html = html.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
    
    // Markdown Links: [text](url)
    html = html.replace(/\[([^\]]+?)\]\(([^)]+?)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    
    // Unordered lists: lines starting with * or -
    const lines = html.split('\n');
    let inList = false;
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (line.startsWith('* ') || line.startsWith('- ')) {
            const content = line.substring(2);
            if (!inList) {
                lines[i] = '<ul><li>' + content + '</li>';
                inList = true;
            } else {
                lines[i] = '<li>' + content + '</li>';
            }
        } else {
            if (inList) {
                lines[i] = '</ul>' + lines[i];
                inList = false;
            }
        }
    }
    if (inList) {
        lines[lines.length - 1] += '</ul>';
    }
    html = lines.join('\n');
    
    // Line breaks
    html = html.replace(/\n/g, '<br>');
    
    return html;
}

// Send Message Handler
async function sendMessage(event) {
    event.preventDefault();
    
    const promptInput = document.getElementById('prompt-input');
    const sendBtn = document.getElementById('send-btn');
    const chatViewport = document.getElementById('chat-viewport');
    
    const prompt = promptInput.value.trim();
    if (!prompt) return;
    
    // Disable inputs
    promptInput.value = '';
    promptInput.disabled = true;
    sendBtn.disabled = true;
    
    // 1. Append User Message
    const userMsgHTML = `
        <div class="message user-message">
            <div class="avatar">U</div>
            <div class="message-body">
                <p>${prompt.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</p>
            </div>
        </div>
    `;
    chatViewport.insertAdjacentHTML('beforeend', userMsgHTML);
    chatViewport.scrollTop = chatViewport.scrollHeight;
    
    // 2. Append Loading Message with Loader
    const loadingId = 'loading-' + Date.now();
    const loadingMsgHTML = `
        <div class="message agent-message" id="${loadingId}">
            <div class="avatar">⚙️</div>
            <div class="message-body">
                <div class="steps-tracker">
                    <div class="step-item active">
                        <span class="step-icon"></span>
                        <span class="step-text">Analyzing prompt and preparing DevOps tools...</span>
                    </div>
                </div>
            </div>
        </div>
    `;
    chatViewport.insertAdjacentHTML('beforeend', loadingMsgHTML);
    chatViewport.scrollTop = chatViewport.scrollHeight;
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ prompt })
        });
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to get response');
        }
        
        const data = await response.json();
        
        // Remove loading message
        document.getElementById(loadingId).remove();
        
        // Build Flow Steps Tracker HTML
        let stepsHTML = '';
        const logs = data.logs || [];
        if (logs.length > 0) {
            stepsHTML = '<div class="steps-tracker">';
            logs.forEach(log => {
                const icon = log.status === 'failed' ? '❌' : '✅';
                const itemClass = log.status === 'failed' ? 'step-item completed status-failed' : 'step-item completed';
                stepsHTML += `
                    <div class="${itemClass}">
                        <span class="step-icon">${icon}</span>
                        <span class="step-text">Used Tool: <strong>${log.tool}</strong></span>
                    </div>
                `;
            });
            stepsHTML += '</div>';
        }
        
        // 3. Append Agent Response Bubble
        const agentMsgHTML = `
            <div class="message agent-message">
                <div class="avatar">🤖</div>
                <div class="message-body">
                    ${stepsHTML}
                    <div class="markdown-content">${parseMarkdown(data.response)}</div>
                </div>
            </div>
        `;
        chatViewport.insertAdjacentHTML('beforeend', agentMsgHTML);
        chatViewport.scrollTop = chatViewport.scrollHeight;
        
    } catch (error) {
        document.getElementById(loadingId).remove();
        
        const errorMsgHTML = `
            <div class="message agent-message">
                <div class="avatar">⚠️</div>
                <div class="message-body" style="border-color: var(--indicator-red); background: rgba(239, 68, 68, 0.08);">
                    <p style="color: var(--indicator-red);"><strong>Error:</strong> ${error.message}</p>
                </div>
            </div>
        `;
        chatViewport.insertAdjacentHTML('beforeend', errorMsgHTML);
        chatViewport.scrollTop = chatViewport.scrollHeight;
    } finally {
        // Re-enable inputs
        promptInput.disabled = false;
        sendBtn.disabled = false;
        promptInput.focus();
    }
}
