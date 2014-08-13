anchorwatch
===========

Simple python anchor watch program which runs in terminal window.

Program requires that GPSD be running on the local machine.  When started, anchorwatch starts a thread to poll GPSD.  This thread loops until a quality position is registered and then captures that position as the center of radius for the alarm.  The program then prompts the user for an alarm radius in feet.  Once this is entered, the program starts providing updates on the terminal window with current distance from the center, the max distance, as well as the number of alarms and at the end of the line, and iterator that can be used to determine that updates are happening.  

To change the alarm radius, the user should use: r <enter> to break the looping and then prompt the user for a different radius.  Similarly, q <enter> exits the program.  Alarm sounds use hildon system sounds for maemo OS devices and Gnome sounds for other devices (which are assumed to be Linux-based).  Thus Gnome sounds must be installed on the computer and if no sounds emitted, check for the correct path.


