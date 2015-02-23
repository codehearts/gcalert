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

# dependencies below come from separate packages, the rest (above) is in the
# standard library so those are expected to work :)
try:
    # google calendar stuff
    import gdata.calendar.service
    import gdata.calendar.client
    import gdata.service
    import gdata.calendar
    # libnotify handler
    import pynotify
    # magical date parser and timezone handler
    import dateutil.tz
    import dateutil.parser
    # For Google Calendar API v3
    import httplib2
    from apiclient.discovery import build
    from oauth2client.file import Storage
    from oauth2client.client import OAuth2WebServerFlow
    from oauth2client.tools import run
except ImportError as e:
    print "Dependency was not found! %s" % e
    print "(Try: sudo apt-get install python-notify python-gdata python-dateutil notification-daemon)"
    sys.exit(1)

# -------------------------------------------------------------------------------------------

__program__ = 'gcalert'
__version__ = '2.0'
__API_CLIENT_ID__ = '447177524849-hh9ogtma7pgbkm39v1br6qa3h3cal9u9.apps.googleusercontent.com'
__API_CLIENT_SECRET__ = 'UECdkOkaoAnyYe5-4DBm31mu'

calendar_service = None


#-----------------------------------------------------------------------------#
# Default settings                                                            #
#-----------------------------------------------------------------------------#

secrets_filename    = '.gcalert_oauth'
secrets_file        = os.path.join(os.environ['HOME'], secrets_filename)
alarm_sleeptime     = 30 # Seconds between waking up to check the alarm list
query_sleeptime     = 180 # Seconds between querying for new events
lookahead_days      = 3 # Look this many days in the future
debug_flag          = False # Display debug messages
quiet_flag          = False # Suppresses all non-debug messages
reconnect_sleeptime = 300 # Seconds between reconnects in case of errors
threads_offset      = 5 # Offset between the two threads' runs, in seconds
strftime_string     = '%Y-%m-%d  %H:%M' # String to format times with
icon                = 'gtk-dialog-info' # Icon to use in notifications



#-----------------------------------------------------------------------------#
# Calendar Alerts Class                                                       #
#-----------------------------------------------------------------------------#

