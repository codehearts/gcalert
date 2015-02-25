## Lightweight Google Calendar notifications
###### Copyright Andras Horvath, 2009

![](https://raw.githubusercontent.com/nejsan/gcalert/master/screenshot.png)

This program periodically checks all of your Google Calendars and displays a desktop notification via `libnotify` whenever a reminder is set for an event. Libnotify windows receive no focus and don't take keyboard input away from other applications, yet are clearly visible even on a cluttered desktop.

Also; getting 'thrown out' from Google Services is apparently normal, and gcalert will reconnect automatically.

## Requirements
### Debian Packages
`python-notify python-gdata python-dateutil notification-daemon`

## License

Copyright 2009 Andras Horvath (andras.horvath nospamat gmailcom) This
program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your
option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program.  If not, see <http://www.gnu.org/licenses/>.
