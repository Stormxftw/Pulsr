"""Profile-wide limits shared by validation, admission, storage and transport."""
MAX_ACTIVE = 24
MAX_DRAFTS = 5
# 12 Discord rings (120/h) plus several GitHub rings fit; 24 Discord rings
# (240/h) leave room for icons and GitHub. Admission uses exact recurring costs.
DEFAULT_REQUESTS_PER_HOUR = 300
MAX_RETRY_SECONDS = 6 * 3600
NOT_FOUND_RETRY_SECONDS = 24 * 3600
SPARKLINE_POINTS = 48