events = [] # all events seen so far that are yet to start
events_lock = thread.allocate_lock() # hold to access events[]
alarmed_events = [] # events (occurences etc) already alarmed
connected = False # Google connection is disconnected

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
        return self.start.astimezone(dateutil.tz.tzlocal()).strftime(strftime_string)

    @property
    def endtime_str(self):
        """Returns a string representing the end time (in the local timezone) of the event."""
        return self.end.astimezone(dateutil.tz.tzlocal()).strftime(strftime_string)

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
        message(" ***** ALARM ALARM ALARM: {0} ****  ".format(self))

        if self.where:
            a = pynotify.Notification(self.title, '<b>Starting:</b> {start}\n<b>Where:</b> {location}'.format(start=self.starttime_str, location=self.where), icon)
        else:
            a = pynotify.Notification(self.title, '<b>Starting:</b> {start}'.format(start=self.starttime_str), icon)

        # Display the alarm notification the user closes it manually
        a.set_timeout(pynotify.EXPIRES_NEVER)

        if not a.show():
            message('Failed to send alarm notification!')

    def __str__(self):
        """Returns a string representation of this object's contents."""
        return 'Title: {title}, Location: {location}, Start: {start}, Alarm_minutes: {minutes}'.format(
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
# Console output functions                                                    #
#-----------------------------------------------------------------------------#

def message(s):
    """Prints s and flushes the buffer; useful when redirected to a file."""
    if not quiet_flag:
        print '{timestamp} {executable}: {message}'.format(
            timestamp=time.asctime(), executable=sys.argv[0], message=s)
        sys.stdout.flush()

def debug(s):
    """Prints s if the debug_flag is set (running with -d or --debug)."""
    if debug_flag:
        message('DEBUG: {function}: {message}'.format(function=sys._getframe(1).f_code.co_name, message=s))



#-----------------------------------------------------------------------------#
# Signal Handlers                                                             #
# Signal handlers are easier than wrapping everything in a giant try/except.  #
# Additionally, we have 2 threads that we need to shut down                   #
#-----------------------------------------------------------------------------#

def stopthismadness(signal, frame):
    """Halts execution and exits. Intended for SIGINT (^C)."""
    message('Shutting down on SIGINT.')
    sys.exit(0)



#-----------------------------------------------------------------------------#
# Google Calendar Query Functions                                             #
#-----------------------------------------------------------------------------#

def date_range_query(start_date=None, end_date=None):
    """
    Get a list of events happening between the given dates in all calendars the user has
    returns: (success, list of events)

    Each reminder occurence creates a new event (GCalendarAlarm object).
    """
    google_events = [] # Events in all Google Calendars
    event_list    = [] # Our parsed events list

    try:
        feed = calendar_service.calendarList().list().execute()

        # Get the id for each calendar
        cal_id_list = map(lambda x: x['id'], calendar_service.calendarList().list().execute()['items'])

        for cal_id in cal_id_list:
            debug('Processing calendar: {0}'.format(cal_id))

            query = calendar_service.events().list(calendarId=cal_id, timeMin=start_date, timeMax=end_date, singleEvents=True).execute()
            google_events += query['items']

            debug('Events so far: {0}'.format(len(google_events)))
    except Exception as error: # FIXME clearer
        debug('Connection lost: {0}.'.format(error))

        try:
            message('Connection lost ({0} {1}), will reconnect.'.format(error.args[0]['status'], error.args[0]['reason']))
        except Exception:
            message('Connection lost with unknown error, will reconnect: {0}'.format(error))
            message('Please report this as a bug.')

        return (False, [])

    for an_event in google_events:
        where_string=''
        try:
            # join all 'where' entries together; you probably only have one anyway
            where_string = an_event['location']
        except KeyError:
            # not all events have 'where' fields, and that's okay
            pass

        # make a GCalendarAlarm out of each (event x reminder x occurence)
        for a_rem in an_event['reminders']['overrides']:
            debug("google event TEXT: %s METHOD: %s" % (an_event['summary'], a_rem) )
            if a_rem['method'] == 'popup': # 'popup' in the web interface
                # event (one for each alarm instance) is done,
                # add it to the list
                this_event=GCalendarAlarm(
                            an_event['summary'],
                            where_string,
                            an_event['start']['dateTime'],
                            an_event['end']['dateTime'],
                            a_rem['minutes'])
                debug("new GCalendarAlarm occurence: %s" % this_event)
                event_list.append(this_event)
    return (True, event_list)



#-----------------------------------------------------------------------------#
# Authentication Functions                                                    #
#-----------------------------------------------------------------------------#

def do_login():
    """
    Authenticates to Google Calendar.
    Occassionally this fails or the connection dies, so this may need to be called again.

    Return:
        True if authentication succeeded, or False otherwise.
    """
    global calendar_service

    try:
        storage = Storage(secrets_file)
        credentials = storage.get()

        if credentials is None or credentials.invalid:
            credentials = run(
                OAuth2WebServerFlow(
                    client_id     = __API_CLIENT_ID__,
                    client_secret = __API_CLIENT_SECRET__,
                    scope         = 'https://www.googleapis.com/auth/calendar',
                    user_agent    = __program__+'/'+__version__
                ),
                storage
            )

        authHttp = credentials.authorize(httplib2.Http())
        calendar_service = build(serviceName='calendar', version='v3', http=authHttp)
    except Exception as error:
        debug('Failed to authenticate to Google: {0}'.format(error))
        message('Failed to authenticate to Google.')
        return False # Login failed

    message('Logged in to Google Calendar')
    return True # We're logged in

# -------------------------------------------------------------------------------------------
def process_events_thread():
    """Process events and raise alarms via pynotify"""
    # Initialize notification system
    if not pynotify.init('{0}'.format(__program__+'/'+__version__)):
        print 'Could not initialize pynotify/libnotify!'
        sys.exit(1)

    time.sleep(threads_offset) # Give a chance for the other thread to get some events

    while True:
        nowunixtime = time.time()
        debug("Running...")

        events_lock.acquire()

        for event in events:
            if event.starttime_unix < nowunixtime:
                debug('Removing event `{0}`'.format(event))
                events.remove(e)

                # Also free up some memory
                if event in alarmed_events:
                    alarmed_events.remove(event)
            # If it starts in the future, check for alarm times if it wasn't alarmed yet
            elif event not in alarmed_events:
                # Check the alarm time. If it's now-ish, raise the alarm,
                # otherwise let the event sleep some more

                # Alarm now if the alarm has 'started'
                if nowunixtime >= event.alarm_time_unix:
                    event.trigger_alarm()
                    alarmed_events.append(event)
                else:
                    debug('Not yet ready to alert for event `{0}`'.format(event))
            else:
                debug('Already alerted for event `{0}`'.format(event))

        events_lock.release()

        debug("Finished")

        # We can't just sleep until the next event as the other thread MIGHT add something new
        time.sleep(alarm_sleeptime)

def get_calendar_service():
    global calendar_service
    return calendar_service

def update_events_thread():
    """Periodically sync the 'events' list to what's in Google Calendar"""
    connectionstatus = do_login()

    while True:
        if(not connectionstatus):
            time.sleep(reconnect_sleeptime)
            connectionstatus = do_login()
        else:
            debug("running")
            # today
            range_start = datetime.datetime.now(dateutil.tz.tzlocal())
            # tommorrow, or later
            range_end = range_start + datetime.timedelta(days=lookahead_days)
            (connectionstatus,newevents) = date_range_query(range_start.isoformat(), range_end.isoformat())
            if connectionstatus: # if we're still logged in, the query was successful and newevents is valid
                events_lock.acquire()
                now = time.time()
                # remove stale events, if the new event list is valid
                for n in events:
                    if not (n in newevents):
                        debug('Event deleted or modified: %s' % n)
                        events.remove(n)
                # add new events to the list
                for n in newevents:
                    debug('Is new event N really new? THIS: %s' % n)
                    if not (n in events):
                        debug('Not seen before: %s' % n)
                        # does it start in the future?
                        if now < n.starttime_unix:
                            debug("-> future, adding")
                            events.append(n)
                        else:
                            debug("-> past already")
                events_lock.release()
            debug("finished")
            time.sleep(query_sleeptime)


#-----------------------------------------------------------------------------#
# Usage instructions                                                          #
#-----------------------------------------------------------------------------#

def usage():
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
            default_secret     = '~/' + secrets_filename,
            default_query      = query_sleeptime,
            default_alarm      = alarm_sleeptime,
            default_look       = lookahead_days,
            default_retry      = reconnect_sleeptime,
            default_timeformat = strftime_string,
            default_icon       = icon
        )
    )


