package notify

import "context"

// FCM accepts at most 500 tokens per multicast call.
const FCMBatch = 500

// PushBatch is one multicast send to a batch of device tokens.
type PushBatch struct {
	Tokens []string
	Title  string
	Body   string
	// Data is the FCM payload (type, screen, optional conference_id).
	Data map[string]string
}

// PushResult is the outcome of one multicast send.
type PushResult struct {
	Sent int
	Dead []string
}

// Pusher sends FCM pushes. Defined here so tests inject a fake and never touch
// Firebase. Implementations must shard tokens into batches of <= FCMBatch.
type Pusher interface {
	Multicast(ctx context.Context, batches []PushBatch) ([]PushResult, error)
}

// DeadTokens collects every token a Pusher reported as permanently invalid so
// the caller can prune them from the database.
func DeadTokens(results []PushResult) []string {
	var dead []string
	for _, r := range results {
		dead = append(dead, r.Dead...)
	}
	return dead
}

// SendMulticast shards tokens into FCM-sized batches and sends one message to
// each. It returns the total delivered count and the list of dead tokens.
func SendMulticast(ctx context.Context, p Pusher, tokens []string, title, body string, data map[string]string) (int, []string) {
	if len(tokens) == 0 {
		return 0, nil
	}
	var batches []PushBatch
	for start := 0; start < len(tokens); start += FCMBatch {
		end := start + FCMBatch
		if end > len(tokens) {
			end = len(tokens)
		}
		batches = append(batches, PushBatch{
			Tokens: tokens[start:end],
			Title:  title,
			Body:   body,
			Data:   data,
		})
	}
	results, err := p.Multicast(ctx, batches)
	if err != nil {
		return 0, nil
	}
	sent := 0
	for _, r := range results {
		sent += r.Sent
	}
	return sent, DeadTokens(results)
}
