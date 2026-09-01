TELEGRAM_API = "https://api.telegram.org/bot{}/{}"
NOTIFY_WINDOW_DAYS = 30
SEND_TIMEOUT = 15
#: Telegram tolerates roughly one message per second to a channel.
INTER_MESSAGE_SLEEP = 2

#: Human labels for the two announced deadline kinds.
_DEADLINE_LABELS = (("abstract_deadline", "Abstract"), ("full_paper_deadline", "Full paper"))
