/**
 * EAA Canvas - Enhanced Code Editor Component
 * ===========================================
 * Features:
 * - Auto language detection
 * - Multi-language error detection
 * - "Fix with AI" button that works for all languages
 * - Real-time error highlighting
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';

// Language definitions
const LANGUAGES = [
  { id: 'python', name: 'Python', extension: '.py', monaco: 'python' },
  { id: 'javascript', name: 'JavaScript', extension: '.js', monaco: 'javascript' },
  { id: 'typescript', name: 'TypeScript', extension: '.ts', monaco: 'typescript' },
  { id: 'html', name: 'HTML', extension: '.html', monaco: 'html' },
  { id: 'css', name: 'CSS', extension: '.css', monaco: 'css' },
  { id: 'java', name: 'Java', extension: '.java', monaco: 'java' },
  { id: 'cpp', name: 'C++', extension: '.cpp', monaco: 'cpp' },
  { id: 'rust', name: 'Rust', extension: '.rs', monaco: 'rust' },
  { id: 'go', name: 'Go', extension: '.go', monaco: 'go' },
  { id: 'php', name: 'PHP', extension: '.php', monaco: 'php' },
  { id: 'ruby', name: 'Ruby', extension: '.rb', monaco: 'ruby' },
  { id: 'sql', name: 'SQL', extension: '.sql', monaco: 'sql' },
  { id: 'json', name: 'JSON', extension: '.json', monaco: 'json' },
];

// Error interface
interface CodeError {
  line: number;
  column: number;
  message: string;
  severity: 'error' | 'warning' | 'info';
  code: string;
  suggestion?: string;
}

// Props interface
interface ProCanvasEditorProps {
  initialCode?: string;
  initialLanguage?: string;
  fileName?: string;
  apiUrl?: string;
  onCodeChange?: (code: string, language: string) => void;
  onLanguageChange?: (language: string) => void;
  onError?: (errors: CodeError[]) => void;
  onFix?: (fixedCode: string) => void;
  runCode?: boolean;
  showLineNumbers?: boolean;
  theme?: 'dark' | 'light';
  height?: string;
  readOnly?: boolean;
}

// Main component
const ProCanvasEditor: React.FC<ProCanvasEditorProps> = ({
  initialCode = '',
  initialLanguage,
  fileName,
  apiUrl = 'http://127.0.0.1:8000',
  onCodeChange,
  onLanguageChange,
  onError,
  onFix,
  runCode = false,
  showLineNumbers = true,
  theme = 'dark',
  height = '100%',
  readOnly = false,
}) => {
  // State
  const [code, setCode] = useState(initialCode);
  const [language, setLanguage] = useState(initialLanguage || 'python');
  const [errors, setErrors] = useState<CodeError[]>([]);
  const [warnings, setWarnings] = useState<CodeError[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isFixing, setIsFixing] = useState(false);
  const [autoDetect, setAutoDetect] = useState(true);
  const [consoleOutput, setConsoleOutput] = useState<string[]>([]);
  
  // Refs
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const analyzeTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // API calls
  const analyzeCode = useCallback(async (codeToAnalyze: string, lang: string) => {
    if (!codeToAnalyze.trim()) {
      setErrors([]);
      setWarnings([]);
      return;
    }

    setIsAnalyzing(true);
    
    try {
      const response = await fetch(`${apiUrl}/v1/canvas/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: codeToAnalyze,
          filename: fileName,
          run_code: runCode && lang === 'python',
        }),
      });

      if (response.ok) {
        const data = await response.json();
        
        // If auto-detect is on, update language
        if (autoDetect && data.language && data.language !== 'unknown') {
          setLanguage(data.language);
          onLanguageChange?.(data.language);
        }
        
        setErrors(data.errors || []);
        setWarnings(data.warnings || []);
        onError?.(data.errors || []);
        
        // Add to console if there's output
        if (data.output) {
          setConsoleOutput(prev => [...prev, data.output]);
        }
      }
    } catch (error) {
      console.error('Analysis failed:', error);
      addConsoleLog('Error: Could not analyze code', 'error');
    } finally {
      setIsAnalyzing(false);
    }
  }, [apiUrl, fileName, runCode, autoDetect, onLanguageChange, onError]);

  // Detect language
  const detectLanguage = useCallback(async (codeToDetect: string) => {
    try {
      const response = await fetch(`${apiUrl}/v1/canvas/detect-language`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: codeToDetect,
          filename: fileName,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        if (data.language && data.language !== 'unknown') {
          setLanguage(data.language);
          onLanguageChange?.(data.language);
        }
      }
    } catch (error) {
      console.error('Language detection failed:', error);
    }
  }, [apiUrl, fileName, onLanguageChange]);

  // Fix code with AI
  const fixCodeWithAI = useCallback(async (errorList: CodeError[]) => {
    if (errorList.length === 0) return;
    
    setIsFixing(true);
    addConsoleLog('🤖 Analyzing errors and preparing fix...', 'info');
    
    try {
      const response = await fetch(`${apiUrl}/v1/canvas/fix`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: code,
          errors: errorList,
          language: language,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        
        if (data.success && data.fixed_code) {
          setCode(data.fixed_code);
          onCodeChange?.(data.fixed_code, language);
          onFix?.(data.fixed_code);
          
          addConsoleLog('✅ Code fixed successfully!', 'success');
          
          // Re-analyze to check if all errors are gone
          await analyzeCode(data.fixed_code, language);
        } else {
          addConsoleLog('❌ Could not fix code automatically', 'error');
        }
      } else {
        addConsoleLog('❌ Fix request failed', 'error');
      }
    } catch (error) {
      console.error('Fix failed:', error);
      addConsoleLog(`❌ Fix failed: ${error}`, 'error');
    } finally {
      setIsFixing(false);
    }
  }, [apiUrl, code, language, onCodeChange, onFix, analyzeCode]);

  // One-click analyze and fix
  const analyzeAndFix = useCallback(async () => {
    setIsFixing(true);
    addConsoleLog('🤖 Analyzing and fixing code...', 'info');
    
    try {
      const response = await fetch(`${apiUrl}/v1/canvas/analyze-and-fix`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: code,
          filename: fileName,
          run_code: runCode,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        
        // Update language if auto-detected
        if (autoDetect && data.language && data.language !== 'unknown') {
          setLanguage(data.language);
          onLanguageChange?.(data.language);
        }
        
        setErrors(data.errors || []);
        setWarnings(data.warnings || []);
        onError?.(data.errors || []);
        
        if (data.has_errors && data.fixed_code) {
          setCode(data.fixed_code);
          onCodeChange?.(data.fixed_code, language);
          onFix?.(data.fixed_code);
          addConsoleLog('✅ Code fixed!', 'success');
        } else if (!data.has_errors) {
          addConsoleLog('✅ No errors found', 'success');
        }
      }
    } catch (error) {
      console.error('Analyze and fix failed:', error);
      addConsoleLog(`❌ Error: ${error}`, 'error');
    } finally {
      setIsFixing(false);
    }
  }, [apiUrl, code, fileName, runCode, autoDetect, language, onCodeChange, onFix, onError, onLanguageChange]);

  // Add console log
  const addConsoleLog = (message: string, type: 'info' | 'error' | 'success' | 'warn' = 'info') => {
    const timestamp = new Date().toLocaleTimeString();
    const prefix = type === 'error' ? '❌' : type === 'success' ? '✅' : type === 'warn' ? '⚠️' : 'ℹ️';
    setConsoleOutput(prev => [...prev, `[${timestamp}] ${prefix} ${message}`]);
  };

  // Handle code change
  const handleCodeChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newCode = e.target.value;
    setCode(newCode);
    onCodeChange?.(newCode, language);
    
    // Debounced analysis
    if (analyzeTimeoutRef.current) {
      clearTimeout(analyzeTimeoutRef.current);
    }
    
    analyzeTimeoutRef.current = setTimeout(() => {
      analyzeCode(newCode, language);
      
      // Auto-detect language on first meaningful input
      if (autoDetect && newCode.length > 20 && !initialLanguage) {
        detectLanguage(newCode);
      }
    }, 500);
  };

  // Handle language change
  const handleLanguageChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newLang = e.target.value;
    setLanguage(newLang);
    setAutoDetect(false); // Manual selection disables auto-detect
    onLanguageChange?.(newLang);
    
    // Re-analyze with new language
    analyzeCode(code, newLang);
  };

  // Clear console
  const clearConsole = () => {
    setConsoleOutput([]);
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (analyzeTimeoutRef.current) {
        clearTimeout(analyzeTimeoutRef.current);
      }
    };
  }, []);

  // Get language info
  const currentLang = LANGUAGES.find(l => l.id === language) || LANGUAGES[0];

  // Render
  return (
    <div className={`pro-canvas-editor ${theme}`} style={{ height, display: 'flex', flexDirection: 'column' }}>
      {/* Toolbar */}
      <div className="toolbar" style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '8px 12px',
        background: theme === 'dark' ? '#1e1e1e' : '#f5f5f5',
        borderBottom: `1px solid ${theme === 'dark' ? '#333' : '#ddd'}`,
      }}>
        {/* Language selector */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <label style={{ fontSize: '12px', color: theme === 'dark' ? '#aaa' : '#666' }}>
            Language:
          </label>
          <select
            value={language}
            onChange={handleLanguageChange}
            style={{
              background: theme === 'dark' ? '#333' : '#fff',
              color: theme === 'dark' ? '#fff' : '#333',
              border: `1px solid ${theme === 'dark' ? '#444' : '#ccc'}`,
              borderRadius: '4px',
              padding: '4px 8px',
              fontSize: '12px',
            }}
          >
            {LANGUAGES.map(lang => (
              <option key={lang.id} value={lang.id}>
                {lang.name}
              </option>
            ))}
          </select>
          
          {/* Auto-detect toggle */}
          <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px' }}>
            <input
              type="checkbox"
              checked={autoDetect}
              onChange={(e) => setAutoDetect(e.target.checked)}
            />
            Auto
          </label>
        </div>

        {/* Status indicator */}
        <div style={{ flex: 1 }} />
        
        {isAnalyzing && (
          <span style={{ fontSize: '12px', color: '#ffa500' }}>
            ⏳ Analyzing...
          </span>
        )}
        
        {errors.length > 0 && (
          <span style={{ fontSize: '12px', color: '#ff4444' }}>
            ❌ {errors.length} error{errors.length > 1 ? 's' : ''}
          </span>
        )}
        
        {warnings.length > 0 && (
          <span style={{ fontSize: '12px', color: '#ffaa00', marginLeft: '8px' }}>
            ⚠️ {warnings.length} warning{warnings.length > 1 ? 's' : ''}
          </span>
        )}
        
        {errors.length === 0 && warnings.length === 0 && code.trim() && (
          <span style={{ fontSize: '12px', color: '#44ff44' }}>
            ✅ No errors
          </span>
        )}
      </div>

      {/* Main content */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Editor area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Code editor */}
          <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
            {/* Line numbers */}
            {showLineNumbers && (
              <div style={{
                width: '40px',
                background: theme === 'dark' ? '#1a1a1a' : '#f0f0f0',
                padding: '8px 4px',
                textAlign: 'right',
                fontFamily: 'monospace',
                fontSize: '13px',
                lineHeight: '1.5',
                color: theme === 'dark' ? '#666' : '#999',
                overflow: 'hidden',
                userSelect: 'none',
              }}>
                {code.split('\n').map((_, i) => (
                  <div
                    key={i}
                    style={{
                      color: errors.some(e => e.line === i + 1)
                        ? '#ff4444'
                        : warnings.some(w => w.line === i + 1)
                          ? '#ffaa00'
                          : undefined,
                    }}
                  >
                    {i + 1}
                  </div>
                ))}
              </div>
            )}
            
            {/* Textarea */}
            <textarea
              ref={editorRef}
              value={code}
              onChange={handleCodeChange}
              readOnly={readOnly}
              style={{
                flex: 1,
                background: theme === 'dark' ? '#1e1e1e' : '#fff',
                color: theme === 'dark' ? '#d4d4d4' : '#333',
                border: 'none',
                padding: '8px',
                fontFamily: 'monospace',
                fontSize: '13px',
                lineHeight: '1.5',
                resize: 'none',
                outline: 'none',
                overflow: 'auto',
              }}
              spellCheck={false}
            />
          </div>

          {/* Error panel */}
          {errors.length > 0 && (
            <div style={{
              maxHeight: '150px',
              overflow: 'auto',
              background: theme === 'dark' ? '#2a1a1a' : '#fff5f5',
              borderTop: `1px solid ${theme === 'dark' ? '#444' : '#ffcccc'}`,
            }}>
              {errors.map((error, index) => (
                <div
                  key={index}
                  style={{
                    padding: '6px 12px',
                    borderBottom: `1px solid ${theme === 'dark' ? '#333' : '#eee'}`,
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '8px',
                  }}
                >
                  <span style={{
                    color: '#ff4444',
                    fontSize: '12px',
                    whiteSpace: 'nowrap',
                  }}>
                    ❌ Line {error.line}: {error.message}
                  </span>
                  
                  {error.suggestion && (
                    <span style={{
                      color: theme === 'dark' ? '#888' : '#666',
                      fontSize: '11px',
                      fontStyle: 'italic',
                    }}>
                      💡 {error.suggestion}
                    </span>
                  )}
                  
                  {/* Fix with AI button - THIS IS THE KEY FIX */}
                  <button
                    onClick={() => fixCodeWithAI([error])}
                    disabled={isFixing}
                    style={{
                      marginLeft: 'auto',
                      background: '#ffc107',
                      color: '#000',
                      border: 'none',
                      borderRadius: '4px',
                      padding: '2px 8px',
                      fontSize: '11px',
                      cursor: isFixing ? 'wait' : 'pointer',
                      fontWeight: 'bold',
                    }}
                  >
                    {isFixing ? '⏳ Fixing...' : '🤖 Fix with AI'}
                  </button>
                </div>
              ))}
              
              {/* Fix all button */}
              {errors.length > 1 && (
                <div style={{ padding: '8px 12px', background: theme === 'dark' ? '#1a1a1a' : '#f5f5f5' }}>
                  <button
                    onClick={() => fixCodeWithAI(errors)}
                    disabled={isFixing}
                    style={{
                      background: '#28a745',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '4px',
                      padding: '6px 16px',
                      fontSize: '12px',
                      cursor: isFixing ? 'wait' : 'pointer',
                      fontWeight: 'bold',
                    }}
                  >
                    {isFixing ? '⏳ Fixing All...' : `🤖 Fix All ${errors.length} Errors`}
                  </button>
                  
                  <button
                    onClick={analyzeAndFix}
                    disabled={isFixing}
                    style={{
                      marginLeft: '8px',
                      background: '#17a2b8',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '4px',
                      padding: '6px 16px',
                      fontSize: '12px',
                      cursor: isFixing ? 'wait' : 'pointer',
                    }}
                  >
                    🔍 Analyze & Auto-Fix
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Console panel */}
        <div style={{
          width: '300px',
          background: theme === 'dark' ? '#0a0a0a' : '#f8f8f8',
          borderLeft: `1px solid ${theme === 'dark' ? '#333' : '#ddd'}`,
          display: 'flex',
          flexDirection: 'column',
        }}>
          <div style={{
            padding: '8px 12px',
            borderBottom: `1px solid ${theme === 'dark' ? '#333' : '#ddd'}`,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <span style={{ fontSize: '12px', fontWeight: 'bold' }}>Console</span>
            <button
              onClick={clearConsole}
              style={{
                background: 'transparent',
                border: 'none',
                color: theme === 'dark' ? '#666' : '#999',
                cursor: 'pointer',
                fontSize: '11px',
              }}
            >
              Clear
            </button>
          </div>
          
          <div style={{
            flex: 1,
            overflow: 'auto',
            padding: '8px',
            fontFamily: 'monospace',
            fontSize: '11px',
          }}>
            {consoleOutput.map((line, i) => (
              <div key={i} style={{
                color: line.includes('❌') ? '#ff4444' :
                       line.includes('✅') ? '#44ff44' :
                       line.includes('⚠️') ? '#ffaa00' :
                       theme === 'dark' ? '#888' : '#666',
                marginBottom: '2px',
              }}>
                {line}
              </div>
            ))}
            {consoleOutput.length === 0 && (
              <div style={{ color: theme === 'dark' ? '#444' : '#999' }}>
                No output yet
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default ProCanvasEditor;
