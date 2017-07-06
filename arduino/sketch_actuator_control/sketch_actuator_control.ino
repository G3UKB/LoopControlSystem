    /*
* Loop controller incorporating a linear actuator driver and and loop switching.
*
* Control is by UDP commands from a client.
*
* Hardware used:
*  Arduino MEGA 2560
*  Arduino Ethernet Shield
*  Driver - Pololu Dual MC33926 Motor Driver Shield (with provider software)
*  Actuator - GLA750-P 12v 100mm with potentiometer feedback
*  VSWR bridge - SOTABEAMS BOXA-SWR High Performance VSWR Bridge
*  Loop switcher - home built relay switching unit
*/

//////////////////////////////////////////////////////////////////////////
// UDP section
#include <SPI.h>                     // Needed for Arduino versions later than 0018
#include <Ethernet.h>                // Base Ethernet lib
#include <math.h>                    // Math function lib
#include <EthernetUdp.h>             // UDP library from: bjoern@cs.stanford.edu 12/30/2008
#include "DualMC33926MotorShield.h"  // Motor shield library

// MAC address must be specified
byte mac[] = {
  0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED
};
// Local IP address and port
IPAddress ip(192, 168, 1, 177);
// Local port to listen on
unsigned int localPort = 8888;
// Event port for status and events
unsigned int eventPort = 8889;

// Buffers for receiving and sending data
char  packetBuffer[UDP_TX_PACKET_MAX_SIZE]; // Buffer to hold incoming packet,
char  replyBuffer[128];                     // The response data
char  progressBuffer[128];                  // Interim data
char  statusBuffer[128];                    // Interim data
char  vswrBuffer[128];                      // Interim data
char  potBuffer[128];                       // Interim data
char  txBuffer[128];                        // Interim data
char  almBuffer[128];                       // Interim data

// An EthernetUDP instance to let us send and receive packets over UDP
EthernetUDP Udp;

// Create motor driver instance
DualMC33926MotorShield md;

//////////////////////////////////////////////////////////////////////////
// Documentation
/*
Motor driver pin assignments (cannot be changed when used as shield:

  Digital 4 D2 (or nD2) - Tri-state disables both outputs of both motor channels when LOW;
                          toggling resets latched driver fault condition
  Digital 7 M1DIR       - Motor 1 direction input
  Digital 8 M2DIR       - Motor 2 direction input
  Digital 9 M1PWM       - Motor 1 speed input
  Digital 10 M2PWM      - Motor 2 speed input
  Digital 12 SF (or nSF)- Status flag indicator (LOW indicates fault)
  Analog 0 M1FB         - Motor 1 current sense output (approx. 525 mV/A)
  Analog 1 M2FB         - Motor 2 current sense output (approx. 525 mV/A)

Interface:
  DualMC33926MotorShield()
  DualMC33926MotorShield(unsigned char M1DIR, unsigned char M1PWM, unsigned char M1FB, 
  unsigned char M2DIR, unsigned char M2PWM, unsigned char M2FB, unsigned char nD2, unsigned char nSF)
  void init()
  void setM1Speed(int speed)
  void setM2Speed(int speed)
  void setSpeeds(int m1Speed, int m2Speed)
  unsigned int getM1CurrentMilliamps()
  unsigned int getM2CurrentMilliamps()
  unsigned char getFault()

NOTE: Do not use analog pins < 6 as these appear to be used or compromised in some way by the motor driver.

Potentiometer
  Analog 8              - Position feedback
  
SWR fwd and rev analogue inputs
  Analog 9              - Forward power
  Analog 10             - Reverse power

Loop switching
  Digital 22            - Relay 1
  Digital 23            - Relay 2
  Digital 24            - Relay 3
  Digital 25            - Relay 4

Notes:
  1. If not using the SWR analog inputs then tie these to 0v otherwise they will float giving random values.
  2. Connect the potentiometer such that at full retraction the wiper is close to 0v potential. The two ends
  of the potentiometer should be connected to VDD and Gnd.
  3. The software allows for an external analog reference connected to the AREF pin. The default is to use VDD
  which must be completely stable, otherwise use an external 5v fed through a 5K resistor (see Arduino documentation
  for AnalogReference()).
  4. The presence of RF can cause noise on the analog pins, giving an unstable reading. To prevent this decouple
  each used analog pin with a 0.1uF disc ceramic as close to the pin as practical.
  5. Keep digital and analog GND wires separate using the GND pin next to the analog pins as the analog ground and
  the GND pin nearest the digital pins for the digital ground.
*/

//////////////////////////////////////////////////////////////////////////
// Motor
// Pre-allocated pin bindings by virtue of the shield (most can be reallocated by constructor)

