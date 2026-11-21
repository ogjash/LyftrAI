import { FormEvent, useEffect, useRef, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  ArrowUp,
  Bot,
  CircleAlert,
  Clock3,
  Cpu,
  Database,
  Settings2,
  Sparkles,
  Zap,
} from "lucide-react"
import { Button } from "./components/ui/button"
import { Card } from "./components/ui/card"
import { Textarea } from "./components/ui/textarea"
import { Badge } from "./components/ui/badge"
import { ScrollArea } from "./components/ui/scroll-area"
import { Separator } from "./components/ui/separator"
import { Tooltip } from "./components/ui/tooltip"
import type { Message, Metadata } from "./types"

const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "")

function makeSessionId() {
  return crypto.randomUUID()
}

function App() {
  const [sessionId] = useState(makeSessionId)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [systemPrompt, setSystemPrompt] = useState("")
  const [showSettings, setShowSettings] = useState(false)
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const message = input.trim()
    if (!message || loading) return

    setMessages((current) => [...current, { role: "user", content: message }])
    setInput("")
    setLoading(true)

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          ...(systemPrompt.trim() ? { system_prompt: systemPrompt.trim() } : {}),
        }),
      })
      const data = await response.json()
      if (!response.ok) {
        const detail = typeof data.detail === "string" ? data.detail : "Could not send your message"
        setMessages((current) => [
          ...current,
          { role: "assistant", content: detail, metadata: emptyErrorMetadata() },
        ])
        return
      }

      setMessages((current) => [
        ...current,
        { role: "assistant", content: data.reply, metadata: data.metadata as Metadata },
      ])
    } catch {
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: "Unable to reach the server. Please try again.",
          metadata: emptyErrorMetadata(),
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"><Sparkles size={18} /></div>
          <div>
            <strong>Lyftr AI</strong>
            <span>Intelligent assistant</span>
          </div>
        </div>
        <Tooltip content={showSettings ? "Hide system prompt" : "Configure system prompt"}>
          <Button
            type="button"
            variant="secondary"
            size="icon"
            aria-label="System prompt settings"
            onClick={() => setShowSettings((current) => !current)}
          >
            <Settings2 size={18} />
          </Button>
        </Tooltip>
      </header>

      {showSettings && (
        <Card className="settings-panel">
          <div className="settings-heading">
            <label htmlFor="system-prompt">System prompt</label>
            <Badge variant="default">Session only</Badge>
          </div>
          <Textarea
            id="system-prompt"
            data-testid="system-prompt-input"
            value={systemPrompt}
            onChange={(event) => setSystemPrompt(event.target.value)}
            placeholder="Give the assistant a role or instructions..."
            className="system-input"
          />
        </Card>
      )}

      <ScrollArea className="chat-scroll">
        <section className="chat-area" aria-live="polite">
          {messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon"><Sparkles size={28} /></div>
              <Badge variant="live">Lyftr AI is ready</Badge>
              <h1>What would you like to explore?</h1>
              <p>Ask a question, brainstorm an idea, or continue a conversation.</p>
              <div className="suggestions">
                {["Explain a complex topic", "Help me plan a project", "Review my ideas"].map((suggestion) => (
                  <button
                    type="button"
                    key={suggestion}
                    onClick={() => setInput(suggestion)}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="messages">
              {messages.map((message, index) =>
                message.role === "user" ? (
                  <div className="message-row user-row" key={index}>
                    <div className="user-bubble">{message.content}</div>
                  </div>
                ) : (
                  <AssistantMessage message={message} key={index} />
                ),
              )}
              {loading && (
                <div className="assistant-row">
                  <div className="assistant-avatar"><Bot size={16} /></div>
                  <div className="thinking-card">
                    <span>Thinking</span>
                    <div className="typing"><i /><i /><i /></div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </section>
      </ScrollArea>

      <form className="composer" onSubmit={handleSubmit}>
        <Textarea
          data-testid="chat-input"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault()
              event.currentTarget.form?.requestSubmit()
            }
          }}
          placeholder="Message Lyftr AI..."
          aria-label="Chat message"
        />
        <Button
          data-testid="send-button"
          type="submit"
          size="icon"
          disabled={!input.trim() || loading}
          aria-label="Send message"
        >
          <ArrowUp size={19} />
        </Button>
      </form>
    </main>
  )
}

function AssistantMessage({ message }: { message: Extract<Message, { role: "assistant" }> }) {
  const isError = message.metadata.model === undefined
  return (
    <div className="assistant-row">
      <div className="assistant-avatar">
        {isError ? <CircleAlert size={16} /> : <Bot size={16} />}
      </div>
      <div data-testid="assistant-message" className="assistant-content">
        {isError ? (
          <Card className="error-card">
            <CircleAlert size={16} />
            <span>{message.content}</span>
          </Card>
        ) : (
          <Card className="reply-card">
            <div className="reply-text">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ children, ...props }) => (
                    <a {...props} target="_blank" rel="noreferrer">{children}</a>
                  ),
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          </Card>
        )}
        {!isError && (
          <>
            <Separator className="metadata-divider" />
            <div className="metadata">
              <Badge
                data-testid="meta-source"
                variant={message.metadata.resolution_source === "LLM_CACHE" ? "cache" : "live"}
              >
                {message.metadata.resolution_source === "LLM_CACHE" ? <Database size={11} /> : <Zap size={11} />}
                {message.metadata.resolution_source}
              </Badge>
              <Badge data-testid="meta-model"><Cpu size={11} />{message.metadata.model}</Badge>
              <Badge data-testid="meta-latency"><Clock3 size={11} />{message.metadata.latency_ms} ms</Badge>
              <Badge data-testid="meta-input-tokens">Input {message.metadata.input_tokens}</Badge>
              <Badge data-testid="meta-output-tokens">Output {message.metadata.output_tokens}</Badge>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function emptyErrorMetadata(): Metadata {
  return {
    resolution_source: "LIVE_INFERENCE",
    model: "",
    latency_ms: 0,
    input_tokens: 0,
    output_tokens: 0,
    key_id: null,
    fallback_attempts: 0,
  }
}

export default App
