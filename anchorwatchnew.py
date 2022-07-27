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
#
# Uses first position as reference--save in file for reuse?
# Prompts user to enter alarm radius in feet--and change by entering "r" while running.
# Displays cur dist,max dist,alarm counts,alarm dist,invalid counts, and now speed in m/s
# Entering "q" quits
# Added raspberry pi gpio buzzer_program_filename output 20150825
# Lots of trouble getting a non-blocking user input.  Still pauses for 2 secs.
# Doesn't work on non gpsd port, but gpsd can read from a tcp port: e.g. tcp://localhost:23000
#
# TODO:
#  Improve alarm test mode--too short right now so just blips
#  Do time interval checks to improve acceleration
#  Do vector speed change to improve acceleration
#  Add wind direction? to improve sensitivity when drifting down-wind??
#  Add option to change max accel
#  Do we want to keep the speed separate as an alarm trigger??
#  save ref lat/long for later recall as ref
#  MAYBE BELOW:
#  refactor function names
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
 
import os
from gps import *
from time import *
import time
# from datetime import datetime
import threading
import math
import sys
import getopt
import signal
import serial
from subprocess import call
# from select import select
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
thresholdspeed = 1  # 15  # m/s where 0.5m/s is 1 knot and 15m/s is 30knots
maxaccel = 5.0  # 10.0  # read-to-read max change in speed or data is ignored

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

gpsd = None  # setting the global variable
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


class GpsPoller(threading.Thread):
  def __init__(self):
    threading.Thread.__init__(self)
    global gpsd  # bring it in scope
    gpsd = gps(mode=WATCH_ENABLE, host=HOST, port=PORT)  # starting the stream of info
    self.current_value = None
    self.running = True  # setting the thread running to true
 
  def run(self):
    global gpsd
    while gpsp.running:
      gpsd.next()  # this will continue to loop and grab EACH set of gpsd info to clear the buffer


if __name__ == '__main__':
  main(sys.argv[1:])
  try: 
    gpsp = GpsPoller() # create the thread
  except:
    print("Could not start gpsd monitor for host: ", HOST)
    sys.exit()


  def calcDistance(lat1, lon1, lat2, lon2):
    # Calculate distance between two lat lons in NM
    # """
    yDistance = (reflat - lat) * nauticalMilePerLat
    xDistance = (math.cos(reflat * rad) + math.cos(lat * rad)) * (reflon - lon) * (nauticalMilePerLongitude / 2)
    distance = math.sqrt(yDistance ** 2 + xDistance ** 2) * FeetPerNauticalMile
    return distance


  class AlarmException(Exception):
    pass


  def alarmHandler(signum, frame):
    raise AlarmException


  def nonBlockingRawInput(prompt='', timeout=2):
    # from Gary Robinson
    signal.signal(signal.SIGALRM, alarmHandler)
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


  def getradius(prompt='Enter Alarm radius in feet:'):
    while True:
      try:
        val = float(input(prompt))
        break
      except ValueError:
        print('That is not a valid number.  Please try again.')
    return val


  def sendCommand(serialport, cmd):
    if os.path.exists(buzzer_dev):
      serialport.write(bytes([cmd]))


  def usb_buzzer_once():
    sendCommand(mSerial, RED_ON)
    sendCommand(mSerial, BUZZER_ON)
    sleep(1.0)
    sendCommand(mSerial, BUZZER_OFF)
    sendCommand(mSerial, RED_OFF)


  def usb_light_on():
    sendCommand(mSerial, RED_BLINK)


  def usb_buzzer_on():
    sendCommand(mSerial, BUZZER_ON)


  def usb_buzzer_off():
    sendCommand(mSerial, BUZZER_OFF)


  def usb_buzzer_light_off():
    sendCommand(mSerial, BUZZER_OFF)
    sendCommand(mSerial, RED_OFF)


  try:
    gpsp.start()  # start it up
    while gpsd.fix.mode != 3:
      os.system('clear')
      print("Waiting for GPS fix...")
      sleep(1)
      print()
      print(' GPS reading for host: ', HOST)
      print('----------------------------------------')
      print('latitude    ', gpsd.fix.latitude)
      print('longitude   ', gpsd.fix.longitude)
      print('time utc    ', gpsd.utc, ' + ', gpsd.fix.time)
      print('altitude (m)', gpsd.fix.altitude)
