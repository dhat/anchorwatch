#! /usr/bin/python
#
# GPS anchor watch (originally only for use on Nokia n810)
# Modified from Python tutorial docs
# by David Hattery
# on 5/18/2011
#
# New version with multi os sound, cmd line options and threaded gps polling.
# GPS polling from code Written by Dan Mandle http://dan.mandle.me September 2012
# License: GPL 2.0
# Integration by David Hattery on 20131122
#
# Last updated on 20150825 for raspberry pi and gpsd
# Last updated on 20220722 to use on amd64 and running gpsd off of the airmar nmea
# Last updated on 20221003:
#   Fixes to check if data is still streaming from airmar and sounds alarm if not
#   Check gpsd time is changing and print warning if not
#   Use gpsd time as an invalid gps val
#   Trigger gpsp restart if too many invalid gps vals
#   Prints out DD + DMS + DDM for both lat and long
#   Added in a gpsp restart to see if it can recover from a data failure
# Last updated on 20240730:
#   Switch to use python gpsd (got rid of threaded poller due to issues)
#   Added usb buzzer and light alarm test on startup as well as with 't' option
#   Should we keep hildon handling--pine phone still uses it and who knows, may buy one of them someday
#   Update to use new haversine library for lat lon distance--also small bug in old function
#   Now saves last reference point
#   The individual x,y,z,h-speed,v-speed,etc. numbers are in the error dictionary--units are meters and seconds
#   Monitors and displays position error and subtracts averaged error from the max radius--so if accuracy drops, so does radius--switched to use first precision number and also smooth it (note root squared x/y error distance was very large)
#   Precision first number is the larger of x or y position errors and second number is altitude position error.  Units are meters.
#   Prints speed accuracy/error, but not sure how to use that yet.  Seems like if raw speed is greater than error there is a problem, but averaged error and speeds don't work the same way--no doubt because of vector.
#   Added number of satellites being used and set an error threshold for min satellites
# Last updated on 20240815
#   Add a help menu 'h'
#   Added compact output display and can toggle between them using menu 'x': compact display shows filtered outputs
#   Added option to display center location and range/bearing menu 'a'
#   Fixes: got output working right, and added some time stamps
#   Created unified help string so only need to update in one place
#   Refactored function names
#   Added alarm pause mode to stop the noise
#   Add ability to enter custom lat lon
#   Added altitude to menu a option
#   Track and show max avg position errors
# Last updated on 20260718:
#   Extracted the distance/bearing math (geo.py) and the drag-alarm decision
#   logic (alarm_state.py) out of this loop into their own modules with unit
#   tests, so the safety-critical alarm decision can be verified without a
#   live GPS/serial rig. Behavior of this script is intended to be unchanged.
#   Fixed a latent crash: if the very first fix after startup came back
#   invalid, fix_error/precision were referenced in the status line before
#   ever being assigned.
#
# Operation:
# Uses first position as reference unless choosing to input from file or can now accept lat/lon too--saves reference location in file for reuse on next startup of the program.
# Prompts user to enter alarm radius in feet--and can be changed by entering "r" while running.
# Displays cur dist,max dist,alarm counts,alarm dist,invalid counts, and now speed in m/s--also tracks GPS position errors and adapts alarm radius according to those errors
# Entering "q" quits
# Entering "h" shows all menu options
# Entering "p" pauses audible alarm for about 30 seconds
# Added raspberry pi gpio buzzer_program_filename output 20150825
# Lots of trouble getting a non-blocking user input.  Still pauses for 2 secs.
# Doesn't work on non gpsd port, but gpsd can read from a tcp port: e.g. tcp://localhost:23000
#
# TODO:
#  Reset max distance stats when new center position is entered.  Make sure max speed isn't spiked.  And reset alarm counter.
#  Reverse order of c results so range is first and bearing 2nd
#  Test iseq alarm works
#  Add ability to enter center range and bearing
#  add something that shows what parameter is triggering the alarm
#  Add display of other GPSD fix details -- maybe create a GPSD fix details menu option
#
#  Better text with below: e.g. only print error on first go
#  Figure out how to integrate with airmar logger
#  Test if data alarm catches problems and if the gpsp restart can recover after an airmar logger restart
#  Test if the gps time test also catches the data problem
#  Low Pri:
#  Do time interval checks to improve acceleration
#  Do vector speed change to improve acceleration
#  Add wind direction? to improve sensitivity when drifting down-wind??--need to parse airmar directly??
#  Add option to change max accel
#  Do we want to keep the speed separate as an alarm trigger??
#  MAYBE BELOW:
#  Increase volume??
#  get proper interrupt handling to switch to menu
#  check lat/long N/S and E/W are same
#   non-hildon sounds--check os and adapt (add windows?? also need to get wav files??)
#    currently uses gnome-sounds package in linux for wav files
#  Sound stuff:
#   set sound level/ramp up volume
#   background warning sound
#  make gtk version

