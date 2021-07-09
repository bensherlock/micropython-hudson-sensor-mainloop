#! /usr/bin/env python
#
# MicroPython MainLoop for HUDSON Sensor Application.
#
# This file is part of micropython-hudson-sensor-mainloop
# https://github.com/bensherlock/micropython-hudson-sensor-mainloop
#
# Standard Interface for MainLoop
# - def run_mainloop() : never returns
#
# MIT License
#
# Copyright (c) 2020 Benjamin Sherlock <benjamin.sherlock@ncl.ac.uk>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
"""MicroPython MainLoop for USMART Sensor Application."""

import pyb
import machine
import utime

from pybd_expansion.main.max3221e import MAX3221E
from pybd_expansion.main.powermodule import PowerModule


from uac_modem.main.unm3driver import MessagePacket, Nm3

from uac_network.main.hudson_sensor_node_network import HudsonSensorNodeNetwork

import jotter

import micropython
micropython.alloc_emergency_exception_buf(100)
# https://docs.micropython.org/en/latest/reference/isr_rules.html#the-emergency-exception-buffer


_env_variables = None

_nm3_callback_flag = False
_nm3_callback_seconds = 0  # used with utime.localtime(_nm3_callback_seconds) to make a timestamp
_nm3_callback_millis = 0  # loops after 12.4 days. pauses during sleep modes.
_nm3_callback_micros = 0  # loops after 17.8 minutes. pauses during sleep modes.


def nm3_callback(line):
    # NB: You cannot do anything that allocates memory in this interrupt handler.
    global _nm3_callback_flag
    global _nm3_callback_seconds
    global _nm3_callback_millis
    global _nm3_callback_micros
    # NM3 Callback function
    _nm3_callback_micros = pyb.micros()
    _nm3_callback_millis = pyb.millis()
    _nm3_callback_seconds = utime.time()
    _nm3_callback_flag = True


def send_usmart_alive_message(modem):
    # Send a standard broadcast Alive message. Usually called on startup and on request by external message.
    # Grab address and voltage from the modem
    if modem:
        nm3_address = modem.get_address()
        utime.sleep_ms(20)
        nm3_voltage = modem.get_battery_voltage()
        utime.sleep_ms(20)
        # print("NM3 Address {:03d} Voltage {:0.2f}V.".format(nm3_address, nm3_voltage))
        # jotter.get_jotter().jot("NM3 Address {:03d} Voltage {:0.2f}V.".format(nm3_address, nm3_voltage),
        #                        source_file=__name__)
        # So here we will broadcast an I'm Alive message. Payload: U (for USMART), A (for Alive), Address, B, Battery
        # Plus a version/date so we can determine if an OTA update has worked
        alive_string = "UA" + "{:03d}".format(nm3_address) + "B{:0.2f}V".format(nm3_voltage) + "REV:2021-07-09T17:38:00"
        modem.send_broadcast_message(alive_string.encode('utf-8'))


# - def set_environment_variables()
def set_environment_variables(env_variables_dict=None):
    """Set a global dictionary of variables."""
    global _env_variables
    _env_variables = env_variables_dict


