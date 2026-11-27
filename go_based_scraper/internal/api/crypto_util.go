// Small crypto / IO helpers used by the FCM client. Kept local to avoid pulling
// in extra dependencies for a handful of stdlib calls.
package api

import (
	"crypto"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"os"
)

// pemDecode decodes a PEM block.
func pemDecode(b []byte) (*pem.Block, error) {
	block, _ := pem.Decode(b)
	return block, nil
}

// pemDER extracts the DER bytes from a PEM string, or errors when malformed.
func pemDER(pemText string) ([]byte, error) {
	block, err := pemDecode([]byte(pemText))
	if err != nil {
		return nil, err
	}
	if block == nil {
		return nil, errNoPEM
	}
	return block.Bytes, nil
}

// x509ParsePKCS8PrivateKey parses a PKCS#8 RSA private key.
func x509ParsePKCS8PrivateKey(der []byte) (*rsa.PrivateKey, error) {
	key, err := x509.ParsePKCS8PrivateKey(der)
	if err != nil {
		return nil, err
	}
	rsaKey, ok := key.(*rsa.PrivateKey)
	if !ok {
		return nil, errNotRSA
	}
	return rsaKey, nil
}

// rsaPKCS1Sign signs data with RS1/PKCS#1 v1.5 using SHA-256.
func rsaPKCS1Sign(key *rsa.PrivateKey, data []byte) ([]byte, error) {
	hash := sha256.Sum256(data)
	return rsa.SignPKCS1v15(nil, key, crypto.SHA256, hash[:])
}

// base64URL encodes a JSON object as a URL-safe base64 string without padding.
func base64URL(v any) string {
	var raw []byte
	if s, ok := v.(string); ok {
		raw = []byte(s)
	} else {
		raw, _ = json.Marshal(v)
	}
	return base64.RawURLEncoding.EncodeToString(raw)
}

// base64URLBytes URL-safely encodes bytes without padding.
func base64URLBytes(b []byte) string {
	return base64.RawURLEncoding.EncodeToString(b)
}

// base64URLDecode decodes a URL-safe base64 string (with or without padding).
func base64URLDecode(s string) ([]byte, error) {
	if b, err := base64.RawURLEncoding.DecodeString(s); err == nil {
		return b, nil
	}
	return base64.StdEncoding.DecodeString(s)
}

// readFile reads a file, returning an empty slice and error on failure.
func readFile(path string) ([]byte, error) {
	return os.ReadFile(path)
}

// claimContains reports whether a JWT claim array contains a value.
func claimContains(claims []string, want string) bool {
	for _, c := range claims {
		if c == want {
			return true
		}
	}
	return false
}

// errNotRSA is returned when a private key is not RSA.
var (
	errNotRSA = errors.New("private key is not RSA")
	errNoPEM  = errors.New("no PEM block")
)
