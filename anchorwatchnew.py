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
# Last updated on 20131123
#
# Uses first position as reference--save in file for reuse?
# Prompts user to enter alarm radius in feet--and change by entering "r" while running.
# Displays cur dist,max dist,alarm counts,alarm dist,invalid counts, and now speed in m/s
# Exceeding alarm radius, first checks velocity is below some threshold--to id bad position data
# Entering "q" quits
# Lots of trouble getting a non-blocking user input.  Still pauses for 2 secs.
#
# Todo:
#  test thresholdspeed works--need acceleration logic??
#  test on nokia
#  test with non gpsd port??
#  Sound stuff:
#   set sound level/ramp up volume
#   background warning sound
#   non-hildon sounds--check os and adapt (add windows?? also need to get wav files??)
#    currently uses gnome-sounds package in linux for wav files
#  get proper interrupt handling to switch to menu
#  save ref lat/long for later recall as ref
#  check lat/long N/S and E/W are same
#  make gtk version
#
 
import os
from gps import *
from time import *
import time
import threading
import math
import sys
import getopt
import signal
from select import select
osname="hildon"
try:
 import hildon
except:
 osname="linux"

if osname == "linux":
 import pygame
 #Sounds
 WARNING="/usr/share/sounds/warning.wav"
 ERROR="/usr/share/sounds/error.wav"
 pygame.mixer.init()
 alertSound=pygame.mixer.Sound(WARNING)
#alertSound.play()
 errorSound=pygame.mixer.Sound(ERROR)
#errorSound.play()
 #pygame.mixer.music.load(WARNING)
# pygame.mixer.music.play()
#os.system('mpg321 foo.mp3 &')

#to put audio in background use:
#import subprocess
#player = subprocess.Popen(["mplayer", "song.mp3", "-ss", "30"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#
#Then, when I wanted to terminate the MPlayer process, I simply wrote "q" for quit to the pipe.
#
#player.stdin.write("q")

maxiseq = 10             #number of bad gps data in a row to trigger info alarm
thresholdspeed = 15 #m/s where 0.5m/s is 1 knot and 15m/s is 30knots

gpsd = None #seting the global variable
#HOST = ''
#PORT = ''
 
#os.system('clear') #clear the terminal (optional)
def main(argv):
   global HOST
   global PORT
   #set default host and port number
   HOST = '127.0.0.1'       # Hostname to bind
   if osname == "hildon":
    PORT = 22947              # Open non-privileged port 8888
   else:
    PORT = 2947
   try:
      opts, args = getopt.getopt(argv,"hg:p:",["gpshost=","portnumber="])
   except getopt.GetoptError:
      print 'anchorwatch.py -g <gpshost> -p <portnumber>'
      sys.exit(2)
   for opt, arg in opts:
      if opt == '-h':
         print 'anchorwatch.py -g <gpshost> -p <portnumber>'
         sys.exit()
      elif opt in ("-g", "--gpshost"):
         HOST = arg
      elif opt in ("-p", "--portnumber"):
         PORT = arg
   print 'GPS Host is ', HOST
   print 'Port number is ', PORT


class GpsPoller(threading.Thread):
  def __init__(self):
    threading.Thread.__init__(self)
    global gpsd #bring it in scope
    gpsd = gps(mode=WATCH_ENABLE,host=HOST,port=PORT) #starting the stream of info
    self.current_value = None
    self.running = True #setting the thread running to true
 
  def run(self):
    global gpsd
    while gpsp.running:
      gpsd.next() #this will continue to loop and grab EACH set of gpsd info to clear the buffer
 
if __name__ == '__main__':
  main(sys.argv[1:])
  try: 
   gpsp = GpsPoller() # create the thread
  except:
   print "Could not start gpsd monitor for host: ",HOST
   sys.exit()
  try:
    gpsp.start() # start it up
    while gpsd.fix.mode != 3:
      os.system('clear')
      print "Waiting for GPS fix..."
      print
      print ' GPS reading for host: ',HOST
      print '----------------------------------------'
      print 'latitude    ' , gpsd.fix.latitude
      print 'longitude   ' , gpsd.fix.longitude
      print 'time utc    ' , gpsd.utc,' + ', gpsd.fix.time
      print 'altitude (m)' , gpsd.fix.altitude
#      print 'eps         ' , gpsd.fix.eps
#      print 'epx         ' , gpsd.fix.epx
#      print 'epv         ' , gpsd.fix.epv
#      print 'ept         ' , gpsd.fix.ept
      print 'speed (m/s) ' , gpsd.fix.speed
#      print 'climb       ' , gpsd.fix.climb
      print 'track       ' , gpsd.fix.track
      print 'mode        ' , gpsd.fix.mode
      print
      print 'sats        ' , gpsd.satellites
      sleep(1)
    sleep(1)
    os.system('clear')
    print "Have GPS fix."
    print
    print ' GPS reading for host: ',HOST
    print '----------------------------------------'
    print 'latitude    ' , gpsd.fix.latitude
    print 'longitude   ' , gpsd.fix.longitude
    print 'time utc    ' , gpsd.utc,' + ', gpsd.fix.time
    print 'altitude (m)' , gpsd.fix.altitude
#    print 'eps         ' , gpsd.fix.eps
#    print 'epx         ' , gpsd.fix.epx
#    print 'epv         ' , gpsd.fix.epv
#    print 'ept         ' , gpsd.fix.ept
    print 'speed (m/s) ' , gpsd.fix.speed
