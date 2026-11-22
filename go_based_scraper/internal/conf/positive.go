// Positive signals: words and shapes that mark an academic event.
package conf

import "regexp"

// EventWords are full words that mark an academic event.
var EventWords = []string{
	"conference", "conf", "symposium", "symposia", "congress", "summit",
	"workshop", "colloquium", "convention", "seminar", "meeting", "forum",
	"proceedings", "icpc",
}

// KnownAcronyms are conference-family acronyms seen across Bangladeshi universities.
var KnownAcronyms = []string{
	"iccit", "icece", "icmiee", "icace", "icca", "iciset", "icerie", "icaeee",
	"icmere", "iceab", "icche", "icict", "iciev", "icaict", "iccad", "iccte",
	"peeiacon", "raaicon", "spicscon", "becithcon", "sticon", "eicon",
	"qpain", "isee", "icefront", "icbbe", "iccma", "wiecon", "hitech",
	"compas", "ntc", "icrest", "icsct", "iccitechn",
}

// LookalikeWords are English words that accidentally match acronym shapes.
var LookalikeWords = []string{
	"falcon", "bacon", "beacon", "deacon", "flacon", "gascon", "rubicon",
	"silicon", "lexicon", "icon", "telecon", "tycoon", "dragon", "wagon",
	"salon", "talon", "melon", "colon", "canon", "cannon", "carton",
	"recon", "sitcon", "zircon",
	"ice", "iced", "icing", "iceland", "icecream", "iconic", "iconify",
	"ical", "icao", "icar", "icam", "ichat", "icloud", "icmp",
	"confetti", "confide", "confirm", "conform", "confuse",
}

// NonEventWords are path words that pair with a year but are not events.
var NonEventWords = []string{
	"summer", "winter", "spring", "autumn", "fall", "semester", "session",
	"batch", "year", "annual", "budget", "calendar", "holiday", "vacation",
	"schedule", "timetable", "circular", "policy", "plan", "report", "review",
	"edition", "volume", "issue", "version", "release", "update", "list",
	"team", "board", "committee", "council", "senate", "syndicate",
	"form", "forms", "guide", "manual", "brochure", "prospectus",
}

var hostLabelShapes = []*regexp.Regexp{
	regexp.MustCompile(`^ic[a-z]{2,8}(?:[-_.]?(?:19|20)\d{2})?$`),
	regexp.MustCompile(`^[a-z]{2,12}i?con(?:[-_.]?(?:19|20)\d{2})?$`),
	regexp.MustCompile(`^[a-z]{2,12}conf(?:erence)?(?:[-_.]?(?:19|20)\d{2})?$`),
	regexp.MustCompile(`^ieee[a-z0-9-]{2,16}$`),
	regexp.MustCompile(`^(?:conference|conf|symposium|congress|summit|workshop|cfp)[a-z0-9]{0,8}(?:[-_.]?(?:19|20)\d{2})?$`),
	regexp.MustCompile(`^[a-z]{2,10}[-_](?:conference|conf|symposium|congress|summit|workshop)(?:[-_.]?(?:19|20)\d{2})?$`),
}

var acronymYearRe = regexp.MustCompile(`(?:^|[-_/])([a-z]{3,15})[-_.]?((?:19|20)\d{2})(?:$|[-_/])`)

var cfpRe = regexp.MustCompile(
	`call[-_ ]?(?:for)?[-_ ]?(?:papers?|abstracts?|submissions?|participation)` +
		`|(?:^|[-_/])cfp(?:$|[-_/.])` +
		`|paper[-_ ]?submission` +
		`|abstract[-_ ]?submission` +
		`|submission[-_ ]?(?:deadline|guideline)` +
		`|author[-_ ]?(?:guideline|instruction)` +
		`|important[-_ ]?date`,
)

var eventYearRe = regexp.MustCompile(
	`(?:conf(?:erence)?|symposium|congress|summit|workshop|colloquium|` +
		`convention|seminar|forum)[a-z]*[-_.]?(?:19|20)\d{2}`,
)