# This now checks change in speed and if it exceeds an acceleration limit, ignores gps update and increments iseq
#  OLD: redo this??  Exceeding alarm radius, first checks velocity is below some threshold--to id bad position data
#  test thresholdspeed works--need acceleration logic??
#
# For the USB buzzer, add this to a file in /etc/udev/rules.d/
# ACTION=="add", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", SYMLINK+="buzzer"
#

import os
import gpsd
from time import *
import time
import math
import pickle
import sys
import getopt
import signal
import serial
from subprocess import call

from geo import calc_distance, calc_bearing, decdeg2dms
from alarm_state import AlarmState, FEET_PER_METER
import gpsd_compat
import nmea_gps_source

# Some receiver/driver combos (confirmed with gpsd 3.25 + NMEA0183 read-only)
# never send gpsd-py3 the per-satellite array it needs to count sats, so it
# silently reports sats=sats_valid=0. See gpsd_compat.py for the full story.
gpsd_compat.patch_satellite_counts()

osname = "hildon"
try:
  import hildon
except:
  osname = "linux"

if osname == "linux":
  import pygame

# to put audio in background use:
# import subprocess
# player = subprocess.Popen(["mplayer", "song.mp3", "-ss", "30"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#
# Then, when I wanted to terminate the MPlayer process, I simply wrote "q" for quit to the pipe.
#
# player.stdin.write("q")
# NOTE: this file has sudo in it!!  If this isn't a valid file path, the file/buzzer_program_filename will not be run
# buzzer_program_filename = "/home/david/bin/anchorbuzzer.sh"
buzzer_program_filename = "disable"
ignore_fix_flag = False  # Set this if gps source doesn't have fix quality info so it will be ignored
maxiseq = 10  # number of bad gps data in a row to trigger info alarm
thresholdspeed = 1.6  # 15  # m/s where 0.5m/s is 1 knot and 15m/s is 30knots
maxaccel = 5.0  # 10.0  # read-to-read max change in speed or data is ignored
min_sats = 4
min_precision = 8
data_log_file_pattern = ""
#data_log_file_pattern = "/home/david/airmar-data/airmar-pb100-raw-log-*.csv"
# file to save last latlon values
latlon_file = 'latlon.pkl'

# For USB Buzzer:
buzzer_dev = "/dev/buzzer"
baudRate = 9600

RED_ON = 0x11
RED_OFF = 0x21
RED_BLINK = 0x41

YELLOW_ON = 0x12
YELLOW_OFF = 0x22
YELLOW_BLINK = 0x42

GREEN_ON = 0x14
GREEN_OFF = 0x24
GREEN_BLINK = 0x44

BUZZER_ON = 0x18
BUZZER_OFF = 0x28
BUZZER_BLINK = 0x48

if os.path.exists(buzzer_dev):
  mSerial = serial.Serial(buzzer_dev, baudRate)

# System Sounds:
# TODO check that these paths exist
# WARNING = "/usr/share/sounds/warning.wav"
WARNING = "/usr/share/sounds/GNUstep/Submarine.wav"
# ERROR = "/usr/share/sounds/error.wav"
ERROR = "/usr/share/sounds/GNUstep/Glass.wav"
# GENERIC = "/usr/share/sounds/generic.wav"
GENERIC = "/usr/share/sounds/GNUstep/Blow.wav"
pygame.mixer.init()
alertSounda = pygame.mixer.Sound(GENERIC)
alertSounda.set_volume(1.0)
alertSound = pygame.mixer.Sound(WARNING)
alertSound.set_volume(1.0)
# alertSound.play()
errorSound = pygame.mixer.Sound(ERROR)
errorSound.set_volume(1.0)
# errorSound.play()
# pygame.mixer.music.load(WARNING)
# pygame.mixer.music.play()