if __name__ == '__main__':
    # -------------------------------------------------------------------------------------------
    # the main thread will start up, then launch the background 'alarmer' thread,
    # and proceed check the calendar every so often
    #

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hdus:q:a:l:r:t:i:", ["help", "debug", "quiet", "secret=", "query=", "alarm=", "look=", "retry=", "timeformat=", "icon="])
    except getopt.GetoptError as err:
        # print help information and exit:
        print str(err) # will print something like "option -a not recognized"
        sys.exit(2)

    try:
        for o, a in opts:
            if o == "-d":
                debug_flag = True
            elif o in ("-h", "--help"):
                usage()
                sys.exit()
            elif o in ("-u", "--quiet"):
                quiet_flag = True
            elif o in ("-s", "--secret"):
                secrets_file = a
                debug("secrets_file set to %s" % secrets_file)
            elif o in ("-q", "--query"):
                query_sleeptime = max(intval(a), 5) # FIXME handle non-integers graciously
                debug("query_sleeptime set to %d" % query_sleeptime)
            elif o in ("-a", "--alarm"):
                alarm_sleeptime = int(a)
                debug("alarm_sleeptime set to %d" % alarm_sleeptime)
            elif o in ("-l", "--look"):
                lookahead_days = int(a)
                debug("lookahead_days set to %d" % lookahead_days)
            elif o in ("-r", "--retry"):
                reconnect_sleeptime = int(a)
                debug("reconnect_sleeptime set to %d" % reconnect_sleeptime)
            elif o in ("-t", "--timeformat"):
                strftime_string = a
                debug("strftime_string set to %s" % strftime_string)
            elif o in ("-i", "--icon"):
                icon = a
                debug("icon set to %s" % icon)
            else:
                assert False, "unhandled option"
    except ValueError:
        print "Option %s requires an integer parameter; use '-h' for help." % o
        sys.exit(1)

    # set up ^C handler
    signal.signal( signal.SIGINT, stopthismadness )

    # start up the event processing thread
    debug("Starting p_e_t")
    thread.start_new_thread(process_events_thread,())

    # starting up
    message("gcalert %s running..." % __version__)
    debug("SETTINGS: secrets_file: %s alarm_sleeptime: %d query_sleeptime: %d lookahead_days: %d reconnect_sleeptime: %d strftime_string: %s" % ( secrets_file, alarm_sleeptime, query_sleeptime, lookahead_days, reconnect_sleeptime, strftime_string ))

    update_events_thread()