// General motor control
const int MAX_SPEED_VALUE = 400;        // Defined by the library -400 0 +400
const int MINIMUM_SPEED_VALUE = 100;    // Motor may stall if we go slower
const int FAST_TUNE_SPEED_VALUE = 300;  // Move to lower setpoint at this speed
const int SLOW_TUNE_SPEED_VALUE = MINIMUM_SPEED_VALUE;
const int MAX_EXTENSION = 100;          // mm full extension
const int MAX_MM_SEC = 10;              // speed mm/sec at full RPM

const int MOTOR_STOP = 0;
const int FORWARD = 0;
const int REVERSE = 1;
int motorDirection = FORWARD;
int motorSpeed = 400;                 // The actual speed (+ve forward, -ve reverse)
int speedSetting = 400;               // The speed setting from the host (always +ve)

//////////////////////////////////////////////////////////////////////////
// Potentiometer
// This is a high precision potentiometer attached to the drive output shaft.
// The linear actuator has limit switches which stop the motor at each end of travel.
// We measure the extension as % of full travel. Minimum travel is fully unmeshed
// capacitor and maximum travel is fully meshed capacitor. However the analog values
// may not be 0 - 1023 so we calibrate 0% and 100% and make them just short of the
// limits of travel as we don't want to hit the end stops which are for fail-safety.
const int MIN_EXTENSION_VALUE = 0;        // Full retraction
const int MAX_EXTENSION_VALUE = 100;      // Full extension
const int MAX_ANALOG_VALUE = 1023;        // Max analog value 0-1023

//////////////////////////////////////////////////////////////////////////
// General running state
bool isRunning = false;

//////////////////////////////////////////////////////////////////////////
// Auto tuning
bool autoTune = false;
const int MAX_AUTOTUNE_TRIES = 10;
int autotuneFailCount = 0;

//////////////////////////////////////////////////////////////////////////
// Setpoints for low/high frequency for current loop
// Note that these are provided by the host with some leeway either side
int lowSetpoint = MAX_EXTENSION_VALUE;
int highSetpoint = MIN_EXTENSION_VALUE;

// Conversion constants
const bool REAL_TO_VIRTUAL = true;
const bool VIRTUAL_TO_REAL = false;

//////////////////////////////////////////////////////////////////////////
// Setpoints for min/max capacitance in % extension
// These are derived from the analog voltage from the potentiometer wiper
// Note that these ae provided by the host from our position events
int minCapSetpoint = 10;    // Defaults clear of end stops
int maxCapSetpoint = 1013;  //  ""

//////////////////////////////////////////////////////////////////////////
// Loop iteration delay
const int MAIN_LOOP_SLEEP = 10;          // 10ms sleep in main loop
const int MAIN_LOOP_COUNT = 20;
int mainLoopCounter = MAIN_LOOP_COUNT;   // Extra tasks every 200ms
const int EX_LOOP_SLEEP = 5;             // 5ms sleep in command execution loops
const int MOTOR_DELAY = 100;             // 100ms sleep between motor commands

// Execution loop timeout, dependent on the motor speed as timeouts must allow a full extension or retraction
double msFullExtensionOrRetraction = (((double)MAX_EXTENSION/(double)MAX_MM_SEC) * ((double)MAX_SPEED_VALUE)/abs((double)speedSetting))*1000.0;
int COMMAND_TIMEOUT = (int)((msFullExtensionOrRetraction*2.0 )/(double)EX_LOOP_SLEEP);  // speed dependent imeout

//////////////////////////////////////////////////////////////////////////
// Potentiometer
// Analog pin allications
const int potPin = 8;
bool potFirstRun = true;  // Fill her up
int potArray[10];
int potIndex = 0;

//////////////////////////////////////////////////////////////////////////
// SWR meter
// Analog pin allocation
const int fwdPin = 9;
const int refPin = 10;

//////////////////////////////////////////////////////////////////////////
// Antenna switcher
// Digital pin allocation
const int rly1Pin = 22;
const int rly2Pin = 23;
const int rly3Pin = 24;
const int rly4Pin = 25;

//////////////////////////////////////////////////////////////////////////
// Called on startup
void setup() {
  
  // Configure serial monitor
  Serial.begin(115200);
  Serial.println("Loop Controller Mk2");
  
  // Set up the motor shield
  md.init();
  
  // Configure the analog pins
  pinMode(potPin, INPUT);
  pinMode(fwdPin, INPUT);
  pinMode(refPin, INPUT);
  
  // Configure the relays for loop switching
  pinMode(rly1Pin, OUTPUT);
  digitalWrite(rly1Pin, LOW);
  pinMode(rly2Pin, OUTPUT);
  digitalWrite(rly2Pin, LOW);
  pinMode(rly3Pin, OUTPUT);
  digitalWrite(rly3Pin, LOW);
  pinMode(rly4Pin, OUTPUT);
  digitalWrite(rly4Pin, LOW); 

  // Start Ethernet and UDP:
  Ethernet.begin(mac, ip);
  Udp.begin(localPort);
}

