// FCM (Firebase Cloud Messaging) HTTP v1 client.
//
// Talks the modern HTTP v1 API directly: it signs a GCP OAuth2 JWT with the
// service account's RSA key, exchanges it for a short-lived access token, then
// posts multicast / topic messages. This avoids the heavy firebase-admin SDK.
package api

import (
	"context"
	"crypto/rsa"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

// fcmBatch is the max tokens FCM accepts per multicast call.
const fcmBatch = 500

// fcmScopes is the OAuth2 scope for sending FCM messages.
const fcmScope = "https://www.googleapis.com/auth/firebase.messages"

// fcmEndpoint / tokenEndpoint are the FCM and OAuth2 endpoints.
const (
	fcmEndpoint   = "https://fcm.googleapis.com/fcm/send/v1"
	tokenEndpoint = "https://oauth2.googleapis.com/token"
)

// FCMClient sends push notifications. It is nil when Firebase is unconfigured.
type FCMClient struct {
	clientEmail string
	privateKey  *rsa.PrivateKey
	projectID   string
	httpClient  *http.Client

	mu          sync.Mutex
	token       string
	tokenExpiry time.Time
}

// fcmAccount is the subset of a service-account JSON we need.
type fcmAccount struct {
	ClientEmail string `json:"client_email"`
	PrivateKey  string `json:"private_key"`
	ProjectID   string `json:"project_id"`
}

// newFCMClient loads the service account from env/file. It returns nil when no
// account is configured, so callers can treat "no FCM" as a clean no-op.
func newFCMClient() *FCMClient {
	raw := getenvDefault("FIREBASE_SERVICE_ACCOUNT_JSON",
		getenvDefault("FIREBASE_SERVICE_ACCOUNT_JSON_B64", ""))
	if raw == "" {
		// Fall back to the mounted secret path.
		if b, err := readFile("/etc/secrets/firebase.json"); err == nil {
			raw = string(b)
		}
	}
	if raw == "" {
		return nil
	}
	if strings.HasPrefix(raw, "{") == false {
		// Try base64 decode when the raw value is not JSON.
		if dec, err := base64.StdEncoding.DecodeString(strings.TrimSpace(raw)); err == nil {
			if strings.HasPrefix(string(dec), "{") {
				raw = string(dec)
			}
		}
	}
	var acct fcmAccount
	if err := json.Unmarshal([]byte(raw), &acct); err != nil {
		return nil
	}
	if acct.ClientEmail == "" || acct.PrivateKey == "" {
		return nil
	}
	key, err := parseRSAPrivateKey(acct.PrivateKey)
	if err != nil {
		return nil
	}
	return &FCMClient{
		clientEmail: acct.ClientEmail,
		privateKey:  key,
		projectID:   acct.ProjectID,
		httpClient:  &http.Client{Timeout: 15 * time.Second},
	}
}

// parseRSAPrivateKey decodes a PEM PKCS#8 RSA private key.
func parseRSAPrivateKey(pemText string) (*rsa.PrivateKey, error) {
	block, _ := pemDecode([]byte(pemText))
	if block == nil {
		return nil, fmt.Errorf("no PEM block in private key")
	}
	return x509ParsePKCS8PrivateKey(block.Bytes)
}

// multicast sends one notification to a batch of tokens, returning the number
// delivered and the tokens FCM rejected (so the caller can prune them).
func (c *FCMClient) multicast(ctx context.Context, tokens []string, title, body string, data map[string]string) (sent int, dead []string) {
	for start := 0; start < len(tokens); start += fcmBatch {
		end := start + fcmBatch
		if end > len(tokens) {
			end = len(tokens)
		}
		s, d, err := c.multicastBatch(ctx, tokens[start:end], title, body, data)
		if err != nil {
			log.Printf("fcm multicast failed: %v", err)
			continue
		}
		sent += s
		dead = append(dead, d...)
	}
	return sent, dead
}

// multicastBatch posts a single FCM-sized batch.
func (c *FCMClient) multicastBatch(ctx context.Context, tokens []string, title, body string, data map[string]string) (int, []string, error) {
	reqBody := map[string]any{
		"message": map[string]any{
			"notification": map[string]string{"title": title, "body": body},
			"data":         data,
			"tokens":       tokens,
		},
	}
	resp, err := c.post(ctx, c.messageURL(), reqBody)
	if err != nil {
		return 0, nil, err
	}
	var out fcmMulticastResp
	if err := json.Unmarshal(resp, &out); err != nil {
		return 0, nil, err
	}
	dead := make([]string, 0, len(out.Responses))
	for i, r := range out.Responses {
		if !r.Success {
			dead = append(dead, tokens[i])
		}
	}
	return out.SuccessCount, dead, nil
}

// sendTopic broadcasts one notification to the subscribed-topic fanout.
func (c *FCMClient) sendTopic(ctx context.Context, title, body string, data map[string]string) error {
	reqBody := map[string]any{
		"message": map[string]any{
			"notification": map[string]string{"title": title, "body": body},
			"data":         data,
			"topic":        "all_users",
		},
	}
	_, err := c.post(ctx, c.messageURL(), reqBody)
	return err
}

// messageURL is the FCM send endpoint for this project.
func (c *FCMClient) messageURL() string {
	return fmt.Sprintf("%s:%s/message", fcmEndpoint, c.projectID)
}

// post signs and sends a JSON POST, authenticating with a cached access token.
func (c *FCMClient) post(ctx context.Context, endpoint string, body any) ([]byte, error) {
	token, err := c.accessToken(ctx)
	if err != nil {
		return nil, err
	}
	marshalled, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, strings.NewReader(string(marshalled)))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	buf := make([]byte, 0, resp.ContentLength)
	tmp := make([]byte, 512)
	for {
		n, rerr := resp.Body.Read(tmp)
		if n > 0 {
			buf = append(buf, tmp[:n]...)
		}
		if rerr != nil {
			break
		}
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("fcm %s: %d: %s", endpoint, resp.StatusCode, strings.TrimSpace(string(buf)))
	}
	return buf, nil
}