#    print 'climb       ' , gpsd.fix.climb
    print 'track       ' , gpsd.fix.track
    print 'mode        ' , gpsd.fix.mode
    print
    print 'sats        ' , gpsd.satellites

    nauticalMilePerLat = 60.00721
    nauticalMilePerLongitude = 60.10793
    rad = math.pi / 180.0
    milesPerNauticalMile = 1.15078
    FeetPerNauticalMile = 6015
    icount = 0       #invalid data counter
    acount = 0       #alarm counter--number of times position is outside alarm radius
    mdist = 0        #max distance from ref
    adist = 0        #user entered alarm radius
    distance = 0     #current distance from ref
    runcount = 0     #number of gps fixes/attempts
    aset = False     #flag for alarm state
    adistset = False #flag for alarm radius set
    refset = False   #flag for reference lat/long set
    iseq = 0         #number of sequential invalid data sets
    speed = 0.0      #speed in m/s
    maxspeed = 0.0   #max speed while at anchor

    def calcDistance(lat1, lon1, lat2, lon2):
 #Caclulate distance between two lat lons in NM
 #"""
     yDistance = ((reflat) - (lat)) * nauticalMilePerLat
     xDistance = (math.cos(reflat * rad) + math.cos(lat * rad)) * (reflon - lon) * (nauticalMilePerLongitude / 2)
     distance = math.sqrt( yDistance**2 + xDistance**2 ) * FeetPerNauticalMile
     return(distance)

    class AlarmException(Exception):
      pass

    def alarmHandler(signum, frame):
      raise AlarmException


    def nonBlockingRawInput(prompt='', timeout=2):
    #from Gary Robinson
      signal.signal(signal.SIGALRM, alarmHandler)
      signal.alarm(timeout)
      try:
        text = raw_input(prompt)
        signal.alarm(0)
        return text
      except AlarmException:
        print '',
        #print '\nPrompt timeout. Continuing...'
      signal.signal(signal.SIGALRM, signal.SIG_IGN)
      return ''

    def getradius():
      while True:
        try:
          adist = float(raw_input('Enter Alarm radius in feet:')) 
          break
        except ValueError:
          print 'That is not a valid number.  Please try again.'
      return(adist)

#    sys.stdout = os.fdopen(sys.stdout.fileno(), "w", newline=None)
    while True:
      runcount = runcount + 1
      if osname == "hildon":
        if aset: hildon.hildon_play_system_sound("/usr/share/sounds/ui-general_warning.wav")
    # if iseq > maxiseq: hildon.hildon_play_system_sound("/usr/share/sounds/ui-general_warning.wav")
    # if iseq > maxiseq: hildon.hildon_play_system_sound("/usr/share/sounds/ui-default_beep.wav")
        if iseq > maxiseq: hildon.hildon_play_system_sound("/usr/share/sounds/ui-information_note.wav")
      if osname == "linux":
        #fix these:
        #if aset: pygame.mixer.music.play()
        if aset: alertSound.play()
        #if iseq > maxiseq: pygame.mixer.music.play()
        if iseq > maxiseq: errorSound.play()
     
      if gpsd.fix.mode != 3:
        iseq = iseq + 1
        print 'Invalid gps data',iseq
        icount = icount + 1
      else:
        iseq = 0
        lat = float(gpsd.fix.latitude)
        lon = float(gpsd.fix.longitude)
        speed = gpsd.fix.speed
#          print "Latitude is ",lat," Long is ",lon
        if refset == False:
          reflat = lat
          reflon = lon
          refset = True
        if adistset == False:
          print '\nCenter in decimal degrees is: lat=',lat,' lon=',lon,' with speed=',speed,'m/s'
          adist = getradius()
          adistset = True
        if speed > maxspeed:
          maxspeed = speed
    
        distance = calcDistance(reflat,reflon,lat,lon)
        if distance > mdist: mdist = distance
        if distance > adist: # and gpsd.fix.speed is below a m/s threshold 
          if speed < thresholdspeed:
            acount = acount + 1
            aset = True
        else:
            aset = False
  
      print '\rAlarm=',aset,'Speed/max=',speed,'/',maxspeed,'m/s Feet/max=', int(distance),'/',int(mdist),'Alarm radius=',int(adist),'Alarms=',acount,'Invalid data ratio=',icount,'/',runcount,'      ',
      #print '\rAlarm=',aset,'Speed/max=',speed,'/',maxspeed,'m/s Feet/max=', int(distance),'/',int(mdist),'Alarm radius=',int(adist),'Alarms=',acount,'Invalid data ratio=',icount,'/',runcount,end='' #this print style for python3 and above
      sys.stdout.flush() #just in case
      menu = nonBlockingRawInput('')
     #menu = nonBlockingRawInput('Enter q to quit, or r to change radius:')
      if menu == 'q':
        break
      elif menu == 'r':
        adistset = False
   
    print "\nKilling GPS Monitor Thread..."#normal exit
    gpsp.running = False
    gpsp.join() # wait for the thread to finish what it's doing
 
  except (KeyboardInterrupt, SystemExit): #runs if you press ctrl+c to exit
    print "\nInterrupt Killing GPS Monitor Thread..."
    gpsp.running = False
    gpsp.join() # wait for the thread to finish what it's doing
  print "Done.\nExiting Anchor Watch."