//////////////////////////////////////////////////////////////////////////
// Called repeatedly to execute main code
void loop() {
  
  // Check and accept messages from UDP
  int packetSize = queryPacket();
  // If there's data available...
  // Note this is synchronous from Arduino point of view
  if (packetSize) {
    // Read the packet
    doRead(packetSize);   
    // Execute the command
    execute(packetBuffer);
    // Send response which is sent to the requesting ip and port
    sendResponse();
  } else {
    // Wait MAIN_LOOP_SLEEP ms to avoid spinning too fast
    delay(MAIN_LOOP_SLEEP);
  }
  
  if (isRunning) {
    // Check for time to send event data
    if (mainLoopCounter-- <= 0) {
      mainLoopCounter = MAIN_LOOP_COUNT;
      // Send an SWR event if transmitting
      if (analogRead(fwdPin) > 0) {
        // Must be transmitting
        sendTX(true);
        sendVSWR(analogRead(fwdPin), analogRead(refPin));
      } else {
        sendTX(false);
      }
      
      // Send the % extension
      sendPotEvent();
    }
   
    // Check for auto-tune
    float vswr;
    float fwd;
    float ref;
    if (autoTune) {
      fwd = analogRead(fwdPin);
      ref = analogRead(refPin);
      if (fwd > 0) {
        // Transmitting
        if (getVSWR() > 1.7) {
          // See if we can do better than 1.7:1
          if (!doTune()) {
            // If we fail to find a good SWR we would keep trying ad-infinitum
            if (autotuneFailCount++ >= MAX_AUTOTUNE_TRIES) {
              sendAlarm("autotune failure");
              autoTune = false;
              autotuneFailCount = MAX_AUTOTUNE_TRIES;
            }
          } else {
            autotuneFailCount = MAX_AUTOTUNE_TRIES;
          }
        }
      }
    }
  } 
}

//////////////////////////////////////////////////////////////////////////
// Basic UDP procs
int queryPacket() {
  
  int packetSize = Udp.parsePacket();
  if (packetSize)
    return packetSize;
   else
     return 0;
}

////////////////////////////////////////
int doRead(int packetSize) {
  
  // Read the packet into packetBufffer
  Udp.read(packetBuffer, UDP_TX_PACKET_MAX_SIZE);
  // Terminate buffer
  packetBuffer[packetSize] = '\0'; 
}

////////////////////////////////////////
int sendResponse() {

  // Send a reply to the IP address and port that sent us the packet we received
  Udp.beginPacket(Udp.remoteIP(), Udp.remotePort());
  Udp.write(replyBuffer);
  Udp.endPacket();   
}

//////////////////////////////////////////////////////////////////////////
// UDP events
int sendProgress(int percentToMove, int percentRemaining) {

  // Send a progress report to the remote IP and event port
  if(percentRemaining%10 == 0) {
    int percentComplete = int(((double)percentRemaining/(double)percentToMove)*100.0);
    strcpy(progressBuffer, "progress:");
    itoa(percentComplete,progressBuffer + strlen(progressBuffer),10);
    Udp.beginPacket(Udp.remoteIP(), eventPort);    
    Udp.write(progressBuffer);
    Udp.endPacket();
  }   
}

////////////////////////////////////////
int sendVSWR(double forward, double reflected) {

  // Send a VSWR report to the remote IP and event port
  char fwdbuff[8];
  char revbuff[8];
  strcpy(vswrBuffer, "vswr:");
  // Note the standard lib sprintf does not support float
  dtostrf(forward,5,2,fwdbuff);
  dtostrf(reflected,5,2,revbuff);
  strcpy(vswrBuffer + strlen(vswrBuffer), fwdbuff);
  strcpy(vswrBuffer + strlen(vswrBuffer), ":");
  strcpy(vswrBuffer + strlen(vswrBuffer), revbuff);
  Udp.beginPacket(Udp.remoteIP(), eventPort);    
  Udp.write(vswrBuffer);
  Udp.endPacket();  
}

////////////////////////////////////////
int sendPot(int rawValue, float percentExtension) {
  
  // Send a Potentiometer report to the remote IP and event port
  char extbuff[8];
  dtostrf(percentExtension,5,1,extbuff);
  //int extension = (int)round(percentExtension);
  strcpy(potBuffer, "pot:");
  itoa(rawValue, potBuffer + strlen(potBuffer),10);
  strcpy(potBuffer + strlen(potBuffer), ":");
  //itoa(extension, potBuffer + strlen(potBuffer),10);
  strcpy(potBuffer + strlen(potBuffer), extbuff);
  Udp.beginPacket(Udp.remoteIP(), eventPort);    
  Udp.write(potBuffer);
  Udp.endPacket();    
}

int sendTX(bool is_tx) {

  // Send a TX status
  if (is_tx)
     strcpy(txBuffer, "tx:on");
   else
     strcpy(txBuffer, "tx:off");
  Udp.beginPacket(Udp.remoteIP(), eventPort);    
  Udp.write(txBuffer);
  Udp.endPacket();  
}

