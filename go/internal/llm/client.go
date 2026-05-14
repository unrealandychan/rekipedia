// Package llm provides an OpenAI-compatible LLM client with retry and streaming.
// Works with any OpenAI-compatible API: Ollama, Anthropic (via proxy), Azure, etc.
package llm

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	openai "github.com/sashabaranov/go-openai"

	"github.com/unrealandychan/close-wiki/internal/models"
)

// ErrEmptyResponse is returned when the LLM returns no choices.
var ErrEmptyResponse = errors.New("llm: empty response")

// Client wraps go-openai and handles provider routing + retry.
type Client struct {
	oc    *openai.Client
	model string
	temp  float32
	cfg   models.LLMConfig
}

// New creates a Client from LLMConfig.
// Provider prefix (e.g. "ollama/llama4", "anthropic/claude-opus-4") is stripped
// before sending to the API; BaseURL is inferred from the prefix when not set.
func New(cfg models.LLMConfig) *Client {
	model := cfg.Model
	baseURL := cfg.BaseURL

	// Infer BaseURL from model prefix when not explicitly set
	if baseURL == "" {
		baseURL = inferBaseURL(cfg.Model)
	}

	// Strip provider prefix for the actual API call
	if idx := strings.Index(model, "/"); idx != -1 {
		model = model[idx+1:]
	}

	ocfg := openai.DefaultConfig(cfg.APIKey)
	if baseURL != "" {
		ocfg.BaseURL = baseURL
	}

	return &Client{
		oc:    openai.NewClientWithConfig(ocfg),
		model: model,
		temp:  float32(cfg.Temperature),
		cfg:   cfg,
	}
}

// inferBaseURL returns a known BaseURL for common provider prefixes.
func inferBaseURL(model string) string {
	switch {
	case strings.HasPrefix(model, "ollama/"):
		return "http://localhost:11434/v1"
	case strings.HasPrefix(model, "lm-studio/"):
		return "http://localhost:1234/v1"
	default:
		return ""
	}
}

// Call sends a chat completion request and returns the full response text.
// Retries up to maxRetries times on transient errors with exponential backoff.
func (c *Client) Call(ctx context.Context, system, prompt string) (string, error) {
	return c.CallWithRetry(ctx, system, prompt, 3)
}

// CallWithRetry allows callers to control retry count.
func (c *Client) CallWithRetry(ctx context.Context, system, prompt string, maxRetries int) (string, error) {
	msgs := buildMessages(system, prompt)
	req := openai.ChatCompletionRequest{
		Model:       c.model,
		Messages:    msgs,
		Temperature: c.temp,
	}

	var lastErr error
	for attempt := 0; attempt < maxRetries; attempt++ {
		if attempt > 0 {
			select {
			case <-ctx.Done():
				return "", ctx.Err()
			case <-time.After(time.Duration(5*(1<<attempt)) * time.Second):
			}
		}

		resp, err := c.oc.CreateChatCompletion(ctx, req)
		if err != nil {
			lastErr = err
			// Only retry on transient errors
			if isTransient(err) {
				continue
			}
			return "", fmt.Errorf("llm call: %w", err)
		}
		if len(resp.Choices) == 0 {
			return "", ErrEmptyResponse
		}
		return resp.Choices[0].Message.Content, nil
	}
	return "", fmt.Errorf("llm call failed after %d retries: %w", maxRetries, lastErr)
}

// StreamCall streams token chunks via the callback cb.
// Returns nil when the stream ends normally (io.EOF is swallowed).
func (c *Client) StreamCall(ctx context.Context, system, prompt string, cb func(token string)) error {
	msgs := buildMessages(system, prompt)
	req := openai.ChatCompletionRequest{
		Model:       c.model,
		Messages:    msgs,
		Temperature: c.temp,
		Stream:      true,
	}

	stream, err := c.oc.CreateChatCompletionStream(ctx, req)
	if err != nil {
		return fmt.Errorf("llm stream: %w", err)
	}
	defer stream.Close()

	for {
		resp, err := stream.Recv()
		if err != nil {
			// io.EOF is normal stream end
			break
		}
		if len(resp.Choices) > 0 {
			cb(resp.Choices[0].Delta.Content)
		}
	}
	return nil
}

