// AI Assistant Panel for Canvas
import React, { useState, useRef, useEffect, useCallback } from 'react';

interface AIAssistantPanelProps {
  code: string;
  language: string;
  filename: string;
  onApplyCode: (code: string) => void;
  onClose: () => void;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

const QUICK_ACTIONS = [
  { id: 'explain', label: 'Explain', icon: '👁', prompt: 'Explain this code in simple terms.' },
  { id: 'improve', label: 'Improve', icon: '✨', prompt: 'Improve this code.' },
  { id: 'fix', label: 'Fix Bugs', icon: '🐛', prompt: 'Fix any bugs in this code.' },
  { id: 'comments', label: 'Add Comments', icon: '📝', prompt: 'Add comments to this code.' },
  { id: 'refactor', label: 'Refactor', icon: '🔄', prompt: 'Refactor this code.' },
  { id: 'optimize', label: 'Optimize', icon: '⚡', prompt: 'Optimize this code.' },
];

export function AIAssistantPanel({ code, language, filename, onApplyCode, onClose }: AIAssistantPanelProps) {
  const messagesState = useState<Message[]>([]);
  const messages = messagesState[0];
  const setMessages = messagesState[1];
  const inputState = useState('');
  const input = inputState[0];
  const setInput = inputState[1];
  const isThinkingState = useState(false);
  const isThinking = isThinkingState[0];
  const setIsThinking = isThinkingState[1];
  const chatRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages]);

  const sendMessage = useCallback(async (message: string) => {
    if (!message.trim() || isThinking) return;
    const userMessage: Message = { role: 'user', content: message };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsThinking(true);
    try {
      const res = await fetch('http://127.0.0.1:8000/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [
            { role: 'system', content: 'Help with code: ' + code.substring(0, 2000) },
            { role: 'user', content: message }
          ],
          stream: false
        })
      });
      if (!res.ok) throw new Error('Server error');
      const data = await res.json();
      setMessages(prev => [...prev, { role: 'assistant', content: data.choices?.[0]?.message?.content || 'No response' }]);
    } catch (e: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Error: ' + e.message }]);
    } finally {
      setIsThinking(false);
    }
  }, [code, isThinking]);

  const extractCode = (text: string): string | null => {
    const codeBlockRegex = /```(?:\w+)?\n([\s\S]*?)```/;
    const match = text.match(codeBlockRegex);
    return match ? match[1].trim() : null;
  };

  return (
    <div style={{ position: 'fixed', right: 0, top: 0, bottom: 0, width: 400, background: 'rgba(10, 14, 20, 0.98)', zIndex: 100, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid rgba(0, 234, 255, 0.1)' }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: '#00eaff' }}>🤖 AI Assistant</span>
        <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: '#666', fontSize: 24, cursor: 'pointer' }}>×</button>
      </div>
      <div style={{ padding: '12px 20px', background: 'rgba(0, 0, 0, 0.3)' }}>
        <span style={{ padding: '2px 8px', background: 'rgba(0, 234, 255, 0.2)', borderRadius: 4, fontSize: 10, color: '#00eaff' }}>{language.toUpperCase()}</span>
        <span style={{ marginLeft: 8 }}>{filename}</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '12px 20px' }}>
        {QUICK_ACTIONS.map(action => (
          <button key={action.id} onClick={() => sendMessage(action.prompt)} disabled={isThinking} style={{ padding: '6px 12px', background: 'rgba(0, 0, 0, 0.3)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: 6, color: '#e6edf3', fontSize: 11, cursor: 'pointer' }}>
            {action.icon} {action.label}
          </button>
        ))}
      </div>
      <div ref={chatRef} style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {messages.length === 0 && <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>Ask me anything about your code</div>}
        {messages.map((msg, i) => {
          const extractedCode = msg.role === 'assistant' ? extractCode(msg.content) : null;
          return (
            <div key={i} style={{ alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '85%' }}>
              <div style={{ padding: '12px 16px', borderRadius: 12, background: msg.role === 'user' ? 'linear-gradient(135deg, #00eaff, #00b4d8)' : 'rgba(0, 0, 0, 0.4)', color: msg.role === 'user' ? '#000' : '#e6edf3', fontSize: 13 }}>
                {msg.content}
              </div>
              {extractedCode && (
                <button onClick={() => onApplyCode(extractedCode)} style={{ marginTop: 8, padding: '8px 14px', background: 'linear-gradient(135deg, #00eaff, #00b4d8)', border: 'none', borderRadius: 6, color: '#000', fontSize: 11, cursor: 'pointer' }}>✅ Apply Code</button>
              )}
            </div>
          );
        })}
        {isThinking && <div style={{ alignSelf: 'flex-start', padding: '12px 16px', background: 'rgba(0, 0, 0, 0.4)', borderRadius: 12 }}>...</div>}
      </div>
      <div style={{ display: 'flex', gap: 8, padding: '16px 20px', borderTop: '1px solid rgba(0, 234, 255, 0.1)' }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); sendMessage(input); } }} placeholder="Ask about your code..." disabled={isThinking} style={{ flex: 1, padding: '12px 16px', background: 'rgba(0, 0, 0, 0.4)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: 8, color: '#e6edf3', fontSize: 13, outline: 'none' }} />
        <button onClick={() => sendMessage(input)} disabled={isThinking || !input.trim()} style={{ padding: '0 16px', background: 'linear-gradient(135deg, #00eaff, #00b4d8)', border: 'none', borderRadius: 8, color: '#000', fontWeight: 600, cursor: 'pointer' }}>{isThinking ? '⏳' : '➤'}</button>
      </div>
    </div>
  );
}
