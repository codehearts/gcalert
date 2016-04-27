from time import mktime

def get_unix_timestamp(time):
    """Converts a datetime object to a UNIX timestamp int."""
    return mktime(time.timetuple())
