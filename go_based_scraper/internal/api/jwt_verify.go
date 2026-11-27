// Helpers for verifying RS256 JWTs (Google/Firebase ID tokens) using keys
// selected by the token's "kid" header. Built on golang-jwt for signature
// handling; we only supply the right public key per kid.
package api

import (
	"crypto/x509"
	"errors"

	"github.com/golang-jwt/jwt/v5"
)

// idTokenClaims is the subset of an ID token we read.
type idTokenClaims struct {
	jwt.RegisteredClaims
	Email string `json:"email"`
}

// decodeRS256 parses and signature-verifies an RS256 JWT, choosing the key by
// the kid in the header. It returns the decoded claims.
func decodeRS256(raw string, keyForKid func(kid string) (*rsaPublicKey, error)) (*idTokenClaims, error) {
	var claims idTokenClaims
	_, err := jwt.ParseWithClaims(raw, &claims, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodRSA); !ok {
			return nil, errors.New("expected RS256")
		}
		kid, _ := t.Header["kid"].(string)
		key, err := keyForKid(kid)
		if err != nil {
			return nil, err
		}
		return key.key, nil
	})
	if err != nil {
		return nil, err
	}
	return &claims, nil
}

// parseCert parses DER-encoded X.509 certificate data.
func parseCert(der []byte) (*x509.Certificate, error) {
	return x509.ParseCertificate(der)
}

var errGoogle = &apiError{400, "Invalid Google token"}
