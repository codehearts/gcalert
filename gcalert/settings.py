from os import path, makedirs
from getopt import GetoptError, getopt
from utils.output import message, debug_message

config_directory	 = '~/.config/gcalert/'
abs_config_directory = path.expanduser(config_directory)

# Create the config directory if it doesn't already exist
if not path.exists(abs_config_directory):
	makedirs(abs_config_directory)

rc_filename			 = 'gcalertrc'
rc_file				 = path.join(abs_config_directory, rc_filename)
secrets_filename	 = '.gcalert_oauth'
secrets_file		 = path.join(abs_config_directory, secrets_filename)
parsed_rc            = False

alarm_sleeptime		 = 300				 # Seconds between waking up to check the alarm list
query_sleeptime		 = 180				 # Seconds between querying for new events
lookahead_days		 = 3				 # Look this many days in the future
debug_flag			 = False			 # Display debug messages
quiet_flag			 = False			 # Suppresses all non-debug messages
reconnect_sleeptime  = 300				 # Seconds between reconnects in case of errors
threads_offset		 = 2				 # Offset between the two threads' runs, in seconds
strftime_string		 = '%H:%M %Y-%m-%d'  # String to format times with
icon				 = 'gtk-dialog-info' # Icon to use in notifications

def usage():
    return '''{program} {version} - Displays reminder notifications for Google Calendar events.

Usage: {executable} [options]

--rc       Specifies the location of the gcalertrc file.
           This file may contain one command line parameter
           per line, and will be used to configure {program}
           before any command line arguments are parsed.
           (Default: {default_rc})

-s
--secret   Specifies the location of the oauth credentials cache.
           (Default: {default_secret})

-d
--debug    Print debug messages.

-q
--quiet    Disable all non-debug messages.

-c
--check    Number of seconds between queries for new calendar events.
           (Default: {default_query})

-a seconds
--alarm seconds
           Number of seconds between checking for reminders to display.
           (Default: {default_alarm})

-l days
--look days
           Number of days to look ahead when checking for new events.
           (Default: {default_look})

-r seconds
--retry seconds
           Number of seconds to wait between reconnection attempts.
           (Default: {default_retry})

-t format_string
--timeformat format_string
           Formatting string to use for displaying event times.
           Must be formatted according to strftime(3).
           (Default: {default_timeformat})

-i icon_name
--icon icon_name
           Sets the icon displayed in reminder notifications.
           (Default: {default_icon})'''.format(
        program            = __program__,
        version            = __version__,
        executable         = argv[0],
        default_rc         = config_directory + rc_filename,
        default_secret     = config_directory + secrets_filename,
        default_query      = query_sleeptime,
        default_alarm      = alarm_sleeptime,
        default_look       = lookahead_days,
        default_retry      = reconnect_sleeptime,
        default_timeformat = strftime_string,
        default_icon       = icon
    )

def apply_cmd_args(args):
	"""Applies the given commandline arguments to the settings variables."""
	try:
		opts, args = getopt(args, 'hdqs:c:a:l:r:t:i:', [
			'help', 'debug', 'quiet', 'secret=', 'rc=', 'check=',
			'alarm=', 'look=', 'retry=', 'timeformat=', 'icon='])
	except GetoptError as err:
		print(err) # Will print something like "option -a not recognized"
		exit(2)

	d_opts = dict(opts)

	if not parsed_rc:
		# If an rc file was specified, parse it now
		if '--rc' in d_opts:
			parse_rc(d_opts['--rc'])
			debug_message('gcalertrc file set to {0}', d_opts['--rc'])
		else:
			# Otherwise, use the default rc file
			parse_rc(rc_file)

	for o, a in opts:
		if o in ('-d', '--debug'):
			debug_flag = True
		elif o in ('-h', '--help'):
			message(usage(), force=True)
			exit()
		elif o in ('-q', '--quiet'):
			quiet_flag = True
		elif o in ('-s', '--secret'):
			secrets_file = a
			debug_message('Secrets file set to {0}', secrets_file)
		elif o in ('-c', '--check'):
			query_sleeptime = max(int(a), 5)
			debug_message('Query sleep time set to {0}', query_sleeptime)
		elif o in ('-a', '--alarm'):
			alarm_sleeptime = int(a)
			debug_message('Alarm sleep time set to {0}', alarm_sleeptime)
		elif o in ('-l', "--look"):
			lookahead_days = int(a)
			debug_message('Lookahead days set to {0}', lookahead_days)
		elif o in ('-r', '--retry'):
			reconnect_sleeptime = int(a)
			debug_message('Reconnect sleep time set to {0}', reconnect_sleeptime)
		elif o in ('-t', '--timeformat'):
			strftime_string = a
			debug_message("strftime format string set to {0}", strftime_string)
		elif o in ('-i', '--icon'):
			icon = a
			debug_message('Icon set to {0}', icon)
		else:
			assert False, 'Unsupported argument'

def parse_rc(rc_file):
	"""Initializes settings from an rc file."""
	global parsed_rc

	if path.exists(rc_file):
		with open(rc_file, 'r') as input:
			args = input.read().splitlines()

		parsed_rc = True
		apply_cmd_args(args)
