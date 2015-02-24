#!/usr/bin/python2
# vim: ai expandtab
#
# This script will periodically check your Google Calendar and display an alarm
# when that's set for the event. It reads ALL your calendars automatically.
#
# Only 'popup' alarms will result in what's essentially a popup. This is a feature :)
#
# Requires: python-notify python-gdata python-dateutil notification-daemon
#
# Home: http://github.com/raas/gcalert
#
# ----------------------------------------------------------------------------
#
# Copyright 2009 Andras Horvath (andras.horvath nospamat gmailcom) This
# program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ----------------------------------------------------------------------------
#
# TODO:
# - warn for unsecure permissions of the password/secret file
# - use some sort of proper logging with log levels etc
# - options for selecting which calendars to alert (currently: all of them)
# - snooze buttons; this requires a gtk.main() thread and that's not trivial
# - testing (as in, unit testing), after having a main()
# - multi-language support
# - GUI and status bar icon

import getopt
import sys
import os
import time
import urllib
import thread
import signal
import datetime
import argparse

# Dependencies below come from separate packages, the rest (above) are in the
# standard library so those are expected to work :)
try:
    # Google calendar stuff
    import gdata.calendar.service
    import gdata.calendar.client
    import gdata.service
    import gdata.calendar
    # libnotify handler
    import pynotify
    # Date parser and timezone handler
    import dateutil.tz
    import dateutil.parser
    # For Google Calendar API v3
    import httplib2
    from apiclient.discovery import build
    from oauth2client import tools
    from oauth2client.file import Storage
    from oauth2client.client import OAuth2WebServerFlow
    from oauth2client.tools import run_flow
except ImportError as e:
    print 'Dependency was not found! {0}\n'.format(e)
    print 'For Debian/Ubuntu, try:'
    print '\tsudo apt-get install python-notify python-gdata python-dateutil notification-daemon'
    sys.exit(1)

#-----------------------------------------------------------------------------#
# Global Properties                                                           #
#-----------------------------------------------------------------------------#

__program__ = 'gcalert'
__version__ = '2.0'
__API_CLIENT_ID__     = '447177524849-hh9ogtma7pgbkm39v1br6qa3h3cal9u9.apps.googleusercontent.com'
__API_CLIENT_SECRET__ = 'UECdkOkaoAnyYe5-4DBm31mu'

#-----------------------------------------------------------------------------#
# Default settings                                                            #
#-----------------------------------------------------------------------------#

class Settings(object):
    """Stores all settings for this gcalert instance."""
    # Text colors
    purple_text    = '\033[95m'
    cyan_text      = '\033[96m'
    darkcyan_text  = '\033[36m'
    blue_text      = '\033[94m'
    green_text     = '\033[92m'
    yellow_text    = '\033[93m'
    red_text       = '\033[91m'
    bold_text      = '\033[1m'
    underline_text = '\033[4m'
    normal_text    = '\033[0m'

    def __init__(self):
        super(Settings, self).__init__()
        self.config_directory    = os.path.expanduser('~/.config/gcalert/')
        self.secrets_filename    = '.gcalert_oauth'
        self.secrets_file        = os.path.join(self.config_directory, self.secrets_filename)
        self.alarm_sleeptime     = 30                # Seconds between waking up to check the alarm list
        self.query_sleeptime     = 180               # Seconds between querying for new events
        self.lookahead_days      = 3                 # Look this many days in the future
        self.debug_flag          = False             # Display debug messages
        self.quiet_flag          = False             # Suppresses all non-debug messages
        self.reconnect_sleeptime = 300               # Seconds between reconnects in case of errors
        self.threads_offset      = 5                 # Offset between the two threads' runs, in seconds
        self.strftime_string     = '%Y-%m-%d  %H:%M' # String to format times with
        self.icon                = 'gtk-dialog-info' # Icon to use in notifications

        # Create the config directory if it doesn't already exist
        if not os.path.exists(self.config_directory):
            os.makedirs(self.config_directory)

    def __str__(self):
        """Returns a string representation of the settings."""
        return '''
            Secrets file:         {secrets_file}
            Alarm sleep time:     {alarm_time}
            Query sleep time:     {query_time}
            Lookahead days:       {lookahead}
            Debug:                {debug}
            Quiet:                {quiet}
            Reconnect sleep time: {reconnect_time}
            Thread offset:        {thread_offset}
            strftime format:      {strftime_str}
            Icon:                 {icon}
        '''.format(
            secrets_file   = self.secrets_file,
            alarm_time     = self.alarm_sleeptime,
            query_time     = self.query_sleeptime,
            lookahead      = self.lookahead_days,
            debug          = self.debug_flag,
            quiet          = self.quiet_flag,
            reconnect_time = self.reconnect_sleeptime,
            thread_offset  = self.threads_offset,
            strftime_str   = self.strftime_string,
            icon           = self.icon
        )