HOST = ''
PORT = ''

# os.system('clear')  # clear the terminal (optional)
def main(argv):
  global HOST
  global PORT
  # set default host and port number
  HOST = '127.0.0.1'       # Hostname to bind
  if osname == "hildon":
    PORT = 22947           # Open non-privileged port 8888
  else:
    PORT = 2947
  try:
    opts, args = getopt.getopt(argv, "hg:p:", ["gpshost=", "portnumber="])
  except getopt.GetoptError:
    print('anchorwatch.py -g <gpshost> -p <portnumber>')
    sys.exit(2)
  for opt, arg in opts:
    if opt == '-h':
       print('anchorwatch.py -g <gpshost> -p <portnumber>')
       sys.exit()
    elif opt in ("-g", "--gpshost"):
       HOST = arg
    elif opt in ("-p", "--portnumber"):
       PORT = arg
  print('GPS Host is ', HOST)
  print('Port number is ', PORT)



if __name__ == '__main__':
  main(sys.argv[1:])

  class AlarmException(Exception):
    pass


  def alarm_handler(signum, frame):
    raise AlarmException


  def non_blocking_raw_Input(prompt='', timeout=2):
    # from Gary Robinson
    signal.signal(signal.SIGALRM, alarm_handler)
    signal.alarm(timeout)
    try:
      text = input(prompt)
      signal.alarm(0)
      return text
    except AlarmException:
      # print('',)
      # need something here but exception is the norm and if we print anything, then the overwrite of lines is broken
      a = 1
      # print '\nPrompt timeout. Continuing...'
    signal.signal(signal.SIGALRM, signal.SIG_IGN)
    return ''


  def get_radius(prompt='Enter Alarm radius in feet:'):
    while True:
      try:
        val = float(input(prompt))
        break
      except ValueError:
        print('That is not a valid number.  Please try again.')
    return val


  def get_dd_lat(prompt='Enter Center latitude in DD between -90 and 90 degrees:'):
    while True:
      try:
        val = float(input(prompt))
        if -90 <= val <= 90:
          break
        else:
          print('Latitude must be between -90 and 90 degrees.')
      except ValueError:
        print('That is not a valid latitude.  Please try again.')
    return val


  def get_dd_lon(prompt='Enter Center longitude in DD between -180 and 180 degrees:'):
    while True:
      try:
        val = float(input(prompt))
        if -180 <= val <= 180:
          break
        else:
          print('Longitude must be between -180 and 180 degrees.')
      except ValueError:
        print('That is not a valid longitude.  Please try again.')
    return val


  def send_command(serialport, cmd):
    if os.path.exists(buzzer_dev):
      serialport.write(bytes([cmd]))


  def usb_buzzer_once(duration=0.5):
    if os.path.exists(buzzer_dev):
      send_command(serial.Serial(buzzer_dev, baudRate), RED_ON)
      send_command(serial.Serial(buzzer_dev, baudRate), BUZZER_ON)
      sleep(duration)
      send_command(serial.Serial(buzzer_dev, baudRate), BUZZER_OFF)
      send_command(serial.Serial(buzzer_dev, baudRate), RED_OFF)


  def usb_light_on():
    if os.path.exists(buzzer_dev):
      send_command(serial.Serial(buzzer_dev, baudRate), RED_BLINK)


  def usb_buzzer_on():
    if os.path.exists(buzzer_dev):
      send_command(serial.Serial(buzzer_dev, baudRate), BUZZER_ON)


  def usb_buzzer_off():
    if os.path.exists(buzzer_dev):
      send_command(serial.Serial(buzzer_dev, baudRate), BUZZER_OFF)


  def usb_buzzer_light_off():
    if os.path.exists(buzzer_dev):
      send_command(serial.Serial(buzzer_dev, baudRate), BUZZER_OFF)
      send_command(serial.Serial(buzzer_dev, baudRate), RED_OFF)


  if osname == "linux" and os.path.exists(buzzer_dev):
    usb_buzzer_light_off()
    serial.Serial(buzzer_dev, baudRate).close()
  try:
    gpsd.connect()
    packet = gpsd.get_current()
    # print("Got packet:")
    # print(packet)
    # print("Position is:")
    # print(packet.position())
    # print(packet.lat)
    # print(packet.lon)
    # print(packet.alt)
    # print(packet.time)
    # print(packet.mode)
    # print(packet.hadop)
    print(packet.error)
    print(packet.sats_valid)
    print(packet.position_precision())
    # print("End")
    print("Connected with gpsd")
  except Exception as e:
    print("Could not start gpsd monitor for host:", HOST, "and port:", PORT, " got exception: ", e)
    sys.exit(2)

  # Masthead GPS (6-axis motion corrected, clear view of the sky) via the raw
  # NMEA stream -- preferred over the gpsd-connected in-boat puck whenever it
  # has a current 3D fix. Not fatal if unreachable at startup: get_current_fix()
  # below just falls back to gpsd every tick, same as if the masthead feed
  # drops out mid-session.
  nmea_source = nmea_gps_source.NmeaGpsSource()
  try:
    nmea_source.connect()
    print("Connected to masthead NMEA stream at", nmea_source.host, ":", nmea_source.port)
  except Exception as e:
    print("Could not connect to masthead NMEA stream (will rely on gpsd only):", e)

  active_gps_source = 'gpsd'  # which source supplied the last fix, for transition logging

  def get_current_fix():
    global active_gps_source
    nmea_fix = None
    try:
      nmea_fix = nmea_source.get_current()
    except Exception as e:
      print("Masthead NMEA read failed, falling back to gpsd:", e)

    if nmea_fix is not None and nmea_fix.mode == 3:
      if active_gps_source != 'nmea':
        print("Using masthead NMEA GPS at", time.strftime("%D %H:%M:%S", time.localtime()))
        active_gps_source = 'nmea'
      return nmea_fix

    if active_gps_source != 'gpsd':
      print("Falling back to gpsd (in-boat puck) at", time.strftime("%D %H:%M:%S", time.localtime()))
      active_gps_source = 'gpsd'
    return gpsd.get_current()

  run = True
  try:
    fix = get_current_fix()
    while run:
      print("Waiting for GPS fix...")
      if fix is None:  # or not 'lat' in fix.keys():
        print("FIX IS NONE!!!!")
        sleep(2)
        fix = get_current_fix()
        continue
      # os.system('clear')
      print()
      print(' GPS reading for host: ', HOST)
      print('----------------------------------------')
      print('latitude    ', fix.lat)
      print('longitude   ', fix.lon)
      print('time utc    ', fix.time)
      print('altitude (m)', fix.alt)
      # print('ept         ', fix['ept'])
      # print('eph         ', fix['eph'])
      print('speed (m/s) ', fix.hspeed)
      print('climb       ', fix.climb)
      print('track       ', fix.track)
      print('total sats  ', fix.sats)
      print('used sats   ', fix.sats_valid)
      print('precision   ', fix.position_precision())
      print('errors      ', fix.error)
      print('mode        ', fix.mode)
      # print('status      ', fix.status)

      if ignore_fix_flag and (fix.lat != 0.0 and not math.isnan(fix.lat)) and (fix.lon != 0.0 and not math.isnan(fix.lon)) and not math.isnan(fix.time):  # and fix.time != ''
        break

      if fix.mode == 3:
        print("Testing alarm")
        if os.path.exists(buzzer_dev):
          print("Buzzer exists")
        else:
          print("Buzzer does not exist at:", buzzer_dev)
        usb_light_on()
        usb_buzzer_once(1.0)
        usb_buzzer_light_off()
        print("Got a good fix and exiting poling setup")
        break

      sleep(2)
      fix = get_current_fix()

    print()
    if ignore_fix_flag:
      print("Ignoring fix flag")
    else:
      # os.system('clear')
      print("Have GPS fix.")
    print(' GPS reading for host: ', HOST)
    print('----------------------------------------')
    print('latitude    ', fix.lat)
    print('longitude   ', fix.lon)
    print('time utc    ', fix.time)
    print('altitude (m)', fix.alt)
    # print('ept         ', fix['ept'])
    # print('eph         ', fix['eph'])
    print('speed (m/s) ', fix.hspeed)
    # print('climb       ', fix.climb)
    print('track       ', fix.track)
    print('total sats  ', fix.sats)
    print('used sats   ', fix.sats_valid)
    print('precision   ', fix.position_precision())
    print('errors      ', fix.error)
    print('mode        ', fix.mode)
    # print('status      ', fix.status)

    feet_per_meter = FEET_PER_METER
    acount = 0        # alarm counter--number of times position is outside alarm radius
    adist = 0         # user entered alarm radius
    runcount = 0      # number of gps fixes/attempts
    adata = False     # check for data update errors
    buzzer_on = False
    light_on = False
    adistset = False  # flag for alarm radius set
    refset = False    # flag for reference lat/long set
    speed_set = True  # flag for setting speed
    pause_interval = 15  # duration of alarm pause
    pause_count = 0   # tracks duration
    extended_output = False  # default display option
    lat = 0       # to ensure a value is set
    lon = 0       # to ensure a value is set
    reflat = 0    # to ensure a value is set
    reflon = 0    # to ensure a value is set
    # Defaults so the status line can't crash if the very first fix in the
    # loop below comes back invalid before these are ever assigned from a fix.
    precision = (0.0, 0.0)
    fix_error = {'x': 0.0, 'y': 0.0, 'v': 0.0, 's': 0.0}

    # The drag-alarm decision logic (smoothing, radius/speed checks, bad-data
    # handling) lives in alarm_state.AlarmState -- see that module for the
    # unit-tested behavior. This loop just feeds it fixes and reacts to the
    # events it reports (alarm triggered/cleared, bad data, etc).
    alarm = AlarmState(thresholdspeed, maxaccel, min_sats, ignore_fix_flag)

    help_str = "\nHelp: \'h\': Use \'r<enter>\' to change radius limit, \'c<enter>\' to change circle center lat/lon, \'a<enter>\' to show anchor position, \'s<enter>\' to change speed limit, \'x<enter>\' to toggle short and long output formats, \'p<enter>\' to temporarily pause alarm, \'t<enter>\' to test alarm or \'q<enter>\' to quit the program."

    # This is to prevent the next fix from having the same time and triggering an invalid gps data warning
    sleep(2)


