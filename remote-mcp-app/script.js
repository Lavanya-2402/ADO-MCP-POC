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
    
    // 2. Create the Real-time Agent Bubble
    const agentMsgId = 'agent-msg-' + Date.now();
    const agentMsgHTML = `
        <div class="message agent-message" id="${agentMsgId}">
            <div class="avatar">🤖</div>
            <div class="message-body">
                <div class="agent-badge" id="${agentMsgId}-badge" style="display: none; margin-bottom: 8px;"></div>
                <div class="markdown-content" id="${agentMsgId}-content">
                    <div class="agent-loading" style="display: flex; align-items: center; gap: 10px; font-size: 14px; opacity: 0.85;">
                        <span style="display: inline-block; animation: rotate 2s linear infinite; font-size: 16px;">⚙️</span>
                        <span>Agent is processing your request...</span>
                    </div>
                </div>
            </div>
        </div>
    `;
    chatViewport.insertAdjacentHTML('beforeend', agentMsgHTML);
    chatViewport.scrollTop = chatViewport.scrollHeight;
    
    const contentArea = document.getElementById(`${agentMsgId}-content`);
    
    try {
        const response = await fetch('/api/chat/stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ prompt })
        });
        
        if (!response.ok) {
            throw new Error('Server returned error status');
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.substring(6));
                    
                    if (data.type === 'subagent') {
                        const agentMap = {
                            "DevOps Engineer": { icon: "⚙️", label: "DevOps Engineer", color: "#ec4899" },
                            "QA Analyst": { icon: "🛡️", label: "QA Analyst", color: "#10b981" },
                            "Technical Writer": { icon: "✍️", label: "Wiki Writer", color: "#06b6d4" },
                            "Product Manager": { icon: "📋", label: "Product Manager", color: "#f59e0b" },
                            "Software Developer": { icon: "💻", label: "Developer", color: "#3b82f6" },
                            "General Assistant": { icon: "🤖", label: "General Assistant", color: "#a855f7" }
                        };
                        const profile = agentMap[data.name] || { icon: "🤖", label: data.name, color: "var(--accent)" };
                        const agentBubble = document.getElementById(agentMsgId);
                        if (agentBubble) {
                            const avatarEl = agentBubble.querySelector('.avatar');
                            if (avatarEl) {
                                avatarEl.textContent = profile.icon;
                                avatarEl.style.borderColor = profile.color;
                                avatarEl.style.boxShadow = `0 0 10px ${profile.color}40`;
                                avatarEl.title = profile.label;
                            }
                            const badgeEl = document.getElementById(`${agentMsgId}-badge`);
                            if (badgeEl) {
                                badgeEl.textContent = profile.label;
                                badgeEl.style.color = profile.color;
                                badgeEl.style.borderColor = profile.color;
                                badgeEl.style.display = 'inline-block';
                            }
                        }
                    }
                    else if (data.type === 'status') {
                        console.log(`[Status]: ${data.message}`);
                    }
                    else if (data.type === 'thought') {
                        console.log(`%c[Thought]: ${data.message}`, 'color: #9333ea; font-style: italic;');
                    }
                    else if (data.type === 'tool_start') {
                        console.log(`%c[Tool Start]: Invoking ${data.tool} -> ${data.reason || ''}`, 'color: #2563eb;');
                    }
                    else if (data.type === 'tool_complete') {
                        console.log(`%c[Tool Complete]: ${data.tool} (${data.status})`, 'color: #16a34a;');
                    }
                    else if (data.type === 'final') {
                        // Render final response text
                        contentArea.innerHTML = parseMarkdown(data.message);
                        chatViewport.scrollTop = chatViewport.scrollHeight;
                    } 
                    else if (data.type === 'error') {
                        throw new Error(data.message);
                    }
                }
            }
        }
        
    } catch (error) {
        contentArea.innerHTML = `
            <div style="color: var(--indicator-red); display: flex; align-items: center; gap: 8px; font-size: 14px;">
                <span>⚠️</span>
                <span><strong>Execution Error:</strong> ${error.message}</span>
            </div>
        `;
        chatViewport.scrollTop = chatViewport.scrollHeight;
    } finally {
        // Re-enable inputs
        promptInput.disabled = false;
        sendBtn.disabled = false;
        promptInput.focus();
    }
}

// File Upload Handler
const fileUploadInput = document.getElementById('file-upload');
if (fileUploadInput) {
    fileUploadInput.addEventListener('change', (event) => {
        const file = event.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            const text = e.target.result;
            const promptInput = document.getElementById('prompt-input');
            promptInput.value = text;
            promptInput.focus();
        };
        reader.readAsText(file);
    });
}





