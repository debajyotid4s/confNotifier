#: Domains queried per run. CertSpotter's free tier is metered, and unscanned
#: domains are prioritised so coverage advances every day.
MAX_QUERIES_PER_RUN = 8
CERTSPOTTER_URL = "https://api.certspotter.com/v1/issuances"
CRTSH_URL = "https://crt.sh/?q=%.{domain}&output=json"
QUERY_TIMEOUT = 15
CRTSH_TIMEOUT = 60
INTER_QUERY_SLEEP = 0.2
