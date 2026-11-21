export type ResolutionSource = "LIVE_INFERENCE" | "LLM_CACHE"

export type Metadata = {
  resolution_source: ResolutionSource
  model: string
  latency_ms: number
  input_tokens: number
  output_tokens: number
  key_id: string | null
  fallback_attempts: number
}

export type Message =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; metadata: Metadata }
