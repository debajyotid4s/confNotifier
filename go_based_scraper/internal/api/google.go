// Server-side Google ID token verification.
//
// A Google ID token is an RS256 JWT signed by Google. We verify the signature
// against Google's public keys (JWKS), check expiry and audience, then read the
// subject and email. We never trust the client: the token is fetched from the
// Android app and must be validated server-side, exactly as the Python
// verify_oauth2_token does.
package api

import (
	"context"
	"crypto/rsa"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sync"
	"time"
)

const googleCertsURL = "https://accounts.google.com/o/oauth2/v2/keys"

// googleKeys caches Google's JWKS so we do not hit their certs endpoint on every
// login. It is safe for concurrent use and refreshes after a short TTL.
type googleKeys struct {
	mu      sync.Mutex
	keys    map[string]rsaPublicKey
	fetched time.Time
}

// rsaPublicKey is a decoded RS256 verification key.
type rsaPublicKey struct {
	key *rsa.PublicKey
	kid string
}

var googleKeyCache = &googleKeys{}

func (g *googleKeys) lookup(ctx context.Context, kid string) (*rsaPublicKey, error) {
	g.mu.Lock()
	if g.keys == nil || time.Since(g.fetched) > 5*time.Minute {
		g.mu.Unlock()
		if err := g.refresh(ctx); err != nil {
			return nil, err
		}
		g.mu.Lock()
	}
	defer g.mu.Unlock()
	for _, k := range g.keys {
		if k.kid == kid {
			return &k, nil
		}
	}
	return nil, errors.New("google signing key not found")
}

func (g *googleKeys) refresh(ctx context.Context) error {
	client := &http.Client{Timeout: 10 * time.Second}
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, googleCertsURL, nil)
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("fetch google certs: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("google certs: %d", resp.StatusCode)
	}
	var jwks jwks
	if err := json.NewDecoder(resp.Body).Decode(&jwks); err != nil {
		return fmt.Errorf("parse google certs: %w", err)
	}
	keys := make(map[string]rsaPublicKey, len(jwks.Keys))
	for _, k := range jwks.Keys {
		pub, err := k.publicKey()
		if err != nil {
			continue // skip keys we cannot decode
		}
		keys[k.Kid] = rsaPublicKey{key: pub, kid: k.Kid}
	}
	g.keys = keys
	g.fetched = time.Now()
	return nil
}

type jwks struct {
	Keys []jwk `json:"keys"`
}

type jwk struct {
	Kid  string   `json:"kid"`
	Kty  string   `json:"kty"`
	X5C  []string `json:"x5c"`
	Kid2 string   `json:"x5t"`
}

// publicKey decodes the PEM certificate chain (x5c) into an RSA public key.
func (j jwk) publicKey() (*rsa.PublicKey, error) {
	if len(j.X5C) == 0 {
		return nil, errors.New("no x5c")
	}
	der, err := base64.StdEncoding.DecodeString(j.X5C[0])
	if err != nil {
		return nil, err
	}
	cert, err := parseCert(der)
	if err != nil {
		return nil, err
	}
	pub, ok := cert.PublicKey.(*rsa.PublicKey)
	if !ok {
		return nil, errors.New("google key is not RSA")
	}
	return pub, nil
}

// verifyGoogleIDToken validates a Google ID token and returns its subject and email.
func verifyGoogleIDToken(ctx context.Context, raw, audience string) (sub, email string, err error) {
	p, err := decodeRS256(raw, func(kid string) (*rsaPublicKey, error) {
		return googleKeyCache.lookup(ctx, kid)
	})
	if err != nil {
		return "", "", errGoogle
	}
	if audience != "" && !claimContains(p.Audience, audience) {
		return "", "", errGoogle
	}
	if p.ExpiresAt.Time.Before(time.Now()) {
		return "", "", errGoogle
	}
	return p.Subject, p.Email, nil
}
