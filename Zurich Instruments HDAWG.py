#   @title      Zurich Instruments HDAWG instrument driver
#   @author     Christian Križan
#   @contrib    Andreas Bengtsson, Simon Gustavsson, Christopher Warren
#   @date       2020-09-14
#   @version    v0.835.1
#   @other      The author of this driver takes no responsibility for
#               any and all bugs and frustration caused by Labber and/or
#               affiliated Zurich Instruments hardware and software.
#               Correspondence should be with the author.
#

#######################################################
""" Labber driver for the Zurich Instruments HDAWG. """
#######################################################

# Python rudimentaries
from __future__ import print_function
from BaseDriver import LabberDriver, Error, IdError
from datetime   import datetime

import glob
import inspect
import numpy as np
import os
import psutil
import re
import shutil
import textwrap
import time

# Zurich Instruments functionality
import zhinst.ziPython as ziPython
import zhinst.utils as ziUtils

# Main Labber driver class
class Driver(LabberDriver):
    
    '''This class implements a Labber driver.

    In order to establish a connection to the HDAWG instrument, please select
    the Zurich Instruments HDAWG driver in the 'Add instruments' dialogue.
    Select USB or TCPIP in the interface list, followed by providing the
    device serial. The serial is provided on the device on the form 'DEV$$$$',
    Should such a serial not be provided, the driver allows for auto-connecting
    to an instrument should the phrase <autodetect> or <autoconnect> be
    provided. This is not recommended in cases where there are multiple
    Zurich Instruments devices connected to the Instrument server PC.
    '''
    
    def performOpen(self, options={}):
        '''Perform the action of opening the instrument.
        '''
        
        # Instantiate the instrument connection, the ZI API, AWG module,
        # and more.
        self.instantiateInstrumentConnection()
        
        # Create an initial configuration of stored waveforms.
        # These will constitute a local set used to track what waveforms are
        # used / changed etc.
        self.defaultWaveformConfiguration()
        
        # If configured to, signal LEDs after completing startup
        if self.getValue('Signal LEDs on startup'):
            self.daq.setInt('/' + self.dev + '/system/identify', 1)
    
    
    def performClose(self, bError=False, options={}):
        '''Perform the close instrument connection operation.
        '''
        
        # It has been chosen not to include a true power-off at this stage
        # (/system/shutdown, 1) as enabling and disabling the instrument in
        # such a recurring fashion would cause a lot of delay.

        # A try-exception is done since the API session might not have
        # been instantiated.
        try:
            self.daq.setInt('/'+str(self.dev)+'/awgs/0/enable', 0)
            
            # If configured to, turn off all outputs when closing the device
            if self.getValue('Disable outputs on close'):
                for i in range(0, self.n_ch):

                    self.daq.setInt('/'+str(self.dev)+'/sigouts/'+str(i)+'/direct',0)
                    self.setValue('Channel '+str(i+1)+' - Bypass DAC to port', False)
                    
                    self.daq.setInt('/'+str(self.dev)+'/sigouts/'+str(i)+'/on',0)
                    self.setValue('Channel '+str(i+1)+' - Output', False)
                    
                    self.daq.setInt('/'+str(self.dev)+'/sigouts/'+str(i)+'/filter', 0)
                    self.setValue('Channel '+str(i+1)+' - Filter', False)
                    
                
            # If configured to, signal LEDs when disconnecting
            if self.getValue('Signal LEDs on close'):
                self.daq.setInt('/' + self.dev + '/system/identify', 1)
        
        except:
            # TODO So ZIAPINotFoundException is generated. How will we define a suitable exception to be thrown at this instance?
            # TODO Likely using some ziUtils.ZIAPINotFoundException or similar. Ask ZI.
            
            self.log( \
                "Could not close the device; " + \
                "there is likely no connection to the ZI API.",level=30)
            

    def performSetValue(self, quant, value, sweepRate=0.0, options={}):
        '''Perform the Set Value instrument operation.
        
        Variables are subject to change between one experiment and another.
        To my knowledge, there is no way of registering whether a
        variable changed in the measurement editor. Thus, all waveforms must
        be seen as subject to change. The solution is to keep a record
        of all waveforms locally, fetch each and every waveform at the
        start of a new measurement, and then compare them for differences.
        
        This in turn is somewhat wasteful, but there is no other algorithmic
        way of guaranteeing that every waveform will be according to the
        user specification in the Measurement editor.

        This function should return the actual value set by the instrument.
        
        '''
        
        # isFirstCall is true each and every time the 'program pointer' of
        # the measurement setup is pointing at the top.
        if self.isFirstCall(options):
            pass
            
        # Is performSetValue attempting to execute a standard ZI API call?
        # (or a command based on the string / other datatype?)
        if '/%s/' in quant.set_cmd:
        
            if 'double /' in quant.set_cmd:
            
                self.daq.setDouble( \
                    quant.set_cmd.replace('double ','') % self.dev, \
                    value if not (quant.datatype > 1) \
                        else float(quant.getCmdStringFromValue(value)) \
                )
            
            elif 'int /' in quant.set_cmd:
            
                self.daq.setInt( \
                    quant.set_cmd.replace('int ','') % self.dev, \
                    value if not (quant.datatype > 1) \
                        else int(quant.getCmdStringFromValue(value)) \
                )
                
            elif 'boolean /' in quant.set_cmd:
                    
                if quant.datatype == 1:
                    self.daq.setInt( \
                        quant.set_cmd.replace('boolean ','') % self.dev, \
                        (1 if value else 0) \
                    )
                
                elif quant.datatype == 2:
                    # Throw suboptimal warning
                    self.log( \
                        "Note: setting booleans using combinational "   + \
                        "lists is very suboptimal due to ambiguity in " + \
                        "the APIs.\nConsider changing the instruction " + \
                        "set_cmd type to integer, using the cmd_defs "  + \
                        "1 and 0 for \'True\' and \'False\' "           + \
                        "respectively ("+quant.name+")." , level=30)
                    
                    fetch_bool = quant.getCmdStringFromValue(value).lower()


                    if (fetch_bool == 'false') or (fetch_bool == '0'):
                        # Do False-case
                        self.daq.setInt( \
                            quant.set_cmd.replace(\
                                'boolean ','') % self.dev \
                            , 0 \
                        )
                    elif (fetch_bool == 'true') or (fetch_bool == '1'):
                        # Do True-case
                        self.daq.setInt( \
                            quant.set_cmd.replace(\
                                'boolean ','') % self.dev \
                            , 1 \
                        )


                    else:
                        raise ValueError( \
                            "Unrecognised boolean value for quantity " + \
                            "name \'"+quant.name+"\' (received \'" + \
                            str(value)+"\').")
                            
                else:
                    raise ValueError( \
                        "Bad datatype for quantity \'" + quant.name + \
                        "\,' expected boolean or combo (of booleans).")
                            
            elif 'other /' in quant.set_cmd:
            
                # Due to the nature of the 'other' datatype, this driver
                # constructs a 'Python switch-case' where every entry spells
                # out a prepared version of the quant.name string.
            
                def Minimise_inter_device_asynchronous_jitter(self, value):
                    ''' TODO missing text
                    '''
                    
                    # If this command is run (and value is True),
                    # we must update the sequencer.
                    self.sequencer_demands_updating = True
                    
                    # Prep. the sequencer generation stage 3:
                    # 'SYNCHRONISE_TO_BEATING_FREQUENCY'
                    self.update_local_awg_program[3] = True
                        
                    # The sequencer program generation in turn checks the
                    # 'Minimise inter-device asynchronous jitter' flag which
                    # at this time may be False, since value is returned
                    # *after* isFinalCall has run. Thus, we must force-set
                    # the flag from here.
                    self.setValue( \
                        'Minimise inter-device asynchronous jitter', \
                        value \
                    )
                    
                    # Modifications may be done to the internal trigger period
                    self.perform_repetition_check = True
                    
                    # Setting this value to true, since it involves the
                    # usage of oscillators, may change the channel grouping
                    # type.
                    if value or \
                        self.getValue('Use oscillator-based repetition delay'):
                        
                        # A channel grouping of 4x2 is required.
                        self.daq.setInt( \
                            '/'+self.dev+'/system/awg/channelgrouping', 0)
                            
                    else:
                        
                        # A channel grouping of 1x8 is sufficient.
                        if self.daq.getInt( \
                            '/'+self.dev+'/system/awg/channelgrouping') != 2:
                            
                            # The grouping should be changed.
                            self.daq.setInt( \
                                '/'+self.dev+'/system/awg/channelgrouping', 2)
                    
                    
                def Beat_frequency(self, value):
                    ''' TODO missing text
                    '''
                    
                    # Set oscillator 1 to the beat frequency of the sequencers.
                    beat_frequency = abs(value)
                    
                    previous_osc_freq = \
                        self.daq.getDouble('/'+str(self.dev)+'/oscs/0/freq')

                    iterfreq = 2
                    while(iterfreq <= 32):

                        setval = beat_frequency / iterfreq
                        
                        if setval < 299000000:
                            
                            self.daq.setDouble( \
                                '/'+str(self.dev)+'/oscs/0/freq', \
                                setval)
                            self.daq.sync()
                            
                            if self.daq.getDouble( \
                                '/'+str(self.dev)+'/oscs/0/freq') == setval:
                                
                                # All is fine. Update value and break.
                                self.setValue('Beat frequency', setval)
                                break
                
                        iterfreq *= 2
                    
                    # Check whether the set was successfull
                    if iterfreq > 32:

                        # Not fine, reset and raise error.
                        self.daq.setDouble( \
                            '/'+str(self.dev)+'/oscs/0/freq',\
                            previous_osc_freq )
                        
                        raise ArithmeticError( \
                            "Cannot set oscillator 1 to an even dividend " + \
                            "of "+str(beat_frequency)+" Sa/s)" )
                
                    # TODO This may be solvable by moving commands around in the 'other' datatype category right here.
                    self.log('WARNING: Changing the beat frequency was fine and all but we must now also change the internal repetition rate if that was set to match the beat frequency.',level=30)
                    
                    
                def Internal_trigger_period(self, value):
                    '''TODO missing text
                    '''
                    # Is the user changing the internal trigger period,
                    # while the system is set to use an oscillator as the
                    # internal repetition delay source?
                    
                    # Is the system set to use oscillator 2 as the internal
                    # repetition source trigger?
                    if self.getValue( \
                        'Use oscillator-based repetition delay'):
                        
                        # TODO The first thing which should happen, is to
                        # check whether the new requested period is reasonable.
                        # This check includes for instance checking whether
                        # it is too small or large to represent by the
                        # oscillator. If yes, modify the period.
                        
                        # Parry for infinite frequencies, check limits.
                        # This part has been somewhat optimised, see if-cases.
                        # For instance the >= 0 or not check is flag-checkable.
                        
                        if value >= 0:
                        
                            # Value is positive
                            if value < 8.333333333333333e-10:
                                
                                # Value is an issue, the oscillator cannot
                                # go any faster. Limit the requested period.
                                value = 8.333333333333333e-10
                        
                        else:
                        
                            # Value is negative
                            if value > -8.333333333333333e-10:
                                
                                # Value is an issue, the oscillator cannot
                                # go any faster. Limit the requested period.
                                value = -8.333333333333333e-10
                        
                        ''' # See triple-apostrophe comment at while loop below
                        
                        # Fetch the current set value for the repetition
                        # oscillator.
                        previous_osc_freq = self.daq.getDouble( \
                            '/'+str(self.dev)+'/oscs/1/freq')'''
                        
                        # Must we synchronise to the jitter-free clause?
                        if self.getValue( \
                            'Minimise inter-device asynchronous jitter'):
                            
                            # Fetch the beat frequency (oscillator) and its
                            # period for repeated usage later.
                            beat_oscill = self.daq.getDouble( \
                                '/'+str(self.dev)+'/oscs/0/freq')
                                
                            beat_peri = abs(1 / beat_oscill)
                            
                            ''' # The below while-segment has been commented,
                            # fetching a perfectly representable value for
                            # the next 'guess' of the while loop is pretty
                            # complicated.
                            attempts = 0
                            while (attempts <= 30):'''
                            
                            # Are the devices *not* in sync?
                            if beat_oscill != 0:

                                # A beat frequency exists. The oscillator
                                # must be set to a whole multiple of the
                                # beat-frequency oscillator.
                                
                                # Is the requested value *not* a legal
                                # and valid multiple of the beat period?
                                if not (value % beat_peri == 0):
                                
                                    # The requested repetition frequency is
                                    # not a multiple of the beat frequency,
                                    # and has to be modified.
                                    
                                    # Is value even smaller than the beat
                                    # period?
                                    #                           TODO is this check still valid after adding 'sense checks?'
                                    if value > beat_peri:
                                
                                        # value mod. beat_peri != 0
                                        nearest_int = \
                                            round(value / beat_peri)
                                        
                                        value = nearest_int * beat_peri
                                    
                                    else:
                                    
                                        # Value is smaller than (or equal
                                        # to) the beat period. Set the
                                        # value to the lowest feasible.
                                        value = beat_peri
                                
                            # Get the corresponding frequency
                            rep_frequency = abs(1 / value)
                            
                            # Try to set rep_frequency.
                            # if success - report and break
                            # else: attempt += 1, value = TODO
                            
                            self.daq.setDouble( \
                                '/'+str(self.dev)+'/oscs/1/freq', \
                                rep_frequency)
                            
                            self.daq.sync()
                        
                            value = 1 / self.daq.getDouble( \
                                '/'+str(self.dev)+'/oscs/1/freq')
                        
                            '''# See triple-apostrophe comment at the while-
                            # loop above.
                            
                            received_rpf = self.daq.getDouble( \
                                '/'+str(self.dev)+'/oscs/1/freq')
                            
                            if received_rpf == rep_frequency:
                            
                                # All is fine, the value was set and legal.
                                break
                                
                            else:
                            
                                # Failure. Increment attempts.
                                attempts += 1
                                
                                # Update value.
                                # TODO Getting this next guess is pretty
                                # much a PhD in itself to get right.
                                # Hence the commented code.
                                value = value * attempts / 30'''
                            
                        else:
                        
                            # The user has not requested to synchronise the
                            # delay to the beat frequency oscillator.
                        
                            # No jitter-free clause needed.
                            rep_frequency = abs(1 / value)
                            
                            self.daq.setDouble( \
                                '/'+str(self.dev)+'/oscs/1/freq', \
                                rep_frequency)
                            
                            self.daq.sync()
                        
                            value = 1 / self.daq.getDouble( \
                                '/'+str(self.dev)+'/oscs/1/freq')
                            
                                    
                        ''' # See triple-apostrophe comment above.
                        # Check whether the set was successfull
                        if attempts > 30:

                            # Not fine, reset and raise error.
                            self.daq.setDouble( \
                                '/'+str(self.dev)+'/oscs/1/freq',\
                                    previous_osc_freq)
                                    
                            raise ArithmeticError( \
                                "Could not modify the requested repetition "+ \
                                "rate to an exact oscillator value given "  + \
                                "the currently set beat frequency." )'''
                    
                    else:
                    
                        # The user has requested not to use an oscillator
                        # for the internal trigger period. This implies
                        # a change of the sequencer program.
                        self.sequencer_demands_updating = True
                    
                    # The internal repetition rate value has to be
                    # set already at this stage, as the value
                    # returns after the isFinalCall check which
                    # might depend on this value.
                    self.setValue('Internal trigger period', value)
                    
                    # Sanity check for validness of internal repetition rate
                    self.perform_repetition_check = True
                
                
                def Use_oscillator_based_repetition_delay(self, value):
                    '''TODO
                    '''
                    # If this command is run (and value is True),
                    # we must update the sequencer.
                    self.sequencer_demands_updating = True
                    
                    # Prep. the sequencer generation stage 2:
                    # WAIT_FOR_INITIAL_TRIGGER, DELAY_BEFORE_LOOP_END,
                    # WAIT_FOR_TRIGGER_TO_REPEAT
                    self.update_local_awg_program[2] = True
                    
                    # The sequencer program generation in turn checks the
                    # 'Use oscillator-based repetition delay' flag which
                    # at this time may be False, since value is returned
                    # *after* isFinalCall has run. Thus, we must force-set
                    # the flag from here.
                    self.setValue( \
                        'Use oscillator-based repetition delay', \
                        value \
                    )
                    
                    # Setting this value to true, since it involves the
                    # usage of oscillators, may change the channel grouping
                    # type.
                    if value or self.getValue( \
                        'Minimise inter-device asynchronous jitter'):
                        
                        # A channel grouping of 4x2 is required.
                        self.daq.setInt( \
                            '/'+self.dev+'/system/awg/channelgrouping', 0)
                            
                    else:
                        
                        # A channel grouping of 1x8 is sufficient.
                        if self.daq.getInt( \
                            '/'+self.dev+'/system/awg/channelgrouping') != 2:
                            
                            # The grouping should be changed.
                            self.daq.setInt( \
                                '/'+self.dev+'/system/awg/channelgrouping', 2)
                
                
                def Reference_clock(self, value):
                    '''TODO write text
                    '''
                    # Is the user changing the reference clock?
                    
                    # As the clock will revert to the 'Internal' mode in case
                    # of failure, more complex behaviour is required than a
                    # simple ZI API call.
                    
                    # To save on the waiting time: if the system is running
                    # in external mode, and we're trying to set it to external
                    # at bootup, simply ignore the set.
                    
                    req_value = int(quant.getCmdStringFromValue(value))
                    rfclk = str( \
                        '/'+self.dev+'/system/clocks/referenceclock/source' )
                    
                    if not (self.daq.getInt( rfclk ) == req_value):
                    
                        # Set the new value
                        self.daq.setInt( rfclk, req_value )
                        
                        # Wait for the 'Reference clock' value to eventually
                        # rebounce. Half of a second is a typical good value.
                        time.sleep(0.5)
                        
                        # Fetch the new value and compare differences.
                        value = self.daq.getInt( rfclk )
                        
                        # Did we fail to change the value?
                        # TODO This if-case together with the if
                        # requested_value below can likely be algorithmically
                        # optimised.
                        if value != req_value:

                            if req_value == 1:
                                
                                # Has the user requested to halt the system in
                                # case this happens?
                                if self.getValue( \
                                    'Halt on external clock failure'):
                                    
                                    raise RuntimeError( \
                                        "Halted: Could not lock the "     + \
                                        "reference clock to an external " + \
                                        "signal.")
                                    
                                else:
                                
                                    # Send a lock failure warning.
                                    self.log( \
                                        "Warning: Could not lock the "    + \
                                        "reference clock to an external " + \
                                        "signal.")
                            
                            else:
                            
                                # Send an unlock failure warning.
                                self.log( \
                                    "Warning: Could not unlock the "      + \
                                    "reference clock from the external "  + \
                                    "signal.")
                
                
                def Output_sample_rate(self, value):
                    '''TODO
                    '''
                    # Is the user changing a ZIAPI double which may invalidate
                    # the current internal repetition delay value?
                    
                    # Modify the sample rate clock
                    self.daq.setDouble( \
                        quant.set_cmd.replace('other ','') % self.dev, \
                        value \
                    )
                    
                    # This operation is delicate, thus we monitor a status
                    # string for its current status.
                    upload_timeout_ms = 2950
                    clock_status = 2 # 2 = 'Busy' acc. to ZI HDAWG doc.
                    
                    # Give it a tiny wait
                    time.sleep(0.050) # TODO This value should be minimised
                    
                    # elf/status provides information whether the upload is
                    # succeeding.
                    while (clock_status != 0) and (upload_timeout_ms >= 0):

                        # Fetch progress
                        clock_status = \
                            self.daq.getInt( \
                                '/%s/system/clocks/sampleclock/status' \
                                % self.dev)
                        
                        # Shortcut ending
                        if clock_status == 0:
                            break
                        
                        # Waiting sequence
                        time.sleep(0.050)
                        upload_timeout_ms -= 50
                    
                    # Check for sample clock change timeout
                    if upload_timeout_ms <= 0:
                        raise RuntimeError( \
                            "Failed to set \'Output sample rate\' due " + \
                            "to command timeout.")
                    
                    # Sample clock change reported failure
                    elif clock_status == 1:
                        raise RuntimeError( \
                            "Failed to set \'Output sample rate\' due " + \
                            "to some unknown device error.")
                    
                    # This command may change the validness of the internal
                    # repetition delay.
                    self.perform_repetition_check = True
                    
                
                def Output_sample_rate_divisor(self, value):
                    '''TODO
                    '''
                    
                    # Is the user changing the sampling rate combo?
                    
                    self.daq.setInt( \
                        quant.set_cmd.replace('other ','') % self.dev, \
                        int(quant.getCmdStringFromValue(value)) \
                    )
                
                    # This command may change the validness of the internal
                    # repetition delay.
                    self.perform_repetition_check = True
                    
                
                def Sequencer_triggers(self, value):
                    '''TODO
                    '''
                    
                    # This command may change the validness of the internal
                    # repetition delay.
                    self.perform_repetition_check = True
                    
                    # Prep. the sequencer generation stage 4:
                    # START_TRIGGER_PULSE, END_TRIGGER_PULSE
                    self.update_local_awg_program[4] = True
                    
                    # Prep. the sequencer generation stage 5:
                    # DELAY_BEFORE_END_TRIGGER
                    self.update_local_awg_program[5] = True


                def Delay_before_end_trigger_changes(self, value):
                    '''TODO
                    '''
                    
                    # Is the user changing a value which should trigger the
                    # internal repetition check?
                    
                    # This command may change the validness of the internal
                    # repetition delay.
                    self.perform_repetition_check = True
                    
                    # Prep. the sequencer generation stage 5:
                    # DELAY_BEFORE_END_TRIGGER
                    self.update_local_awg_program[5] = True
                    
                    
                def Run_mode(self, value):
                    '''TODO
                    '''
                    
                    # Is the user changing the Run mode?
                    
                    # This command will require a change in the
                    # sequencer program.
                    self.sequencer_demands_updating = True
                    
                    # If changing back to 'Internal trigger' -> we may need
                    # to double-check that the internal repetition rate is
                    # valid. All previous calls during other Run modes
                    # have been ignored.
                    self.perform_repetition_check = True
                    
                    # We now make a note to the generateSequencerProgram
                    # that the run mode has changed.
                    
                    # Prep. the sequencer generation stage 2:
                    # WAIT_FOR_INITIAL_TRIGGER, DELAY_BEFORE_LOOP_END,
                    # WAIT_FOR_TRIGGER_TO_REPEAT
                    self.update_local_awg_program[2] = True
                    
                    # The Labber-stored value for 'Run mode' must be updated
                    # at this location as the generateSequencerProgram function
                    # will run before the setValue default after isFinalCall.
                    self.setValue('Run mode', value)
                
                
                def Range(self, value):
                    '''TODO
                    '''
                    
                    # Get the channel in question
                    channel = int( \
                        ( \
                            quant.name.replace(' - Range','') \
                        ).replace('Channel ',''))
                    
                    # Alter the output range, make sure to update the
                    # self-object list of ranges. This list is used when
                    # resetting the output range after disabling the direct
                    # output.
                    
                    val = float(quant.getCmdStringFromValue(value))
                    
                    # Execute command
                    self.daq.setDouble( \
                        '/%s/sigouts/%s/range' % (self.dev, channel-1), val \
                    )
                    
                    # Update list
                    self.previous_ranges[channel-1] = val
                
                
                def Bypass_DAC_to_port(self, value):
                    ''' TODO
                    
                        For your information, the DAC bypass to port function
                        is known as 'Direct output' in ZI LabOne.
                    '''
                    # Get the channel in question
                    channel = int( \
                        ( \
                            quant.name.replace(' - Bypass DAC to port','') \
                        ).replace('Channel ',''))
                    
                    # Disable and restore if false, merely enable if true
                    if not value:
                        
                        # Execute disablement
                        self.daq.setInt( \
                            '/%s/sigouts/%s/direct' % (self.dev,channel-1), 0 \
                        )
                        
                        # Note to reader: this clause usually changes the
                        # measurement range in such a way that a relay
                        # will toggle the instrument into said range.
                        # Meaning that a weird double-klicking is expected.
                        self.daq.setDouble( \
                            '/%s/sigouts/%s/range' % (self.dev,channel-1), \
                            float(self.previous_ranges[channel-1]) \
                        )
                    
                    else:
                    
                        # Merely execute the enablement
                        self.daq.setInt( \
                            '/%s/sigouts/%s/direct' % (self.dev,channel-1), 1 \
                        )
                        
                
                def Output_Marker_config(self, value):
                    '''TODO
                    '''
                    
                    # The config can change three major topics:
                    # 1. Start time for marker 1/2
                    # 2. Duration of marker 1/2
                    # 3. Whether there are any markers left to be played.
                    
                    # Which channel was it and what channel are we talking?
                    split   = (quant.name).split(' Marker ', 1)
                    channel = int(split[0].replace('Output '    ,'')) -1
                    marker  = int((split[1].replace(' start time','')).replace(' duration','')) -1
                    
                    # Get the current sample rate (per divisor)
                    sample_rate =                                            \
                        self.getValue('Output sample rate') /                \
                        2**self.getValueIndex('Output sample rate divisor')
                    
                    # Change marker start or duration?
                    if('st' in quant.name):
                        
                        # Start it is. Convert value to samples.
                        start = int(round(value * sample_rate))
                        
                        # Fetch the current duration.
                        duration = int(self.marker_configuration[channel,marker,1])
                        
                        # Update the marker configuration.
                        self.configureMarker(channel,marker,start,duration)
                        
                    else:
                    
                        # So it's duration then.
                        duration = int(round(value * sample_rate))
                        
                        # Fetch the current start.
                        start = int(self.marker_configuration[channel,marker,0])
                        
                        # Update the marker configuration.
                        self.configureMarker(channel,marker,start,duration)
                    

                # Setup and fetch a 'switch/case' clause
                quant_name_swicas = \
                    ((quant.name).replace(' ','_')).replace('-','_')
                
                switch_case = {
                    'Trigger_out_delay':\
                        Delay_before_end_trigger_changes,
                    'Dynamic_repetition_rate':\
                        Delay_before_end_trigger_changes,
                    'Calibrate_trigger_out_delay':\
                        Delay_before_end_trigger_changes,
                    'Halt_on_illegal_repetition_rate':\
                        Delay_before_end_trigger_changes,
                    'Calibrate_internal_trigger_period':\
                        Delay_before_end_trigger_changes,
                        
                    'Channel_1___Bypass_DAC_to_port':\
                        Bypass_DAC_to_port,
                    'Channel_2___Bypass_DAC_to_port':\
                        Bypass_DAC_to_port,
                    'Channel_3___Bypass_DAC_to_port':\
                        Bypass_DAC_to_port,
                    'Channel_4___Bypass_DAC_to_port':\
                        Bypass_DAC_to_port,
                    'Channel_5___Bypass_DAC_to_port':\
                        Bypass_DAC_to_port,
                    'Channel_6___Bypass_DAC_to_port':\
                        Bypass_DAC_to_port,
                    'Channel_7___Bypass_DAC_to_port':\
                        Bypass_DAC_to_port,
                    'Channel_8___Bypass_DAC_to_port':\
                        Bypass_DAC_to_port,
                    
                    'Channel_1___Range':\
                        Range,
                    'Channel_2___Range':\
                        Range,
                    'Channel_3___Range':\
                        Range,
                    'Channel_4___Range':\
                        Range,
                    'Channel_5___Range':\
                        Range,
                    'Channel_6___Range':\
                        Range,
                    'Channel_7___Range':\
                        Range,
                    'Channel_8___Range':\
                        Range,
                    
                    'Output_1_Marker_1_start_time':\
                        Output_Marker_config,
                    'Output_1_Marker_2_start_time':\
                        Output_Marker_config,
                    'Output_2_Marker_1_start_time':\
                        Output_Marker_config,
                    'Output_2_Marker_2_start_time':\
                        Output_Marker_config,
                    'Output_3_Marker_1_start_time':\
                        Output_Marker_config,
                    'Output_3_Marker_2_start_time':\
                        Output_Marker_config,
                    'Output_4_Marker_1_start_time':\
                        Output_Marker_config,
                    'Output_4_Marker_2_start_time':\
                        Output_Marker_config,
                    'Output_5_Marker_1_start_time':\
                        Output_Marker_config,
                    'Output_5_Marker_2_start_time':\
                        Output_Marker_config,
                    'Output_6_Marker_1_start_time':\
                        Output_Marker_config,
                    'Output_6_Marker_2_start_time':\
                        Output_Marker_config,
                    'Output_7_Marker_1_start_time':\
                        Output_Marker_config,
                    'Output_7_Marker_2_start_time':\
                        Output_Marker_config,
                    'Output_8_Marker_1_start_time':\
                        Output_Marker_config,
                    'Output_8_Marker_2_start_time':\
                        Output_Marker_config,
                        
                    'Output_1_Marker_1_duration':\
                        Output_Marker_config,
                    'Output_1_Marker_2_duration':\
                        Output_Marker_config,
                    'Output_2_Marker_1_duration':\
                        Output_Marker_config,
                    'Output_2_Marker_2_duration':\
                        Output_Marker_config,
                    'Output_3_Marker_1_duration':\
                        Output_Marker_config,
                    'Output_3_Marker_2_duration':\
                        Output_Marker_config,
                    'Output_4_Marker_1_duration':\
                        Output_Marker_config,
                    'Output_4_Marker_2_duration':\
                        Output_Marker_config,
                    'Output_5_Marker_1_duration':\
                        Output_Marker_config,
                    'Output_5_Marker_2_duration':\
                        Output_Marker_config,
                    'Output_6_Marker_1_duration':\
                        Output_Marker_config,
                    'Output_6_Marker_2_duration':\
                        Output_Marker_config,
                    'Output_7_Marker_1_duration':\
                        Output_Marker_config,
                    'Output_7_Marker_2_duration':\
                        Output_Marker_config,
                    'Output_8_Marker_1_duration':\
                        Output_Marker_config,
                    'Output_8_Marker_2_duration':\
                        Output_Marker_config,
                
                    'Run_mode':\
                        Run_mode,
                    'Beat_frequency':\
                        Beat_frequency,
                    'Reference_clock':\
                        Reference_clock,
                    'Output_sample_rate':\
                        Output_sample_rate,
                    'Sequencer_triggers':\
                        Sequencer_triggers,
                    'Internal_trigger_period':\
                        Internal_trigger_period,
                    'Output_sample_rate_divisor':\
                        Output_sample_rate_divisor,
                    'Use_oscillator_based_repetition_delay':\
                        Use_oscillator_based_repetition_delay,
                    'Minimise_inter_device_asynchronous_jitter':\
                        Minimise_inter_device_asynchronous_jitter
                }
                
                # Execute
                switch_case.get(quant_name_swicas)(self, value)
                
                # TODO  Is it even necessary to pass on the value parameter?
                #       Because, quant seems to work just fine.
                
                # TODO  This switch-case setup can likely be moved elsewhere.
                #       For instance to defaultWaveformConfiguration or similar.
          
            
            elif 'string /' in quant.set_cmd:
            
                # The quant name if-case is commented as there is currently
                # only one command in the instruction file which uses the
                # string datatype.
                #if quant.name == 'Command line box':
                
                # This portion only runs if the user is giving an explicit
                # command line command.
                
                if not ', ' in value:
                    self.log("Parser error: \', \' missing.", level=30)
                
                else:
                
                    # Grab the substring after ', ' - store the process value.
                    parsed = value[value.index(', ')+2 : ]
                    proc   = (value.replace(', ' + parsed,'')).lower()

                    if 'int /%s/' in proc:
                        
                        try:
                            self.daq.setInt( \
                                (proc.replace('int ','')) % self.dev, \
                                int(parsed) \
                            )
                            
                            self.log("ZIAPI command accepted: \'" + value + \
                                     "\'",level=30)
                        
                        except: # TODO define this exception
                            
                            # These lines are mainly for debug.
                            #self.log("ZIAPI command line parser exception: "+ \
                            #         "cannot interpret \'" + value + "\' as"+ \
                            #         " a valid \'int\' command.",level=30)
                            pass

                    elif 'double /%s/' in proc:
                        
                        try:
                            self.daq.setDouble(                   \
                                (proc.replace(        \
                                    'double ','')              \
                                ) % self.dev, float(parsed)    \
                            )
                        
                            self.log("ZIAPI command accepted: \'" + value + \
                                     "\'",level=30)
                            
                        except: # TODO define this exception
                            
                            # These lines are mainly for debug.
                            #self.log("ZIAPI command line parser exception: "+ \
                            #         "cannot interpret \'" + value + "\' as"+ \
                            #         " a valid \'double\' command.",level=30)
                            pass

                    elif 'boolean /%s/' in proc:
                        
                        try:                        
                            if (parsed.lower() == 'true')        \
                                or (parsed.lower() == '1')       \
                                or (parsed.lower() == 'ya boi'):
                                
                                self.daq.setInt( \
                                    (proc.replace('boolean ','')) \
                                        % self.dev, 1 \
                                )
                                
                                self.log("ZIAPI command accepted: \'" +value+ \
                                         "\'",level=30)
                            
                            elif (parsed.lower() == 'false')     \
                                or (parsed.lower() == '0')       \
                                or (parsed.lower() == 'na'):
                                
                                self.daq.setInt( \
                                    (proc.replace('boolean ','')) \
                                        % self.dev, 0 \
                                )
                                
                                self.log("ZIAPI command accepted: \'" +value+ \
                                         "\'",level=30)

                        except:
                            
                            # These lines are mainly for debug.
                            #self.log("ZIAPI command line parser exception: "+ \
                            #         "cannot interpret \'" + value + "\' as"+ \
                            #         " a valid \'boolean\' command.",level=30)
                            pass
                            
                    elif 'awgmodule' in proc: # No capitalisation on M
                    
                        # Fix the lower()-conversion
                        proc = proc.replace('awgmodule','awgModule')
                        
                        # The AWG module is datatype agnostic as to integers
                        # versus doubles. Any attempt to hard-define such
                        # a datatype results is in vain, ergo remove all
                        # (feasible) datatype specifiers from the beginning
                        # of the command line parsed.
                        if 'int ' in proc:
                            proc = proc.replace('int ','')

                        elif 'double ' in proc:
                            proc = proc.replace('double ','')
                            
                        elif 'boolean ' in proc:
                            if (parsed.lower() == 'true')        \
                                or (parsed.lower() == '1')       \
                                or (parsed.lower() == 'ya boi'):
                                
                                proc.replace('boolean ','')
                                parsed = 1
                            
                            elif (parsed.lower() == 'false')     \
                                or (parsed.lower() == '0')       \
                                or (parsed.lower() == 'na'):
                                
                                proc.replace('boolean ','')
                                parsed = 0

                        try:
                            self.awgModule.set(proc, float(parsed))
                            self.log("ZIAPI command accepted: \'" + value + \
                                     "\'",level=30)
                        
                        except: # TODO define this exception
                            
                            # # These lines are mainly for debug.
                            # #self.log("ZIAPI command line parser "+ \
                            # #         "exception: cannot interpret \'" + \
                            # #         value + "\' as"+ \
                            # #         " a valid awgModule command.",level=30)
                            pass
                    
                    #else:
                        
                    #    # These lines are mainly for debug
                    #    #self.log("Warning: the command line parser did not"+\
                    #    #" understand at all what you put in the command "  +\
                    #    #"line box: \'"+str(value)+"\'",level=30)
                    #pass

            else:
                raise NotImplementedError( \
                    "Unrecognised ZI API command: " + quant.set_cmd \
                )
        
        # Is the setValue attempting to set an awgModule value?
        elif 'awgModule' in quant.set_cmd:
            
            self.awgModule.set( \
                quant.set_cmd, \
                    value if not (quant.datatype > 1) \
                        else float(quant.getCmdStringFromValue(value)) \
            )
        
        
        # In the final call, we may have had changes that require uploading
        # new waveforms or even requires recompiling the sequencer code.
        # 'isFinalCall' is true each and every time the 'program pointer' of
        # the measurement setup is pointing at the bottom.

        if self.isFinalCall(options):
        
            # Prepare for adjusting the buffer length.
            ''' Two variables keep track of said length:
                - self.buffer_length:
                    The actual length value sent onto the sequence generator.
                    Will correspond to the longest waveform length of all
                    loaded waveforms in the previous isFinalCall-run.
                - current_buffer_length:
                    Buffer length following the very latest update, will update
                    the self.buffer_length after the wave for-loop if the
                    current buffer length does not correspond to the previous
                    one (= the required maximum buffers do not match).
            '''
            current_buffer_length = 0
            
            # Keep track of the highest waveform in use.
            # This is used when declaring the sequencer program as well
            # as determining whether to upload a waveform interleaved or
            # in single mode in writeWaveformToMemory. 0 corresponds to
            # zero waveforms being used. 1 corresponds to one waveform in
            # use total, playing on output 1.
            self.highest_waveform_in_use = 0
            
            # Figure out whether we require waveform uploading
            for wave in range(0, self.n_ch):
            
                # Fetch the current waveform. It may either have been
                # declared directly, or by using waveform primitives.
                current_waveform = self.fetchAndAssembleWaveform(wave)
                
                # Counteract Labber randomly returning [None].
                if np.array_equal(current_waveform,[None]):
                    current_waveform = []
                    
                    # TODO:
                    # Remove this portion when Labber starts returning
                    # values as expected.
                    self.log( \
                        "Labber encountered an internal (non-critical) " + \
                        "error."                                         , \
                        level=30)
                        
                    # TODO:
                    # Insert code for dropping this measurement point entirely.
                    #self.log( \
                    #    "Labber encountered an internal (non-critical) " + \
                    #    "error. This waveform update is discarded."      , \
                    #    level=30)
                    
                    # In case Labber actually returned [None], then the length
                    # of the current waveform can impossibly be longer
                    # than the current buffer length. Hence the elif below.
                    
                    # Calculate a new buffer length
                elif len(current_waveform) > current_buffer_length:
                    current_buffer_length = len(current_waveform)
                
                    # Algorithmic piggyback, we know that if this is true
                    # then this is automatically the highest waveform in use.
                    self.highest_waveform_in_use = wave +1
                
                elif not len(current_waveform) == 0:
                    self.highest_waveform_in_use = wave +1
                
                # Acquire the previous waveform for future comparisons
                previous_waveform = self.loaded_waveforms[wave]
                
                # Has something happened?
                # TODO This comparison should be hashed in the future.
                if not np.array_equal(current_waveform, previous_waveform):
                    
                    # Is the loaded waveform None?
                    if len(current_waveform) == 0:
                        
                        # The user has requested to unload a waveform.
                        self.loaded_waveforms[wave] = []
                        
                        # The sequencer should thus be updated. The waveform
                        # being unloaded should not be marked as 'changed' as
                        # there will be no memory allocated for it.                        
                        self.sequencer_demands_updating = True
                        
                        # Prep. the sequencer generation stage 0:
                        # MARKER_DECLARATION, WAVEFORM_DECLARATION, PLAYWAVE, WAITWAVE
                        self.update_local_awg_program[0] = True
                        
                    else: # len(current_waveform) > 0:
                    
                        # The user is changing the waveform, update and tag
                        # the waveform for update ('something changed').
                        self.loaded_waveforms[wave] = current_waveform
                        self.waveform_changed[wave] = True
                        
                        # Is this an entirely new waveform?
                        if len(previous_waveform) == 0:
                            
                            # A new waveform was added, update the sequencer.
                            self.sequencer_demands_updating = True
                            
                            # Prep. the sequencer generation stage 0:
                            # MARKER_DECLARATION, WAVEFORM_DECLARATION,
                            # PLAYWAVE, WAITWAVE
                            self.update_local_awg_program[0] = True
                        
            # Does the longest waveform in the new waveform package differ
            # from the previously used buffer length? Ergo, update sequencer?
            if current_buffer_length != self.buffer_length:
                self.buffer_length = current_buffer_length
                self.sequencer_demands_updating = True
                
                # Prep. the sequencer generation stage 0:
                # MARKER_DECLARATION, WAVEFORM_DECLARATION, PLAYWAVE, WAITWAVE
                self.update_local_awg_program[0] = True
            
            # Has any runtime values tampered with the internal repetition
            # rate? Ie. must we check whether the repetition rate is valid?
            if self.perform_repetition_check:
            
                # Reset call flag
                self.perform_repetition_check = False
                
                if self.getValue('Run mode') == 'Internal trigger':
                
                    # Run check, at this stage we even know what waveforms to
                    # change and what the buffer length is.
                    self.checkInternalRepetitionRateValid()
                    

            # The next task on the agenda is to carry out a potential
            # sequencer update and / or upload new waveforms.
            if self.sequencer_demands_updating:
            
                # Halt the sequencer. # TODO look at the compile-code.
                self.awgModule.set('awgModule/awg/enable', 0)
            
                # Recompile the sequencer, this requires re-uploading all
                # waveforms anew. This is mainly due to the most common
                # triggering condition for sequencer re-compilation, being
                # buffer length discrepancy versus the old sequencer code.
                
                self.updateSequencer()
                self.sequencer_demands_updating = False

                # The writeWaveform function will inject and reset the
                # changed-status of the waveform(s) to False.
                self.writeWaveformToMemory()
                    
                # Enable playback again. # TODO look at the compile-code.
                self.awgModule.set('awgModule/awg/enable', 1)
                
            elif np.any(self.waveform_changed):
                
                # The sequencer can remain the same. However, there were
                # changes done to the loaded waveforms.
                
                # The writeWaveform function will reset the changed-status
                # of the waveform(s) to False.
                self.writeWaveformToMemory()

        return value
    
    
    def performGetValue(self, quant, options={}):
        '''Perform the Get Value instrument operation.
        TODO not written.
        '''
        
        # Is performGetValue attempting to execute a standard ZI API call?
        if '/%s/' in quant.get_cmd:

            if 'double /' in quant.get_cmd:

                if quant.datatype == 0:
                    return self.daq.getDouble(\
                        quant.get_cmd.replace('double ','') % self.dev \
                    )
                    
                elif quant.datatype == 2:
                    return quant.getValueFromCmdString( \
                        self.daq.getDouble( \
                            quant.get_cmd.replace('double ','') % self.dev\
                        ) \
                    )
                        
                else:
                    raise ValueError( \
                        "Bad datatype for quantity \'" + quant.name + \
                        "\,' expected double or combo (of doubles).") 
            
            elif 'int /' in quant.get_cmd:
                if quant.datatype == 2:
                    return quant.getValueFromCmdString( \
                        self.daq.getInt( \
                            quant.get_cmd.replace('int ','') % self.dev \
                        ) \
                    )
                # As of 20190913, Labber does not support integer types.
                # Thus a get_cmd of datatype int would correspond exclusively
                # to a combinational list.                
                # elif quant.datatype < 2:
                #     return self.daq.getInt(\
                #         quant.get_cmd.replace('int ','') % self.dev \
                #    )
                else:
                    raise ValueError( \
                        "Bad datatype for quantity \'" + quant.name + \
                        "\,' expected combo (of integers).") 
            
            elif 'boolean /' in quant.get_cmd:
                if quant.datatype == 1: \
                    return self.daq.getInt( \
                        quant.get_cmd.replace('boolean ','') % self.dev \
                    ) > 0
                
                elif quant.datatype == 2:
                    # Throw suboptimal warning
                    self.log( \
                        "Note: getting booleans using combinational lists "  +\
                        "is very suboptimal due to ambiguity in the APIs. "  +\
                        "\nConsider changing the instruction get_cmd type to"+\
                        " integer, using the cmd_defs 1 and 0 for \'True\' " +\
                        "and \'False\' respectively ("+quant.name+")."       ,\
                        level=30)
                
                    # Fetch True or False, and try to return it.
                    # Due to string ambiguity, several try-exceptions are made.
                    fetched_bool = self.daq.getInt( \
                        quant.get_cmd.replace('boolean ','') % self.dev \
                    ) > 0
                
                    try:
                        return quant.getValueFromCmdString(str(fetched_bool))
                    
                    except: # TODO: define this exception
                        try:
                            return quant.getValueFromCmdString( \
                                '1' if fetched_bool else '0' \
                            )
                            
                        except: # TODO define this exception
                            
                            # If all else fails, return the lower case version
                            # of the string-parsed boolean. If this throws an
                            # error, the user is not using a reasonable name
                            # for a boolean.
                            return quant.getValueFromCmdString( \
                                str(fetched_bool).lower() \
                            )
                else:
                    raise ValueError( \
                        "Bad datatype for quantity \'" + quant.name + \
                        "\,' expected boolean or combo (of booleans).")                    

            elif 'string /' in quant.get_cmd:
                
                # Check whether this is the command line parser
                if quant.name == 'Command line box':
                
                    # Return the default value
                    return 'double /%s/example/0/command/13, 313.0'
                    
            elif 'other /' in quant.get_cmd:
            
                # TODO This performGet 'other /'-category should be made more
                # effective. Even a switch-case perhaps?
                
                # TODO If there is no need to include any other get command,
                # other than - Range, then the 'return status quo' should
                # be put as a 'if not '- Range' in quant.name:' to speed
                # up the process further.
            
                # Acquire more complex datatype values. Fortunately, the
                # get routine for these are all quite simple.
                    
                if ' - Range' in quant.name:
                    # Unfortunately, '/range' does not return a number which
                    # may be passed through straight.
                    
                    # Round the return.
                    return quant.getValueFromCmdString( \
                        round(
                            self.daq.getDouble( \
                                quant.get_cmd.replace('other ','') % self.dev \
                            ) \
                        , 1) \
                    )
                
                    '''
                    TODO    Executing a performGet to fetch the current marker
                            settings might be unnecessary. This would likely
                            only return zeroes on bootup since the marker
                            settings at this time would have been defaulted.
                            
                            Although the code below is verified and may be
                            uncommented at any time should you wish to use it.
                            
                elif ('Output ' in quant.name) and ('Marker ' in quant.name):
                
                    # The user is requesting the currently set marker
                    # duration or start time for some given channel and marker.
                    
                    # Which channel was it and what channel are we talking?
                    split   = (quant.name).split(' Marker ', 1)
                    channel = int(split[0].replace('Output '    ,'')) -1
                    marker  = int((split[1].replace(' start time','')).replace(' duration','')) -1
                    
                    # Get the current sample rate (per divisor)
                    sample_rate =                                            \
                        self.getValue('Output sample rate') /                \
                        2**self.getValueIndex('Output sample rate divisor')
                    
                    # Get marker start or duration?
                    if('st' in quant.name):
                        
                        # Start it is. Get value (converted to time).
                        return self.marker_configuration[channel,marker,0] / sample_rate
                        
                    else:
                    
                        # Duration then. Get value (converted to time).
                        return self.marker_configuration[channel,marker,1] / sample_rate
                '''
                        
                else:
                
                    # Return status quo
                    return quant.getValue()

            else:
                raise NotImplementedError( \
                    "Unrecognised ZI API or other command: " + quant.get_cmd \
                )

        # Is the getValue attempting to get an awgModule value?
        elif 'awgModule' in quant.get_cmd:
            
            if quant.datatype != 2:
                
                # TODO:
                # For some reason, acquiring 'enable' from the AWG module
                # works completely opposite to other parametres. This causes
                # the following atrocity, and should be reported as a bug /
                # missing feature to Zurich Instruments.
                
                # Frankly the entirety of awgModule/awgs/enable is still very
                # broken as of 20191016.
                
                if not 'awgModule/awg/enable' in quant.get_cmd:
                    return self.awgModule.get(quant.get_cmd)
                else:
                    self.daq.sync()
                    return ((( \
                        self.awgModule.get('awgModule/awg/enable') \
                            ).get('awg')).get('enable')[0] > 0)
            else:
                return quant.getValueFromCmdString( \
                    self.awgModule.get(quant.get_cmd) \
                )

        return quant.getValue()


    ################################
    """ Marker configuration """
    ################################
    
    def configureMarker(self, channel=0, marker=0, start=0, duration=0):
        ''' TODO
        '''
        # Safekeeping hard type conversion
        start    = int(start)
        duration = int(duration)
        
        # Update the currently held configuration.
        # Check whether there is a change to be made.
        old_start    = self.marker_configuration[channel,marker,0]
        old_duration = self.marker_configuration[channel,marker,1]
        
        # Get new values.
        self.marker_configuration[channel,marker,0] = start
        self.marker_configuration[channel,marker,1] = duration
        
        # Difference?
        if (old_start != start) or (old_duration != duration):
            
            # Then this waveform should be tagged for updating!
            self.waveform_changed[channel] = True
        
        # Does the channel even have marker data?
        # And is this even a sequencer change?
        # If we changed state between "any True" and "none True", then we
        # should also update the sequencer.
        
        if duration <= 0:

            # Check if any waveform has markers:
            if any(self.waveform_has_markers):
                
                # Update current status of the removed markers.
                self.waveform_has_markers[channel] = False
                
                # Was this the last removal?
                if not any(self.waveform_has_markers):
                    
                    # If yes, then this is a sequencer change!
                    self.sequencer_demands_updating = True
                    
                    # Prep. the sequencer generation stage 0:
                    # MARKER_DECLARATION, WAVEFORM_DECLARATION,
                    # PLAYWAVE, WAITWAVE
                    self.update_local_awg_program[0] = True
                    
            # Note: should this be false, then all waveforms are already
            # without markers, and we can skip updating whether there
            # are markers or not present.
            
        else:
        
            # Check if no waveforms have markers:
            if not any(self.waveform_has_markers):
                
                # Update current status of the added markers.
                self.waveform_has_markers[channel] = True
                
                # Was this the first addition?
                if any(self.waveform_has_markers):
                    
                    # If yes, then this is a sequencer change!
                    self.sequencer_demands_updating = True
                    
                    # Prep. the sequencer generation stage 0:
                    # MARKER_DECLARATION, WAVEFORM_DECLARATION,
                    # PLAYWAVE, WAITWAVE
                    self.update_local_awg_program[0] = True
            
            else:
                
                # Ok, so this is not a sequencer change.
                # Just tag the waveform.
                self.waveform_has_markers[channel] = True
        
        

    ################################
    """ Instrument instantiation """
    ################################
    
    def instantiateInstrumentConnection(self):
        ''' TODO This function sets up the instrument connection, fetches
            an instance of the ZI API, connects to the AWG module, and
            more.
        '''
        
        # Check whether LabOne is running on the Instrument Server PC.
        # A returned True implies successful operation.
        assert self.isLabOneRunning(), \
            "The operating system did not return a valid process "  + \
            "entry for LabOne. The program is likely not running. " + \
            "Please start LabOne, or try rebooting the Instrument " + \
            "Server PC."
        
        # Acquire device serial / Check whether the user wishes to autoconnect
        user_address_input = self.comCfg.address
        
        # Is this an autoconnect attempt?
        if  user_address_input == '<autodetect>' or \
            user_address_input == '<autoconnect>':
            
            # Attempt autoconnect attempt using API level 6
            self.daq = ziUtils.autoConnect(api_level = 6)
            self.dev = ziUtils.autoDetect(self.daq)
            
            # Set the amount of channels available
            device_model = self.daq.getByte(
                str('/'+self.dev+'/features/devtype')
            )
            
            # Set the amount of channels depending on model
            if 'HDAWG' in device_model:
                self.n_ch = int(re.sub('HDAWG','',device_model))
                
                assert (self.n_ch <= 16) and (self.n_ch > 0), \
                    "The device reported an unreasonable amount of " + \
                    "channels. The driver is thus not compatible with " + \
                    "this device."
            else:
                raise AutoconnectFailure( \
                    "The autoconnected device did not identify as an " + \
                    "HDAWG. Please specify device serial manually in the " + \
                    "address field.")
            
            # Acquire device options
            device_options = self.daq.getByte(
                str('/'+self.dev+'/features/options')
            )
 
        else:
        
            # Will attempt to connect to the specified device
            self.dev_uppercase = user_address_input.upper()
            if 'HDAWG-' in self.dev_uppercase:
                self.dev_uppercase = self.dev_uppercase.replace('HDAWG-','')
            self.dev = self.dev_uppercase.lower()
            
            # Assert that the assigned serial string is valid
            assert 'DEV' in self.dev_uppercase, \
                "Error: Illegal name of instrument (missing \'DEV\')."
 
            # Scan for connected devices, acquire device props
            discov  = ziPython.ziDiscovery()
            props   = discov.get(discov.find(self.dev_uppercase))
            
            # Props provides a usable API level and additional information
            ZI_API = props['apilevel']
            self.log("The server address for the specified address is: \'" + \
                props['serveraddress']+"\', at port "+ \
                str(props['serverport'])+".",level=30)
 
            # Generate API session
            self.daq, self.device, device_info = ziUtils.create_api_session(
                user_address_input,
                ZI_API,
                required_devtype = "HDAWG",
                required_err_msg = \
                    "The device does not respond like an HDAWG should. "    +\
                    "You may have attempted to connect to the HDAWG at "    +\
                    "an unexpected moment in time, or provided a serial ("  +\
                    str(self.dev_uppercase)+") which does not belong to "   +\
                    "an HDAWG.")
 
            # Acquire device model and its installed options
            device_model   = device_info['devicetype']
            device_options = device_info['options']

            # Set the amount of channels depending on model
            try:
                self.n_ch = int(re.sub('HDAWG','',device_model))
            except: # TODO This exception does not have a clear exemption, even SystemClose is a valid exception.
                raise AttributeError( \
                    "The device returned an unexpected model name: \'" + \
                    str(device_model) + "\'")

            assert (self.n_ch <= 16) and (self.n_ch > 0), \
                "The device reported an unreasonable amount of channels. " + \
                "The driver is thus not compatible with this device."
            
            """ Force connection interface """
            # Connect identified device to session
            # self.daq.connectDevice(
            #     self.dev_uppercase,
            #     props['interfaces'][0]
            # )
 
        # Update the device options in the instrument server
        self.setValue('CNT installed', False)
        self.setValue( 'MF installed', False)
        self.setValue( 'ME installed', False)
        self.setValue('SKW installed', False)
        self.setValue( 'PC installed', False)
        
        while len(device_options) > 0:
            option_installed_str = str(next(iter(device_options)))
            try:
                self.setValue(option_installed_str+' installed', True)
            except: # TODO find a suitable exception to use here.
                self.log( \
                    "WARNING: The device reported an unrecognised option ("  +\
                    option_installed_str+") - features stemming from having "+\
                    "this option installed may not be usable in this driver."+\
                    " Should this warning remain after updating Labber, "    +\
                    "please send a bug report to info@labber.org."           ,\
                    level=30)
            device_options.remove(option_installed_str)
            
        # TODO This section is invalid until Labber adds support for multiple
        #   state_quant properties for the same instruction file value.
        # Update the channel amount and the related options
        # for the driver instruction file
        # for channel_check in range(1, 9): # TODO 9 (= 8) should be increased
            # if channel_check <= self.n_ch:
                # self.setValue('Output channel '+str(channel_check)+' detected', True)
            # else:
                # self.setValue('Output channel '+str(channel_check)+' detected', False)
            
        
        # Check if the API release version differs from the connected
        # data server's release version.
        ziUtils.api_server_version_check(self.daq)
 
        # Report successful connection
        self.log('Connected to device '+str(self.dev.upper())+'.', level=30)
        
        # Acquire AWG module control
        self.fetchAwgModule()
        

    ##################
    """ AWG module """
    ##################
    
    def fetchAwgModule(self):
        '''This function fetches the AWG module from the API session.
        '''
        
        # Fetching the AWG module may throw a general error.
        awgModuleAttempts = 3
        
        while awgModuleAttempts > 0:
            
            try:
                # Do the actual module instantiation in order to acquire
                # AWG control.
                self.awgModule = self.daq.awgModule()             # Acq. module
                self.awgModule.set('awgModule/device', self.dev)  # Set dev. ID
         
                # Instantiate the thread
                self.awgModule.execute()
         
                # Acquire the AWG data directory and its waveform directory.
                self.awg_data_dir = \
                    self.awgModule.getString('awgModule/directory')
                self.awg_waveform_dir = \
                    os.path.join(self.awg_data_dir, "awg", "waves")
         
                # Identify whether the waveform directory exists.
                if not os.path.isdir(self.awg_waveform_dir):
                    raise DirectoryNotInPath( \
                        "Did not recognise AWG module waveform directory " + \
                        "\'{}\'. Did you modify it?".format(self.awg_waveform_dir))
                
                # Clear the loop
                awgModuleAttempts = -1
                
                
            
            except Exception as awg_fetch_exception: # TODO define exception
                
                self.log( \
                    "WARNING: \'awgModule fetch\' timeout. " + \
                    str(awgModuleAttempts-1) + \
                    " awgModule fetch attempt(s) remaining.",level=30)
                awgModuleAttempts -= 1
                
                if awgModuleAttempts == 0:
                    raise RuntimeError( \
                        "Failed to acquire AWG module. The returned error was:" + \
                        "\n##############################\n"+str(awg_fetch_exception))
                
                time.sleep(5) # TODO is this waiting clause a valid tactic?
                
    
    ############################
    """ Resetting the device """
    ############################
    
    def defaultWaveformConfiguration(self):
        '''This function generates a default waveform information set.
        This can very well be used to reset said configuration if needed.
        '''
        
        # Declare the set of loaded waveforms.
        self.loaded_waveforms = [[]]    * self.n_ch  # All waveform data.
        self.waveform_changed = [False] * self.n_ch  # Update this channel?
        
        # Declare the marker configuration and whether to play markers.
        # Syntax: channel, marker (1 or 2), [start value, duration]
        self.marker_configuration = np.zeros((self.n_ch, 2, 2))
        self.waveform_has_markers = [False] * self.n_ch
        self.declare_marker       = [False] * self.n_ch

        # Declare a flag for detecting when the sequencer requires an update.
        self.sequencer_demands_updating = False
        
        # Declare the initial buffer length
        self.buffer_length = 0
        
        # Declare an initial highest waveform in use. 0 corresponds to no
        # waveforms declared at all. 1 corresponds to one waveform declared
        # in total, playing on output 1.
        self.highest_waveform_in_use = 0
        
        # Initialise a default flag value, monitoring whether to perform
        # an internal repetition delay check. The default is 'Do check.'
        self.perform_repetition_check = True
        
        # Declare a default sequencer program.
        self.local_awg_program = { \
            'WAVEFORM_DECLARATION'              : "&" , \
            'WHILE_LOOP_START'                  : "while(true){" , \
            'WAIT_FOR_INITIAL_TRIGGER'          : "&" , \
            'SYNCHRONISE_TO_BEATING_FREQUENCY'  : "&" , \
            'START_TRIGGER_PULSE'               : "&" , \
            'PLAYWAVE'                          : "&" , \
            'WAITWAVE'                          : "&" , \
            'DELAY_BEFORE_END_TRIGGER'          : "&" , \
            'END_TRIGGER_PULSE'                 : "&" , \
            'DELAY_BEFORE_LOOP_END'             : "&" , \
            'WAIT_FOR_TRIGGER_TO_REPEAT'        : "&" , \
            'WHILE_LOOP_END'                    : "}\n\n" , \
            'TIMESTAMP'                         : "&" , \
            }
        
        # Generate an initial update-parameter list for the sequencer program
        # generator.
        self.update_local_awg_program = [True] * 6
        
        # Generate a list for keeping track of the output ranges, its content
        # of which disabling the 'Bypass DAC to port' option will return to.
        # Upon startup, we don't really have any idea what would be the
        # last set value. Thus, poll the instrument for said values.
        self.previous_ranges = [1.0] * self.n_ch
        for i in range(0,self.n_ch):
            self.previous_ranges[i] = float(round(self.daq.getDouble( \
                '/%s/sigouts/%s/range' % (self.dev, str(i))),1))
        
    
    ##############################################################
    """ Writing waveforms to memory and updating the sequencer """
    ##############################################################
    
    def updateSequencer(self):
        '''Description goes here.
        '''
        self.generateSequencerProgram()
        self.compileAndUploadSourceString()
        
        # After blasting the sequencer memory,
        # we must restore the now lost waveforms.
        for wave in range(0, self.n_ch):
        
            # TODO Checking for lengths is hardly optimised, right?
            # Thus, this section may be made more efficient. For instance using
            # some waveform_used list.
        
            if len(self.loaded_waveforms[wave]) > 0:
                self.waveform_changed[wave] = True
        
    
    def compileAndUploadSourceString(   self, \
                                        compile_timeout_ms = 10000, \
                                        upload_timeout_ms  = 10000):
        '''Description goes here.
        '''
        
        # Transfer the source string to the compiler.
        self.awgModule.set( \
            'awgModule/compiler/sourcestring',
            self.plain_local_awg_program)
        
        self.log(   "Note: if the instrument halts unexpectedly at " + \
                    "this time, check the local AWG program and/or " + \
                    "restart the device entirely."                   , \
                    level=30)
        
        # Run the compilation process
        while   (self.awgModule.getInt('awgModule/compiler/status') == -1) \
            and (compile_timeout_ms >= 0):
            
            # Timeout monitoring, and setting the polling time
            compile_timeout_ms -= 50
            time.sleep(0.050)
            
            # Monitor whether the user halts the measurement.
            if self.isStopped():
                raise CompileAndUploadFailure(  "The measurement was " + \
                                                "halted unexpectedly.")

        # Fetch compilation status
        compiler_status = self.awgModule.getInt('awgModule/compiler/status')
        
        # Check for compilation timeout
        if compile_timeout_ms <= 0:
            raise CompileAndUploadFailure("The compilation process timed out.")

        # Compiler reports success.
        elif self.awgModule.getInt('awgModule/compiler/status') == 0:
            # Included in the elif-tree to catch and abort the other checks.
            pass
            
        #    self.log(   "Compilation fully successful, will " + \
        #                 "upload the program to the instrument.", level=30)

        # Compiler reports failure.
        elif compiler_status == 1:
            raise CompileAndUploadFailure( \
                self.awgModule.getString('awgModule/compiler/statusstring'))

        # Compiler reports successful with warnings.
        elif compiler_status == 2:
            self.log(
                "Compilation successful with warnings, will upload "       + \
                "the program to the instrument.\nCompiler warning: "       + \
                self.awgModule.getString('awgModule/compiler/statusstring'), \
                level=30)
        
        # TODO The -1 compiler status is currently unknown, although it does
        # exist. What should be done about -1? This is likely something that ZI
        # has to answer.
        # TODO They have been contacted.
        elif compiler_status == -1:
            raise CompileAndUploadFailure(  "Compilation failure: compiler "+ \
                                            "returned status \'-1\' which " + \
                                            "seems to indicate \'compiler " + \
                                            "at idle state.\' The compiler "+ \
                                            "message was: \n"               + \
                                            self.awgModule.getString(\
                                            'awgModule/compiler/statusstring'))
        
        # Unknown error
        elif compiler_status != 0:
            raise CompileAndUploadFailure(  "Unknown compiler status "   + \
                                            "reported by instrument. "   + \
                                            "Please report this error: " + \
                                            "status integer = \'"        + \
                                            str(compiler_status)+"\'")

        # Initiate upload process.
        report_line = 1
        time.sleep(0.2) # TODO: This delay should be minimised.
        
        # elf/status provides information whether the upload is succeeding.
        while (self.awgModule.getDouble('awgModule/progress') < 1.0) \
            and (self.awgModule.getInt('awgModule/elf/status') != 1) \
            and (upload_timeout_ms >= 0):

            # Fetch progress
            progress = self.awgModule.getDouble('awgModule/progress') * 100.0
            
            if progress >= 100.0:
                break   # Take a shortcut in case of tiny sequencer snippets
            
            # Print status
            self.log("< {} > awgModule/progress: {:.1f}%".format( \
                    report_line, \
                    progress     \
                ), \
                level=30 \
            )
            
            # Increments the current amount of printed objects
            report_line += 1
            
            # The delay should be minimised to the smallest number possible
            # not affecting the overall performance. For instance, a de-sync
            # would be considered performance-breaking.
            if progress >= 98.0:
                time.sleep(0.025)
                compile_timeout_ms -= 25
                
            elif progress >= 70.0:
                time.sleep(0.300)
                compile_timeout_ms -= 300
                
            else:
                time.sleep(0.600)
                compile_timeout_ms -= 600
        
        # Fetch upload status
        elf_status = self.awgModule.getInt('awgModule/elf/status')
        
        # Check for upload timeout
        if upload_timeout_ms <= 0:
            raise CompileAndUploadFailure("The upload process timed out.")
        
        # Upload reported success
        elif elf_status == 0:
            self.log("< {} > awgModule/progress: 100% - Success".format( \
                    report_line
                ), \
                level=30 \
            )

        # Upload reported failure (by not reporting success)
        elif elf_status == 1:
            raise CompileAndUploadFailure( \
                "Upload to the instrument failed at {:.2f}".format( \
                    self.awgModule.getDouble('awgModule/progress') * 100.0 \
                ) \
            )
        
        # Unknown error
        else:
            raise CompileAndUploadFailure( \
                "Unknown upload status reported " + \
                "by instrument at {:.2f}".format(   \
                    self.awgModule.getDouble('awgModule/progress') * 100.0 \
                ) \
            )

        # # TODO Delete or leave in?
        # # If the device was playing before, enable playback again.
        # # Ensure that the value is indeed set.
        # if AWG_playback_status == 1:
            # timeout = 0.0
            # while (((self.awgModule.get('awgModule/awg/enable')).get('awg'))\
                # .get('enable')[0] != 1) and (timeout <= 2.0):
                
                # # TODO these values should be minimised
                # time.sleep(0.05)
                # timeout += 0.05
                # self.awgModule.set('awgModule/awg/enable', 1)
    
        # Perform a final check whether the sequencer has run out of memory
        cache_utilisation = self.daq.getDouble( \
            '/'+str(self.dev)+'/awgs/0/waveform/memoryusage')
        
        if cache_utilisation > 0.9999:
            if self.getValue('Halt on cache overflow'):
                raise MemoryError( "The sequencer ran out of cache space "  + \
                                   "("+str(cache_utilisation * 100.0)+"%)"  + \
                                   ". Disable \'Halt on cache overflow\' "  + \
                                   "or reduce waveform lengths to continue.")
            else:
                self.log(   "Warning: out of sequencer cache memory. " + \
                            "Expect lower performance.", level=30)


    def writeWaveformToMemory(self):
        ''' Upload waveform vector data to device memory.
        
        TODO insert more description.
        '''
        
        # Resetting the core and wave indices
        core_index = 0
        
        # Acquiring package length
        n = self.buffer_length
        
        # First, we disable the playback. # TODO necessary?
        '''self.daq.setInt('/'+str(self.dev)+'/awgs/0/enable', 0)'''
        
        # In order to not crash the device, all waveforms must be uploaded
        # interleaved except the last one if it's odd. Not used channels
        # must also be declared as phantom waveforms up to the highest channel
        # in use, causing a large waste of resources.
        
        # Upload waveform vector data, poll all channels pairwise.
        # Remember that highest_waveform_in_use = 0 corresponds to no
        # waveforms declared for playback, and 1 corresponds to update
        # waveform 0 for channel 1. This way, this loop will not trigger
        # when there are no waveforms to play back.
        for channel in range(0, self.highest_waveform_in_use, 2):

            # Upload waveforms?
            if self.waveform_changed[channel] or \
                self.waveform_changed[channel+1]:
            
                # Because the user may have changed the measurement range
                # between the two measurement points in question,
                # we must fetch and re-check both x1 and x2.
                
                # Reset flags:
                self.waveform_changed[channel  ] = False
                self.waveform_changed[channel+1] = False
                
                # Load waveforms channel and channel+1 for treatment
                x1 = np.asarray( self.loaded_waveforms[channel  ] , dtype = float )
                x2 = np.asarray( self.loaded_waveforms[channel+1] , dtype = float )
                
                # Get their lengths, used several times.
                len_x1 = len(x1)
                len_x2 = len(x2)
                
                # Get the output range of the channels. When running waves with
                # 'Direct output' enabled, the output range is fixed to 800 mV.
                # The direct output is known as 'Bypass DAC to port' in the
                # instruction file due to repeated confusion in usage cases.
                '''TODO This is unnecessary right? Since the instrument
                and/or command automatically changes the output range when
                the 'Direct mode' (Bypass) is in effect? Meaning that
                first checking whether it is bypassed is unnecessary.'''
                if not self.getValue( \
                    'Channel %d - Bypass DAC to port' % (channel + 1)):
                    output_range_x1 = float(self.getCmdStringFromValue( \
                        'Channel %d - Range' % (channel + 1)))
                else:
                    output_range_x1 = 0.8
                    
                if not self.getValue( \
                    'Channel %d - Bypass DAC to port' % (channel + 2)):
                    output_range_x2 = float(self.getCmdStringFromValue( \
                        'Channel %d - Range' % (channel + 2)))
                else:
                    output_range_x2 = 0.8    
                
                # Prepare mnemonic package
                data = np.zeros((n, 3))
                data[:len_x1, 0] = x1 / output_range_x1
                data[:len_x2, 1] = x2 / output_range_x2
                
                assert np.max(abs(data[:,0])) <= 1, \
                    "Halted. The HDAWG was tasked to play a value on "    + \
                    "channel "+str(channel+1)+" larger than the "         + \
                    "channel's range. The absolute value of the maximum " + \
                    "was "+str(np.max(abs(x1)))+" V."
                
                assert np.max(abs(data[:,1])) <= 1, \
                    "Halted. The HDAWG was tasked to play a value on "    + \
                    "channel "+str(channel+2)+" larger than the "         + \
                    "channel's range. The absolute value of the maximum " + \
                    "was "+str(np.max(abs(x2)))+" V."
                
                # Convert the array data to an injectable data format.
                
                # The appropriate core index is hard-coded to 0 as we either
                # replace the first waveform, or both the first and second
                # waveform of the core in question. In both cases, the index
                # should be 0.
                
                # Does the waveform contain markers? This check is done
                # in order to speed up uploading, since most waveforms will
                # not contain markers.
                if self.waveform_has_markers[channel] or \
                    self.waveform_has_markers[channel+1]:
                
                    # The waveform has associated marker data.
                    # The promise up to this point is that this marker data
                    # *must* be of the same length as the waveforms themselves.
                    
                    # Load associated marker data for treatment. Remember that
                    # markers are stored per channel output, and contains both
                    # available markers on that channel.
                    
                    # TODO THIS DOES NOT LOAD MARKER 2
                    # TODO There is a mismatch in the marker data.
                    #       There is a single spurious single datapoint that
                    #       is left turned on.
                    marker = 0
                    x_marks = np.zeros(n)
                    x_marks[int(self.marker_configuration[channel,marker,0]): int(self.marker_configuration[channel,marker,0])+int(self.marker_configuration[channel,marker,1])] = 1
                    
                    data[:, 2] = x_marks
                    
                    # TODO If ZI adds support for different-length upload packets,
                    # then the marker data cannot be locked to be strictly the
                    # length of the buffer.
                    
                    # Will there be an interleaved upload?
                    # Note the optimisation:
                    # if channel+1 <= self.highest_waveform_in_use-1:
                    if channel <= self.highest_waveform_in_use-2:
                        inject = \
                            ziUtils.convert_awg_waveform(   wave1=data[:,0], \
                                                            wave2=data[:,1], \
                                                            markers=data[:,2])
                    else:
                        inject = \
                            ziUtils.convert_awg_waveform(   wave1=data[:,0], \
                                                            markers=data[:,2])
                    
                    try:
                        # Set command basis
                        base = '/%s/awgs/%d/' % (self.dev, core_index)
                        
                        # Inject the injectable data. Note that all uploads
                        # whatsoever will be sent to wave index 0, even
                        # interleaved ones.
                        self.daq.setVector(base + 'waveform/waves/0', inject)
                        
                    
                    except Exception as setVector_exception:
                    
                        # Get time of error
                        error_timestamp = \
                            (datetime.now()).strftime("%d-%b-%Y (%H:%M:%S)")
                        self.log( "WARNING: There was an exception when "   +\
                                  "attempting to upload waveforms (with "   +\
                                  "markers) at time: "+\
                                  error_timestamp, level=30)
                
                        # Get exception
                        self.log( \
                            "The exception was: " + str(setVector_exception),\
                            level=30)
                        
                else:

                    # The waveform does not have associated markers.
                    # Perform normal upload.
                
                    # Will there be an interleaved upload?
                    # Note the optimisation:
                    # if channel+1 <= self.highest_waveform_in_use-1:
                    if channel <= self.highest_waveform_in_use-2:
                        inject = \
                            ziUtils.convert_awg_waveform(   wave1=data[:,0], \
                                                            wave2=data[:,1])
                    else:
                        inject = \
                            ziUtils.convert_awg_waveform( wave1=data[:,0] )
                    
                    # Set command basis
                    base = '/%s/awgs/%d/' % (self.dev, core_index)
                    
                    try:
                        # Inject the injectable data. Note that all uploads
                        # whatsoever will be sent to wave index 0, even
                        # interleaved ones.
                        self.daq.setVector(base + 'waveform/waves/0', inject)
                    
                    except Exception as setVector_exception:
                    
                        # Get time of error
                        error_timestamp = \
                            (datetime.now()).strftime("%d-%b-%Y (%H:%M:%S)")
                        self.log( "WARNING: There was an exception when "  + \
                                  "attempting to upload waveforms " + \
                                  "(without markers) at time: " + \
                                  error_timestamp, level=30)
                
                        # Get exception
                        self.log( \
                            "The exception was: " + str(setVector_exception), \
                            level=30)
            
        
            # Increase the core index for the next run of the for-loop
            core_index += 1
        
            # Attempt to enable instrument (even after injection failure).
            remaining_enable_attempts = 3
           
            while remaining_enable_attempts >= 0:
                try:                    
                    # Re-enable the playback
                    self.daq.setInt('/'+str(self.dev)+'/awgs/0/enable', 1)
                
                    # Success
                    remaining_enable_attempts = -1
                
                except Exception: # TODO define exception
                    
                    self.log( \
                        "WARNING: setVector timeout. "   + \
                        str(remaining_enable_attempts-1) + \
                        " upload attempt(s) remaining.", level=30)
                    remaining_enable_attempts -= 1
                    time.sleep(5) # TODO is this waiting clause a valid tactic?
                
                if remaining_enable_attempts == 0:
                    
                    # Shall we consider waiting for device to auto-restore?
                    if self.getValue( \
                        'Attempt API reconnection when the HDAWG crashes'):
                        
                        # Perform long wait.
                        halt_time = self.getValue('Time to wait')
                        
                        self.log( + \
                            "The measurement was halted by the instrument "  +\
                            "driver for device \'"+self.dev_uppercase        +\
                            "\' because the device crashed. The measurement" +\
                            " will now wait for "+str(halt_time)+" seconds " +\
                            "and attempt to reconnect to the ZI API.",level=30)
                        
                        time.sleep(halt_time)
                        
                        # Attempt to re-fetch the API.
                        self.instantiateInstrumentConnection()
                    
                    else:                
                        raise RuntimeError( \
                            "HDAWG \'"+self.dev_uppercase+"\' has crashed; the " + \
                            "device does not respond to any calls from the PC. " + \
                            "Consider restarting the device using the front button.")
                    
    
    def fetchAndAssembleWaveform(self, wave):
        '''TODO
        
        Following experiments, CK (author) concluded that uploading segments
        of playWave and filling them retroactively with setWave uploads is not
        a scalable solution, mainly as the amount of uploads increase for each
        and every possible combination of waveform primitives.
        
        Hence, the solution was to assemble primitives before simply uploading
        the finished segment as a flat waveform.
        
        '''
        
        # We have received a request to assemble waveform 'wave.'
        # Is the blueprint empty?
        blueprint = \
            self.getValueArray('Waveform '+str(wave+1)+' sequence blueprint')
        
        # Prepare waveform for assembly
        assembled_waveform = []
        
        if len(blueprint) > 0: # TODO is it possible that Labber returns a [None] at this stage?
            
            # There is a blueprint, assemble the waveform.
            # The syntax of the blueprint is:
            # [S1, P1, S2, P2, S3, P3] where for Blueprint X (1...n_ch) -
            # insert S1 zeroes, insert primitive 1, insert S2 zeroes, etc.
            # The unit is volts. Vectors start at 0. The number of elements
            # in a blueprint is always even.
            
            # Example
            # Primitive 4: [0.313 0.13 0.313 0.13]
            # Primitive 16: [3.13 31.3 0 0 0.3]
            # Blueprint 7: [3, 4, 2, 16]
            # Result 7: [0 0 0 0.313 0.13 0.313 0.13 0 0 3.13 31.3 0 0 0.3]
            
            # For blueprint X, [insert Y zeroes, insert primitive Z ...]
            for i in range(0,len(blueprint),2):
                assembled_waveform.extend([0] * blueprint[i])
                assembled_waveform.extend( \
                    self.getValueArray( \
                        'Waveform primitive '+str(blueprint[i+1]+1) \
                    ) \
                )
        
        else:
            
            # No blueprint is given, default to fetching the
            # Channel - Waveform vector
            assembled_waveform = \
                self.getValueArray('Channel '+str(wave+1)+' - Waveform')
        
        return assembled_waveform
    
    
    #####################################################
    """ Check validness of requested repetition delay """
    #####################################################
    
    def checkInternalRepetitionRateValid(self):
        ''' TODO finish writing stuff
        
        RETURNS BY ASSIGNING A SELF VALUE: The internal delay period following
        calculation, ie. how much time (in seconds) will be pure delay.
        
        Should this value be negative, then there is insufficient time left
        for internally delaying the repetition to the user-requested value.
        
        Required ini values to have been set for this calculation to be valid
        are listed below. Do note that these values are NOT order-sensitive
        in the instruction file. Because, all of these ini commands simply
        trigger an Internal repetition period check upon the next isFinalCall
        via setting the boolean self.perform_repetition_check.
        
        - Internal trigger period
        - Sequencer triggers
        - Output sample rate
        - Output sample rate divisor
        - Trigger out delay
        - Calibrate trigger out delay
        - AWGX - Waveform , where X = self.n_ch amount of waveforms defined
        - Calibrate internal trigger period
        - Halt on illegal repetition rate
        - Dynamic repetition rate
        
        When calling to check whether the internal trigger period is valid,
        the value stored in Labber at 'Internal trigger period' will be
        seen as the new deadline.
        
        '''

        # Fetch the value to be checked
        requested_trigger_period = self.getValue('Internal trigger period')
        
        # Count the amount of trigger cycles required for setting
        # the triggers.
        # TODO Remember to remove this part when changing from
        # setTrigger to markers.
        
        sequencer_trigger = self.getValue('Sequencer triggers')

        if sequencer_trigger == \
            'Send at AWG program start':
            trigger_cycles = 2
            
        elif sequencer_trigger == \
            'Send at AWG program finish':
            trigger_cycles = 2
            
        elif sequencer_trigger == \
            'Hold high during playback':
            trigger_cycles = 2
            
        elif sequencer_trigger == \
            'Send at AWG program start + finish':
            trigger_cycles = 4
        
        else:
            trigger_cycles = 0
        
        # Fetch the sequencer clock and the required amount of
        # wait cycles before the final trigger (if any).
        
        sample_rate =                               \
            self.getValue('Output sample rate') /         \
            2**self.getValueIndex('Output sample rate divisor')
    
        # The sequencer operational count (OPS) is 1/8 of the
        # sample clock.
        sequencer_clk = sample_rate / 8.0
        
        # Now once we have fetched the sequencer clock rate, we may
        # acquire the amount of wait cycles requested before the
        # trigger.
        
        wait_cycles_before_trigger = 0

        # Shall there be a trigger out delay?
        if self.getValue('Trigger out delay') > 0:
            if self.getValue('Sequencer triggers') in [ \
                'Send at AWG program finish', \
                'Send at AWG program start + finish' ]:
                
                # At this instance, we (rightly so) expect the
                # trigger out delay to be confirmed as valid.

                # Fetch the requested trigger out delay.
                trigger_out_delay = \
                    self.getValue('Trigger out delay') - \
                    self.getValue('Calibrate trigger out delay')

                # Calculate how many cycles of the sequencer clock is required
                # to equal the user-requested delay. Send it to UserReg(0).
                wait_cycles_before_trigger = \
                    int(round(trigger_out_delay * sequencer_clk))

        time_for_running_auxiliary_code = \
            (wait_cycles_before_trigger + trigger_cycles) \
            / sequencer_clk
        
        # How much time is spent playing waveforms? We require the buffer
        # length and the amount of currently playing waves. The latter is
        # solved by observing self.highest_waveform_in_use. Remember that
        # if no waveform is declared, highest_waveform_in_use = 0.
        # The 2* factor stems from 2 sequencer cycles being added for every
        # declared waveform in the sequencer program. This in turn stems
        # from playWave, where two arguments (one cycle each) are required
        # to get a waveform onto the output.
        
        time_for_playing_waveforms = \
            (self.buffer_length / sample_rate) + \
            2 * (self.highest_waveform_in_use / sequencer_clk)
        
        # Perform the final check
        internal_delay_period = \
            requested_trigger_period \
            - time_for_running_auxiliary_code \
            - time_for_playing_waveforms \
            - self.getValue('Calibrate internal trigger period')
        
        # Internal trigger period valid or invalid?
        if internal_delay_period < 0:
        
            # Negative = invalid
            # Do the following checks:
            
            if self.getValue('Halt on illegal repetition rate'):
                # The repetition rate is illegal since the internal delay
                # period is negative, hence 'the requested' minus
                # 'the internal' below.
                raise AssertionError(
                    "Instrument halted: the sequencer program requires "   + \
                    "more time to play than the requested internal "       + \
                    "repetition rate. With the current settings, the "     + \
                    "requested trigger period must be increased to "       + \
                    str(requested_trigger_period - internal_delay_period)  + \
                    " s minimum. Should the settings change, this minimum "+ \
                    "value may increase. It is thus good practice to add " + \
                    "some additional time to the updated value.")
            
            elif self.getValue('Dynamic repetition rate'):
                
                # Expand the calculated delay.
                # Note: subtracting a negative value.
                internal_delay_period = \
                    requested_trigger_period - internal_delay_period
                
                # Update the Labber setting.
                self.setValue( \
                    'Internal trigger period', \
                    internal_delay_period
                )
                
                # # Insert the calculated value into the sequencer program.
                # internal_trigger_waiting = \
                #     int(round(internal_delay_period * sequencer_clk))
                
                # self.local_awg_program = self.local_awg_program.replace(\
                #     '&DELAY_BEFORE_LOOP_END', \
                #     'wait(' +str(internal_trigger_waiting)+ ');')
            
            else:
                
                # The repetition rate is illegal but the user wishes to
                # ignore said fact.
                self.log(   "Warning: illegal repetition rate detected " + \
                            "and ignored.", level=30)
            
        # "Return" an internal delay period. This is used in the sequencer
        # program generator.
        self.verified_internal_delay_period = internal_delay_period
        
        
    
    #######################################
    """ Generate AWG sequencer program. """
    #######################################

    def generateSequencerProgram(self):
        '''This function generates a local AWG program, that in turn will be
        uploaded into the sequencer.
        
        The general layout of the sequencer program generation is to assemble
        a skeleton dictionary bearing &-tags. Depending on a vast array of
        options, these tags will be modified by the generation functions
        accordingly. {'waveform_declaration','&'} may for instance be replaced
        with the waveform declarations, enabling the instrument to play the
        Labber-defined waveforms.
        
        Default skeleton:
        
        self.local_awg_program = { \
            'WAVEFORM_DECLARATION'              : "&" , \
            'WHILE_LOOP_START'                  : "&" , \
            'WAIT_FOR_INITIAL_TRIGGER'          : "&" , \
            'SYNCHRONISE_TO_BEATING_FREQUENCY'  : "&" , \
            'START_TRIGGER_PULSE'               : "&" , \
            'PLAYWAVE'                          : "&" , \
            'WAITWAVE'                          : "&" , \
            'DELAY_BEFORE_END_TRIGGER'          : "&" , \
            'END_TRIGGER_PULSE'                 : "&" , \
            'DELAY_BEFORE_LOOP_END'             : "&" , \
            'WAIT_FOR_TRIGGER_TO_REPEAT'        : "&" , \
            'WHILE_LOOP_END'                    : "&" , \
            'TIMESTAMP'                         : "&" , \
            }
        
        '''
        
        # Calculate basic clock and samling rates, used for several functions
        # in the sequencer program generation.
        sample_rate =                               \
            self.getValue('Output sample rate') /         \
            2**self.getValueIndex('Output sample rate divisor')
                
        # The sequencer operational count (OPS) is 1/8 of the sample clock.
        sequencer_clk = sample_rate / 8.0
        
        # The channel grouping has been modified at the performSet for
        # every command that involves the usage of the on-board oscillators.




        # # # # Generate program # # # #
        
        # TODO DEBUG
        self.log('Should we update local program [0]? : '+str(self.update_local_awg_program[0])+'\nDID any waveform have markers? = '+str(any(self.waveform_has_markers)),level=30)
        
        # Are there any changes to entry 0:
        # MARKER_DECLARATION, WAVEFORM_DECLARATION, PLAYWAVE, WAITWAVE?
        if self.update_local_awg_program[0]:
            
            # Waveform declaration and playwave compiler prototypes.
            waveform_declaration_setup = ''
            playwave_setup = ''
            
            # Should we place commas between waveforms?
            first_waveform_declared = False
            
            # Should there be a marker declaration in the beginning?
            if any(self.waveform_has_markers):
                
                # Add marker declaration.
                waveform_declaration_setup += \
                    'wave w_m = marker({0}, 1);\n'.format(self.buffer_length)
                    
            
            # What waveforms should be declared with a marker?
            self.declare_marker = [False] * self.n_ch
            for n in range(0, self.highest_waveform_in_use, 2):
                
                # For all channels
                if n < self.highest_waveform_in_use-1:
                    if self.waveform_has_markers[n] or self.waveform_has_markers[n+1]:
                        self.declare_marker[n]   = True
                        self.declare_marker[n+1] = True
                
                elif n == self.highest_waveform_in_use-1:
                    # But, if this waveform is the highest waveform in use,
                    # and the following (non-existant) waveform has marker
                    # data, then do not declare markers on the higher part
                    # of the waveform pair.
                    
                    if self.waveform_has_markers[n]:
                        self.declare_marker[n]   = True
                    
                    
                    
            
            # How many waveforms should be declared?
            # Remember that self.highest_waveform_in_use = 0 corresponds to no
            # waveforms declared.
            for n in range(0, self.highest_waveform_in_use):
                
                # Is this waveform wasted? If len > 0, then no.
                if len(self.loaded_waveforms[n]) > 0:
                    
                    # TODO This here below is a variant waveform
                    # declaration using randomUniform. I've been told that
                    # using zeros might cause unwanted optimisation in the
                    # SeqC compiler, so that for instance the setVector
                    # command would not be able to correctly upload
                    # waveforms.
                    
                    #   'wave w{0} = randomUniform({1},1e-4) + m1;\n'\
                    #       .format(n+1, self.buffer_length)
                    
                    if(self.declare_marker[n]):
                        waveform_declaration_setup += \
                            'wave w{0} = zeros({1}) + w_m;\n'\
                                .format(n+1, self.buffer_length)
                    else:
                        waveform_declaration_setup += \
                            'wave w{0} = zeros({1});\n'\
                                .format(n+1, self.buffer_length)
                        
                else:
                    
                    # Waveform is wasted. Add markers or not?
                    if(self.declare_marker[n]):
                        waveform_declaration_setup += \
                            'wave w{0} = zeros({1}) + w_m; // Unused.\n'\
                                .format(n+1, self.buffer_length)
                    else:
                        waveform_declaration_setup += \
                            'wave w{0} = zeros({1}); // Unused.\n'\
                                .format(n+1, self.buffer_length)
                
                # Waveform initial declaration / generation
                if first_waveform_declared:
                    playwave_setup += ', {0}, w{0}'.format(n+1)
                
                else:
                    # Declare the first waveform for playback
                    playwave_setup += '{0}, w{0}'.format(n+1)
                    first_waveform_declared = True

            # The condition for checking the waveform declaration is covered
            # by the playwave setup condition, thus the actions have been
            # combined.
            if playwave_setup != '':
                self.local_awg_program.update({ \
                    'WAVEFORM_DECLARATION':waveform_declaration_setup + '\n', \
                    'PLAYWAVE':'\tplayWave('+playwave_setup+');\n', \
                    'WAITWAVE':'\twaitWave();\n'})
            else:
                # There are no waves to play, remove all instances related
                # to playing a wave. The HDAWG has a tendancy to crash if this
                # step is done improperly.
                self.local_awg_program.update({ \
                    'WAVEFORM_DECLARATION':'', \
                    'PLAYWAVE':'', \
                    'WAITWAVE':''})

        
        # Are there any changes to entry 1:
        # WHILE_LOOP_START, WHILE_LOOP_END?
        # (Aka: 'Is the measurement of some single-shot type?)'
        if self.update_local_awg_program[1]:
            
            # TODO: perform a check whether this is a single shot measurement.
            # if( Single shot measurement )
            ''' TODO There is currently no setting which modifies this part of the generateSequencerProgram function. '''
            self.local_awg_program.update({ \
                'WHILE_LOOP_START':'while(true){\n', \
                'WHILE_LOOP_END':'}\n\n'})
            # else:
            #    self.local_awg_program.update({ \
            #        'WHILE_LOOP_START':'', \
            #        'WHILE_LOOP_END':''})
        
        
        # Are there any changes to entry 2:
        # WAIT_FOR_INITIAL_TRIGGER, DELAY_BEFORE_LOOP_END,
        # WAIT_FOR_TRIGGER_TO_REPEAT?
        if self.update_local_awg_program[2]:
            
            # How and when should the HDAWG play the sequencer?
            trigger_mode = self.getValue('Run mode')
            
            if trigger_mode == 'Play once, then external trigger':
                
                # The 'Play once, then external trigger' option is very similar
                # to the external trigger apart from playing the AWG once
                # to initiate the measurement cycle.
                self.local_awg_program.update({ \
                    'WAIT_FOR_INITIAL_TRIGGER':'', \
                    'WAIT_FOR_TRIGGER_TO_REPEAT':'\twaitDigTrigger(1);\n', \
                    'DELAY_BEFORE_LOOP_END':''})
                
            elif trigger_mode == 'Internal trigger':

                # On internal trigger, set up a delay at the end of
                # the sequencer program.
                
                # Trash the 'wait_for_trigger' tags.
                self.local_awg_program.update({ \
                    'WAIT_FOR_INITIAL_TRIGGER':'', \
                    'WAIT_FOR_TRIGGER_TO_REPEAT':''})
                
                # At this point in time, the isFinalCall subfunction
                # already checked and verified the internal repetition delay
                # if any. If the "returned" verified_internal_delay_period is
                # negative, and the checkInternalRepetitionRateValid function
                # did not halt the program - then perform the following action:
                
                if self.verified_internal_delay_period < 0:
                
                    # The checked internal delay period is negative ergo
                    # impossible to represent.
                    self.local_awg_program.update({ \
                        'DELAY_BEFORE_LOOP_END': \
                        '\t// Invalid internal repetition delay.\n'})

                elif self.getValue('Use oscillator-based repetition delay'):
                
                    # Insert oscillator waiting code
                    self.local_awg_program.update({ \
                        'DELAY_BEFORE_LOOP_END':'\twaitSineOscPhase(2);\n'})
                        
                else:
                    
                    # Insert the calculated wait delay before the final loop
                    # as done by the checkInternalRepetitionRateValid function.
                    internal_delay_period = self.verified_internal_delay_period
                    
                    internal_trigger_waiting = \
                        int(round(internal_delay_period * sequencer_clk))
                        
                    self.local_awg_program.update({ \
                        'DELAY_BEFORE_LOOP_END': \
                        '\twait(' + str(internal_trigger_waiting) + ');\n'})

            elif trigger_mode == 'External trigger':
                
                # On external trigger, the AWG will halt its execution in the
                # beginning of the sequencer program. It proceeds to await an
                # external triggering signal.
                self.local_awg_program.update({ \
                    'WAIT_FOR_INITIAL_TRIGGER':'\twaitDigTrigger(1);\n', \
                    'WAIT_FOR_TRIGGER_TO_REPEAT':'', \
                    'DELAY_BEFORE_LOOP_END':''})
                
            else:
                raise ValueError( \
                    "Unknown run mode acquired, there is likely " + \
                    "an error in the driver .ini-file.")

            
        # Are there any changes to entry 3:
        # SYNCHRONISE_TO_BEATING_FREQUENCY?
        if self.update_local_awg_program[3]:
            
            # Synchronise to beating frequency to minimise inter-device jitter?
            if self.getValue('Minimise inter-device asynchronous jitter'):
                self.local_awg_program.update({ \
                    'SYNCHRONISE_TO_BEATING_FREQUENCY':'\twaitSineOscPhase(1);\n'})
            else:
                self.local_awg_program.update({ \
                    'SYNCHRONISE_TO_BEATING_FREQUENCY':''})

                    
        # Are there any changes to entry 4:
        # START_TRIGGER_PULSE, END_TRIGGER_PULSE?
        if self.update_local_awg_program[4]:
            
            # Sequencer triggers
            sequencer_trigger = self.getValue('Sequencer triggers')
            
            if sequencer_trigger == 'Send at AWG program start':
                
                # On 'Send at AWG program start,' send an initial digital
                # marker pulse and remove all other markers.
                self.local_awg_program.update({ \
                    'START_TRIGGER_PULSE': \
                        '\tsetTrigger(0b1111); setTrigger(0b0000);\n', \
                    'END_TRIGGER_PULSE': \
                        '' \
                }) # TODO This paragraph will be changed at version 0.84
                
            elif sequencer_trigger == 'Send at AWG program finish':
            
                # On 'Send at AWG program finish,' send a final digital marker
                # pulse and remove all other markers.
                self.local_awg_program.update({ \
                    'START_TRIGGER_PULSE': \
                        '', \
                    'END_TRIGGER_PULSE': \
                        '\tsetTrigger(0b1111); setTrigger(0b0000);\n' \
                })
                
            elif sequencer_trigger == 'Hold high during playback':
                
                # On 'Hold high during playback,' send an initial marker start,
                # and as a final marker gesture pull it low.
                self.local_awg_program.update({ \
                    'START_TRIGGER_PULSE': \
                        '\tsetTrigger(0b1111);\n', \
                    'END_TRIGGER_PULSE': \
                        '\tsetTrigger(0b0000);\n' \
                })
            
            elif sequencer_trigger == 'Send at AWG program start + finish':
                
                # On 'Send at AWG program start + finish,' send a marker both
                # at the sequencer program start and finish.
                self.local_awg_program.update({ \
                    'START_TRIGGER_PULSE': \
                        '\tsetTrigger(0b1111); setTrigger(0b0000);\n', \
                    'END_TRIGGER_PULSE': \
                        '\tsetTrigger(0b1111); setTrigger(0b0000);\n' \
                })
                
            elif sequencer_trigger == 'Do not send sequencer triggers':
                
                # On 'Do not send any triggers,' remove all program
                # tags related to generating sequencer triggers.
                self.local_awg_program.update({ \
                    'START_TRIGGER_PULSE': \
                        '', \
                    'END_TRIGGER_PULSE': \
                        '' \
                })
                
            else:
                raise ValueError( \
                    "Unknown option selected for sequencer triggers. " + \
                    "There is likely an error in the driver .ini-file.")

        
        # Are there any changes to entry 5:
        # DELAY_BEFORE_END_TRIGGER?
        if self.update_local_awg_program[5]:
            
            # Shall there be a trigger out delay?
            if self.getValue('Trigger out delay') > 0 \
                and self.getValue('Sequencer triggers') in [ \
                    'Send at AWG program finish', \
                    'Send at AWG program start + finish' ]:
                
                # Is the requested trigger out delay representable?
                
                # Calculate the lowest representable delay:
                # Because of the layout of the combinational list, it is
                # sufficient to acquire the value index.
                    
                # Three softcore cycles are required for acquiring the userreg
                # content. When trying to set the lowest possible delay without
                # removing the getUserReg clause altogether, adding these three
                # strikes is crucial.
                lowest_representable_delay = 3 / sequencer_clk

                #   TODO:
                #   Check whether there is in fact some calculation error that
                #   causes the delay to overshoot (thus removing the purpose of
                #   calibrating the Trigger out delay)
                
                # Fetch the requested trigger out delay.
                trigger_out_delay = self.getValue('Trigger out delay') \
                    - self.getValue('Calibrate trigger out delay')
                
                if trigger_out_delay >= lowest_representable_delay:
                    # The requested Trigger out delay is representable.
                    # Calculate how many cycles of the sequencer clock is
                    # required to equal the user-requested delay.
                    # Send it to UserReg(0).

                    self.daq.setDouble( \
                        '/' + self.dev + '/awgs/0/userregs/0', \
                        int(round(trigger_out_delay * sequencer_clk))
                        )
                    
                    # Insert the command itself.
                    self.local_awg_program.update({ \
                        'DELAY_BEFORE_END_TRIGGER':'\twait(getUserReg(0));'})
                    
                else:
                    # Not representable.
                    if trigger_out_delay != 0:
                        self.log( \
                            "Warning: the \'Trigger out delay\' requested "  +\
                            "is lower than the minimum representable delay " +\
                            "at the selected sample clock rate.", level=30)

                    # Return 0 to the user.
                    self.setValue('Trigger out delay', 0)
                    
                    # Remove the tag.
                    self.local_awg_program.update({ \
                        'DELAY_BEFORE_END_TRIGGER':''})
                    
            else:
                # No trigger out delay was requested.
                    self.local_awg_program.update({ \
                        'DELAY_BEFORE_END_TRIGGER':''})
    
    
        # Are there any changes to TIMESTAMP?
        # Yes. Most scientists agree that time moves forward.
        # Insert final message and timestamp into the sequencer code.
        timestamp = (datetime.now()).strftime("%d-%b-%Y (%H:%M:%S)")
        self.local_awg_program.update({'TIMESTAMP': \
            "// This sequencer code was automatically generated at " + \
            timestamp})
        
        
        # Reset the entire list. This is likely the quickest operation, right?
        self.update_local_awg_program = [False] * 6
        
        
        # Generate a plain text local AWG program from the dictionary.
        self.plain_local_awg_program = ''
        for key in self.local_awg_program:
            self.plain_local_awg_program += self.local_awg_program[key]
        
        # Sanity check
        if '&' in self.plain_local_awg_program:
            raise SystemError(\
                "The local AWG sequencer program has not been generated " + \
                "properly. This bug should not appear, please report it." + \
                "\n\nThe generated AWG program was:\n"                    + \
                self.plain_local_awg_program                              )

    
    ###################################################
    """ Functions not related to Labber explicitly. """
    ###################################################

    def isLabOneRunning(self):
        '''This function asserts that LabOne is running.
        '''
        
        # For all running process ID's:
        for process_id in psutil.pids():
        
            # Acquire current process information to sift through
            process_information = psutil.Process(process_id)
            
            # Is this the ziService process?
            if 'ziService' in process_information.name():
                return True
        
        # Failure fallback:
        return False
        
            
    def printAllListItemsToFile(self, list, name_of_file = 'ListOutput.txt', halt_after_write = False):
        ''' TODO DEBUG
        This is a debug function, it will be removed before the final release.
        '''

        with open('C:\\Users\\qtlab\\Desktop\\'+str(name_of_file), 'w') as f:
            for item in list:
                f.write("%s\n" % item)

        assert halt_after_write == False, "Wrote list to file!"
        
####################################
""" Miscellaneous functionality. """
####################################

if __name__ == '__main__':
    raise NotImplementedError("This driver is currently not executable " + \
                              "from the command line.")
    
class AutoconnectFailure(Exception):
    pass
    
class DirectoryNotInPath(Exception):
    pass
    
class CompileAndUploadFailure(Exception):
    pass
    
class CloseDeviceException(Exception):
    pass