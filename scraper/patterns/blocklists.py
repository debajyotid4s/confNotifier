"""Negative signals: hosts and path fragments to reject."""

import re

#: Hosts that never host a Bangladeshi CFP but are linked from every homepage.
HOST_BLOCKLIST = frozenset({
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
    "easychair.org", "edas.info", "cmt3.research.microsoft.com",
    "ieee.org", "www.ieee.org", "site.ieee.org", "sites.ieee.org",
    "acm.org", "dl.acm.org",
    "play.google.com", "apps.apple.com", "apple.com",
    "adobe.com", "get.adobe.com", "microsoft.com", "office.com",
    "zoom.us", "meet.google.com", "teams.microsoft.com",
    "paypal.com", "sslcommerz.com",
    "portal.gov.bd", "bangladesh.gov.bd", "ugc.gov.bd", "moedu.gov.bd",
})
#: Path/host fragments that mark administrative or archival pages.
JUNK_SEGMENTS = frozenset({
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
})

#: Words that mean "this happened already".
STALE_WORDS = re.compile(
    r"(?:^|[-_/.])(?:past|previous|archive[sd]?|history|proceedings?|"
    r"report|gallery|photos?|highlights?|recap|concluded|completed)(?:$|[-_/.])"
)

NON_HTML_EXTENSIONS = frozenset({
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".bmp", ".tiff",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".mp4", ".mp3", ".mov", ".avi", ".wmv", ".mkv", ".webm", ".wav", ".flac",
    ".ico", ".css", ".js", ".mjs", ".map", ".xml", ".json", ".csv", ".txt",
    ".rss", ".atom", ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".exe", ".msi", ".deb", ".rpm", ".dmg", ".apk", ".jar",
})

#: Host labels that are infrastructure, never a conference (used by crt_monitor).
INFRA_LABELS = frozenset({
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
})
