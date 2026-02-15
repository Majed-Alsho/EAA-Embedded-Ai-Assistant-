import React, { useState, useEffect } from 'react';
import { QRCodeSVG } from 'qrcode.react';

interface HubProps {
  onSelectLocal: () => void;
}

const ConnectionHub: React.FC<HubProps> = ({ onSelectLocal }) => {
  const [view, setView] = useState<'choice' | 'remote'>('choice');
  const [tunnelUrl, setTunnelUrl] = useState<string>("Fetching...");

  // Fetch the tunnel URL when entering Remote view
  useEffect(() => {
    if (view === 'remote') {
      fetch('http://127.0.0.1:8000/v1/system/tunnel')
        .then(res => res.json())
        .then(data => setTunnelUrl(data.url || "Tunnel Offline"))
        .catch(() => setTunnelUrl("Error: Backend Offline"));
    }
  }, [view]);

  return (
    <div className="hub-overlay">
      <div className="hub-container">
        
        {view === 'choice' ? (
          <>
            <h1 className="hub-title">SELECT INTERFACE MODE</h1>
            <p className="hub-subtitle">Where will you operate EAA from?</p>
            
            <div className="choice-grid">
              {/* CHOICE 1: THIS PC */}
              <div className="choice-card" onClick={onSelectLocal}>
                <div className="card-icon">🖥️</div>
                <h3>THIS TERMINAL</h3>
                <p>Operate directly on this PC.</p>
              </div>

              {/* CHOICE 2: REMOTE PHONE */}
              <div className="choice-card" onClick={() => setView('remote')}>
                <div className="card-icon">📱</div>
                <h3>REMOTE LINK</h3>
                <p>Control from Phone via Cloudflare.</p>
              </div>
            </div>
          </>
        ) : (
          /* REMOTE VIEW */
          <div className="remote-panel glass-panel">
            <button className="hub-back-btn" onClick={() => setView('choice')}>← BACK</button>
            <h2 className="remote-title">SECURE TUNNEL ACTIVE</h2>
            
            <div className="remote-box">
              <p className="label">PUBLIC API URL</p>
              <div className="url-display">
                <input type="text" readOnly value={tunnelUrl} className="electric-input" />
                <button className="copy-btn" onClick={() => navigator.clipboard.writeText(tunnelUrl)}>COPY</button>
              </div>
            </div>

            <div className="qr-section">
              <div className="qr-bg">
                <QRCodeSVG value={tunnelUrl} size={150} bgColor="#ffffff" fgColor="#000000" />
              </div>
              <p>Scan to Connect App</p>
            </div>
          </div>
        )}

      </div>
    </div>
  );
};

export default ConnectionHub;