# Create a global settings instance
settings = Settings()

#-----------------------------------------------------------------------------#
# Console output functions                                                    #
#-----------------------------------------------------------------------------#

def message(message):
    """Prints the given message and flushes the buffer; useful when redirected to a file."""
    if not settings.quiet_flag:
        print message
        sys.stdout.flush()

def debug(message):
    """Prints the given message if the debug_flag is set (running with -d or --debug)."""
    if settings.debug_flag:
        print '{timestamp} (DEBUG): in {function}: {message}'.format(
            timestamp=time.asctime(), executable=sys.argv[0],
            function=sys._getframe(1).f_code.co_name, message=message)
        sys.stdout.flush()

#-----------------------------------------------------------------------------#
# Calendar Alerts Class                                                       #
#-----------------------------------------------------------------------------#

class GCalendarAlarm(object):
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
        self.start   = dateutil.parser.parse(start_string)
        self.end     = dateutil.parser.parse(end_string)
        self.minutes = minutes

        # Google sometimes does not supply timezones
        # (for events that last more than a day and have no time set, apparently)
        # python can't compare two dates if only one has TZ info
        # this might screw us at, say, if DST changes between when we get the event and its alarm
        try:
            if not self.start.tzname():
                self.start = self.start.replace(tzinfo=dateutil.tz.tzlocal())
        except AttributeError:
            self.start = self.start.replace(tzinfo=dateutil.tz.tzlocal())

        try:
            if not self.end.tzname():
                self.end = self.end.replace(tzinfo=dateutil.tz.tzlocal())
        except AttributeError:
            self.end = self.end.replace(tzinfo=dateutil.tz.tzlocal())

    @property
    def starttime_str(self):
        """Returns a string representing the start time (in the local timezone) of the event."""
        return self.start.astimezone(dateutil.tz.tzlocal()).strftime(settings.strftime_string)

    @property
    def endtime_str(self):
        """Returns a string representing the end time (in the local timezone) of the event."""
        return self.end.astimezone(dateutil.tz.tzlocal()).strftime(settings.strftime_string)

    @property
    def starttime_unix(self):
        """Returns the start time of the event in unix time."""
        return int(self.start.astimezone(dateutil.tz.tzlocal()).strftime('%s'))

    @property
    def alarm_time_unix(self):
        """Returns the end time of the event in unix time."""
        return self.starttime_unix - 60 * int(self.minutes)

    def trigger_alarm(self):
        """Show the alarm box for one event/recurrence"""
        message(settings.bold_text+'\n########## ALARM ##########'+settings.normal_text)
        message('\n{0}'.format(self))
        message(settings.bold_text+'########## ALARM ##########\n'+settings.normal_text)

        if self.where:
            a = pynotify.Notification(self.title, '<b>Starting:</b> {start}\n<b>Where:</b> {location}'.format(start=self.starttime_str, location=self.where), settings.icon)
        else:
            a = pynotify.Notification(self.title, '<b>Starting:</b> {start}'.format(start=self.starttime_str), settings.icon)

        # Display the alarm notification the user closes it manually
        a.set_timeout(pynotify.EXPIRES_NEVER)

        if not a.show():
            message('Failed to send alarm notification!')

    def __str__(self):
        """Returns a string representation of this object's contents."""
        return 'Title: {title}\nLocation: {location}\nStart: {start}\nAlarm_minutes: {minutes}\n'.format(
            title    = self.title,
            location = self.where,
            start    = self.starttime_str,
            minutes  = self.minutes
        )

    def __repr__(self):
        """Returns a string representation of this object."""
        return 'GCalendarAlarm({title}, {location}, {start}, {end}, {minutes})'.format(
            title    = self.title,
            location = self.where,
            start    = self.starttime_str,
            end      = self.endtime_str,
            minutes  = self.minutes
        )

    def __eq__(self, other):
        """Returns True if this instance has the same data as the comparison instance."""
        return self.__repr__() == other.__repr__()