int sendAlarm(char *msg) {

  // Send an alarm to the remote IP and event port
  strcpy(almBuffer, "alarm:");
  strcpy(almBuffer + strlen(almBuffer), msg);
  Udp.beginPacket(Udp.remoteIP(), eventPort);    
  Udp.write(almBuffer);
  Udp.endPacket();  
}

//////////////////////////////////////////////////////////////////////////
// API for commands
void execute(char *command) {
  
  /*
  * The command set is as follows. Commands are terminated strings.
  * Ping                   - "ping"              -  connectivity test
  * Set analog ref def     - "refdefault"        -  set analog reference to default (vdd)
  * Set analog ref ext     - "refexternal"       -  set analog reference to external, via AREF pin
  * Is TX                  - "istx"              -  TX state
  * Set speed              - "[n][nn]s"          -  set the nominal motor speed, although some commands will set their own speed
  * Stop                   - "stop"              -  stop motor
  * Move to %              - "[n][nn]m"          -  move to the given % setting
  * Move to value          - "[n][nn]n"          -  move to the given analog value
  * Nudge forwards         - "[n][nn]f"          -  nudge forwards by analog value
  * Nudge reverse          - "[n][nn]r"          -  nudge reverse by analog value
  * Set freq low           - "[n][nn]l"          -  % absolute for low frequency setpoint for this loop
  * Set freq high          - "[n][nn]h"          -  % absolute for high frequency setpoint for this loop
  * Set cap max            - "[n][nn]x"          -  analog value of pot setting for maximum capacity
  * Set cap min            - "[n][nn]y"          -  analog value of pot setting for minimum capacity
  * Tune                   - "tune"              -  tune for minimum SWR
  * Auto-tune on           - "autotuneon"        -  autotune on, tune for minimum SWR as necessary when TX
  * Auto-tune off          - "autotuneoff"       -  turn autotune off
  * Relay energise         - "[n]e"              -  energise relay n 1-8
  * Relay de-energise      - "[n]d"              -  de_energise relay n 1-8
  */ 
  
  char *p;
  int value = 0;
  bool forward = true;
   
  // Assume success
  strcpy(replyBuffer, "success");
  if (strcmp(command, "ping") == 0) {
    // Nothing to do, just a connectivity check
    ;
  } else if (strcmp(command, "refdefault") == 0) {
    analogReference(DEFAULT);
    isRunning = true;
  } else if (strcmp(command, "refexternal") == 0) {
    analogReference(EXTERNAL);
    isRunning = true;
  } else if (strcmp(command, "istx") == 0) {
    if (isRunning) {
      if (analogRead(fwdPin) > 0.0) {
        strcpy(replyBuffer, "tx:on");
      } else {
        strcpy(replyBuffer, "tx:off");
      }
    } else {
      strcpy(replyBuffer, "tx:off");
    }
  } else if (strcmp(command, "stop") == 0) {
    doStop();
  } else if  (strcmp(command, "tune") == 0) {
    doTune();
  } else if  (strcmp(command, "autotuneon") == 0) {
    autoTune = true;
  } else if  (strcmp(command, "autotuneoff") == 0) {
    autoTune = false;
  } else {
    // A speed/ move/ relay/ low,high setpoint command?
    for(p=command; *p; p++) {
      if(*p == 0x2B){
        // '+' sign value
        forward = true;
      } else if(*p == 0x2D){
        // '-' sign value
        forward = false;        
      } else if(*p >= '0' && *p <= '9') {
        // Numeric entered, so accumulate numeric value
        value = value*10 + *p - '0';
      } else if(*p == 's') {
        // Instructed to change speed
        if(value > 0 && value <= MAX_SPEED_VALUE)
          setSpeed(value);
        break;
      } else if(*p == 'm') {
        // Instructed to move to n extension
        if(value >= 0 && value <= MAX_EXTENSION_VALUE) {
          doMove(value, speedSetting, true);
        }
        break;
      } else if(*p == 'n') {
        // Instructed to move to n analog value
        if(value >= 0 && value <= MAX_ANALOG_VALUE) {
          doMove(value, speedSetting, false);
        }
        break;
      } else if(*p == 'l') {
        // Instructed to set low setpoint
        if(value >= 0 && value <= MAX_EXTENSION_VALUE)
          setLowSetpoint(value);
        break;
      } else if(*p == 'h') {
        // Instructed to set high setpoint
        if(value >= 0 && value <= MAX_EXTENSION_VALUE)
          setHighSetpoint(value);
        break;
      } else if(*p == 'f') {
        // Instructed to nudge forwards
        if(value > 0 && value < 50)
          doNudge(true, value);
        break;
      } else if(*p == 'r') {
        // Instructed to nudge reverse
        if(value > 0 && value < 50)
          doNudge(false, value);
        break;
      } else if(*p == 'x') {
        // Instructed to set max capacitance setpoint
        setMaxCapSetpoint(value);
        break;
      } else if(*p == 'y') {
        // Instructed to set min capacitance setpoint
        setMinCapSetpoint(value);
        break;
      } else if(*p == 'e') {
        // Instructed to energise relay n
        if(value >= 0)
          doRelay(value, true);
        break;
      } else if(*p == 'd') {
        // Instructed to de-energise relay n
        if(value >= 0)
          doRelay(value, false);
        break;
      } else {
         // Invalid command
         strcpy(replyBuffer, "failure:Invalid command");
         break;
      } 
    }
  }
}