#      print 'eps         ', gpsd.fix.eps
#      print 'epx         ', gpsd.fix.epx
#      print 'epv         ', gpsd.fix.epv
#      print 'ept         ', gpsd.fix.ept
      print('speed (m/s) ', gpsd.fix.speed)
#      print 'climb       ', gpsd.fix.climb
      print('track       ', gpsd.fix.track)
      print('mode        ', gpsd.fix.mode)
      print()
      print('sats        ', gpsd.satellites)
      # Type checks
      # print("lat type", type(gpsd.fix.latitude), gpsd.fix.latitude)
      # print("fix type", type(gpsd.fix.time), gpsd.fix.time)
      # print("utc type", type(gps.uts))  # invalid type
      print("utc", gpsd.utc)

      if ignore_fix_flag and (gpsd.fix.latitude != 0.0 and not math.isnan(gpsd.fix.latitude)) and (gpsd.fix.longitude != 0.0 and not math.isnan(gpsd.fix.longitude)) and not math.isnan(gpsd.fix.time):  # and gps.utc != ''
        break

    print()
    if ignore_fix_flag:
      print("Ignoring fix flag")
    else:
      # sleep(1)
      os.system('clear')
      print("Have GPS fix.")
    print(' GPS reading for host: ', HOST)
    print('----------------------------------------')
    print('latitude    ', gpsd.fix.latitude)
    print('longitude   ', gpsd.fix.longitude)
    print('time utc    ', gpsd.utc, ' + ', gpsd.fix.time)
    print('altitude (m)', gpsd.fix.altitude)
#    print 'eps         ', gpsd.fix.eps
#    print 'epx         ', gpsd.fix.epx
#    print 'epv         ', gpsd.fix.epv
#    print 'ept         ', gpsd.fix.ept
    print('speed (m/s) ', gpsd.fix.speed)
#    print 'climb       ', gpsd.fix.climb
    print('track       ', gpsd.fix.track)
    print('mode        ', gpsd.fix.mode)
    print()
    print('sats        ', gpsd.satellites)

    nauticalMilePerLat = 60.00721
    nauticalMilePerLongitude = 60.10793
    rad = math.pi / 180.0
    milesPerNauticalMile = 1.15078
    FeetPerNauticalMile = 6015
    icount = 0        # invalid data counter
    acount = 0        # alarm counter--number of times position is outside alarm radius
    mdist = 0         # max distance from ref
    mrawdist = 0
    avgdist = 0
    adist = 0         # user entered alarm radius
    distance = 0      # current distance from ref
    runcount = 0      # number of gps fixes/attempts
    aset = False      # flag for alarm state
    buzzer_on = False
    light_on = False
    adistset = False  # flag for alarm radius set
    refset = False    # flag for reference lat/long set
    speed_set = True  # flag for setting speed
    iseq = 0          # number of sequential invalid data sets
    speed = 0.0       # speed in m/s
    maxspeed = 0.0    # max speed while at anchor
    avgspeed = 0.0
    mrawspeed = 0.0
    track = 0.0
    avgtrack = 0.0


