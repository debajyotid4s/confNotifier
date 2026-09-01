import re

_DATE_PATTERNS = re.compile(
    r"(?:19|20)\d{2}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}[/.]\d{1,2}[/.](?:19|20)\d{2}"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?\s*,?\s*(?:19|20)\d{2}"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
    r"\s*,?\s*(?:19|20)\d{2}",
    re.IGNORECASE,
)

_KEYWORDS = re.compile(
    r"deadline|due\s+(?:date|by|on)|last\s+date|closing\s+date|closes?\s+on"
    r"|submission|submit|abstract|full\s+paper|manuscript|camera[-\s]?ready"
    r"|call\s+for\s+paper|cfp|important\s+date|key\s+date|timeline"
    r"|notification|acceptance|registration|extended|extension"
    r"|revised|new\s+deadline|final\s+date",
    re.IGNORECASE,
)
