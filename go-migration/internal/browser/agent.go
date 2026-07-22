package browser

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os/exec"
	"sync"
)

type Request struct {
	ID     int    `json:"id"`
	Method string `json:"method"` // "fetch_page_text" | "fetch_page_html"
	Params struct {
		URL     string `json:"url"`
		Timeout int    `json:"timeout,omitempty"`
	} `json:"params"`
}

type Response struct {
	ID     int    `json:"id"`
	Result string `json:"result,omitempty"`
	Error  string `json:"error,omitempty"`
}

type Agent struct {
	cmd    *exec.Cmd
	stdin  io.Writer
	stdout *bufio.Scanner
	mu     sync.Mutex
	nextID int
}

func NewAgent(ctx context.Context, tsScript string) (*Agent, error) {
	cmd := exec.CommandContext(ctx, "node", tsScript)
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, fmt.Errorf("stdin pipe: %w", err)
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("stdout pipe: %w", err)
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return nil, fmt.Errorf("stderr pipe: %w", err)
	}

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start agent: %w", err)
	}

	// Drain stderr in background
	go io.Copy(io.Discard, stderr)

	return &Agent{
		cmd:    cmd,
		stdin:  stdin,
		stdout: bufio.NewScanner(stdout),
	}, nil
}

func (a *Agent) FetchPageText(ctx context.Context, url string, timeout int) (string, error) {
	return a.call(ctx, "fetch_page_text", url, timeout)
}

func (a *Agent) FetchPageHTML(ctx context.Context, url string, timeout int) (string, error) {
	return a.call(ctx, "fetch_page_html", url, timeout)
}

func (a *Agent) call(ctx context.Context, method, url string, timeout int) (string, error) {
	a.mu.Lock()
	a.nextID++
	id := a.nextID
	a.mu.Unlock()

	req := Request{
		ID:     id,
		Method: method,
	}
	req.Params.URL = url
	req.Params.Timeout = timeout

	reqBytes, err := json.Marshal(req)
	if err != nil {
		return "", fmt.Errorf("marshal request: %w", err)
	}

	if _, err := fmt.Fprintln(a.stdin, string(reqBytes)); err != nil {
		return "", fmt.Errorf("write request: %w", err)
	}

	// Read response lines until we find our ID
	for a.stdout.Scan() {
		var resp Response
		if err := json.Unmarshal(a.stdout.Bytes(), &resp); err != nil {
			continue
		}
		if resp.ID != id {
			continue
		}
		if resp.Error != "" {
			return "", fmt.Errorf("browser error: %s", resp.Error)
		}
		return resp.Result, nil
	}

	return "", fmt.Errorf("browser agent closed unexpectedly")
}

func (a *Agent) Close() error {
	fmt.Fprintln(a.stdin, `{"id":0,"method":"shutdown"}`)
	return a.cmd.Wait()
}