////////////////////////////////////////
void setSpeed(int value) {
  
  /*
  * Change speed
  */
  
  speedSetting = value;
  if (motorDirection == FORWARD) {
    motorSpeed = value;
  } else {
    motorSpeed = -value;
  }
  
  // Recalculate the command timeout value
  msFullExtensionOrRetraction = (((double)MAX_EXTENSION/(double)MAX_MM_SEC) * ((double)MAX_SPEED_VALUE)/abs((double)speedSetting))*1000.0;
  COMMAND_TIMEOUT = (int)((msFullExtensionOrRetraction*2.0 )/(double)EX_LOOP_SLEEP);  // speed dependent imeout
}
    
////////////////////////////////////////
void doStop() {
  
  /*
  * Stop Rotation
  */
  
  md.setM1Speed(MOTOR_STOP);
  stopIfFault();
}

////////////////////////////////////////
void doMove(int extensionOrRaw, int nspeed, bool extension) {
  
  /*
  * Move to the given virtual % extension using the pot feedback
  *
  *  extensionOrRaw = normalised extension % ot raw analog value of pot
  *  speed = suggested speed
  *  extension = true if extension else raw
  */

  if (extension) {
    return doMoveExtension(extensionOrRaw, nspeed);
  } else {
    return doMoveRaw(extensionOrRaw, nspeed);
  }
}

////////////////////////////////////////
void doMoveExtension(int extension, int nspeed) {
  
  bool lforward = true;
  int timeout = COMMAND_TIMEOUT;
 
  // Get the current extension
  // The host works in integer % values
  // For positioning we work in float as 1% is 8 in analog value (assuming a range 100-900).
  // We want to hit the exact same spot every time and not be up to analog 8 different in position.
  // For even better accuracy the host may need to work in float as well.
  
  float reqdExtension = (float)extension;
  float currentExtension = getExtension();
  float percentToMove = abs(currentExtension - (float)extension);
  if (reqdExtension >= (currentExtension - 1.0) && extension <= (currentExtension + 1.0))
    // Close to target +- 1%
    return;
  else if (reqdExtension > currentExtension - 1.0) {
    // Need to extend further
    // This equates to a move forward
    // Pot increases analog voltage in extend (forward) direction
    md.setM1Speed(nspeed);
    stopIfFault();
    lforward = true;
  } else {
    // Need to contract
    // This equates to a move reverse
    // Pot decreases analog voltage in a contract (reverse) direction
    md.setM1Speed(-nspeed);
    stopIfFault();
    lforward = false;
  }
  while (true) {
    delay(EX_LOOP_SLEEP);
    currentExtension = getExtension();
    // Every 100ms: 
    //  Send the current heading
    //  Send a progress report
    //  Check for a new command, we might get a stop if still tuning
    if ((timeout%100) == 0) { 
      sendPotEvent();
      sendProgress(percentToMove, abs((int)currentExtension - extension));
      if (checkForStop()) break;
    }
    if (timeout-- <= 0) {
      strcpy(replyBuffer, "failure:Timeout when executing doMove");
      break;
    }
      
    if (currentExtension >= (reqdExtension - 1.0) && currentExtension <= (reqdExtension + 1.0)) {
      // Close to target +- 1%
       break;
    }
  }
  // Arrived close to or broken so stop motor
  doStop();
  
  // See if we need a final tweak
  float diff;
  int tries = 5;
  while (true) {
    currentExtension = getExtension();
    diff = currentExtension - reqdExtension;
    if ((diff >= -0.5) && (diff <= 0.5)) {
      // Probably can't do much better
      break;
    } else if (diff > 0.0) {
      // Need to move backwards a tad
      doNudge(false, 2);
    } else {
      // Need to move forwards a tad
      doNudge(true, 2);
    }
    if (--tries < 0) {
       // Have to give up and hope its close enough 
       break;
    }
    delay(MOTOR_DELAY);
  }
  sendPotEvent(); 
}