// accessToken returns a cached access token, refreshing when expired.
func (c *FCMClient) accessToken(ctx context.Context) (string, error) {
	c.mu.Lock()
	if c.token != "" && time.Now().Before(c.tokenExpiry) {
		tok := c.token
		c.mu.Unlock()
		return tok, nil
	}
	c.mu.Unlock()

	jwt2 := c.signJWT()
	form := url.Values{}
	form.Set("grant_type", "urn:ietf:params:oauth:grant-type:jwt-token")
	form.Set("assertion", jwt2)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, tokenEndpoint, strings.NewReader(form.Encode()))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	var tok oauthToken
	if err := json.NewDecoder(resp.Body).Decode(&tok); err != nil {
		return "", err
	}
	if tok.AccessToken == "" {
		return "", fmt.Errorf("fcm: empty access token")
	}
	c.mu.Lock()
	c.token = tok.AccessToken
	c.tokenExpiry = time.Now().Add(time.Duration(tok.ExpiresIn)*time.Second - time.Minute)
	c.mu.Unlock()
	return tok.AccessToken, nil
}

// signJWT builds and signs a GCP OAuth2 JWT v2 assertion.
func (c *FCMClient) signJWT() string {
	header := base64URL(map[string]string{"alg": "RS256", "typ": "JWT"})
	now := time.Now().UTC()
	payload := base64URL(map[string]any{
		"iss":   c.clientEmail,
		"scope": fcmScope,
		"aud":   tokenEndpoint,
		"iat":   now.Unix(),
		"exp":   now.Add(1 * time.Hour).Unix(),
	})
	signingInput := header + "." + payload
	signed, err := rsaPKCS1Sign(c.privateKey, []byte(signingInput))
	if err != nil {
		return signingInput // unsigned; will fail server-side
	}
	return signingInput + "." + base64URLBytes(signed)
}

// fcmMulticastResp is the FCM multicast response envelope.
type fcmMulticastResp struct {
	SuccessCount int                    `json:"successCount"`
	FailureCount int                    `json:"failureCount"`
	Responses    []fcmMulticastResponse `json:"responses"`
}

// fcmMulticastResponse is one batch member's outcome.
type fcmMulticastResponse struct {
	Success bool `json:"success"`
}

// oauthToken is the token-endpoint response.
type oauthToken struct {
	AccessToken string `json:"access_token"`
	TokenType   string `json:"token_type"`
	ExpiresIn   int    `json:"expires_in"`
}