// Embed creates embeddings for the given texts using the configured embed model.
// Returns a slice of float32 vectors, one per input text.
func (c *Client) Embed(ctx context.Context, texts []string) ([][]float32, error) {
	embedModel := c.cfg.EmbedModel
	if embedModel == "" {
		embedModel = "text-embedding-3-small"
	}

	// Strip provider prefix
	if idx := strings.Index(embedModel, "/"); idx != -1 {
		embedModel = embedModel[idx+1:]
	}

	// Build a separate client if embed provider differs
	ec := c.oc
	if c.cfg.EmbedProvider != "" && c.cfg.EmbedProvider != providerFromModel(c.cfg.Model) {
		ecfg := openai.DefaultConfig(c.cfg.APIKey)
		if baseURL := inferBaseURLForProvider(c.cfg.EmbedProvider); baseURL != "" {
			ecfg.BaseURL = baseURL
		}
		ec = openai.NewClientWithConfig(ecfg)
	}

	req := openai.EmbeddingRequest{
		Model: openai.EmbeddingModel(embedModel),
		Input: texts,
	}
	resp, err := ec.CreateEmbeddings(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("embed: %w", err)
	}

	vectors := make([][]float32, len(resp.Data))
	for i, d := range resp.Data {
		v := make([]float32, len(d.Embedding))
		for j, f := range d.Embedding {
			v[j] = float32(f)
		}
		vectors[i] = v
	}
	return vectors, nil
}

// ToolCallResponse holds the result of a CallWithTools call.
type ToolCallResponse struct {
	Content   string
	ToolCalls []map[string]any
}

// CallWithTools sends a multi-turn conversation with optional tool schemas.
// Returns ToolCallResponse with Content and ToolCalls.
// If tools is nil or the model doesn't support function calling, Content is returned directly.
func (c *Client) CallWithTools(ctx context.Context, messages []map[string]any, tools []map[string]any) (*ToolCallResponse, error) {
	// Convert generic messages to go-openai format
	var oaiMsgs []openai.ChatCompletionMessage
	for _, m := range messages {
		role, _ := m["role"].(string)
		content, _ := m["content"].(string)
		msg := openai.ChatCompletionMessage{Role: role, Content: content}

		// Handle tool_call_id for tool results
		if tcID, ok := m["tool_call_id"].(string); ok {
			msg.ToolCallID = tcID
		}

		// Handle tool_calls in assistant messages
		if tcs, ok := m["tool_calls"].([]map[string]any); ok {
			for _, tc := range tcs {
				id, _ := tc["id"].(string)
				fn, _ := tc["function"].(map[string]any)
				name, _ := fn["name"].(string)
				args, _ := fn["arguments"].(string)
				msg.ToolCalls = append(msg.ToolCalls, openai.ToolCall{
					ID:   id,
					Type: openai.ToolTypeFunction,
					Function: openai.FunctionCall{
						Name:      name,
						Arguments: args,
					},
				})
			}
		}
		oaiMsgs = append(oaiMsgs, msg)
	}

	req := openai.ChatCompletionRequest{
		Model:       c.model,
		Messages:    oaiMsgs,
		Temperature: c.temp,
	}

	// Add tool schemas if provided
	if len(tools) > 0 {
		b, _ := json.Marshal(tools)
		var oaiTools []openai.Tool
		if err := json.Unmarshal(b, &oaiTools); err == nil {
			req.Tools = oaiTools
			req.ToolChoice = "auto"
		}
	}

	resp, err := c.oc.CreateChatCompletion(ctx, req)
	if err != nil {
		return nil, fmt.Errorf("llm call with tools: %w", err)
	}
	if len(resp.Choices) == 0 {
		return nil, ErrEmptyResponse
	}

	msg := resp.Choices[0].Message
	result := &ToolCallResponse{Content: msg.Content}

	for _, tc := range msg.ToolCalls {
		result.ToolCalls = append(result.ToolCalls, map[string]any{
			"id":   tc.ID,
			"type": "function",
			"function": map[string]any{
				"name":      tc.Function.Name,
				"arguments": tc.Function.Arguments,
			},
		})
	}
	return result, nil
}

// Model returns the effective model name (without provider prefix).
func (c *Client) Model() string { return c.model }

// ── helpers ───────────────────────────────────────────────────────────────────

func buildMessages(system, prompt string) []openai.ChatCompletionMessage {
	var msgs []openai.ChatCompletionMessage
	if system != "" {
		msgs = append(msgs, openai.ChatCompletionMessage{
			Role: openai.ChatMessageRoleSystem, Content: system,
		})
	}
	msgs = append(msgs, openai.ChatCompletionMessage{
		Role: openai.ChatMessageRoleUser, Content: prompt,
	})
	return msgs
}

func isTransient(err error) bool {
	if err == nil {
		return false
	}
	s := err.Error()
	return strings.Contains(s, "timeout") ||
		strings.Contains(s, "connection reset") ||
		strings.Contains(s, "502") ||
		strings.Contains(s, "503") ||
		strings.Contains(s, "429")
}

func providerFromModel(model string) string {
	if idx := strings.Index(model, "/"); idx != -1 {
		return model[:idx]
	}
	return ""
}

func inferBaseURLForProvider(provider string) string {
	switch provider {
	case "ollama":
		return "http://localhost:11434/v1"
	case "lm-studio":
		return "http://localhost:1234/v1"
	default:
		return ""
	}
}
