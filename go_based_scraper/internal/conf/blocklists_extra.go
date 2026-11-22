// Negative signals: asset extensions and infrastructure labels.
package conf

// NonHTMLExtensions are binary/asset file extensions to reject.
var NonHTMLExtensions = []string{
	".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".bmp", ".tiff",
	".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
	".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
	".mp4", ".mp3", ".mov", ".avi", ".wmv", ".mkv", ".webm", ".wav", ".flac",
	".ico", ".css", ".js", ".mjs", ".map", ".xml", ".json", ".csv", ".txt",
	".rss", ".atom", ".woff", ".woff2", ".ttf", ".eot", ".otf",
	".exe", ".msi", ".deb", ".rpm", ".dmg", ".apk", ".jar",
}

// TitleStopwords are words that carry no distinguishing information in titles.
var TitleStopwords = []string{
	"the", "a", "an", "and", "or", "of", "on", "in", "at", "for", "to", "with",
	"international", "national", "global", "annual", "biennial",
	"conference", "conferences", "symposium", "congress", "summit", "workshop",
	"colloquium", "convention", "seminar", "meeting", "forum", "proceedings",
	"ieee", "acm", "st", "nd", "rd", "th",
	"bangladesh", "bangladeshi", "dhaka",
}

// InfraLabels are host labels that are infrastructure, never a conference.
var InfraLabels = []string{
	"autodiscover", "autoconfig", "cpanel", "whm", "webdisk", "webmail",
	"cpcontacts", "cpcalendars", "mail", "smtp", "imap", "pop", "mx",
	"ns1", "ns2", "dns", "vpn", "remote", "ftp", "sftp", "ssh",
	"moodle", "lms", "elearning", "library", "portal", "sis", "erp",
	"accounts", "account", "admission", "admissions", "result", "results",
	"notice", "news", "blog", "cms", "wiki", "git", "gitlab", "jenkins",
	"test", "dev", "staging", "demo", "backup", "old", "new", "temp",
	"api", "cdn", "static", "assets", "img", "images", "media", "files",
	"convocation", "convapi", "alumni", "campus", "registrar",
	"ictcell", "ictserver", "ictvm", "ict", "info", "contact", "app", "apps",
	"heqep", "emss", "clab", "econ", "secondaryschool",
	"email", "print", "proxy", "monitor", "grafana", "status",
}

func containsString(slice []string, s string) bool {
	for _, v := range slice {
		if v == s {
			return true
		}
	}
	return false
}
