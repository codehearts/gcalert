from utils import time
from datetime import timedelta
import settings

# Dependencies below come from separate packages, the rest (above) are in the
# standard library so those are expected to work :)
try:
    # libnotify handler
    from notify2 import init, Notification, EXPIRES_NEVER

    # Date parser and timezone handler
    from dateutil.tz import tzlocal
    from dateutil.parser import parse as parse_time

    # For Google Calendar API v3
    from httplib2 import Http
    from oauth2client.file import Storage
    from oauth2client.tools import run_flow, argparser
    from googleapiclient.discovery import build
    from oauth2client.client import OAuth2WebServerFlow
except ImportError as e:
    print('Dependency was not found! {0}\n'.format(e))
    print('For Debian/Ubuntu, try:')
    print('\tsudo apt-get install python-notify python-dateutil python-googleapi notification-daemon')
    exit(1)

class GCalertNotification(object):
    """Represents an instance of a calendar alarm for an event."""

    def __init__(self, title, where, start_string, end_string, minutes):
        """Creates a new alarm for the given event.

        Args:
            title (str): The title of the event.
            where (str): The location of the event, or an empty string.
            start_string (str): The start time of the event as a string.
            end_string (str): The end time of the event as a string.
            minutes (int): How many minutes before the start of the event to set off the alarm.
        """
        self.title   = title
        self.where   = where
        self.start   = parse_time(start_string)
        self.minutes = minutes

        # Google sometimes does not supply timezones
        # (for events that last more than a day and have no time set, apparently)
        # python can't compare two dates if only one has TZ info
        # this might screw us at, say, if DST changes between when we get the event and its alarm
        try:
            if not self.start.tzname():
                self.start = self.start.replace(tzinfo=tzlocal())
        except AttributeError:
            self.start = self.start.replace(tzinfo=tzlocal())

        self.start_str = self.start.astimezone(tzlocal()).strftime(settings.strftime_string)
        self.reminder_time = time.get_unix_timestamp(self.start - timedelta(minutes=self.minutes)) # Store only the UNIX timestamp
        self.start = time.get_unix_timestamp(self.start) # Store only the UNIX timestamp

    def notify(self):
        """Show the alarm box for one event/recurrence"""
        message(text.bold+'\n########## ALARM ##########'+text.normal)
        message(self.get_formatted())
        message(text.bold+'########## ALARM ##########\n'+text.normal)

        if self.where:
            a = Notification(self.title, '<b>Starting:</b> {start}\n<b>Where:</b> {location}'.format(start=self.start_str, location=self.where), settings.icon)
        else:
            a = Notification(self.title, '<b>Starting:</b> {start}'.format(start=self.start_str), settings.icon)

        # Display the alarm notification the user closes it manually
        a.set_timeout(EXPIRES_NEVER)

        if not a.show():
            message('Failed to send alarm notification!')

    def get_formatted(self):
        """Returns a string representation of this object's contents."""
        representation = (
            ('Title:',        self.title),
            ('Location:',     self.where),
            ('Start time:',   self.start),
            ('Reminder set:', '{0} minutes before'.format(self.minutes)),
        )

        return '\n'.join(map(lambda x: '{0:<15} {1}'.format(x[0], x[1]), representation))

    def __str__(self):
        """Returns a string representation of this object."""
        return 'GCalertNotification({title}, {location}, {start}, {minutes})'.format(
            title    = self.title,
            location = self.where,
            start    = self.start,
            minutes  = self.minutes
        )

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __hash__(self):
        return hash(str(self))
