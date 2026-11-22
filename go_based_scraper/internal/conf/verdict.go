// Validation verdict type.
package conf

// Verdict is the outcome of validating one extraction.
type Verdict struct {
	Ok        bool
	Permanent bool
	Reason    string
	Fields    []string
}

// Valid returns a passing verdict.
func Valid() Verdict { return Verdict{Ok: true} }

// Reject returns a failing verdict.
func Reject(reason string, fields []string, permanent bool) Verdict {
	return Verdict{Ok: false, Permanent: permanent, Reason: reason, Fields: fields}
}

func (v Verdict) Bool() bool { return v.Ok }
