from sys import stdout
import settings

def message(message, *args, **kwargs):
    """Prints the given message and flushes the buffer; useful when redirected to a file."""
    if not settings.quiet_flag or 'force' in kwargs:
        print(message.format(*args, **kwargs))
        stdout.flush()

def debug_message(message, *args, **kwargs):
    """Prints the given message if the debug_flag is set (running with -d or --debug)."""
    if settings.debug_flag:
        message = message.format(*args, **kwargs)
        print('{0} in {1}: {2}'.format(
            asctime(), _getframe(1).f_code.co_name, message))
        stdout.flush()
