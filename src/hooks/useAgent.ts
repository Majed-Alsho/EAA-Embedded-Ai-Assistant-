// useAgent hook for EAA Agent Mode
import { useState, useCallback, useRef } from 'react';

export interface AgentEvent {
  type: 'tool_use' | 'tool_result' | 'thinking' | 'message' | 'error';
  name?: string;
  args?: Record<string, any>;
  result?: any;
  text?: string;
  timestamp: number;
}

export interface AgentState {
  isRunning: boolean;
  events: AgentEvent[];
  currentTool: string | null;
}

// Tool icon mapping
export function getToolIcon(toolName: string): string {
  const icons: Record<string, string> = {
    'read_file': '📄',
    'write_file': '✏️',
    'edit_file': '📝',
    'list_directory': '📁',
    'execute_command': '⚡',
    'search_web': '🔍',
    'analyze_code': '🔬',
    'run_python': '🐍',
    'create_image': '🎨',
    'default': '🔧'
  };
  return icons[toolName] || icons['default'];
}

export function useAgent() {
  const stateRef = useRef<AgentState>({
    isRunning: false,
    events: [],
    currentTool: null
  });
  
  const eventsState = useState<AgentEvent[]>([]);
  const events = eventsState[0];
  const setEvents = eventsState[1];
  
  const isRunningState = useState(false);
  const isRunning = isRunningState[0];
  const setIsRunning = isRunningState[1];
  
  const currentToolState = useState<string | null>(null);
  const currentTool = currentToolState[0];
  const setCurrentTool = currentToolState[1];

  const addEvent = useCallback((event: Omit<AgentEvent, 'timestamp'>) => {
    const newEvent: AgentEvent = {
      ...event,
      timestamp: Date.now()
    };
    setEvents(prev => [...prev, newEvent]);
    return newEvent;
  }, []);

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  const runAgent = useCallback(async (prompt: string, onStream?: (text: string) => void): Promise<string> => {
    setIsRunning(true);
    setEvents([]);
    
    try {
      addEvent({ type: 'thinking', text: 'Starting agent...' });
      
      const response = await fetch('http://127.0.0.1:8000/v1/agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, stream: true })
      });

      if (!response.ok) {
        throw new Error(`Agent error: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      let result = '';
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              
              if (data.type === 'tool_use') {
                setCurrentTool(data.name);
                addEvent({ type: 'tool_use', name: data.name, args: data.args });
              } else if (data.type === 'tool_result') {
                addEvent({ type: 'tool_result', name: data.name, result: data.result });
                setCurrentTool(null);
              } else if (data.type === 'message') {
                result += data.text || '';
                if (onStream) onStream(data.text || '');
              } else if (data.type === 'thinking') {
                addEvent({ type: 'thinking', text: data.text });
              }
            } catch (e) {
              // Ignore parse errors for incomplete JSON
            }
          }
        }
      }

      addEvent({ type: 'message', text: 'Agent completed successfully' });
      return result;
    } catch (error: any) {
      addEvent({ type: 'error', text: error.message || 'Agent failed' });
      throw error;
    } finally {
      setIsRunning(false);
      setCurrentTool(null);
    }
  }, [addEvent]);

  const stopAgent = useCallback(() => {
    setIsRunning(false);
    setCurrentTool(null);
    addEvent({ type: 'message', text: 'Agent stopped by user' });
  }, [addEvent]);

  return {
    events,
    isRunning,
    currentTool,
    addEvent,
    clearEvents,
    runAgent,
    stopAgent
  };
}