# Standard Interface for MainLoop
# - def run_mainloop() : never returns
def run_mainloop():
    """Standard Interface for MainLoop. Never returns."""

    global _env_variables
    global _nm3_callback_flag
    global _nm3_callback_seconds
    global _nm3_callback_millis
    global _nm3_callback_micros

    # Firstly Initialise the Watchdog machine.WDT. This cannot now be stopped and *must* be fed.
    wdt = machine.WDT(timeout=30000)  # 30 seconds timeout on the watchdog.

    # Now if anything causes us to crashout from here we will reboot automatically.

    # Last reset cause
    last_reset_cause = "PWRON_RESET"
    if machine.reset_cause() == machine.PWRON_RESET:
        last_reset_cause = "PWRON_RESET"
    elif machine.reset_cause() == machine.HARD_RESET:
        last_reset_cause = "HARD_RESET"
    elif machine.reset_cause() == machine.WDT_RESET:
        last_reset_cause = "WDT_RESET"
    elif machine.reset_cause() == machine.DEEPSLEEP_RESET:
        last_reset_cause = "DEEPSLEEP_RESET"
    elif machine.reset_cause() == machine.SOFT_RESET:
        last_reset_cause = "SOFT_RESET"
    else:
        last_reset_cause = "UNDEFINED_RESET"

    jotter.get_jotter().jot("Reset cause: " + last_reset_cause, source_file=__name__)

    print("last_reset_cause=" + last_reset_cause)


    # Feed the watchdog
    wdt.feed()

    pyb.LED(2).on()  # Green LED On

    jotter.get_jotter().jot("Powering off NM3", source_file=__name__)

    # Cycle the NM3 power supply on the powermodule
    powermodule = PowerModule()
    powermodule.disable_nm3()

    # Enable power supply to 232 driver and sensors and sdcard
    pyb.Pin.board.EN_3V3.on()
    pyb.Pin('Y5', pyb.Pin.OUT, value=0)  # enable Y5 Pin as output
    max3221e = MAX3221E(pyb.Pin.board.Y5)
    max3221e.tx_force_on()  # Enable Tx Driver

    # Set callback for nm3 pin change - line goes high on frame synchronisation
    # make sure it is clear first
    nm3_extint = pyb.ExtInt(pyb.Pin.board.Y3, pyb.ExtInt.IRQ_RISING, pyb.Pin.PULL_DOWN, None)
    nm3_extint = pyb.ExtInt(pyb.Pin.board.Y3, pyb.ExtInt.IRQ_RISING, pyb.Pin.PULL_DOWN, nm3_callback)

    # Serial Port/UART is opened with a 100ms timeout for reading - non-blocking.
    # UART is opened before powering up NM3 to ensure legal state of Tx pin.
    uart = machine.UART(1, 9600, bits=8, parity=None, stop=1, timeout=100)
    nm3_modem = Nm3(input_stream=uart, output_stream=uart)
    utime.sleep_ms(20)

    # Feed the watchdog
    wdt.feed()

    jotter.get_jotter().jot("Powering on NM3", source_file=__name__)

    utime.sleep_ms(10000)
    powermodule.enable_nm3()
    utime.sleep_ms(10000)  # Await end of bootloader

    # Feed the watchdog
    wdt.feed()

    jotter.get_jotter().jot("NM3 running", source_file=__name__)


    # Grab address and voltage from the modem
    nm3_address = nm3_modem.get_address()
    utime.sleep_ms(20)
    nm3_voltage = nm3_modem.get_battery_voltage()
    utime.sleep_ms(20)
    print("NM3 Address {:03d} Voltage {:0.2f}V.".format(nm3_address, nm3_voltage))
    jotter.get_jotter().jot("NM3 Address {:03d} Voltage {:0.2f}V.".format(nm3_address, nm3_voltage),
                            source_file=__name__)


    # Here we will broadcast an I'm Alive message. Payload: U (for USMART), A (for Alive), Address, B, Battery
    send_usmart_alive_message(nm3_modem)



    # Feed the watchdog
    wdt.feed()

    # Delay for transmission of broadcast packet
    utime.sleep_ms(500)


    # Mauro's HUDSON Network Protocol to be created here
    nm3_network = HudsonSensorNodeNetwork()
    nm3_network.init_interfaces(nm3_modem, wdt)  # Provides the modem and watchdog timer to be held by the network module

    utime.sleep_ms(100)

    # Feed the watchdog
    wdt.feed()

    # Uptime
    uptime_start = utime.time()


    # Operating Mode
    #
    # Note: This application only acts in response to incoming acoustic messages.
    # The remainder of the time it will be in lightsleep mode. The modem will remain powered up.
    # The NM3 Flagline on the HW interrupt will wake us up.


    while True:
        try:
            # Feed the watchdog
            wdt.feed()

            # Enable power supply to 232 driver
            pyb.Pin.board.EN_3V3.on()


            # If we're within 30 seconds of the last timestamped NM3 synch arrival then poll for messages.
            if _nm3_callback_flag or (utime.time() < _nm3_callback_seconds + 30):
                if _nm3_callback_flag:
                    print("Has received nm3 synch flag.")

                _nm3_callback_flag = False  # clear the flag

                # There may or may not be a message for us. And it could take up to 0.5s to arrive at the uart.

                nm3_modem.poll_receiver()
                nm3_modem.process_incoming_buffer()

                while nm3_modem.has_received_packet():
                    # print("Has received nm3 message.")
                    print("Has received nm3 message.")
                    jotter.get_jotter().jot("Has received nm3 message.", source_file=__name__)

                    message_packet = nm3_modem.get_received_packet()
                    # Copy the HW triggered timestamps over
                    message_packet.timestamp = utime.localtime(_nm3_callback_seconds)
                    message_packet.timestamp_millis = _nm3_callback_millis
                    message_packet.timestamp_micros = _nm3_callback_micros

                    # Process special packets US
                    if message_packet.packet_payload and bytes(message_packet.packet_payload) == b'USMRT':
                        # print("Reset message received.")
                        jotter.get_jotter().jot("Reset message received.", source_file=__name__)
                        # Reset the device
                        machine.reset()

                    if message_packet.packet_payload and bytes(message_packet.packet_payload) == b'USOTA':
                        # print("OTA message received.")
                        jotter.get_jotter().jot("OTA message received.", source_file=__name__)
                        # Write a special flag file to tell us to OTA on reset
                        try:
                            with open('.USOTA', 'w') as otaflagfile:
                                # otaflagfile.write(latest_version)
                                otaflagfile.close()
                        except Exception as the_exception:
                            jotter.get_jotter().jot_exception(the_exception)

                            import sys
                            sys.print_exception(the_exception)
                            pass

                        # Reset the device
                        machine.reset()

                    if message_packet.packet_payload and bytes(message_packet.packet_payload) == b'USPNG':
                        # print("PNG message received.")
                        jotter.get_jotter().jot("PNG message received.", source_file=__name__)
                        send_usmart_alive_message(nm3_modem)

                    if message_packet.packet_payload and bytes(message_packet.packet_payload) == b'USMOD':
                        # print("MOD message received.")
                        jotter.get_jotter().jot("MOD message received.", source_file=__name__)
                        # Send the installed modules list as single packets with 1 second delay between each -
                        # Only want to be calling this after doing an OTA command and ideally not in the sea.

                        nm3_address = nm3_modem.get_address()

                        if _env_variables and "installedModules" in _env_variables:
                            installed_modules = _env_variables["installedModules"]
                            if installed_modules:
                                for (mod, version) in installed_modules.items():
                                    mod_string = "UM" + "{:03d}".format(nm3_address) + ":" + str(mod) + ":" \
                                                 + str(version if version else "None")
                                    nm3_modem.send_broadcast_message(mod_string.encode('utf-8'))

                                    # delay whilst sending
                                    utime.sleep_ms(1000)

                                    # Feed the watchdog
                                    wdt.feed()

                    # How are HUDSON network messages prefixed to filter from other messages? Is this the '#'?

                    # Send on to submodules: Network/Localisation UN/UL
                    if message_packet.packet_payload and len(message_packet.packet_payload) > 2 and \
                            bytes(message_packet.packet_payload[:1]) == b'#':
                        # Network Packet

                        # Wrap with garbage collection to tidy up memory usage.
                        import gc
                        gc.collect()
                        # Call Mauro's Network Module here and provide the packet
                        nm3_network.handle_packet(message_packet)
                        gc.collect()

                        pass  # End of Network Packets



            # If too long since last synch
            if (not _nm3_callback_flag) and (utime.time() > _nm3_callback_seconds + 30):

                # Double check the flags before powering things off
                if (not _nm3_callback_flag):
                    print("Going to sleep.")
                    jotter.get_jotter().jot("Going to sleep.", source_file=__name__)


                    # Disable the I2C pullups
                    pyb.Pin('PULL_SCL', pyb.Pin.IN)  # disable 5.6kOhm X9/SCL pull-up
                    pyb.Pin('PULL_SDA', pyb.Pin.IN)  # disable 5.6kOhm X10/SDA pull-up
                    # Disable power supply to 232 driver, sensors, and SDCard
                    max3221e.tx_force_off()  # Disable Tx Driver
                    pyb.Pin.board.EN_3V3.off()  # except in dev
                    pyb.LED(2).off()  # Asleep
                    utime.sleep_ms(10)

                while (not _nm3_callback_flag):
                    # Feed the watchdog
                    wdt.feed()
                    # Now wait
                    #utime.sleep_ms(100)
                    # pyb.wfi()  # wait-for-interrupt (can be ours or the system tick every 1ms or anything else)
                    machine.lightsleep()  # lightsleep - don't use the time as this then overrides the RTC

                # Wake-up
                # pyb.LED(2).on()  # Awake
                # Feed the watchdog
                wdt.feed()
                # Enable power supply to 232 driver, sensors, and SDCard
                pyb.Pin.board.EN_3V3.on()
                max3221e.tx_force_on()  # Enable Tx Driver
                # Enable the I2C pullups
                pyb.Pin('PULL_SCL', pyb.Pin.OUT, value=1)  # enable 5.6kOhm X9/SCL pull-up
                pyb.Pin('PULL_SDA', pyb.Pin.OUT, value=1)  # enable 5.6kOhm X10/SDA pull-up

            pass  # end of operating mode

        except Exception as the_exception:
            import sys
            sys.print_exception(the_exception)
            jotter.get_jotter().jot_exception(the_exception)
            pass
            # Log to file

    # end of while True

