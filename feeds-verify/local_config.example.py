# Copy to local_config.py (git-ignored) and edit.
HOME_LAT, HOME_LON = 40.7222, -73.9573   # Citi Bike distances are measured from here
PREFERRED_STATION = "Some Station Name"  # pinned first in the Citi Bike list, or None
# Next Up reads these Google calendars (ids from the Calendar API calendarList), default just "primary":
# NEXT_EVENT_GCAL_IDS = ["primary", "<id>@import.calendar.google.com"]
# When reading calendars through Home Assistant instead, limit to these entity ids (default all):
# NEXT_EVENT_CALENDARS = {"calendar.personal"}
