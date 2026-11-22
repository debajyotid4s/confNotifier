// Text focus constants and regex patterns.
package conf

import "regexp"

const headChars = 2000
const defaultBudget = 14000
const contextChars = 320

var datePatterns = regexp.MustCompile(
	`(?i)(?:19|20)\d{2}-\d{1,2}-\d{1,2}` +
		`|\d{1,2}[/.]\d{1,2}[/.](?:19|20)\d{2}` +
		`|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\s*,?\s*(?:19|20)\d{2}` +
		`|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*,?\s*(?:19|20)\d{2}`,
)

var keywords = regexp.MustCompile(
	`(?i)deadline|due\s+(?:date|by|on)|last\s+date|closing\s+date|closes?\s+on` +
		`|submission|submit|abstract|full\s+paper|manuscript|camera[-\s]?ready` +
		`|call\s+for\s+paper|cfp|important\s+date|key\s+date|timeline` +
		`|notification|acceptance|registration|extended|extension` +
		`|revised|new\s+deadline|final\s+date`,
)
