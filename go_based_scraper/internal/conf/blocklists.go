// Negative signals: hosts and path fragments to reject.
package conf

// HostBlocklist contains hosts that never host a Bangladeshi CFP.
var HostBlocklist = []string{
	"facebook.com", "m.facebook.com", "fb.com", "fb.me",
	"twitter.com", "x.com", "t.co",
	"youtube.com", "youtu.be", "m.youtube.com",
	"instagram.com", "linkedin.com", "pinterest.com", "tiktok.com",
	"whatsapp.com", "wa.me", "telegram.me", "t.me",
	"wikipedia.org", "en.wikipedia.org", "wikimedia.org",
	"google.com", "docs.google.com", "drive.google.com", "forms.gle",
	"goo.gl", "bit.ly", "tinyurl.com",
	"scholar.google.com", "researchgate.net", "academia.edu",
	"springer.com", "link.springer.com", "sciencedirect.com",
	"elsevier.com", "wiley.com", "onlinelibrary.wiley.com",
	"tandfonline.com", "mdpi.com", "hindawi.com", "arxiv.org",
	"doi.org", "dx.doi.org", "orcid.org", "scopus.com",
	"easychair.org", "edas.info",
	"ieee.org", "www.ieee.org", "site.ieee.org", "sites.ieee.org",
	"acm.org", "dl.acm.org",
	"play.google.com", "apps.apple.com", "apple.com",
	"adobe.com", "get.adobe.com", "microsoft.com", "office.com",
	"zoom.us", "meet.google.com", "teams.microsoft.com",
	"paypal.com", "sslcommerz.com",
	"portal.gov.bd", "bangladesh.gov.bd", "ugc.gov.bd", "moedu.gov.bd",
}

// JunkSegments are path/host fragments marking admin or archival pages.
var JunkSegments = []string{
	"news", "notice", "notices", "noticeboard", "announcement", "announcements",
	"archive", "archives", "gallery", "galleries", "photo", "photos", "album",
	"albums", "video", "videos", "media", "press", "blog", "blogs",
	"result", "results", "exam", "exams", "routine", "syllabus", "curriculum",
	"admission", "admissions", "apply", "fee", "fees", "payment", "tuition",
	"tender", "tenders", "procurement", "auction",
	"job", "jobs", "career", "careers", "vacancy", "vacancies", "recruitment",
	"alumni", "convocation", "graduation",
	"faculty", "staff", "employee", "teachers", "department", "departments",
	"login", "signin", "signup", "register-user", "account", "accounts",
	"webmail", "mail", "email", "roundcube", "cpanel", "webdisk",
	"sitemap", "rss", "feed", "feeds", "tag", "tags", "category", "categories",
	"author", "search", "print", "download", "downloads", "upload", "uploads",
	"wp-admin", "wp-json", "wp-content", "wp-includes", "wp-login.php",
	"privacy", "terms", "disclaimer", "contact", "contact-us", "about-us",
	"library", "moodle", "lms", "elearning", "portal", "erp", "sis",
	"hostel", "transport", "clubs", "sports", "cafeteria",
}