#    sys.stdout = os.fdopen(sys.stdout.fileno(), "w", newline=None)
    while run:
      #sleep(.4)
      fix = get_current_fix()
      runcount += 1
      if pause_count > 0:
        pause_count -= 1
      if osname == "hildon":
        if alarm.aset and pause_count == 0:
          hildon.hildon_play_system_sound("/usr/share/sounds/ui-general_warning.wav")
        # if iseq > maxiseq: hildon.hildon_play_system_sound("/usr/share/sounds/ui-general_warning.wav")
        # if iseq > maxiseq: hildon.hildon_play_system_sound("/usr/share/sounds/ui-default_beep.wav")
        if alarm.iseq > maxiseq:
          hildon.hildon_play_system_sound("/usr/share/sounds/ui-information_note.wav")
      if osname == "linux":
        # fix these:
        # if aset: pygame.mixer.music.play()
        if alarm.aset and pause_count == 0:
          if os.path.isfile(buzzer_program_filename):
            # call(["ls", "-l"])
            call([buzzer_program_filename])
          if not buzzer_on:
            usb_buzzer_on()
            buzzer_on = True
          else:
            usb_buzzer_off()
            buzzer_on = False
          if not light_on:
            print("Alarm triggered", time.strftime("%D %H:%M:%S", time.localtime()))
            acount += 1
            usb_light_on()
            light_on = True

          # TODO catch error here? if these don't work??
          alertSounda.play()
          alertSound.play()

        if alarm.iseq > maxiseq:
           print("Invalid gps", alarm.iseq, "times which is over threshold of", maxiseq)
           usb_light_on()
           usb_buzzer_once()
           sleep(1)
           usb_buzzer_light_off()
           # errorSound.play()

      if fix.mode != 3 and not ignore_fix_flag:
        result = alarm.update(fix, reflat, reflon, adist, adata)
        if result.invalid_fix_is_new:
          print('Invalid gps data at', time.strftime("%D %H:%M:%S", time.localtime()))
      else:
        lat = float(fix.lat)
        lon = float(fix.lon)
        speed = fix.hspeed
        precision = fix.position_precision()
        fix_error = fix.error
        if not refset:
          if os.path.exists(latlon_file):
            with open(latlon_file, 'rb') as file:
              oldlat, oldlon = pickle.load(file)
            print(oldlat, oldlon)
            distance = calc_distance(lat, lon, oldlat, oldlon)
            bearing = calc_bearing(lat, lon, oldlat, oldlon)
            print("Old Latitude", oldlat, "and Longitude", oldlon, "is", distance, "feet from current location and bearing", bearing, "deg true")
            use_old = input('Reuse old reference point? y/N')
            # print("You entered:", use_old)
            if use_old == 'y':
              print("Using old reference point")
              lat = oldlat
              lon = oldlon
            else:
              print("Using new reference point")
          degrees, minutes, seconds = decdeg2dms(lat)
          print("Latitude DD: %f or DMS: %d:%d:%f or DDM: %d:%f" % (lat, degrees, minutes, seconds, degrees, minutes + seconds/60))
          degrees, minutes, seconds = decdeg2dms(lon)
          print("Longitude DD: %f or DMS: %d:%d:%f or DDM: %d:%f" % (lon, degrees, minutes, seconds, degrees, minutes + seconds/60))
          reflat = lat
          reflon = lon
          with open(latlon_file, 'wb') as file:
            pickle.dump([reflat, reflon], file)
          refset = True
        if not adistset:
          print('\nCenter in decimal degrees is: lat=', lat, ' lon=', lon, ' with speed=', speed, 'm/s', time.strftime("%D %H:%M:%S", time.localtime()))
          adist = get_radius(prompt="Enter new Alarm radius in feet (radius limit was " + str(adist) + " feet): ")
          fix = get_current_fix()
          adistset = True
          print("Radius limit", adist, "feet and speed limit", alarm.thresholdspeed, "m/s.")
          print(help_str)
        if not speed_set:
          alarm.thresholdspeed = get_radius(prompt="Enter new speed limit in m/s where 1.0 m/s is approx 2 knots (speed limit was " + str(alarm.thresholdspeed) + " m/s): ")
          fix = get_current_fix()
          speed_set = True
          print("Radius limit", adist, "feet and speed limit", alarm.thresholdspeed, "m/s.")

        # if len(data_log_file_pattern) > 0:
        #   # This checks the data logger file which relies on the same ground truth as the gpsd.  So a failure here
        #   # could be just the gps-poller or it could be the airmar data logger.  This will catch both even though
        #   # only a loss of the airmar process will cause a gpsd data freeze--and we check for that using the utc time checks
        #   line_checks = 0
        #   # This returns exit code 0 if time match is found and another integer if failed to find
        #   line_count = int(os.system("tail " + data_log_file_pattern + " | grep -sqc \"$(date +'%Y-%m-%d, %H:%M')\""))
        #   # print("TEST line count:", type(line_count), line_count)
        #   while line_count != 0 and not adata:
        #     # We can easily get 1 repeat since our resolution is 1 sec, but if more than 1 it is an issue to track
        #     if line_count > 1:
        #       # print("missing data", line_checks)
        #       icount += 1
        #     if line_checks > 10:
        #       adata = True
        #       print("Data not updated error in", line_checks, "checks at", time.strftime("%D %H:%M:%S", time.localtime()))
        #       usb_buzzer_once()
        #       break
        #     sleep(2)
        #     line_count = int(os.system("tail " + data_log_file_pattern + " | grep -sqc \"$(date +'%Y-%m-%d, %H:%M')\""))
        #     # print("TEST line count again:", type(line_count), line_count)
        #     line_checks += 1
          # if adata:
          #   # and line_count == 0:
          #   print("Restarting GPS poller due to adata at", time.strftime("%D %H:%M:%S", time.localtime()))
          #   adata = False
          #   gpsp.running = False
          #   gpsp.join()
          #   gpsp = GpsPoller()  # create the thread
          #   gpsp.start()
          #   sleep(4)
          #   if gpsp.running:
          #     print("GPS poller running")
          #     fix = gpsp.get_current_value()
          #   else:
          #     print("GPS not running")
          #   # TODO may not need the next line
          #   continue

        old_iseq = alarm.iseq
        result = alarm.update(fix, reflat, reflon, adist, adata)

        if result.bad_distance:
          print("bad distance", result.bad_distance_value, "with speed", speed, "m/s and acceleration", speed - alarm.avgspeed, "at", time.strftime("%D %H:%M:%S", time.localtime()))
        else:
          if result.stale_time and result.stale_time_is_new:
            print("WARNING: Time stopped at GPS time", fix.time, "at", time.strftime("%D %H:%M:%S", time.localtime()))
          if result.iseq_reset:
            print("Resetting iseq from", old_iseq, " to 0 at", time.strftime("%D %H:%M:%S", time.localtime()))
            usb_buzzer_light_off()
            buzzer_on = False
            light_on = False

          if result.bad_speed:
            print("bad speed", speed, "at", time.strftime("%D %H:%M:%S", time.localtime()))

          if result.low_sats:
            print("Not enough sats tracked:", fix.sats_valid, "out of", fix.sats, "total with min sats:", min_sats, "at", time.strftime("%D %H:%M:%S", time.localtime()))

        if result.alarm_cleared:
          print("Alarm cleared at", time.strftime("%D %H:%M:%S", time.localtime()))
          usb_buzzer_light_off()
          buzzer_on = False
          light_on = False

      if extended_output:
        sys.stdout.write('\rAlarm=%d: Cnt=%d: Center=%d ft/%03.0f degT/%d maxft/%.1f errft: filtered=%d ft/%d maxft/%.1f alarmft: Speed=%.1f mps/%.1f maxmps/%.1f errmps: filtered=%.1f mps/%.1f maxmps/%.1f alarmmps: Ivld=%d/%d: sats=%d/%d: AvgErr=%0.1fft/%0.1fmax-err:       ' % (alarm.aset, acount, alarm.distance, alarm.bearing, alarm.mrawdist, precision[0] * feet_per_meter, alarm.avgdist, alarm.mdist, adist - alarm.pos_error, alarm.speed, alarm.mrawspeed, fix_error['s'], alarm.avgspeed, alarm.maxspeed, alarm.thresholdspeed, alarm.icount, runcount, fix.sats_valid, fix.sats, alarm.pos_error, alarm.maxerror))
      # sys.stdout.write('\rAlarm=%d: Cnt=%d: RawRad/mx=%d/%dfeet: SmRad/mx/lmt=%d/%d/%dft: RawSpd/mx=%.1f/%.1fm/s: SmSpd/mx/lmt=%.1f/%.1f/%.1fm/s: Trk/avg=%.1f/%.1fD: Ivd=%d/%d   ' % (aset,  acount, distance, mrawdist, avgdist, mdist, adist, speed, mrawspeed, avgspeed, maxspeed, thresholdspeed, track, avgtrack, icount, runcount))
      else:
        sys.stdout.write(
          '\rAlarm=%d: Cnt=%d: Center=%dft/%.1falarm-ft %03.0fdegT %dmax-ft %0.1ferr-ft/%0.1fmax-err:: Speed=%.1fmps/%.1falarm-mps %.1fmax-mps %.1ferr-mps:: Ivld=%d/%d:: sats=%d/%d::       ' % (
          alarm.aset, acount, alarm.avgdist, adist - alarm.pos_error, alarm.bearing, alarm.mdist, alarm.pos_error, alarm.maxerror, alarm.avgspeed, alarm.thresholdspeed, alarm.maxspeed, fix_error['s'], alarm.icount, runcount, fix.sats_valid, fix.sats))
      sys.stdout.flush()  # to clear when using \r
      menu = non_blocking_raw_Input('')
      if menu == 'q':
        break
      elif menu == 'h':
        print(help_str)
      elif menu == 'r':
        adistset = False
      elif menu == 's':
        speed_set = False
      elif menu == 'c':
        print("Change center location")
        templat = get_dd_lat(prompt="Enter new lat in DD to replace current of " + str(reflat) + ": ")
        templon = get_dd_lon(prompt="Enter new lon in DD to replace current of " + str(reflon) + ": ")

        degrees, minutes, seconds = decdeg2dms(templat)
        print("Entered Latitude DD: %f or DMS: %d:%d:%f or DDM: %d:%f" % (
          templat, degrees, minutes, seconds, degrees, minutes + seconds / 60))
        degrees, minutes, seconds = decdeg2dms(templon)
        print("Entered Longitude DD: %f or DMS: %d:%d:%f or DDM: %d:%f" % (
          templon, degrees, minutes, seconds, degrees, minutes + seconds / 60))
        distance = calc_distance(lat, lon, templat, templon)
        bearing = calc_bearing(lat, lon, templat, templon)
        print("Entered center is", distance, "feet from current location and bearing", bearing, "deg true")
        use_new = input('Use new reference point? y/N')
        # print("You entered:", use_new)
        if use_new == 'y':
          print("Using new reference point")
          reflat = templat
          reflon = templon
          # print("WARNING LATLON FILE SAVE DISABLED")
          with open(latlon_file, 'wb') as file:
            pickle.dump([reflat, reflon], file)
        else:
          print("Keeping previous center point")
        fix = get_current_fix()
      elif menu == 'p':
        print("Pausing alarm")
        pause_count = pause_interval
        usb_buzzer_off()
        buzzer_on = False
      elif menu == 'x':
        if extended_output:
          extended_output = False
        else:
          extended_output = True
      elif menu == 'a':
        degrees, minutes, seconds = decdeg2dms(reflat)
        print("\nCenter latitude DD: %f or DMS: %d:%d:%f or DDM: %d:%f" % (reflat, degrees, minutes, seconds, degrees, minutes + seconds/60))
        degrees, minutes, seconds = decdeg2dms(reflon)
        print("Center longitude DD: %f or DMS: %d:%d:%f or DDM: %d:%f" % (reflon, degrees, minutes, seconds, degrees, minutes + seconds/60))
        print("Center bearing from current position is %03.1f degrees True, distance is %d feet and height is %0.1f feet at %s" % (alarm.bearing, alarm.distance, fix.alt * feet_per_meter, time.strftime("%D %H:%M:%S", time.localtime())))
        fix = get_current_fix()
      elif menu == 't':
        alarm.aset = True
        print("\nTesting alarm")
        if os.path.exists(buzzer_dev):
          print("Buzzer exists")
        else:
          print("Buzzer does not exist at:", buzzer_dev)
        usb_light_on()
        usb_buzzer_once(1.0)
        usb_buzzer_light_off()
        fix = get_current_fix()
      # elif menu == 'g':
      #   print("Restarting GPS poller on demand at", time.strftime("%D %H:%M:%S", time.localtime()))
      #   gpsp.running = False
      #   gpsp.join()
      #   gpsp = GpsPoller()  # create the thread
      #   gpsp.start()
      #   if gpsp.running:
      #     print("GPS poller running")
      #   else:
      #     print("GPS not running")
      #   sleep(5)
      #   fix = gpsp.get_current_value()

    # Exit while loop
    print("\nExiting normally...")  # normal exit
    run = False
    if osname == "linux" and os.path.exists(buzzer_dev):
      usb_buzzer_light_off()
      serial.Serial(buzzer_dev, baudRate).close()

  except (KeyboardInterrupt, SystemExit):  # runs if you press ctrl+c to exit
    print("\nInterrupt Killing Program...")
    run = False
    if osname == "linux" and os.path.exists(buzzer_dev):
      usb_buzzer_light_off()
      serial.Serial(buzzer_dev, baudRate).close()

  except Exception as e:
    # TODO are there cases where we can restart automatically?
    print("General failure exception:", e)
    # Turn on buzzer alarm
    if osname == "linux" and os.path.exists(buzzer_dev):
      usb_buzzer_on()
      usb_light_on()

  print("Done.\nExiting Anchor Watch.")
