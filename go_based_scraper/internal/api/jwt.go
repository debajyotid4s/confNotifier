// JWT creation and verification (HS256).
//
// The token embeds the user's token_version (`tv`) so logout / account delete
// can revoke every issued token by bumping that counter. Verification compares
// the embedded tv against the current value in the database.
package api

import (
	"os"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// jwtExpDays is the token lifetime, matching auth.py JWT_EXP_DAYS.
const jwtExpDays = 7

// payload is the verified JWT claim set.
type payload struct {
	Sub   string `json:"sub"`
	Email string `json:"email"`
	TV    int    `json:"tv"`
}

// jwtManager signs and verifies tokens with the configured secret.
type jwtManager struct {
	secret []byte
}

func newJWTManager() *jwtManager {
	return &jwtManager{secret: []byte(os.Getenv("JWT_SECRET"))}
}

// create returns a signed token embedding the user's current token_version.
func (m *jwtManager) create(uid, email string, tv int) (string, error) {
	now := time.Now()
	claims := struct {
		jwt.RegisteredClaims
		Email string `json:"email"`
		TV    int    `json:"tv"`
	}{
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   uid,
			ExpiresAt: jwt.NewNumericDate(now.Add(jwtExpDays * 24 * time.Hour)),
			IssuedAt:  jwt.NewNumericDate(now),
		},
		Email: email,
		TV:    tv,
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return tok.SignedString(m.secret)
}

// decode verifies the signature and expiry, returning the claims. It does not
// check revocation — callers compare payload.TV against the database.
func (m *jwtManager) decode(token string) (*payload, error) {
	p := struct {
		jwt.RegisteredClaims
		Email string `json:"email"`
		TV    int    `json:"tv"`
	}{}
	_, err := jwt.ParseWithClaims(token, &p, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errBadAlg
		}
		return m.secret, nil
	})
	if err != nil {
		return nil, err
	}
	return &payload{Sub: p.Subject, Email: p.Email, TV: p.TV}, nil
}