////////////////////////////////////////
void doMoveRaw(int raw, int nspeed) {
  
  bool lforward = true;
  int timeout = COMMAND_TIMEOUT;
 
  // Get the current extension
  // The host works in integer % values
  // However, for better accuracy when operting without a user we can use the raw value
  
  int currentRaw = getPotValue();
  int rawToMove = abs(currentRaw - raw);
  if (raw >= (currentRaw - 8) && raw <= (currentRaw + 8))
    // Close to target +-8 == +-1%
    return;
  else if (raw > currentRaw - 8) {
    // Need to extend further
    // This equates to a move forward
    // Pot increases analog voltage in extend (forward) direction
    md.setM1Speed(nspeed);
    stopIfFault();
    lforward = true;
  } else {
    // Need to contract
    // This equates to a move reverse
    // Pot decreases analog voltage in a contract (reverse) direction
    md.setM1Speed(-nspeed);
    stopIfFault();
    lforward = false;
  }
  while (true) {
    delay(EX_LOOP_SLEEP);
    currentRaw = getPotValue();
    // Every 100ms: 
    //  Send the current heading
    //  Send a progress report
    //  Check for a new command, we might get a stop if still tuning
    if ((timeout%100) == 0) { 
      sendPotEvent();
      sendProgress(rawToMove, abs((int)currentRaw - raw));
      if (checkForStop()) break;
    }
    if (timeout-- <= 0) {
      strcpy(replyBuffer, "failure:Timeout when executing doMove");
      break;
    }
      
    if (currentRaw >= (raw - 8) && currentRaw <= (raw + 8)) {
      // Close to target +-8 == +-1%
       break;
    }
  }
  // Arrived close to or broken so stop motor
  doStop();
  
  // See if we need a final tweak
  float diff;
  int tries = 5;
  while (true) {
    currentRaw = getPotValue();
    diff = currentRaw - raw;
    if ((diff >= -2) && (diff <= 2)) {
      // Probably can't do much better
      break;
    } else if (diff > 0) {
      // Need to move backwards a tad
      doNudge(false, 2);
    } else {
      // Need to move forwards a tad
      doNudge(true, 2);
    }
    if (--tries < 0) {
       // Have to give up and hope its close enough 
       break;
    }
    delay(MOTOR_DELAY);
  }
  sendPotEvent(); 
}

////////////////////////////////////////
void doNudge(bool forwards, int value) {
  
  /*
  * Nudge forward/reverse by the given analog value
  */
  float currentRaw = getPotValue();
  float requiredRaw;
  if (forwards) {
    // Need to move forwards a tad
    md.setM1Speed(MINIMUM_SPEED_VALUE);
    stopIfFault();
    requiredRaw = currentRaw + value;
  } else {
    // Need to move backwards a tad
    md.setM1Speed(-MINIMUM_SPEED_VALUE);
    stopIfFault();
    requiredRaw = currentRaw - value;
  }
  
  int count = 5; 
  while (true) {
    // Give motor 100ms run time
    delay(100);
    doStop();
    // Allow to settle
    delay(100);
    if (count-- <= 0) {
      break;
    }
    if ((getPotValue() >= requiredRaw - 1) && (getPotValue() <= requiredRaw + 1)) {
      // Close enough
      break;
    } else if (getPotValue() < requiredRaw) {
      // Go forward a bit more
      md.setM1Speed(MINIMUM_SPEED_VALUE);
      stopIfFault();
    } else {
      // Go reverse a bit more
      md.setM1Speed(-MINIMUM_SPEED_VALUE);
      stopIfFault();
    }   
  }
  sendPotEvent();
}
 
////////////////////////////////////////
void setLowSetpoint(int extension) {
  
  /*
  Absolute extension for the low frequency for the current loop
  */
  
  lowSetpoint = extension;
}

////////////////////////////////////////
void setHighSetpoint(int extension) {
  
  /*
  Absolute extension for the high frequency for the current loop
  */
  
  highSetpoint = extension;
}

////////////////////////////////////////
void setMaxCapSetpoint(int extension) {
  
  /*
  Analog value of pot setting for the maximum capacitance
  */
  
  maxCapSetpoint = extension;
}

////////////////////////////////////////
void setMinCapSetpoint(int extension) {
  
  /*
  Analog value of pot setting for the minimum capacitance
  */
  
  minCapSetpoint = extension;
}

