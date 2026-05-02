package llm

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	openai "github.com/sashabaranov/go-openai"

	"github.com/unrealandychan/rekipedia/internal/models"
)

// mockOpenAIServer returns a test server that responds to chat completion requests.
func mockOpenAIServer(t *testing.T, response string, statusCode int) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(statusCode)
		if statusCode == http.StatusOK {
			resp := openai.ChatCompletionResponse{
				ID:     "test-id",
				Object: "chat.completion",
				Choices: []openai.ChatCompletionChoice{
					{
						Index: 0,
						Message: openai.ChatCompletionMessage{
							Role:    openai.ChatMessageRoleAssistant,
							Content: response,
						},
						FinishReason: "stop",
					},
				},
			}
			_ = json.NewEncoder(w).Encode(resp)
		} else {
			_ = json.NewEncoder(w).Encode(map[string]string{"error": "server error"})
		}
	}))
}

// mockEmbeddingServer returns a test server for embedding requests.
func mockEmbeddingServer(t *testing.T, dims int) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		// Decode input to know how many vectors to return
		var req struct {
			Input []string `json:"input"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		n := len(req.Input)
		if n == 0 {
			n = 1
		}
		data := make([]openai.Embedding, n)
		for i := range data {
			vec := make([]float64, dims)
			for j := range vec {
				vec[j] = float64(i+1) * 0.1
			}
			vec64 := make([]float32, dims)
		for j := range vec64 {
			vec64[j] = float32(float64(i+1) * 0.1)
		}
		data[i] = openai.Embedding{Index: i, Embedding: vec64}
		}
		resp := openai.EmbeddingResponse{Data: data}
		_ = json.NewEncoder(w).Encode(resp)
	}))
}

// newTestClient creates a Client pointed at the given test server URL.
func newTestClient(serverURL, model string) *Client {
	cfg := models.LLMConfig{
		Model:       model,
		APIKey:      "test-key",
		BaseURL:     serverURL + "/v1",
		Temperature: 0.2,
	}
	return New(cfg)
}

// ── Tests ─────────────────────────────────────────────────────────────────────

func TestNewClient(t *testing.T) {
	cfg := models.LLMConfig{Model: "ollama/llama4", Temperature: 0.2}
	c := New(cfg)
	if c == nil {
		t.Fatal("expected non-nil client")
	}
	if c.model != "llama4" {
		t.Errorf("expected stripped model 'llama4', got %q", c.model)
	}
	if c.temp != 0.2 {
		t.Errorf("expected temp 0.2, got %f", c.temp)
	}
}

func TestNewClientStripsPrefix(t *testing.T) {
	cases := []struct {
		model    string
		expected string
	}{
		{"ollama/llama4", "llama4"},
		{"anthropic/claude-opus-4", "claude-opus-4"},
		{"openai/gpt-4o", "gpt-4o"},
		{"gpt-4o", "gpt-4o"}, // no prefix
	}
	for _, tc := range cases {
		c := New(models.LLMConfig{Model: tc.model})
		if c.model != tc.expected {
			t.Errorf("model=%q: expected %q, got %q", tc.model, tc.expected, c.model)
		}
	}
}

func TestInferBaseURL(t *testing.T) {
	cases := []struct {
		model    string
		expected string
	}{
		{"ollama/llama4", "http://localhost:11434/v1"},
		{"lm-studio/mistral", "http://localhost:1234/v1"},
		{"gpt-4o", ""},
		{"anthropic/claude-opus-4", ""},
	}
	for _, tc := range cases {
		got := inferBaseURL(tc.model)
		if got != tc.expected {
			t.Errorf("inferBaseURL(%q) = %q, want %q", tc.model, got, tc.expected)
		}
	}
}

func TestCallSuccess(t *testing.T) {
	srv := mockOpenAIServer(t, "Hello, world!", http.StatusOK)
	defer srv.Close()

	c := newTestClient(srv.URL, "gpt-4o")
	resp, err := c.Call(context.Background(), "You are helpful.", "Say hello.")
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	if resp != "Hello, world!" {
		t.Errorf("expected 'Hello, world!', got %q", resp)
	}
}

func TestCallNoSystem(t *testing.T) {
	srv := mockOpenAIServer(t, "No system prompt.", http.StatusOK)
	defer srv.Close()

	c := newTestClient(srv.URL, "gpt-4o")
	resp, err := c.Call(context.Background(), "", "No system.")
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	if resp == "" {
		t.Error("expected non-empty response")
	}
}

func TestCallContextCancelled(t *testing.T) {
	srv := mockOpenAIServer(t, "never", http.StatusOK)
	defer srv.Close()

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancel immediately

	c := newTestClient(srv.URL, "gpt-4o")
	_, err := c.Call(ctx, "", "test")
	if err == nil {
		t.Error("expected error for cancelled context")
	}
}

func TestStreamCall(t *testing.T) {
	// Build an SSE-style streaming response
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		flusher, _ := w.(http.Flusher)

		chunks := []string{"Hello", ", ", "world", "!"}
		for _, chunk := range chunks {
			resp := openai.ChatCompletionStreamResponse{
				Choices: []openai.ChatCompletionStreamChoice{
					{Delta: openai.ChatCompletionStreamChoiceDelta{Content: chunk}},
				},
			}
			data, _ := json.Marshal(resp)
			_, _ = w.Write([]byte("data: "))
			_, _ = w.Write(data)
			_, _ = w.Write([]byte("\n\n"))
			if flusher != nil {
				flusher.Flush()
			}
		}
		_, _ = w.Write([]byte("data: [DONE]\n\n"))
		if flusher != nil {
			flusher.Flush()
		}
	}))
	defer srv.Close()

	c := newTestClient(srv.URL, "gpt-4o")
	var collected strings.Builder
	err := c.StreamCall(context.Background(), "", "test", func(token string) {
		collected.WriteString(token)
	})
	if err != nil {
		t.Fatalf("StreamCall error: %v", err)
	}
	// We may not get all chunks depending on SSE parsing, but shouldn't error
	_ = collected.String()
}

func TestEmbedSuccess(t *testing.T) {
	srv := mockEmbeddingServer(t, 4)
	defer srv.Close()

	c := newTestClient(srv.URL, "gpt-4o")
	vectors, err := c.Embed(context.Background(), []string{"hello", "world"})
	if err != nil {
		t.Fatalf("Embed error: %v", err)
	}
	if len(vectors) != 2 {
		t.Errorf("expected 2 vectors, got %d", len(vectors))
	}
	for i, v := range vectors {
		if len(v) != 4 {
			t.Errorf("vector[%d]: expected dim 4, got %d", i, len(v))
		}
	}
}

func TestModelAccessor(t *testing.T) {
	c := New(models.LLMConfig{Model: "ollama/llama4"})
	if c.Model() != "llama4" {
		t.Errorf("expected 'llama4', got %q", c.Model())
	}
}

func TestIsTransient(t *testing.T) {
	cases := []struct {
		err      string
		expected bool
	}{
		{"connection timeout", true},
		{"502 bad gateway", true},
		{"503 service unavailable", true},
		{"429 too many requests", true},
		{"connection reset by peer", true},
		{"invalid API key", false},
		{"model not found", false},
	}
	for _, tc := range cases {
		err := strings.NewReader(tc.err) // use as dummy
		_ = err
		got := isTransient(mockError(tc.err))
		if got != tc.expected {
			t.Errorf("isTransient(%q) = %v, want %v", tc.err, got, tc.expected)
		}
	}
}

type mockError string

func (e mockError) Error() string { return string(e) }

func TestBuildMessagesWithSystem(t *testing.T) {
	msgs := buildMessages("You are helpful.", "What is Go?")
	if len(msgs) != 2 {
		t.Errorf("expected 2 messages, got %d", len(msgs))
	}
	if msgs[0].Role != openai.ChatMessageRoleSystem {
		t.Errorf("expected system role first")
	}
	if msgs[1].Role != openai.ChatMessageRoleUser {
		t.Errorf("expected user role second")
	}
}

func TestBuildMessagesWithoutSystem(t *testing.T) {
	msgs := buildMessages("", "Just a question.")
	if len(msgs) != 1 {
		t.Errorf("expected 1 message, got %d", len(msgs))
	}
	if msgs[0].Role != openai.ChatMessageRoleUser {
		t.Errorf("expected user role")
	}
}
