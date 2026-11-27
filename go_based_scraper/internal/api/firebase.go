// Firebase ID token verification without the firebase-admin SDK.
//
// Firebase signs ID tokens RS256 with the project's service-account key. The
// matching public certificate is published at the x509 metadata endpoint keyed
// by the service account email, so we fetch it, verify the signature, and read
// the claims. This mirrors firebase_admin.auth.verify_id_token's server-side
// checks (signature, expiry, audience) without the heavy SDK.
package api

import (
	"context"
	"crypto"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

// x509MetadataURL returns the Google x509 certificate endpoint for an email.
func x509MetadataURL(email string) string {
	return "https://www.googleapis.com/robot/v1/metadata/x509/" + email
}

// firebaseInvalid is a rejected/invalid Firebase token (401).
var firebaseInvalid = &apiError{http.StatusUnauthorized, "Invalid Firebase token"}

// firebaseUnavailable means we could not verify (503).
var firebaseUnavailable = &apiError{http.StatusServiceUnavailable, "Firebase verification unavailable"}

// verifyFirebaseIDToken verifies a Firebase ID token and returns its uid, email,
// and email-verified flag.
func verifyFirebaseIDToken(ctx context.Context, token string) (uid, email string, verified bool, apiErr *apiError) {
	parts := strings.SplitN(token, ".", 3)
	if len(parts) != 3 {
		return "", "", false, firebaseInvalid
	}

	headerJSON, err := base64URLDecode(parts[0])
	if err != nil {
		return "", "", false, firebaseInvalid
	}
	var header struct {
		Kid string `json:"kid"`
		Alg string `json:"alg"`
	}
	if err := json.Unmarshal(headerJSON, &header); err != nil {
		return "", "", false, firebaseInvalid
	}
	if strings.EqualFold(header.Alg, "RS256") == false {
		return "", "", false, firebaseInvalid
	}

	acctEmail, audience := firebaseConfig()
	certs, err := fetchX509Certs(ctx, acctEmail)
	if err != nil {
		return "", "", false, firebaseUnavailable
	}
	certPEM, ok := certs[header.Kid]
	if !ok {
		return "", "", false, firebaseInvalid
	}
	der, err := pemDER(certPEM)
	if err != nil {
		return "", "", false, firebaseInvalid
	}
	cert, err := parseCert(der)
	if err != nil {
		return "", "", false, firebaseInvalid
	}
	pub, ok := cert.PublicKey.(*rsa.PublicKey)
	if !ok {
		return "", "", false, firebaseInvalid
	}

	sig, err := base64URLDecode(parts[2])
	if err != nil {
		return "", "", false, firebaseInvalid
	}
	hash := sha256.Sum256([]byte(parts[0] + "." + parts[1]))
	if err := rsa.VerifyPKCS1v15(pub, crypto.SHA256, hash[:], sig); err != nil {
		return "", "", false, firebaseInvalid
	}

	payloadJSON, err := base64URLDecode(parts[1])
	if err != nil {
		return "", "", false, firebaseInvalid
	}
	var claims struct {
		Sub           string `json:"sub"`
		Email         string `json:"email"`
		EmailVerified bool   `json:"email_verified"`
		Aud           string `json:"aud"`
		Exp           int64  `json:"exp"`
	}
	if err := json.Unmarshal(payloadJSON, &claims); err != nil {
		return "", "", false, firebaseInvalid
	}
	if time.Now().Unix() >= claims.Exp {
		return "", "", false, firebaseInvalid
	}
	if audience != "" && claims.Aud != audience {
		return "", "", false, firebaseInvalid
	}

	return claims.Sub, claims.Email, claims.EmailVerified, nil
}

// firebaseConfig returns the service account email (for the x509 endpoint) and
// the expected audience, read from the service-account JSON and env.
func firebaseConfig() (email, audience string) {
	audience = getenvDefault("FIREBASE_AUDIENCE", "")
	raw := getenvDefault("FIREBASE_SERVICE_ACCOUNT_JSON", getenvDefault("FIREBASE_SERVICE_ACCOUNT_JSON_B64", ""))
	if raw == "" {
		if b, err := readFile("/etc/secrets/firebase.json"); err == nil {
			raw = string(b)
		}
	}
	if strings.HasPrefix(raw, "{") {
		var acct fcmAccount
		if err := json.Unmarshal([]byte(raw), &acct); err == nil {
			email = acct.ClientEmail
		}
	}
	return email, audience
}

// fetchX509Certs retrieves the {kid: PEM} certificate map for an email.
func fetchX509Certs(ctx context.Context, email string) (map[string]string, error) {
	if email == "" {
		return nil, fmt.Errorf("no service account email configured")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, x509MetadataURL(email), nil)
	if err != nil {
		return nil, err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("x509 metadata: %d", resp.StatusCode)
	}
	var certs map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&certs); err != nil {
		return nil, err
	}
	return certs, nil
}