////////////////////////////////////////
bool doTune() {
  
  /*
  * Tune for lowest SWR
  * We know the low and high setpoints for this loop:
  *  1. Move to low setpoint at a reasonable speed.
  *  2. Move from the low setpoint checking SWR.
  *  3. If SWR reaches a good minimum value stop.
  *  4. If SWR does not come down then stop at high setpoint.
  *
  * Note: lowSetpoint and highSetpoint are virtual percent extension
  */
  
  const int MOVE_FORWARDS = 0;
  const int MOVE_REVERSE = 1;
  float ref, refMin = -1.0;
  float vswr;
  bool moveDirection;
  int target;
  float extension = 0.0;
  bool success = false;
  int timeout;
  
  // Check TX
  if (analogRead(fwdPin) == 0.0) {
    // Need some RF!
    strcpy(replyBuffer, "failure:No RF detected!");
    return success;
  }
  
  // Check setpoints
  // The low frequency will require more capacitance so must be set as a higher extension setting.
  // The high frequency will then be a lower extension setting. That is, reverse from the low frequency setting.
  if (highSetpoint >= lowSetpoint) {
    // Wrong way around
    strcpy(replyBuffer, "failure:Setpoints are reversed!");
    return success;
  }
  
  // Move to the closest setpoint as a start point for tuning
  // Recalculate the command timeout value
  msFullExtensionOrRetraction = (((double)MAX_EXTENSION/(double)MAX_MM_SEC) * ((double)MAX_SPEED_VALUE)/abs((double)FAST_TUNE_SPEED_VALUE))*1000.0;
  COMMAND_TIMEOUT = (int)((msFullExtensionOrRetraction*2.0 )/(double)EX_LOOP_SLEEP);  // speed dependent imeout
  if (getExtension() > lowSetpoint) {
    // Move to the low setpoint
    doMove(lowSetpoint, FAST_TUNE_SPEED_VALUE, true);
    // Move reverse from here
    moveDirection = MOVE_REVERSE;
  } else {
    doMove(highSetpoint, FAST_TUNE_SPEED_VALUE, true);
    // Move forward from here
    moveDirection = MOVE_FORWARDS;
  }
  
  // Now move from the current setpoint to the far setpoint giving fwd and ref feedback
  // We check the reflected value and stop when we reach a good value
  // Recalculate the command timeout value
  msFullExtensionOrRetraction = (((double)MAX_EXTENSION/(double)MAX_MM_SEC) * ((double)MAX_SPEED_VALUE)/abs((double)SLOW_TUNE_SPEED_VALUE))*1000.0;
  timeout = (int)((msFullExtensionOrRetraction*2.0 )/(double)EX_LOOP_SLEEP);  // speed dependent imeout
  if (moveDirection == MOVE_FORWARDS) {
    md.setM1Speed(SLOW_TUNE_SPEED_VALUE);
  } else {
    md.setM1Speed(-SLOW_TUNE_SPEED_VALUE);
  }  
  stopIfFault();
  
  // Compare virtual extensions
  while(true) {
    
    if (((moveDirection == MOVE_FORWARDS) && (getExtension() > lowSetpoint)) || ((moveDirection == MOVE_REVERSE) && (getExtension() < highSetpoint))) {
      // Reached other end of freq zone without a good match so leave it at that
      break;
    }
    
    // Get the current reflected value
    ref = analogRead(refPin);
    
    if (ref == 0.0) {
      // We have 1:1
      // Get new real extension
      success = true;
      extension = getExtension();
      break;
    }
      
    if (refMin == -1.0) {
      // First time through
      refMin = ref;
      vswr = getVSWR();
    } else {    
      if (ref < refMin) {
        // Going in right direction
        // Remember new minimum
        refMin = ref;
        vswr = getVSWR();
        if (vswr < 1.7) {
          // Good enough, so do tail end processing
          success = true;
          break;
        }
        // Get new VSWR minimum real extension
        extension = getExtension();
      } else if (ref > refMin+20) {
        success = true;
        // Going up so do tail end processing
        break;
      }
    }
    // Every 100ms: 
    //  Send the pot readings
    //  Send the current VSWR
    //  Send a progress report
    //  Check for a new command, in particular we might get a stop
    if ((timeout%100) == 0) {
      sendPotEvent();
      sendVSWR(analogRead(fwdPin), analogRead(refPin));     
      sendProgress(lowSetpoint - highSetpoint , normalisePotValue(getExtension(), REAL_TO_VIRTUAL) - highSetpoint);      
      if (checkForStop()) {
        break;
      }
    }
    // See if we exceeded a reasonable time for a revolution so we don't get stuck 
    // if for example the motor is not moving.
    if (timeout-- <= 0) {
      strcpy(replyBuffer, "failure:Timeout when executing tune");
      break;
    }
    // Wait LOOP_SLEEP ms so we don't spin too fast. Also timeout takes account of this delay.
    delay(EX_LOOP_SLEEP);
  }
 
  // Stop the motor
  doStop();
  
  // Tail end processing
  if (success) {
    int ref1, ref2;
    // We went through a minimum, so at least it is tuning
    // See if we can improve the VSWR
    if (getVSWR() > 1.7) {
      // Room for improvement
      while (true) {
        ref1 = analogRead(refPin);
        // Try moving forward a tad
        doNudge(true, 2);
        ref2 = analogRead(refPin);
        if (ref2 < ref1) {
          // Improved a bit
          break;
        } else {
          ref1 = analogRead(refPin);
          // Try moving backwards a tad
          doNudge(false, 2);
          ref2 = analogRead(refPin);
          if (ref2 < ref1) {
            // Improved a bit
            break;
          }
        }
        delay(MOTOR_DELAY);
      }
    }
  } else {
    strcpy(replyBuffer, "failure:Reached end of search or aborted!");
  }
  
  // Then send the final results
  sendPotEvent();
  sendVSWR(analogRead(fwdPin), analogRead(refPin));     
  sendProgress(lowSetpoint - highSetpoint, 0);
  
  // Reset the command timeout value
  msFullExtensionOrRetraction = (((double)MAX_EXTENSION/(double)MAX_MM_SEC) * ((double)MAX_SPEED_VALUE)/abs((double)speedSetting))*1000.0;
  COMMAND_TIMEOUT = (int)((msFullExtensionOrRetraction*2.0 )/(double)EX_LOOP_SLEEP);  // speed dependent imeout
  
  return success; 
}