#-----------------------------------------------------------------------------#
# GCalert Class                                                               #
# The main thread will start up and then launch the background alerts thread, #
# and proceed check the calendar every so often                               #
#-----------------------------------------------------------------------------#

class GCalert(object):
    """Connects to Google Calendar and notifies about events at their reminder time."""

    def __init__(self):
        super(GCalert, self).__init__()

        # Set GCalert properties
        self.events = [] # all events seen so far that are yet to start
        self.events_lock = thread.allocate_lock() # hold to access events[]
        self.alerted_events = [] # Events (occurrences, etc) already notified about
        self.calendar_service = None

        # Handle arguments to the program
        self.handle_program_arguments()

        # Set up ^C handler
        signal.signal(signal.SIGINT, self.stopthismadness)

        # Start up the event processing thread
        debug('Starting event processing thread')
        thread.start_new_thread(self.process_events_thread, ())

        # Start up
        message('{0} {1} running...'.format(__program__, __version__))
        debug('Settings: {0}'.format(settings))

        self.update_events_thread()

    #-----------------------------------------------------------------------------#
    # Google Calendar Query Functions                                             #
    #-----------------------------------------------------------------------------#

    def date_range_query(self, start_date=None, end_date=None):
        """
        Get a list of events happening between the given dates in all calendars the user has
        Each reminder occurrence creates a new event (GCalendarAlarm object).

        Returns:
            A tuple in the format (<success boolean>, <list of events>).
        """
        google_events = [] # Events in all Google Calendars
        event_list    = [] # Our parsed events list

        try:
            feed = self.calendar_service.calendarList().list().execute()

            # Get the id for each calendar
            cal_ids = map(lambda x: x['id'], self.calendar_service.calendarList().list().execute()['items'])

            for cal_id in cal_ids:
                debug('Processing calendar: {0}'.format(cal_id))

                query = self.calendar_service.events().list(calendarId=cal_id, timeMin=start_date, timeMax=end_date, singleEvents=True).execute()
                google_events += query['items']

                debug('Events so far: {0}'.format(len(google_events)))
        except Exception as error:
            debug('Connection lost: {0}.'.format(error))

            try:
                message('Connection lost ({0} {1}), will reconnect.'.format(error.args[0]['status'], error.args[0]['reason']))
            except Exception:
                message('Connection lost with unknown error, will reconnect: {0}'.format(error))
                message('Please report this as a bug.')

            return (False, [])

        for event in google_events:
            where = ''
            try:
                where = event['location']
            except KeyError:
                pass # Not all events have 'where' fields, and that's okay

            # Create a GCalendarAlarm out of each (event x reminder x occurrence)
            for reminder in event['reminders']['overrides']:
                debug('Google event TEXT: {0} METHOD: {1}'.format(event['summary'], reminder['method']))

                if reminder['method'] == 'popup': # 'popup' in the web interface
                    # Event (one for each alarm instance) is done, add it to the list
                    this_event = GCalendarAlarm(
                        event['summary'],
                        where,
                        event['start']['dateTime'],
                        event['end']['dateTime'],
                        reminder['minutes'])

                    debug('New GCalendarAlarm instance: {0}'.format(this_event))

                    event_list.append(this_event)

        return (True, event_list)

    #-----------------------------------------------------------------------------#
    # Authentication Functions                                                    #
    #-----------------------------------------------------------------------------#

    def do_login(self):
        """
        Authenticates to Google Calendar.
        Occassionally this fails or the connection dies, so this may need to be called again.

        Return:
            True if authentication succeeded, or False otherwise.
        """
        try:
            storage = Storage(settings.secrets_file)
            credentials = storage.get()

            if credentials is None or credentials.invalid:
                flow = OAuth2WebServerFlow(
                    client_id     = __API_CLIENT_ID__,
                    client_secret = __API_CLIENT_SECRET__,
                    user_agent    = __program__+'/'+__version__,
                    redirect_uri  = 'urn:ietf:wg:oauth:2.0:oob:auto',
                    scope         = 'https://www.googleapis.com/auth/calendar')

                parser = argparse.ArgumentParser(
                    formatter_class = argparse.RawDescriptionHelpFormatter,
                    parents         = [tools.argparser])

                # Parse the command-line flags
                flags = parser.parse_args(sys.argv[1:])

                credentials = run_flow(flow, storage, flags)

            auth_http = credentials.authorize(httplib2.Http())
            self.calendar_service = build(serviceName='calendar', version='v3', http=auth_http)
        except Exception as error:
            debug('Failed to authenticate to Google: {0}'.format(error))
            message('Failed to authenticate to Google.')
            return False # Login failed

        message('Logged in to Google Calendar')
        return True # We're logged in

    #-----------------------------------------------------------------------------#
    # Event Thread Handlers                                                       #
    #-----------------------------------------------------------------------------#

    def process_events_thread(self):
        """Process events and raise alarms via pynotify."""
        # Initialize notification system
        if not pynotify.init('{0}'.format(__program__+'/'+__version__)):
            print 'Could not initialize pynotify/libnotify!'
            sys.exit(1)

        time.sleep(settings.threads_offset) # Give a chance for the other thread to get some events

        while True:
            nowunixtime = time.time()
            debug('Processing events thread...')

            self.events_lock.acquire()

            for event in self.events:
                if event.starttime_unix < nowunixtime:
                    debug('Removing event `{0}`'.format(event))
                    self.events.remove(event)

                    # Also free up some memory
                    if event in self.alerted_events:
                        self.alerted_events.remove(event)
                # If it starts in the future, check for alarm times if it wasn't alarmed yet
                elif event not in self.alerted_events:
                    # Check the alarm time. If it's now-ish, raise the alarm,
                    # otherwise let the event sleep some more

                    # Alarm now if the alarm has 'started'
                    if nowunixtime >= event.alarm_time_unix:
                        event.trigger_alarm()
                        self.alerted_events.append(event)
                    else:
                        debug('Not yet ready to alert for event `{0}`'.format(event))
                else:
                    debug('Already alerted for event `{0}`'.format(event))

            self.events_lock.release()

            debug('Finished')

            # We can't just sleep until the next event as the other thread MIGHT add something new
            time.sleep(settings.alarm_sleeptime)

    def update_events_thread(self):
        """Periodically syncs the 'events' list to what's in Google Calendar."""
        connection_status = self.do_login()

        while True:
            if not connection_status:
                time.sleep(settings.reconnect_sleeptime)
                connection_status = self.do_login()
            else:
                debug('Updating events thread...')

                # Today
                range_start = datetime.datetime.now(dateutil.tz.tzlocal())
                # Tomorrow, or later
                range_end = range_start + datetime.timedelta(days=settings.lookahead_days)

                (connection_status, new_events) = self.date_range_query(range_start.isoformat(), range_end.isoformat())

                if connection_status: # If we're still logged in, the query was successful and `new_events` is valid
                    self.events_lock.acquire()
                    now = time.time()

                    # Remove stale events, if the new event list is valid
                    for event in self.events:
                        if not event in new_events:
                            debug('Event deleted or modified: `{0}`'.format(event))
                            self.events.remove(event)

                    # Add new events to the list
                    for event in new_events:
                        debug('Is new event really new? `{0}`'.format(event))

                        if not event in self.events:
                            debug('Event not seen before: {0}'.format(event))

                            # Does it start in the future?
                            if now < event.starttime_unix:
                                debug('-> future, adding')
                                self.events.append(event)
                            else:
                                debug('-> past already')

                    self.events_lock.release()

                debug('Finished')
                time.sleep(settings.query_sleeptime)

    #-----------------------------------------------------------------------------#
    # Command Line Argument Handling                                              #
    #-----------------------------------------------------------------------------#

    def handle_program_arguments(self):
        try:
            opts, args = getopt.getopt(sys.argv[1:], 'hdus:q:a:l:r:t:i:', ['help', 'debug', 'quiet', 'secret=', 'query=', 'alarm=', 'look=', 'retry=', 'timeformat=', 'icon='])
        except getopt.GetoptError as err:
            # Print help information and exit:
            print str(err) # Will print something like "option -a not recognized"
            sys.exit(2)

        try:
            for o, a in opts:
                if o == '-d':
                    settings.debug_flag = True
                elif o in ('-h', '--help'):
                    usage()
                    sys.exit()
                elif o in ('-u', '--quiet'):
                    settings.quiet_flag = True
                elif o in ('-s', '--secret'):
                    settings.secrets_file = a
                    debug('Secrets file set to {0}'.format(settings.secrets_file))
                elif o in ('-q', '--query'):
                    settings.query_sleeptime = max(intval(a), 5)
                    debug('Query sleep time set to {0}'.format(settings.query_sleeptime))
                elif o in ('-a', '--alarm'):
                    settings.alarm_sleeptime = int(a)
                    debug('Alarm sleep time set to {0}'.format(settings.alarm_sleeptime))
                elif o in ('-l', "--look"):
                    settings.lookahead_days = int(a)
                    debug('Lookahead days set to {0}'.format(settings.lookahead_days))
                elif o in ('-r', '--retry'):
                    settings.reconnect_sleeptime = int(a)
                    debug('Reconnect sleep time set to {0}'.format(settings.reconnect_sleeptime))
                elif o in ('-t', '--timeformat'):
                    settings.strftime_string = a
                    debug("strftime format string set to {0}".format(settings.strftime_string))
                elif o in ('-i', '--icon'):
                    settings.icon = a
                    debug('Icon set to {0}'.format(settings.icon))
                else:
                    assert False, 'Unsupported argument'
        except ValueError:
            message('Option {0} requires an integer parameter; use \'-h\' for help.'.format(o))
            sys.exit(1)

    #-----------------------------------------------------------------------------#
    # Signal Handlers                                                             #
    # Signal handlers are easier than wrapping everything in a giant try/except.  #
    # Additionally, we have 2 threads that we need to shut down                   #
    #-----------------------------------------------------------------------------#

    def stopthismadness(self, signal, frame):
        """Halts execution and exits. Intended for SIGINT (^C)."""
        message('Shutting down on SIGINT.')
        sys.exit(0)

    #-----------------------------------------------------------------------------#
    # Usage instructions                                                          #
    #-----------------------------------------------------------------------------#

    def usage(self):
        print('''gcalert {version} - Polls Google Calendar and displays reminder notifications for events.

Usage: {executable} [options]

-s
--secret   Specifies the location of the oauth credentials cache.
           (Default: {default_secret})

-d
--debug    Produces debug messages.

-u
--quiet    Disables all non-debug messages.

-q
--query    How often to check for new calendar events.
           (Default: {default_query})

-a seconds
--alarm seconds
           Amount of time to wait before checking for alarms to set off.
           (Default: {default_alarm})

-l days
--look days
           Number of days to look ahead by and cache.

-r seconds
--retry seconds
           Number of seconds to wait between reconnection attempts.
           (Default: {default_retry})

-t format_string
--timeformat format_string
           Formatting string to use for displaying event times.
           Must be formatted according to strftime(3). (Default: {default_timeformat})

-i icon_name
--icon icon_name
           Sets the icon displayed in alarm notifications.
           (Default: {default_icon})
            '''.format(
                version            = __version__,
                executable         = sys.argv[0],
                default_secret     = settings.secrets_filename,
                default_query      = settings.query_sleeptime,
                default_alarm      = settings.alarm_sleeptime,
                default_look       = settings.lookahead_days,
                default_retry      = settings.reconnect_sleeptime,
                default_timeformat = settings.strftime_string,
                default_icon       = settings.con
            )
        )



#-----------------------------------------------------------------------------#
# Let's get started!                                                          #
#-----------------------------------------------------------------------------#

if __name__ == '__main__':
    GCalert()