#    sys.stdout = os.fdopen(sys.stdout.fileno(), "w", newline=None)
    while True:
      runcount += 1
      if osname == "hildon":
        if aset:
          hildon.hildon_play_system_sound("/usr/share/sounds/ui-general_warning.wav")
        # if iseq > maxiseq: hildon.hildon_play_system_sound("/usr/share/sounds/ui-general_warning.wav")
        # if iseq > maxiseq: hildon.hildon_play_system_sound("/usr/share/sounds/ui-default_beep.wav")
        if iseq > maxiseq:
          hildon.hildon_play_system_sound("/usr/share/sounds/ui-information_note.wav")
      if osname == "linux":
        # fix these:
        # if aset: pygame.mixer.music.play()
        if aset:
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

          # TODO catch error here? if these doesn't work??
          alertSounda.play()
          alertSound.play()

        if iseq > maxiseq:
          print("Invalid gps", iseq, "times which is over threshold of", maxiseq)
          usb_buzzer_once()
          # errorSound.play()
     
      if gpsd.fix.mode != 3 and not ignore_fix_flag:
        iseq += 1
        print('Invalid gps data', iseq)
        icount += 1
      else:
        lat = float(gpsd.fix.latitude)
        lon = float(gpsd.fix.longitude)
        speed = gpsd.fix.speed
        track = gpsd.fix.track
        if not refset:
          print("Latitude is ", lat, " Longitude is ", lon)
          reflat = lat
          reflon = lon
          refset = True
        if not adistset:
          print('\nCenter in decimal degrees is: lat=', lat, ' lon=', lon, ' with speed=', speed, 'm/s', time.strftime("%D %H:%M:%S", time.localtime()))
          adist = getradius(prompt="Enter new Alarm radius in feet (radius limit was " + str(adist) + " feet): ")
          adistset = True
          print("Radius limit", adist, "feet and speed limit", thresholdspeed, "m/s.  Use \'r<enter>\' to change radius limit, \'s<enter>\' to change speed limit, or \'q<enter>\' to quit the program.")
        if not speed_set:
          thresholdspeed = getradius(prompt="Enter new speed limit in m/s where 1.0 m/s is approx 2 knots (speed limit was " + str(thresholdspeed) + " m/s): ")
          speed_set = True
    
        distance = calcDistance(reflat, reflon, lat, lon)
        if math.isnan(distance) or speed > avgspeed + maxaccel:
          print("bad distance", distance, "with speed", speed, "m/s and acceleration", speed - avgspeed)
          distance = 0.
          icount += 1
          iseq += 1
        else:
          iseq = 0
          avgdist *= 0.8
          avgdist += 0.2 * distance
          if avgdist > mdist:
            mdist = avgdist
          if distance > mrawdist:
            mrawdist = distance

          if math.isnan(speed):
            print("bad speed", speed)
            speed = 0.
            icount += 1
            # set alarm??
          else:
            avgspeed *= 0.8
            avgspeed += 0.2 * speed
            if avgspeed > maxspeed:
              maxspeed = avgspeed
            if speed > mrawspeed:
              mrawspeed = speed

        if not math.isnan(track):
          avgtrack *= 0.8
          avgtrack += 0.2 * track
        else:
          # We get a lot of bad tracks
          # print("bad track", track)
          track = avgtrack

        if avgdist > adist or avgspeed > thresholdspeed:  # and gpsd.fix.speed is below some m/s threshold
          aset = True
        else:
          if aset:
            print("Alarm cleared", time.strftime("%D %H:%M:%S", time.localtime()))
            usb_buzzer_light_off()
            buzzer_on = False
            light_on = False
          aset = False

      sys.stdout.write('\rAlarm status=%d: Alarm count=%d: RawRadius/max=%d/%d feet: SmoothRadius/max/limit=%d/%d/%d feet: RawSpeed/max=%.1f/%.1f m/s: SmoothSpeed/max/limit=%.1f/%.1f/%.1f m/s: Track/avg=%.1f/%.1f degrees: Invalid data ratio=%d/%d          ' % (aset,  acount, distance, mrawdist, avgdist, mdist, adist, speed, mrawspeed, avgspeed, maxspeed, thresholdspeed, track, avgtrack, icount, runcount))
      sys.stdout.flush()  # to clear when using \r
      menu = nonBlockingRawInput('')
      if menu == 'q':
        break
      elif menu == 'r':
        adistset = False
      elif menu == 's':
        speed_set = False
      elif menu == 't':
        aset = True
   
    print("\nKilling GPS Monitor Thread...")  # normal exit
    gpsp.running = False
    gpsp.join()  # wait for the thread to finish what it's doing
    if osname == "linux":
      usb_buzzer_light_off()
      mSerial.close()
 
  except (KeyboardInterrupt, SystemExit):  # runs if you press ctrl+c to exit
    print("\nInterrupt Killing GPS Monitor Thread...")
    gpsp.running = False
    gpsp.join()  # wait for the thread to finish what it's doing
    if osname == "linux":
      usb_buzzer_light_off()
      mSerial.close()
  print("Done.\nExiting Anchor Watch.")

