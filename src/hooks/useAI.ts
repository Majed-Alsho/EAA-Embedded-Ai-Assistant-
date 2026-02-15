import { useState, useCallback } from 'react';

export type AIMessage = {
  role: 'user' | 'assistant' | 'system';
  content: string;
};

const AI_ENDPOINT = "http://127.0.0.1:8000/v1/chat/completions"; 

export type AIResponse = {
  text: string;
  model: string;
  isStream?: boolean;
};

export function useAI(logLine: (s: string) => void) {
  const [isGenerating, setIsGenerating] = useState(false);

  const generate = useCallback(async (
    userPrompt: string, 
    systemContext: string,
    // Note: onComplete is now called repeatedly with updates
    onUpdate: (partial: AIResponse) => void 
  ) => {
    setIsGenerating(true);

    const messages: AIMessage[] = [
      { role: 'system', content: `You are EAA. Context:\n${systemContext}` },
      { role: 'user', content: userPrompt }
    ];

    try {
      const response = await fetch(AI_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: messages, stream: true }), // Request Stream
      });

      if (!response.ok || !response.body) throw new Error(`Brain offline: ${response.status}`);

      // Create a Reader to read the stream
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let fullText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        fullText += chunk;

        // Send update to UI immediately
        onUpdate({ 
            text: fullText, 
            model: "EAA-STREAM", 
            isStream: true 
        });
      }

    } catch (err) {
      logLine(`[ai] Error: ${String(err)}`);
      onUpdate({ text: "⚠️ Connection Error or Timeout.", model: "ERROR" });
    } finally {
      setIsGenerating(false);
    }
  }, [logLine]);

  return { generate, isGenerating };
}