////////////////////////////////////////
void doRelay(int value, boolean energise) {
  // (De)energise relay
  
  int mode;
  if (energise)
    mode = HIGH;
  else
    mode = LOW;
    
  switch (value) {
    case 1:
      digitalWrite(rly1Pin, mode);
    case 2:
      digitalWrite(rly2Pin, mode);
    case 3:
      digitalWrite(rly3Pin, mode);
    case 4:
      digitalWrite(rly4Pin, mode);
  }
}

//////////////////////////////////////////////////////////////////////////
// Utility routines
// Check for motor malfunction
bool stopIfFault() {
  if (md.getFault())
  {
    strcpy(replyBuffer, "failure:Motor fault");
    doStop();
    return false;
  }
  return true;
}

////////////////////////////////////////
// Interim command check for a stop command
boolean checkForStop() {
  int packetSize = queryPacket();
  // If there's data available, read and execute
  if (packetSize) {
    // Read
    doRead(packetSize); 
    if (strcmp(packetBuffer, "stop") == 0)
      return true;
  }  
  return false;
}

////////////////////////////////////////
// Set motor running at given speed
void startMotor(int value) {
  
  /*
  * Change speed
  */
  
  if (motorDirection == FORWARD) {
    motorSpeed = value;
  } else {
    motorSpeed = -value;
  }
  md.setM1Speed(motorSpeed);
  stopIfFault();
}

////////////////////////////////////////
// Get VSWR
float getVSWR() {
  
  float fwd = analogRead(fwdPin);
  float ref = analogRead(refPin);
  if ((fwd - ref) > 0.0) {
    return ((fwd + ref)/(fwd - ref));
  } else {
    return 0.0;
  }
}
       
          
////////////////////////////////////////
// Get current potentiometer analog value
int getPotValue() {
  
  /*
  * Get the current potentiometer reading
  */
  
  // Averaging causes more issues than not
  return analogRead(potPin);
  
  /*
  int i;
  int arraySum = 0;
  
  if (potFirstRun) {
    potFirstRun = false;
    // Do 10 readings to fill up the array
    for(i=0;i<10;i++) {
     potArray[i] = analogRead(potPin);
    }    
   } else {
    potArray[potIndex++] = analogRead(potPin);
    if (potIndex > 9)
      potIndex = 0;
   } 

  for(i=0;i<10;i++) {
    arraySum = arraySum + potArray[i];    
  }
  return arraySum/10;
  */
}

////////////////////////////////////////
// Send the current real and virtual values
void sendPotEvent() {
  
  /*
  * Send the current real and virtual values
  */
  sendPot(getPotValue(), getExtension());
}

////////////////////////////////////////
// Get the current extension
float getExtension() {
  
  /*
  * Get the virtual extension
  */
  return normalisePotValue(getPotValue(), REAL_TO_VIRTUAL);
}

////////////////////////////////////////
// Normalise pot value to an extension %
float normalisePotValue(int value, bool real_to_virtual) {
 
 // The host deals in 0 - 100 % extension which is fully unmeshed to fully meshed
 // i.e min to max capacitance. This muat be mapped to the actual values for min 
 // and max which have been configured.
 // The potentiometer reading is 0 - 1023 but we may not hit zero or maximum resistance.
 //
 // Real (say 0 - 500 analog value) to virtual (0-100 ext) = (value - minCapSetpoint) * (100/(maxCapSetpoint - minCapSetpoint))
 // Virtual (0-100 ext) to analog value = extension * (((maxCapSetpoint - minCapSetpoint)/100) + minCapSetpoint)
 
 
 if (real_to_virtual) {
   // Given an actual reading map it 0-100 % extension
   return ((float)value - (float)minCapSetpoint) * (100.0/((float)maxCapSetpoint - (float)minCapSetpoint));
 } else {
   // Given a virtual reading map it to a real % extension
   return ((float)value * (((float)maxCapSetpoint) - (float)minCapSetpoint)/100.0) + (float)minCapSetpoint;
 }
}
  
